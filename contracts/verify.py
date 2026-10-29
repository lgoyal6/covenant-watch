"""Bind exact quotes, verify complete output, and compare independent readings."""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass

from shared.schema import ContractExtraction, Span
from contracts.models import Quote, SourceDocument
from contracts.segment import Segment


class EvidenceError(ValueError):
    pass


def bind_quote(quote: Quote, source: SourceDocument, chunk: Segment | None = None) -> Span:
    lo, hi = (chunk.start, chunk.end) if chunk else (0, len(source.text))
    hint = quote.char_start
    if hint is not None and lo <= hint and hint + len(quote.text) <= hi:
        start = hint
    else:
        start = source.text.find(quote.text, lo, hi)
        if start < 0 or source.text.find(quote.text, start + 1, hi) >= 0:
            raise EvidenceError('quote absent or repeated without an exact offset hint')
    span = Span(accession=source.agreement.accession, url=source.key,
                section=quote.section, char_start=start,
                char_end=start + len(quote.text), text=quote.text)
    verify_span(span, {source.key: source})
    return span


def verify_span(span: Span, sources: dict[str, SourceDocument]) -> None:
    source = sources.get(span.url)
    if (source is None or source.agreement.accession != span.accession
            or not span.text or span.char_start < 0 or span.char_end <= span.char_start
            or span.char_end > len(source.text)
            or source.text[span.char_start:span.char_end] != span.text):
        raise EvidenceError(f'invalid span: {span.accession} {span.char_start}:{span.char_end}')


def all_spans(contract: ContractExtraction):
    for term in contract.terms:
        yield term.span
    for covenant in contract.covenants:
        yield covenant.span
        for threshold in covenant.thresholds:
            yield threshold.source


def verify_contract(contract: ContractExtraction, sources: dict[str, SourceDocument]) -> int:
    agreements = {(a.accession, a.url) for a in contract.agreements}
    count = 0
    for span in all_spans(contract):
        if (span.accession, span.url) not in agreements:
            raise EvidenceError('span references an undeclared agreement')
        verify_span(span, sources)
        count += 1
    if len({c.id for c in contract.covenants}) != len(contract.covenants):
        raise EvidenceError('duplicate covenant ids')
    for node in contract.terms:
        verify_node_number(node)
    for covenant in contract.covenants:
        for threshold in covenant.thresholds:
            verify_number(threshold.value, threshold.source.text)
        if covenant.agreement_accession not in {a.accession for a in contract.agreements}:
            raise EvidenceError('covenant references an undeclared agreement')
    return count


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def semantic(value):
    """Offsets and quotation length may differ without changing financial meaning."""
    data = value.model_dump(mode='json') if hasattr(value, 'model_dump') else value
    if isinstance(data, dict):
        return {k: semantic(v) for k, v in data.items()
                if k not in {'span', 'source', 'section', 'char_start', 'char_end', 'text'}}
    if isinstance(data, list):
        return [semantic(v) for v in data]
    return data


def disagreements(first: dict, second: dict) -> set[str]:
    return {key for key in first.keys() | second.keys()
            if key not in first or key not in second or semantic(first[key]) != semantic(second[key])}


@dataclass
class VerificationStats:
    compared: int = 0
    disagreed: int = 0
    verifier_calls: int = 0
    span_retries: int = 0

    def as_dict(self):
        return dict(compared=self.compared, disagreed=self.disagreed,
                    disagreement_rate=self.disagreed / self.compared if self.compared else None,
                    verifier_calls=self.verifier_calls, span_retries=self.span_retries)


def summarize(contracts: list[ContractExtraction]) -> dict:
    refusals = Counter(r.reason for c in contracts for r in c.refusals)
    totals = dict(compared=0, disagreed=0, verifier_calls=0, span_retries=0)
    for contract in contracts:
        for note in contract.extraction_notes:
            if note.startswith('contracts.metrics='):
                metrics = json.loads(note.split('=', 1)[1])
                for key in totals:
                    totals[key] += metrics.get(key, 0)
    return dict(companies=len(contracts),
                companies_with_covenants=sum(bool(c.covenants) for c in contracts),
                covenants=sum(len(c.covenants) for c in contracts),
                terms=sum(len(c.terms) for c in contracts), refusals_by_reason=dict(refusals),
                **totals,
                verifier_disagreement_rate=totals['disagreed'] / totals['compared']
                if totals['compared'] else None)


def verify_number(value: float, text: str, *, percentage: bool = False) -> None:
    """Require a matching literal, including stated scaling, in the cited clause."""
    import math
    import re
    from contracts.segment import visible_text

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EvidenceError('numeric claim must be a finite number')
    visible = visible_text(text)
    pattern = r'(?<![\w.])(-?\d+(?:,\d{3})*(?:\.\d+)?)\s*(billion|million|thousand|bn|mm)?\s*(%|percent\b)?'
    scales = {None: 1, 'billion': 1e9, 'bn': 1e9, 'million': 1e6, 'mm': 1e6, 'thousand': 1e3}
    for match in re.finditer(pattern, visible, re.I):
        if percentage and not match[3]:
            continue
        amount = float(match[1].replace(',', '')) * scales[match[2].lower() if match[2] else None]
        if match[3]:
            amount /= 100
        if math.isfinite(value) and math.isclose(value, amount, rel_tol=1e-10, abs_tol=1e-12):
            return
    if value == 0 and re.search(r'\bzero\b', visible, re.I) and not percentage:
        return
    raise EvidenceError(f'numeric claim {value} has no matching literal in its cited clause')


def verify_node_number(node) -> None:
    if node.cap:
        if node.cap.get('kind') == 'pct_of':
            verify_number(node.cap.get('pct', float('nan')), node.span.text, percentage=True)
        elif node.cap.get('kind') == 'abs':
            verify_number(node.cap.get('usd', float('nan')), node.span.text)
