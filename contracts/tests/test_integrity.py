from datetime import date

import pytest

from shared.schema import Agreement, Covenant, Span, TermNode, Threshold
from contracts.amendments import AmendmentError, apply_amendments, overlay, validate_schedule
from contracts.definitions import DefinitionError, normalize
from contracts.models import DocumentResult, Quote, SourceDocument
from contracts.segment import chunks, segment
from contracts.verify import EvidenceError, bind_quote, verify_span


@pytest.fixture
def source():
    text = 'ARTICLE I\nSECTION 1.01 Definitions\n"Debt" means total borrowings.\nSECTION 7.11 Maximum leverage 4.50 to 1.00.'
    return SourceDocument(Agreement(accession='a', url='https://www.sec.gov/a',
                          filed=date(2022, 3, 15), kind='original', redacted=False), text)


def node(source, id='debt', **kwargs):
    span = bind_quote(Quote(text='total borrowings'), source)
    return TermNode(id=id, label=id, op='leaf', span=span, **kwargs)


def covenant(source, **kwargs):
    span = bind_quote(Quote(text='Maximum leverage 4.50 to 1.00.'), source)
    values = dict(id='lev', kind='max_leverage', direction='max', numerator_term='debt',
                  denominator_term=None, test_period='point_in_time', agreement_accession='a', span=span,
                  thresholds=[Threshold(effective_from=date(2022, 3, 15), value=4.5, source=span)])
    return Covenant(**(values | kwargs))


def result(source, terms=None, covenants=None, **kwargs):
    span = bind_quote(Quote(text='ARTICLE I'), source)
    values = dict(source=source, facility_id='facility', facility_source=span,
                  effective_date=source.agreement.filed, effective_date_source=span,
                  terms=terms if terms is not None else [node(source)],
                  covenants=covenants if covenants is not None else [covenant(source)],
                  removed_covenants={}, refusals=[], notes=[])
    return DocumentResult(**(values | kwargs))


def test_span_exact_and_source_bound(source):
    span = bind_quote(Quote(text='total borrowings'), source)
    verify_span(span, {source.key: source})
    for update in [{'char_start': span.char_start + 1}, {'char_end': -1}, {'text': 'invented'},
                   {'url': 'other'}, {'accession': 'wrong'}]:
        with pytest.raises(EvidenceError):
            verify_span(span.model_copy(update=update), {source.key: source})
    with pytest.raises(EvidenceError):
        bind_quote(Quote(text='Total borrowings'), source)


def test_repeated_quotes_require_exact_hint(source):
    repeated = SourceDocument(source.agreement, 'debt debt')
    with pytest.raises(EvidenceError):
        bind_quote(Quote(text='debt'), repeated)
    assert bind_quote(Quote(text='debt', char_start=5), repeated).char_start == 5
    with pytest.raises(EvidenceError):
        bind_quote(Quote(text='debt', char_start=1), repeated)


def test_segmentation_and_chunk_layouts_preserve_all_characters(source):
    text = source.text * 20
    sections = segment(text)
    assert ''.join(s.text for s in sections) == text
    layouts = [chunks(text, alternate=alt, size=128) for alt in (False, True)]
    assert [(s.start, s.end) for s in layouts[0]] != [(s.start, s.end) for s in layouts[1]]
    for layout in layouts:
        covered = set()
        for chunk in layout:
            assert text[chunk.start:chunk.end] == chunk.text
            covered.update(range(chunk.start, chunk.end))
        assert covered == set(range(len(text)))


def test_normalize_topology_prunes_orphans_and_checks_cap(source):
    debt = node(source)
    base = node(source, id='base')
    cap = node(source, id='cap').model_copy(update={'op': 'cap', 'children': ['debt'],
                    'cap': {'kind': 'pct_of', 'of': 'base', 'pct': 0.1}})
    normalized = normalize([cap, debt, base, node(source, id='orphan')],
                           [covenant(source, numerator_term='cap')])
    assert [n.id for n in normalized] == ['base', 'debt', 'cap']
    with pytest.raises(DefinitionError, match='missing term'):
        normalize([cap, debt], [covenant(source, numerator_term='cap')])
    cyclic = base.model_copy(update={'op': 'sum', 'children': ['cap']})
    with pytest.raises(DefinitionError, match='cycle'):
        normalize([cap, debt, cyclic], [covenant(source, numerator_term='cap')])


def test_non_atomic_leaf_is_rejected(source):
    bad = node(source).model_copy(update={'label': 'Debt'})
    with pytest.raises(DefinitionError, match='unexpanded'):
        normalize([bad], [covenant(source)], ['"Debt" means Funded Debt. "Funded Debt" means total borrowings.'])


def test_temporary_amendment_preserves_future_steps(source):
    span = covenant(source).span
    old = [Threshold(effective_from=date(2022, 3, 15), effective_to=date(2024, 12, 31), value=4.5, source=span),
           Threshold(effective_from=date(2025, 1, 1), value=4.0, source=span)]
    new = [Threshold(effective_from=date(2023, 8, 1), effective_to=date(2024, 6, 30), value=5.25, source=span)]
    output = overlay(old, new, date(2023, 8, 1))
    assert [(t.effective_from, t.effective_to, t.value) for t in output] == [
        (date(2022, 3, 15), date(2023, 7, 31), 4.5),
        (date(2023, 8, 1), date(2024, 6, 30), 5.25),
        (date(2024, 7, 1), date(2024, 12, 31), 4.5), (date(2025, 1, 1), None, 4.0)]
    with pytest.raises(AmendmentError):
        validate_schedule(old + new)


def test_apply_amendment_replaces_definition_adds_covenant_and_isolates_facilities(source):
    amended_source = SourceDocument(source.agreement.model_copy(update={
        'accession': 'b', 'url': 'https://www.sec.gov/b', 'filed': date(2023, 8, 1), 'kind': 'amendment'}), source.text)
    base = result(source)
    amended_node = node(amended_source).model_copy(update={'label': 'replaced debt'})
    threshold = covenant(amended_source).thresholds[0].model_copy(update={
        'effective_from': date(2023, 8, 1), 'value': 5.25})
    amended_cov = covenant(amended_source, thresholds=[threshold])
    added = amended_cov.model_copy(update={'id': 'extra'})
    amendment = result(amended_source, [amended_node], [amended_cov, added])
    other = result(source, facility_id='another')
    terms, covenants, refusals, _ = apply_amendments([amendment, other, base])
    assert not refusals
    by_id = {c.id: c for c in covenants}
    assert len(by_id) == 3
    assert [t.value for t in by_id['facility:lev'].thresholds] == [4.5, 5.25]
    assert [t.value for t in by_id['another:lev'].thresholds] == [4.5]
    assert {n.id: n.label for n in terms}['facility:debt'] == 'replaced debt'


def test_missing_base_or_uncited_lineage_blocks_publication(source):
    amendment = SourceDocument(source.agreement.model_copy(update={'kind': 'amendment'}), source.text)
    terms, covenants, refusals, _ = apply_amendments([result(amendment)])
    assert not terms and not covenants and refusals[0].reason == 'missing_filing'
    bad = result(amendment, facility_id=None)
    terms, covenants, refusals, _ = apply_amendments([result(source), bad])
    assert not covenants and refusals


def test_definition_index_stops_at_separate_paragraph(source):
    from contracts.segment import defined_terms
    text = '"Interest Expense" means total interest expense\n\nUnrelated cap based on Consolidated EBITDA.\n\n"Consolidated EBITDA" means net income.'
    assert 'Consolidated EBITDA' not in defined_terms(text)['interest expense']


def test_number_claims_must_match_cited_values_and_scaling():
    from contracts.verify import verify_number
    verify_number(25_000_000, 'not more than $25 million')
    verify_number(0.10, 'capped at 10% of EBITDA', percentage=True)
    verify_number(4.5, 'maximum 4.50 to 1.00')
    with pytest.raises(EvidenceError):
        verify_number(5.25, 'maximum 4.50 to 1.00')
    with pytest.raises(EvidenceError):
        verify_number(0.10, 'a fee of $0.10', percentage=True)


def test_html_section_headers_do_not_split_inline_cross_references():
    text = '<p>SECTION 1.01 Definitions</p><p>See Section 7.11 for limits.</p><p>SECTION 7.11 Financial Covenants</p>'
    parts = segment(text)
    assert [s.section for s in parts if s.section] == ['SECTION 1.01', 'SECTION 7.11']
    assert ''.join(s.text for s in parts) == text
