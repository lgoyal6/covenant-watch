from datetime import date

from contracts import discover as discovery


def test_exhibit_table_and_classification():
    parser = discovery.ExhibitIndex()
    parser.feed('<table><tr><td>2</td><td>Credit Agreement</td><td><a href="ex10.htm">ex10.htm</a></td>'
                '<td>EX-10.1</td><td>100</td></tr></table>')
    assert parser.rows == [('Credit Agreement', 'EX-10.1', 'ex10.htm')]
    assert discovery.agreement_kind('FIRST AMENDMENT to AMENDED AND RESTATED CREDIT AGREEMENT') == 'amendment'
    assert discovery.agreement_kind('AMENDED AND RESTATED CREDIT AGREEMENT') == 'restatement'
    assert discovery.credit_document('<p>CREDIT AGREEMENT</p><p>Borrower and Lenders</p>')
    assert discovery.redacted('<p>[***]</p>')
    assert discovery.redacted('Confidential treatment requested')


def test_search_pagination_includes_exhibits(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return {'hits': {'total': {'value': 2}, 'hits': [{'_id': str(len(calls))}]}}

    monkeypatch.setattr(discovery.edgar, 'get_json', get)
    assert len(list(discovery.search('"ratio"', cik='1', end=date(2024, 1, 1)))) == 2
    assert 'forms=-0' in calls[0] and 'ciks=0000000001' in calls[0]
    assert 'from=1' in calls[1]


def test_discovery_finds_amendment_not_in_search_and_historical_original(monkeypatch):
    monkeypatch.setattr(discovery, 'search', lambda *a, **k: iter([{'_source': {
        'ciks': ['0000000001'], 'adsh': 'b', 'file_date': '2024-01-01'}}]))
    monkeypatch.setattr(discovery.edgar, 'submissions', lambda cik: {
        'cik': '1', 'name': 'Borrower', 'tickers': ['BOR'], 'sic': '2000',
        'filings': {'recent': {'accessionNumber': ['b'], 'filingDate': ['2024-01-01'], 'form': ['8-K']},
                    'files': [{'name': 'older.json'}]}})
    monkeypatch.setattr(discovery.edgar, 'get_json', lambda url: {
        'accessionNumber': ['a'], 'filingDate': ['2022-01-01'], 'form': ['10-K']})

    def get(url):
        if url.endswith('-index.html'):
            return b'<tr><td>2</td><td>EX-10.1</td><td><a href="ex10.htm">x</a></td><td>EX-10.1</td></tr>'
        return (('AMENDMENT TO ' if '/b/' in url else '') +
                'CREDIT AGREEMENT between Borrower and Lenders').encode()

    monkeypatch.setattr(discovery.edgar, 'get', get)
    output = discovery.discover('1')
    assert not output.refusals
    assert [(d.agreement.accession, d.agreement.kind) for d in output.documents] == [('a', 'original'), ('b', 'amendment')]
