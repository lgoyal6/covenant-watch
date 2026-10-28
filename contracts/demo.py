"""Prepare example timelines plus source-verified SEC threshold observations, without inference."""

import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from shared import edgar
from shared.paths import CONTRACTS, FIXTURES
from shared.schema import Agreement, ContractExtraction, CovenantArtifact
from contracts.context import bind_evidence, plan_context, readable
from contracts.models import Quote, SourceDocument
from contracts.runtime import atomic_json
from contracts.verify import all_spans, verify_contract, verify_number

SEC_URL = 'https://www.sec.gov/Archives/edgar/data/1590955/000119312522210029/d362080dex101.htm'
SEC_ACCESSION = '0001193125-22-210029'


def example_artifact():
    artifact = CovenantArtifact.model_validate_json((FIXTURES / 'artifact_example.json').read_text())
    payload = artifact.model_dump(mode='json')
    mapping = {a.url: f'https://example.invalid/covenant-watch/{a.accession}' for a in artifact.contract.agreements}

    def replace(value):
        if isinstance(value, dict):
            return {key: (mapping.get(item, item) if key == 'url' and isinstance(item, str) else replace(item))
                    for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return value

    payload = replace(payload)
    payload['contract']['company']['name'] = 'Example Holdings, Inc. (Example data)'
    payload['contract']['extraction_notes'].append(
        'Synthetic example contract and financial values. Not a real company or an extraction accuracy result.')
    payload['generated_at'] = payload['contract']['generated_at'] = datetime.now(timezone.utc).isoformat()
    for quarter in payload['quarters']:
        for item in quarter['inputs']:
            if item['fact_accession']:
                item['fact_accession'] = 'example:financial-inputs'
    artifact = CovenantArtifact.model_validate(payload)
    sources = {}
    for agreement in artifact.contract.agreements:
        text = 'SYNTHETIC EXAMPLE DATA. Example Holdings and Example Agent.\n'
        for span in sorted((s for s in all_spans(artifact.contract) if s.url == agreement.url),
                           key=lambda s: s.char_start):
            gap = span.char_start - len(text)
            if gap < 0:
                raise ValueError('Example source spans overlap')
            text += ('\n\n' + ' ' * (gap - 2) if gap >= 2 else ' ' * gap) + span.text
        sources[agreement.url] = SourceDocument(agreement, text)
    verify_contract(artifact.contract, sources)
    return artifact, sources


def threshold_observations(source):
    plan = plan_context(source, pilot=True)
    section = next((unit for unit in plan.units if re.search(r'Financial\s+Covenants', readable(source, unit)[:250], re.I)), None)
    if section is None:
        raise ValueError('No complete financial-covenant section found')
    text = readable(source, section)
    match = re.search(r'SECTION\s+(\d+\.\d+)', text, re.I)
    label = match[1] + '(a)' if match else None
    months = 'January|February|March|April|May|June|July|August|September|October|November|December'
    pattern = re.compile(r'(?P<date>(?:' + months + r')\s+\d{1,2},\s+\d{4})'
                         r'(?P<after>\s+and\s+thereafter)?\s+(?P<ratio>\d+(?:\.\d+)?)\s+to\s+1\.00', re.I)
    rows = []
    for match in pattern.finditer(text):
        date_text = re.sub(r'\s+', ' ', match['date'])
        period_end = datetime.strptime(date_text, '%B %d, %Y').date()
        value = float(match['ratio'])
        span = bind_evidence(Quote(text=match[0], section=label), source, [section])
        verify_number(value, span.text)
        rows.append(dict(period_end=period_end.isoformat(), maximum_leverage_ratio=value,
                         applies_thereafter=bool(match['after']), source=span.model_dump(mode='json')))
    if not rows:
        raise ValueError('No complete, source-matched threshold rows found')
    return rows


def prepare_demo(directory=CONTRACTS / '_demo'):
    directory = Path(directory)
    artifact, sources = example_artifact()
    contract = artifact.contract
    atomic_json(directory / 'example_contract.json', contract.model_dump(mode='json'))
    atomic_json(directory / 'example_artifact.json', artifact.model_dump(mode='json'))
    for source in sources.values():
        path = directory / 'example_sources' / (source.agreement.accession + '.txt')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source.text, encoding='utf-8')
    source = SourceDocument(Agreement(accession=SEC_ACCESSION, url=SEC_URL, filed=date(2022, 8, 2),
                                     kind='original', redacted=False), edgar.get(SEC_URL).decode('utf-8', errors='strict'))
    rows = threshold_observations(source)
    real = dict(data_origin='SEC document', company=dict(cik='0001590955', name='Paycom Software, Inc.', ticker='PAYC'),
                agreement_url=SEC_URL, source_sha256=hashlib.sha256(source.text.encode()).hexdigest(),
                verification='Every threshold quotation matches the original filing at its raw character offsets.',
                scope='Contract thresholds only. Financial ratios, headroom and current amended terms are not verified.',
                financial_ratios_verified=False, observations=rows)
    atomic_json(directory / 'real_sec_thresholds.json', real)
    manifest = dict(
        example=dict(data_origin='synthetic example', artifact='example_artifact.json', contract='example_contract.json',
                     companies=1, covenants=len(contract.covenants), terms=len(contract.terms),
                     quarter_records=len(artifact.quarters), quarter_ends=len({q.period_end for q in artifact.quarters}),
                     statuses=dict(Counter(q.status for q in artifact.quarters))),
        real=dict(data_origin='SEC document', file='real_sec_thresholds.json', source_verified_thresholds=len(rows),
                  financial_ratios_verified=False),
        display=dict(example_label='Example data', real_label='SEC contract thresholds',
                     rule='Keep example financial values separate from real-company observations.'))
    atomic_json(directory / 'manifest.json', manifest)
    # Verify published bytes and reconstructed source bodies, rather than only the inputs.
    published = CovenantArtifact.model_validate_json((directory / 'example_artifact.json').read_text())
    ContractExtraction.model_validate_json((directory / 'example_contract.json').read_text())
    verify_contract(published.contract, sources)
    saved = json.loads((directory / 'real_sec_thresholds.json').read_text())
    from contracts.verify import verify_span
    from shared.schema import Span
    for row in saved['observations']:
        verify_span(Span.model_validate(row['source']), {source.key: source})
    return manifest


if __name__ == '__main__':
    print(json.dumps(prepare_demo(), indent=2))
