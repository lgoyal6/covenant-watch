"""SEC agreement discovery using full-text search and the full submissions history."""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from shared import edgar
from shared.schema import Agreement, Company, Refusal
from contracts.models import SourceDocument
from contracts.segment import visible_text


class DiscoveryError(RuntimeError):
    pass


@dataclass
class Discovery:
    company: Company
    documents: list[SourceDocument] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class ExhibitIndex(HTMLParser):
    """Read the SEC document table, including generic EX-10 descriptions."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self.cells = None
        self.cell = None
        self.href = None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.cells, self.href = [], None
        if tag == 'td' and self.cells is not None:
            self.cell = []
        if tag == 'a' and self.cell is not None:
            self.href = dict(attrs).get('href')

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == 'td' and self.cell is not None:
            self.cells.append(''.join(self.cell).strip())
            self.cell = None
        if tag == 'tr' and self.cells is not None:
            if len(self.cells) >= 4 and self.href:
                self.rows.append((self.cells[1], self.cells[3], self.href))
            self.cells = None


def search(query: str, *, cik: str | None = None, start: date = date(1994, 1, 1),
           end: date | None = None):
    """forms=-0 includes exhibits. EX-10 is not a valid EFTS forms filter."""
    end = end or date.today()
    offset = 0
    while True:
        params = dict(q=query, forms='-0', dateRange='custom', startdt=start.isoformat(),
                      enddt=end.isoformat(), **{'from': str(offset)})
        if cik:
            params['ciks'] = f'{int(cik):010d}'
        data = edgar.get_json(str(httpx.URL('https://efts.sec.gov/LATEST/search-index', params=params)),
                              use_cache=False)
        if data.get('timed_out') or data.get('_shards', {}).get('failed', 0):
            raise DiscoveryError('SEC search timed out or returned failed shards')
        total = data['hits']['total']
        count = total['value'] if isinstance(total, dict) else total
        if count >= 10000:
            if start == end:
                raise DiscoveryError('SEC search exceeds its 10,000-hit window for one day')
            midpoint = start + (end - start) // 2
            yield from search(query, cik=cik, start=start, end=midpoint)
            yield from search(query, cik=cik, start=midpoint + timedelta(days=1), end=end)
            return
        hits = data['hits']['hits']
        yield from hits
        offset += len(hits)
        if offset >= count:
            return
        if not hits:
            raise DiscoveryError('SEC search stopped before its advertised total')


def company_from_submissions(data: dict) -> Company:
    tickers = data.get('tickers', [])
    return Company(cik=f"{int(data['cik']):010d}", name=data['name'],
                   ticker=tickers[0] if tickers else None, sic=str(data['sic']) if data.get('sic') else None)


def filing_rows(data: dict):
    accessions = data.get('accessionNumber', [])
    for key in ('filingDate', 'form'):
        if len(data.get(key, [])) != len(accessions):
            raise DiscoveryError('submissions filing columns have unequal lengths')
    yield from zip(accessions, data['filingDate'], data['form'])


def redacted(text: str) -> bool:
    return bool(re.search(r'\[\s*\*{3,}\s*\]|confidential\s+treatment\s+requested', visible_text(text), re.I))


def agreement_kind(text: str) -> str:
    heading = visible_text(text)[:10000]
    if re.search(r'\b(?:amendment|waiver|consent|modification|joinder)\b', heading[:2500], re.I):
        return 'amendment'
    if re.search(r'\b(?:amended\s+and\s+restated|restatement|restated)\b', heading[:2500], re.I):
        return 'restatement'
    return 'original'


def credit_document(text: str) -> bool:
    heading = visible_text(text)[:30000]
    return bool(re.search(r'\b(?:credit|loan|financing)\s+agreement\b', heading, re.I)
                and re.search(r'\b(?:borrower|lender|administrative agent)\b', heading, re.I))


def discover(cik: str) -> Discovery:
    data = edgar.submissions(cik)
    output = Discovery(company_from_submissions(data))
    filings = {}
    # Full-text hits identify older agreements and filings that mention later changes.
    try:
        for hit in search('"credit agreement" OR "loan agreement" OR "financing agreement"', cik=cik):
            record = hit['_source']
            if any(int(value) == int(cik) for value in record.get('ciks', [])):
                filings[record['adsh']] = record['file_date']
    except (DiscoveryError, httpx.HTTPError, KeyError, ValueError) as error:
        output.refusals.append(Refusal(scope='company', ref=output.company.cik,
                              reason='missing_filing', detail=f'Incomplete full-text search: {error}'))
    # Submissions are independent of keyword hits, so amendments lacking the ratio
    # phrase are still inspected. Include historical submission pages, not only recent.
    histories = [data['filings']['recent']]
    for page in data['filings'].get('files', []):
        try:
            histories.append(edgar.get_json('https://data.sec.gov/submissions/' + page['name']))
        except (httpx.HTTPError, RuntimeError) as error:
            output.refusals.append(Refusal(scope='company', ref=output.company.cik,
                                  reason='missing_filing', detail=f'Historical submissions unavailable: {error}'))
    earliest = min(filings.values(), default='1994-01-01')
    for history in histories:
        for accession, filed, form in filing_rows(history):
            if form.removesuffix('/A') in {'8-K', '10-K', '10-Q', '6-K', '20-F', '40-F'} and earliest <= filed <= date.today().isoformat():
                filings[accession] = filed
    seen = set()
    for accession, filed in sorted(filings.items(), key=lambda item: (item[1], item[0])):
        base = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/'
        try:
            parser = ExhibitIndex()
            parser.feed(edgar.get(base + accession + '-index.html').decode('utf-8', errors='strict'))
            for description, kind, href in parser.rows:
                if not re.fullmatch(r'EX-10(?:[.\-].*)?', kind, re.I):
                    continue
                url = urljoin(base, href)
                if url in seen:
                    continue
                seen.add(url)
                if not url.startswith(base):
                    raise DiscoveryError('exhibit link leaves its SEC filing directory')
                if not url.lower().endswith(('.htm', '.html', '.txt')):
                    output.refusals.append(Refusal(scope='agreement', ref=url, reason='missing_filing',
                                          detail='EX-10 exhibit is not a supported text/HTML document.'))
                    continue
                text = edgar.get(url).decode('utf-8', errors='strict')
                if credit_document(text):
                    agreement = Agreement(accession=accession, url=url, filed=date.fromisoformat(filed),
                                          kind=agreement_kind(text), redacted=redacted(text))
                    output.documents.append(SourceDocument(agreement, text))
        except (httpx.HTTPError, RuntimeError, UnicodeError, DiscoveryError) as error:
            output.refusals.append(Refusal(scope='agreement', ref=accession, reason='missing_filing',
                                  detail=f'Cannot completely inspect filing exhibits: {error}'))
    output.notes.append(f'Discovery inspected {len(filings)} filing indexes and {len(seen)} EX-10 exhibits; '
                        f'found {len(output.documents)} credit documents. No date-window truncation.')
    return output


def dev_companies(count: int = 5) -> list[Company]:
    """Find public borrowers in EX-10 hits. Do not write Dat's universe.json."""
    companies = []
    seen = set()
    for hit in search('"Consolidated Leverage Ratio"'):
        record = hit['_source']
        if not re.fullmatch(r'EX-10(?:[.\-].*)?', record.get('file_type', ''), re.I):
            continue
        for cik in record.get('ciks', []):
            cik = f'{int(cik):010d}'
            if cik in seen:
                continue
            seen.add(cik)
            data = edgar.submissions(cik)
            if data.get('tickers'):
                companies.append(company_from_submissions(data))
                if len(companies) == count:
                    return companies
    raise DiscoveryError(f'Only {len(companies)} public borrowers found, expected {count}')
