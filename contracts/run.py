"""Write verified shared-schema contracts: python -m contracts.run --cik X / --universe."""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import httpx

from shared.paths import CONTRACTS, UNIVERSE
from shared.schema import SCHEMA_VERSION, ContractExtraction, Refusal, UniverseEntry
from contracts.amendments import apply_amendments
from contracts.definitions import DefinitionError, normalize
from contracts.discover import Discovery, DiscoveryError, dev_companies, discover
from contracts.extract import ExtractionError, Extractor
from contracts.context import ContextError, plan_context
from contracts.runtime import BudgetError, Runtime, atomic_json
from contracts.verify import EvidenceError, fingerprint, summarize, verify_contract


METRICS_PREFIX = 'contracts.metrics='


def pipeline_fingerprint() -> str:
    root = Path(__file__).parent
    paths = sorted(root.glob('*.py')) + sorted((root / 'prompts').glob('*.txt'))
    return fingerprint([(str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths])


def source_fingerprints(discovery: Discovery) -> dict:
    return {document.key: fingerprint({'agreement': document.agreement.model_dump(mode='json'),
                                      'sha256': hashlib.sha256(document.text.encode('utf-8')).hexdigest()})
            for document in discovery.documents}


def build_contract(discovery: Discovery, extractor: Extractor, *, pilot=False) -> ContractExtraction:
    before = extractor.stats.as_dict()
    refusals = list(discovery.refusals)
    notes = list(discovery.notes)
    documents = discovery.documents
    terms, covenants = [], []
    if not documents and not refusals:
        refusals.append(Refusal(scope='company', ref=discovery.company.cik, reason='missing_filing',
                                detail='No credit-agreement EX-10 exhibits discovered.'))
    redactions = [document for document in documents if document.agreement.redacted]
    for document in redactions:
        refusals.append(Refusal(scope='agreement', ref=document.key, reason='redacted',
                                detail='Redaction marker present; complete operative definition coverage cannot be established.'))
    if not refusals:
        results = [extractor.read(document) for document in documents]
        terms, covenants, rejected, result_notes = apply_amendments(results)
        refusals.extend(rejected)
        notes.extend(result_notes)
        accepted = []
        for covenant in covenants:
            try:
                normalize(terms, [covenant], [d.text for d in documents])
                accepted.append(covenant)
            except DefinitionError as error:
                refusals.append(Refusal(scope='covenant', ref=covenant.id, reason='ambiguous_definition', detail=str(error)))
                notes.append(f'Definition normalization refused {covenant.id}: {error}')
        covenants = sorted(accepted, key=lambda c: c.id)[:1] if pilot else accepted
        terms = normalize(terms, covenants)
        if not covenants and not refusals:
            refusals.append(Refusal(scope='company', ref=discovery.company.cik, reason='ambiguous_definition',
                                    detail='Two extraction passes produced no supported maintenance financial covenant.'))
    else:
        notes.append('Company held closed because discovery or redaction prevents complete amendment coverage.')
    # Stable order and duplicate-refusal suppression make retries reviewable.
    unique_refusals = {fingerprint(r.model_dump()): r for r in refusals}
    notes.extend(f'Unresolved {r.scope} {r.ref}: {r.detail}' for r in unique_refusals.values()
                 if r.reason == 'ambiguous_definition')
    metrics = extractor.stats.as_dict()
    for key in ('compared', 'disagreed', 'verifier_calls', 'span_retries'):
        metrics[key] -= before[key]
    metrics['disagreement_rate'] = metrics['disagreed'] / metrics['compared'] if metrics['compared'] else None
    notes.append(METRICS_PREFIX + json.dumps(metrics, sort_keys=True))
    notes.append('Span offsets index the exact UTF-8 decoded SEC exhibit HTTP body, including HTML markup; '
                 'no whitespace normalization or HTML decoding is applied to evidence.')
    contract = ContractExtraction(schema_version=SCHEMA_VERSION, generated_at=datetime.now(timezone.utc),
        company=discovery.company, agreements=[d.agreement for d in documents],
        terms=terms, covenants=sorted(covenants, key=lambda c: c.id),
        refusals=list(unique_refusals.values()), extraction_notes=notes)
    verify_contract(contract, {d.key: d for d in documents})
    return ContractExtraction.model_validate_json(contract.model_dump_json())


def cached_contract(discovery: Discovery, directory: Path) -> ContractExtraction | None:
    path = directory / (discovery.company.cik + '.json')
    manifest_path = directory / '_evidence' / (discovery.company.cik + '.json')
    if not path.exists() or not manifest_path.exists() or discovery.refusals:
        return None
    try:
        manifest = json.loads(manifest_path.read_text())
        contract = ContractExtraction.model_validate_json(path.read_text())
        if (manifest.get('pipeline') != pipeline_fingerprint()
                or manifest.get('sources') != source_fingerprints(discovery)
                or manifest.get('output') != fingerprint(contract.model_dump(mode='json'))
                or contract.company != discovery.company or contract.schema_version != SCHEMA_VERSION
                or contract.agreements != [d.agreement for d in discovery.documents]):
            return None
        verify_contract(contract, {d.key: d for d in discovery.documents})
        normalize(contract.terms, contract.covenants, [d.text for d in discovery.documents])
        return contract
    except (ValueError, OSError, EvidenceError, DefinitionError):
        return None


def process_company(discovery: Discovery, extractor: Extractor, directory: Path = CONTRACTS, *, pilot=False) -> tuple[ContractExtraction, bool]:
    existing = cached_contract(discovery, directory)
    if existing is not None:
        return existing, True
    contract = build_contract(discovery, extractor, pilot=pilot)
    # Validate a round trip and evidence BEFORE replacing any earlier valid output.
    payload = contract.model_dump(mode='json')
    ContractExtraction.model_validate(payload)
    atomic_json(directory / (contract.company.cik + '.json'), payload)
    atomic_json(directory / '_evidence' / (contract.company.cik + '.json'),
                {'pipeline': pipeline_fingerprint(), 'sources': source_fingerprints(discovery),
                 'output': fingerprint(payload)})
    # Read the actual published bytes, not just the object that was intended to be written.
    published = ContractExtraction.model_validate_json((directory / (contract.company.cik + '.json')).read_text())
    verify_contract(published, {d.key: d for d in discovery.documents})
    return published, False


def universe_ciks() -> list[str]:
    if UNIVERSE.exists():
        payload = json.loads(UNIVERSE.read_text())
        entries = payload['universe'] if isinstance(payload, dict) else payload
        if not isinstance(entries, list) or not entries:
            raise ValueError('data/universe.json must contain a nonempty list of UniverseEntry records')
        return list(dict.fromkeys(f'{int(UniverseEntry.model_validate(entry).cik):010d}' for entry in entries))
    return [company.cik for company in dev_companies()]


def pilot_discovery(discovery: Discovery) -> Discovery:
    candidates = [d for d in discovery.documents if d.agreement.kind in {'original', 'restatement'}
                  and not d.agreement.redacted]
    if not candidates:
        raise ValueError('No complete, unredacted original/restated document available for a pilot')
    skipped = []
    for selected in sorted(candidates, key=lambda d: (d.agreement.filed, d.key), reverse=True):
        try:
            plan_context(selected, pilot=True).report()
        except ContextError as error:
            skipped.append(f'Pilot excluded {selected.key}: {error}')
            continue
        return Discovery(discovery.company, [selected], notes=[
            'PILOT ONLY: one locally plannable agreement and one covenant. Later amendments and complete '
            'company coverage are not certified. This file is not a production company artifact.', *skipped])
    raise ValueError('No complete document has a bounded local financial-covenant context')



def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--cik', help='SEC company CIK')
    group.add_argument('--universe', action='store_true', help='Read Dat\'s universe, otherwise discover 5 public dev borrowers')
    parser.add_argument('--plan-only', action='store_true', help='Report local retrieval plan without model calls')
    parser.add_argument('--pilot', action='store_true', help='One agreement, at most one covenant; writes under _pilots/')
    parser.add_argument('--max-cost-usd', help='Explicit total model budget for this invocation, including retries and Opus')
    args = parser.parse_args(argv)
    if args.pilot and args.universe:
        parser.error('--pilot requires a single --cik')
    agent = os.environ.get('SEC_USER_AGENT', '')
    if not agent.startswith('Covenant Watch ') or '@' not in agent:
        print('SEC_USER_AGENT must be set to Covenant Watch followed by a contact email.', file=sys.stderr)
        return 2
    if not args.plan_only and args.max_cost_usd is None:
        print('Paid extraction requires --max-cost-usd. Use --plan-only for an offline model-free plan.', file=sys.stderr)
        return 2
    if not args.plan_only and not os.environ.get('ANTHROPIC_API_KEY'):
        print('ANTHROPIC_API_KEY is missing.', file=sys.stderr)
        return 2
    runtime = None
    try:
        if args.cik and (not args.cik.isdigit() or not 0 < int(args.cik) < 10**10):
            raise ValueError('CIK must contain 1 to 10 digits and be positive')
        if not args.plan_only:
            runtime = Runtime(CONTRACTS, args.max_cost_usd)
            extractor = Extractor(runtime=runtime, pilot=args.pilot)
            extractor.preflight()
        ciks = [f'{int(args.cik):010d}'] if args.cik else universe_ciks()
        completed, failures, plans = [], [], []
        for cik in ciks:
            print(f'Discovering {cik}...', file=sys.stderr, flush=True)
            try:
                discovery = discover(cik)
                if args.pilot:
                    discovery = pilot_discovery(discovery)
                if args.plan_only:
                    for document in discovery.documents:
                        plans.append(plan_context(document, pilot=args.pilot).report())
                    failures.extend({'cik': cik, 'error': r.detail} for r in discovery.refusals)
                    continue
                if args.pilot:
                    contract, cached = process_company(discovery, extractor, CONTRACTS / '_pilots', pilot=True)
                else:
                    contract, cached = process_company(discovery, extractor)
                completed.append(contract)
                print(f'{cik}: {len(contract.covenants)} covenants, {len(contract.terms)} terms, '
                      f'{len(contract.refusals)} refusals, cached={cached}', file=sys.stderr, flush=True)
            except (httpx.HTTPError, DiscoveryError, EvidenceError, DefinitionError, ContextError, ValueError, OSError) as error:
                failures.append({'cik': cik, 'error': str(error)})
                print(f'{cik}: failed, output not counted as verified: {error}', file=sys.stderr, flush=True)
        if args.plan_only:
            print(json.dumps(dict(mode='plan', inference_started=False, plans=plans, failures=failures), indent=2))
            return 1 if failures else 0
        report = summarize(completed) | {'requested_companies': len(ciks), 'failed_companies': failures,
                 'mode': 'pilot' if args.pilot else 'company', 'charged_or_reserved_usd': str(runtime.charged),
                 'budget_usd': str(runtime.cap), 'ledger': str(runtime.ledger_path) if runtime.ledger_path.exists() else None}
        print(json.dumps(report, indent=2))
        return 1 if failures or any(not c.covenants or c.refusals for c in completed) else 0
    except BudgetError as error:
        print(f'Budget/checkpoint stop: {error}', file=sys.stderr)
        if runtime:
            print(f'Charged or reserved: ${runtime.charged}; ledger: {runtime.ledger_path}', file=sys.stderr)
        return 2
    except anthropic.AuthenticationError:
        print('Anthropic rejected ANTHROPIC_API_KEY (HTTP 401). Live extraction stopped.', file=sys.stderr)
        return 2
    except (anthropic.APIError, ExtractionError, httpx.HTTPError, DiscoveryError, ValueError, OSError) as error:
        print(f'Contracts run stopped: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
