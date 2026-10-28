"""Offline golden integration test. Claude transport is mocked, not live accuracy evidence."""

from shared.paths import FIXTURES
from shared.schema import ContractExtraction
from contracts.discover import Discovery
from contracts.extract import Extractor
from contracts.models import Quote, QuotedCovenant, QuotedTerm, QuotedThreshold, Reading, SourceDocument
from contracts.run import build_contract
from contracts.tests.test_extract import FakeExtractor
from contracts.verify import all_spans, verify_contract


def test_synthetic_agreement_reproduces_frozen_fixture_structure():
    golden = ContractExtraction.model_validate_json((FIXTURES / 'contract_example.json').read_text())
    original, amendment = golden.agreements
    documents = []
    # The frozen fixture intentionally uses synthetic, disjoint quotation offsets.
    # Reconstruct only synthetic source bodies here, never real SEC data.
    for agreement, header in [(original, 'Effective March 15, 2022'), (amendment, 'Effective August 1, 2023')]:
        text = 'SYNTHETIC TEST ONLY. Example Holdings and Example Agent, original facility March 15, 2022. ' + header + '.\n'
        spans = sorted((span for span in all_spans(golden) if span.accession == agreement.accession),
                       key=lambda span: span.char_start)
        for span in spans:
            assert span.char_start >= len(text)
            padding = span.char_start - len(text)
            text += ('\n\n' + ' ' * (padding - 2) if padding >= 2 else ' ' * padding) + span.text
        documents.append(SourceDocument(agreement, text))

    def quote(span):
        return Quote(text=span.text, section=span.section, char_start=span.char_start)

    def quoted_threshold(threshold):
        return QuotedThreshold(**(threshold.model_dump() | {'source': quote(threshold.source)}))

    def quoted_covenant(covenant, thresholds, span=None, accession=None):
        return QuotedCovenant(**(covenant.model_dump() | {
            'span': quote(span or covenant.span), 'thresholds': [quoted_threshold(t) for t in thresholds],
            'agreement_accession': accession or covenant.agreement_accession}))

    leverage, coverage = golden.covenants
    initial = leverage.thresholds[0].model_copy(update={'effective_to': None})
    response_original = Reading(is_credit_agreement=True, facility_id='fixture',
        facility_source=Quote(text='Example Holdings and Example Agent, original facility March 15, 2022.'),
        effective_date=original.filed, effective_date_source=Quote(text='Effective March 15, 2022'),
        terms=[QuotedTerm(**(n.model_dump() | {'span': quote(n.span)})) for n in golden.terms],
        covenants=[quoted_covenant(leverage, [initial]), quoted_covenant(coverage, coverage.thresholds)])
    response_amendment = Reading(is_credit_agreement=True, facility_id='fixture',
        facility_source=response_original.facility_source, effective_date=amendment.filed,
        effective_date_source=Quote(text='Effective August 1, 2023'),
        covenants=[quoted_covenant(leverage, leverage.thresholds[1:],
                                  span=leverage.thresholds[1].source, accession=amendment.accession)])
    extractor = FakeExtractor(lambda source, ranges, kwargs, number:
                             response_original if source.agreement.accession == original.accession else response_amendment)
    actual = build_contract(Discovery(golden.company, documents), extractor)
    assert not actual.refusals
    assert verify_contract(actual, {d.key: d for d in documents}) == 16

    def remove_namespace(model):
        data = model.model_dump(mode='json')
        for key in ('id', 'numerator_term', 'denominator_term'):
            if data.get(key):
                data[key] = data[key].removeprefix('fixture:')
        if 'children' in data:
            data['children'] = [key.removeprefix('fixture:') for key in data['children']]
        if data.get('cap') and data['cap'].get('kind') == 'pct_of':
            data['cap']['of'] = data['cap']['of'].removeprefix('fixture:')
        return data

    assert {n.id.removeprefix('fixture:'): remove_namespace(n) for n in actual.terms} == {
        n.id: n.model_dump(mode='json') for n in golden.terms}
    assert {c.id.removeprefix('fixture:'): remove_namespace(c) for c in actual.covenants} == {
        c.id: c.model_dump(mode='json') for c in golden.covenants}
