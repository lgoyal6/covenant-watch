from datetime import date

import pytest

from contracts.context import ContextError, bind_evidence, plan_context, readable, render
from contracts.models import Quote, SourceDocument
from contracts.segment import Segment
from contracts.verify import EvidenceError, verify_span
from shared.schema import Agreement


def document(text, kind='original'):
    return SourceDocument(Agreement(accession='a', url='https://www.sec.gov/a', filed=date(2022, 1, 1),
                                    kind=kind, redacted=False), text)


def test_readable_quote_maps_entities_and_markup_to_exact_raw_span():
    source = document('<style>noise</style><p>Debt is <b>$25&nbsp;million</b> &amp; fees.</p>')
    view = render(source.text)
    assert 'noise' not in view.text
    assert 'Debt is $25 million & fees.' in view.text
    span = bind_evidence(Quote(text='$25 million & fees.'), source, [Segment(0, len(source.text), source.text)])
    assert span.text == '$25&nbsp;million</b> &amp; fees.'
    verify_span(span, {source.key: source})
    with pytest.raises(EvidenceError):
        bind_evidence(Quote(text='$26 million'), source, [Segment(0, len(source.text), source.text)])


def test_quotes_cannot_escape_selected_ranges_or_choose_repeated_occurrence():
    source = document('<p>Debt</p><p>Debt</p>')
    with pytest.raises(EvidenceError):
        bind_evidence(Quote(text='Debt'), source, [Segment(0, len(source.text), source.text)])
    span = bind_evidence(Quote(text='Debt', char_start=3), source, [Segment(0, 11, source.text[:11])])
    assert span.char_start == 3
    with pytest.raises(EvidenceError):
        bind_evidence(Quote(text='Debt', char_start=14), source, [Segment(0, 11, source.text[:11])])


def test_targeted_context_follows_recursive_definitions_and_keeps_conditions():
    unrelated = '<p>' + 'Unrelated warranty. ' * 1000 + '</p>'
    source = document('<p>Credit Agreement, Borrower and Agent, January 1, 2022.</p>' + unrelated +
        '<p>SECTION 1.01 Definitions</p>'
        '<p>“Leverage Ratio” means Debt divided by EBITDA.</p>'
        '<p>“Debt” means total borrowings.</p>'
        '<p>“EBITDA” means Net Income plus Interest.</p>'
        '<p>“Net Income” means consolidated net income.</p>'
        '<p>“Interest” means total interest expense.</p>'
        '<p>“Unrelated” means irrelevant.</p>'
        '<p>SECTION 7.11 Financial Covenants</p>'
        '<p>Borrower shall not permit the Leverage Ratio to exceed 4.50 to 1.00.</p>'
        '<p>Applies only when revolving loans exceed $5 million.</p>'
        '<p>SECTION 8.01 Miscellaneous</p><p>No financial tests here.</p>')
    plan = plan_context(source)
    selected = '\n'.join(readable(source, part) for part in plan.units)
    assert 'Applies only when revolving loans' in selected
    assert set(plan.definitions) == {'leverage ratio', 'debt', 'ebitda', 'net income', 'interest'}
    assert '“Unrelated”' not in selected
    assert len(selected) < len(render(source.text).text) / 2
    assert {p.start for group in plan.layout() for p in group} == {p.start for group in plan.layout(True) for p in group}


def test_no_whole_document_fallback_and_no_silent_large_unit_truncation():
    with pytest.raises(ContextError):
        plan_context(document('<p>Operating agreement with no financial test.</p>'))
    source = document('<p>SECTION 7.11 Financial Covenants</p><p>Borrower shall maintain minimum liquidity. '
                      + 'Condition. ' * 2000 + '</p>')
    with pytest.raises(ContextError, match='exceeds'):
        plan_context(source).layout()


def test_amendment_keeps_non_ratio_changes():
    source = document('<p>Amendment: Section 1.01 is replaced with the following definition.</p>', 'amendment')
    plan = plan_context(source)
    assert 'replaced' in '\n'.join(readable(source, part) for part in plan.units)


def test_quote_from_hidden_markup_is_not_accepted_as_displayed_evidence():
    source = document('<style>made-up threshold 9.99</style><p>Real visible clause.</p>')
    with pytest.raises(EvidenceError):
        bind_evidence(Quote(text='made-up threshold 9.99'), source, [Segment(0, len(source.text), source.text)])


def test_step_down_table_rows_are_not_mistaken_for_section_headers():
    source = document('<p>Credit Agreement.</p><p>' + 'Unrelated warranty. ' * 500 + '</p>' +
        '<p>SECTION 7.11 Financial Covenants</p>'
        '<p>Borrower shall maintain leverage no greater than the following schedule:</p>'
        '<table><tr><td>4.50 to 1.00</td><td>through June 30, 2024</td></tr>'
        '<tr><td>3.50 to 1.00</td><td>thereafter</td></tr></table>'
        '<p>Applies only while revolving loans are outstanding.</p>'
        '<p>SECTION 8.01 Other Provisions</p>')
    selected = '\n'.join(readable(source, unit) for unit in plan_context(source).units)
    assert '3.50 to 1.00' in selected
    assert 'Applies only while revolving loans' in selected
    assert '1.00 through' in selected


def test_header_and_legal_roles_are_not_financial_dependency_roots():
    source = document('<p>Credit Agreement among Borrower, Lenders and Administrative Agent.</p>'
        '<p>' + 'Unrelated warranty. ' * 200 + '</p>'
        '<p>SECTION 1.01 Definitions</p>'
        '<p>“Borrower” means Example Corporation, an Affiliate of Person.</p>'
        '<p>“Lenders” means every Person governed by Boilerplate.</p>'
        '<p>“Boilerplate” means Unrelated Rate.</p>'
        '<p>“Unrelated Rate” means a published benchmark.</p>'
        '<p>“Debt” means aggregate principal borrowings of Borrower.</p>'
        '<p>SECTION 7.11 Financial Covenants</p>'
        '<p>Borrower shall maintain minimum liquidity and Debt below the maximum.</p>'
        '<p>SECTION 8.01 Other Provisions</p>')
    plan = plan_context(source)
    selected = '\n'.join(readable(source, unit) for unit in plan.units)
    assert '“Debt”' in selected and '“Borrower”' in selected
    assert '“Boilerplate”' not in selected and '“Unrelated Rate”' not in selected
