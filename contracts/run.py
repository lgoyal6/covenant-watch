"""Write verified shared-schema contracts: python -m contracts.run --cik X / --universe."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
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


def build_contract(discovery: Discovery, extractor: Extractor) -> ContractExtraction:
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
        covenants = accepted
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


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.stem + '-', suffix='.tmp', delete=False) as handle:
            temp = Path(handle.name)
            json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write('\n')
        temp.replace(path)
    finally:
        if temp and temp.exists():
            temp.unlink()


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


def process_company(discovery: Discovery, extractor: Extractor, directory: Path = CONTRACTS) -> tuple[ContractExtraction, bool]:
    existing = cached_contract(discovery, directory)
    if existing is not None:
        return existing, True
    contract = build_contract(discovery, extractor)
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--cik', help='SEC company CIK')
    group.add_argument('--universe', action='store_true', help='Read Dat\'s universe, otherwise discover 5 public dev borrowers')
    args = parser.parse_args(argv)
    agent = os.environ.get('SEC_USER_AGENT', '')
    if not agent.startswith('Covenant Watch ') or '@' not in agent:
        print('SEC_USER_AGENT must be set to Covenant Watch followed by a contact email.', file=sys.stderr)
        return 2
    if not os.environ.get('ANTHROPIC_API_KEY'):
        print('ANTHROPIC_API_KEY is missing.', file=sys.stderr)
        return 2
    try:
        if args.cik and (not args.cik.isdigit() or not 0 < int(args.cik) < 10**10):
            raise ValueError('CIK must contain 1 to 10 digits and be positive')
        extractor = Extractor()
        extractor.preflight()
        ciks = [f'{int(args.cik):010d}'] if args.cik else universe_ciks()
        completed = []
        failures = []
        for cik in ciks:
            print(f'Discovering {cik}...', file=sys.stderr, flush=True)
            try:
                discovery = discover(cik)
                contract, cached = process_company(discovery, extractor)
                completed.append(contract)
                print(f'{cik}: {len(contract.covenants)} covenants, {len(contract.terms)} terms, '
                      f'{len(contract.refusals)} refusals, cached={cached}', file=sys.stderr, flush=True)
            except (httpx.HTTPError, DiscoveryError, EvidenceError, DefinitionError, ValueError, OSError) as error:
                failures.append({'cik': cik, 'error': str(error)})
                print(f'{cik}: failed, output not counted as verified: {error}', file=sys.stderr, flush=True)
        report = summarize(completed) | {'requested_companies': len(ciks), 'failed_companies': failures}
        print(json.dumps(report, indent=2))
        # Refusal-only files are valid artifacts, but never an extraction success.
        return 1 if failures or any(not c.covenants or c.refusals for c in completed) else 0
    except anthropic.AuthenticationError:
        print('Anthropic rejected ANTHROPIC_API_KEY (HTTP 401). Live extraction stopped.', file=sys.stderr)
        return 2
    except (anthropic.APIError, ExtractionError, httpx.HTTPError, DiscoveryError, ValueError, OSError) as error:
        print(f'Contracts run stopped: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
