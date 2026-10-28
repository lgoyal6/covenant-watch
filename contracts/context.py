"""Local clause retrieval and readable text with exact offsets into raw SEC HTML."""

import html
import re
from array import array
from bisect import bisect_left
from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser

from contracts.models import Quote, SourceDocument
from contracts.segment import Segment
from contracts.verify import EvidenceError, bind_quote


class ContextError(ValueError):
    pass


class Rendered(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=False)
        self.raw = raw
        self.lines = [0] + [m.end() for m in re.finditer('\n', raw)]
        self.chars, self.starts, self.ends = [], array('q'), array('q')
        self.hidden = 0
        self.feed(raw)
        self.close()
        self.text = ''.join(self.chars)
        del self.chars

    def raw_position(self):
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def emit(self, text, start, end, direct=False):
        if self.hidden:
            return
        for index, char in enumerate(text):
            a, b = (start + index, start + index + 1) if direct else (start, end)
            if char.isspace():
                char = '\n' if char in '\r\n' else ' '
                if self.chars and self.chars[-1].isspace():
                    if char == '\n':
                        self.chars[-1] = '\n'
                    self.ends[-1] = b
                    continue
            self.chars.append(char)
            self.starts.append(a)
            self.ends.append(b)

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1
        if tag in {'p', 'div', 'br', 'tr', 'h1', 'h2', 'h3', 'li'}:
            start = self.raw_position()
            self.emit('\n', start, start + len(self.get_starttag_text()))

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {'p', 'div', 'tr', 'h1', 'h2', 'h3', 'li'}:
            start = self.raw_position()
            self.emit('\n', start, self.raw.find('>', start) + 1)

    def handle_data(self, text):
        self.emit(text, self.raw_position(), self.raw_position() + len(text), direct=True)

    def handle_entityref(self, name):
        start = self.raw_position()
        raw = '&' + name + ';'
        self.emit(html.unescape(raw), start, start + len(raw))

    def handle_charref(self, name):
        start = self.raw_position()
        raw = '&#' + name + ';'
        self.emit(html.unescape(raw), start, start + len(raw))

    def bounds(self, start, end):
        return bisect_left(self.starts, start), bisect_left(self.starts, end)

    def raw_segment(self, start, end, section=None):
        while start < end and self.text[start].isspace():
            start += 1
        while end > start and self.text[end - 1].isspace():
            end -= 1
        if start == end:
            raise ContextError('empty source unit')
        a, b = self.starts[start], self.ends[end - 1]
        return Segment(a, b, self.raw[a:b], section)


@lru_cache(maxsize=4)
def render(raw: str) -> Rendered:
    return Rendered(raw)


def readable(source: SourceDocument, part: Segment) -> str:
    view = render(source.text)
    a, b = view.bounds(part.start, part.end)
    return view.text[a:b].strip()


def bind_evidence(quote: Quote, source: SourceDocument, ranges: list[Segment]):
    """Wire quotes may be readable text. Final Spans always contain exact raw HTML."""
    view = render(source.text)
    candidates = {}
    for part in ranges:
        # Existing raw quotes and offset hints remain valid, including plain-text fixtures.
        pos = source.text.find(quote.text, part.start, part.end)
        while pos >= 0:
            candidates[(pos, pos + len(quote.text))] = None
            pos = source.text.find(quote.text, pos + 1, part.end)
        lo, hi = view.bounds(part.start, part.end)
        pos = view.text.find(quote.text, lo, hi)
        while pos >= 0:
            end = pos + len(quote.text)
            # A quotation cannot select only one decoded character of a multi-char entity.
            if not (pos and view.starts[pos - 1] == view.starts[pos]) and not (
                    end < len(view.text) and view.ends[end - 1] == view.ends[end]):
                a, b = view.starts[pos], view.ends[end - 1]
                if part.start <= a < b <= part.end:
                    candidates[(a, b)] = None
            pos = view.text.find(quote.text, pos + 1, hi)
    if quote.char_start is not None:
        candidates = {key: None for key in candidates if key[0] == quote.char_start}
    if len(candidates) != 1:
        raise EvidenceError('quote absent or repeated in supplied source units; provide a longer exact quote')
    a, b = next(iter(candidates))
    return bind_quote(Quote(text=source.text[a:b], section=quote.section, char_start=a), source,
                      Segment(a, b, source.text[a:b]))


DEFINITION = re.compile(r'["“]([^"”\n]{2,140})["”]\s*(?:(?:shall\s+)?mean(?:s)?\b|has the meaning\b|:)', re.I)
HEADER = re.compile(r'(?im)^\s*((?:SECTION\s+)?\d+\.\d+(?:\([a-z0-9]+\))?[^\n]{0,180}|ARTICLE\s+[IVXLCDM]+[^\n]{0,100})')
FINANCIAL = re.compile(r'financial\s+covenants?|leverage(?:\s+ratio)?|interest\s+coverage|fixed.charge\s+coverage|minimum\s+liquidity', re.I)
OPERATIVE = re.compile(r'permit|maintain|shall|must|not\s+(?:exceed|less)|at\s+least|maximum|minimum|greater\s+than|less\s+than', re.I)


@dataclass
class ContextPlan:
    source: SourceDocument
    units: list[Segment]
    definitions: list[str]
    root_count: int

    def layout(self, alternate=False, size=18000):
        # Keep clauses/definitions intact. Reorder and regroup whole units for pass 2.
        units = self.units if not alternate else list(reversed(self.units))
        groups, group, length = [], [], 0
        target = size if not alternate else max(1, size * 2 // 3)
        for unit in units:
            count = len(readable(self.source, unit))
            if count > size:
                raise ContextError(f'Complete source unit at {unit.start}:{unit.end} exceeds {size} readable characters')
            if group and length + count > target:
                groups.append(group)
                group, length = [], 0
            group.append(unit)
            length += count
        if group:
            groups.append(group)
        return groups

    def report(self):
        return dict(source_url=self.source.key, raw_characters=len(self.source.text),
                    readable_characters=len(render(self.source.text).text),
                    selected_characters=sum(len(readable(self.source, p)) for p in self.units),
                    source_units=len(self.units), definition_count=len(self.definitions),
                    covenant_sections=self.root_count,
                    calls_layout_1=len(self.layout()), calls_layout_2=len(self.layout(True)))


def plan_context(source: SourceDocument, *, pilot=False) -> ContextPlan:
    view = render(source.text)
    text = view.text
    headers = list(HEADER.finditer(text))
    definitions = list(DEFINITION.finditer(text))
    catalog = {}
    for index, match in enumerate(definitions):
        end = definitions[index + 1].start() if index + 1 < len(definitions) else len(text)
        boundary = next((h.start() for h in headers if h.start() > match.end()), end)
        end = min(end, boundary)
        catalog.setdefault(match[1].casefold(), []).append((match.start(), end))
    roots = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        body = text[header.start():end]
        # Keep the entire financial section, including tables, conditions and elections.
        if FINANCIAL.search(body[:240]) and OPERATIVE.search(body[header.end() - header.start():]):
            roots.append((header.start(), end))
    # Unnumbered text: complete paragraphs only, never an arbitrary character window.
    for match in FINANCIAL.finditer(text):
        if any(a <= match.start() < b for a, b in roots):
            continue
        if any(a <= match.start() < b for ranges in catalog.values() for a, b in ranges):
            continue
        a, b = text.rfind('\n', 0, match.start()) + 1, text.find('\n', match.end())
        b = len(text) if b < 0 else b
        if OPERATIVE.search(text[a:b]):
            roots.append((a, b))
    roots = sorted(set(roots))
    if pilot:
        roots = roots[:1]
    chosen = list(roots)
    if source.agreement.kind == 'amendment':
        # Do not assume an amendment is irrelevant because it lacks a ratio phrase.
        # Keep its entire readable body if it is small; otherwise refuse locally.
        chosen = [(0, len(text))]
    elif not roots:
        raise ContextError('No locally identifiable operative financial covenant; no whole-document model fallback')
    # Header supplies parties and operative date; finish its paragraph rather than cutting it.
    end = len(text) if len(text) <= 3000 else text.rfind('\n', 0, 3000)
    if end <= 0:
        raise ContextError('Cannot isolate a bounded agreement header')
    chosen.append((0, end))
    names, queued = set(), list(chosen)
    while queued:
        a, b = queued.pop()
        body = text[a:b]
        for name, ranges in catalog.items():
            if name not in names and re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', body, re.I):
                names.add(name)
                chosen.extend(ranges)  # Ambiguous duplicate definitions must all be visible.
                queued.extend(ranges)
    merged = []
    for a, b in sorted(set(chosen)):
        if merged and a < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    units = [view.raw_segment(a, b) for a, b in merged if text[a:b].strip()]
    return ContextPlan(source, units, sorted(names), len(roots))
