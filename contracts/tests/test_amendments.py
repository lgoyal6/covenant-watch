from datetime import date

from contracts.amendments import apply_amendments
from contracts.models import SourceDocument
from contracts.tests.test_integrity import covenant, node, result, source


def test_threshold_only_amendment_keeps_original_clause_provenance(source):
    amended = SourceDocument(source.agreement.model_copy(update={'accession': 'b', 'url': 'https://www.sec.gov/b',
                    'kind': 'amendment', 'filed': date(2023, 8, 1)}), source.text)
    threshold = covenant(amended).thresholds[0].model_copy(update={'effective_from': date(2023, 8, 1), 'value': 5.25})
    _, covenants, refusals, _ = apply_amendments([result(source), result(amended,
                                    covenants=[covenant(amended, thresholds=[threshold])])])
    assert not refusals
    actual = covenants[0]
    assert actual.agreement_accession == source.agreement.accession
    assert actual.span.url == source.key
    assert actual.thresholds[-1].source.url == amended.key


def test_restatement_replaces_facility_and_explicit_deletion_removes_covenant(source):
    restated = SourceDocument(source.agreement.model_copy(update={'accession': 'b', 'url': 'https://www.sec.gov/b',
                    'kind': 'restatement', 'filed': date(2023, 8, 1)}), source.text)
    replacement = covenant(restated).model_copy(update={'id': 'new'})
    _, covenants, refusals, _ = apply_amendments([result(source), result(restated, covenants=[replacement])])
    assert not refusals and [c.id for c in covenants] == ['facility:new']
    amended = SourceDocument(restated.agreement.model_copy(update={'kind': 'amendment'}), restated.text)
    deletion = result(amended, terms=[], covenants=[], removed_covenants={'lev': covenant(amended).span})
    _, covenants, refusals, _ = apply_amendments([result(source), deletion])
    assert not refusals and not covenants


def test_empty_amendment_cannot_silently_assert_no_financial_change(source):
    amended = SourceDocument(source.agreement.model_copy(update={'accession': 'b', 'url': 'https://www.sec.gov/b',
                    'kind': 'amendment', 'filed': date(2023, 8, 1)}), source.text)
    _, covenants, refusals, _ = apply_amendments([result(source), result(amended, terms=[], covenants=[])])
    assert not covenants
    assert any(r.reason == 'ambiguous_definition' for r in refusals)
