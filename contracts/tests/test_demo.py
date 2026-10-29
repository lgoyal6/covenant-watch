from datetime import date

from shared.schema import Agreement
from contracts.demo import example_artifact, threshold_observations
from contracts.models import SourceDocument
from contracts.verify import all_spans, verify_contract


def test_example_timeline_has_clear_origin_and_no_fake_sec_links():
    artifact, sources = example_artifact()
    assert 'Example data' in artifact.contract.company.name
    assert len(artifact.contract.covenants) == 2 and len(artifact.contract.terms) == 10
    assert len(artifact.quarters) == 16
    assert verify_contract(artifact.contract, sources) == 16
    assert all(s.url.startswith('https://example.invalid/') for s in all_spans(artifact.contract))
    assert {q.status for q in artifact.quarters} >= {'ok', 'warning', 'indeterminate', 'refused'}
    assert all(i.fact_accession is None for q in artifact.quarters for i in q.inputs)


def test_real_threshold_reader_uses_exact_document_rows_and_marks_scope():
    text = ('<p>SECTION 6.11 Financial Covenants</p><p>Borrower shall not permit leverage above the following:</p>'
            '<table><tr><td>September 30, 2022</td><td>3.75 to 1.00</td></tr>'
            '<tr><td>December 31, 2025 and thereafter</td><td>3.00 to 1.00</td></tr></table>'
            '<p>SECTION 8.01 Other Provisions</p>')
    source = SourceDocument(Agreement(accession='a', url='https://www.sec.gov/test', filed=date(2022, 8, 2),
                                     kind='original', redacted=False), text)
    rows = threshold_observations(source)
    assert [(r['period_end'], r['maximum_leverage_ratio'], r['applies_thereafter']) for r in rows] == [
        ('2022-09-30', 3.75, False), ('2025-12-31', 3.0, True)]
    for row in rows:
        span = row['source']
        assert text[span['char_start']:span['char_end']] == span['text']
