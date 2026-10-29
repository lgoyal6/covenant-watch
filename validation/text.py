"""Deterministic filing-document -> plain-text conversion, plus sentence helpers.

Every Span written by validation/ has offsets into `doc_text(url)`, which is
`html_to_text(edgar.get(url))`. Anyone (UI, scorer) can reproduce the exact
text with:

    from validation.text import doc_text
    text = doc_text(span.url)
    assert text[span.char_start:span.char_end] == span.text

The conversion is pure Python stdlib and has no configuration, so it is stable.
"""

from __future__ import annotations

import html
import re
from functools import lru_cache
from html.parser import HTMLParser

from shared import edgar

BLOCK_TAGS = {
    "p", "div", "br", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "blockquote", "pre", "hr", "title", "body", "html",
    "page", "document", "type", "text",
}
CELL_TAGS = {"td", "th"}
SKIP_TAGS = {"script", "style", "head", "ix:header", "xbrl"}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip += 1
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in CELL_TAGS:
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in CELL_TAGS:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


_WS = re.compile(r"[ \t\r\f\v   ​]+")
_NL = re.compile(r" *\n[ \n]*")


def normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = _WS.sub(" ", text)
    text = _NL.sub("\n", text)
    return text.strip()


def html_to_text(raw: bytes | str) -> str:
    """HTML (or plain text) filing document -> normalized plain text.

    Rules: drop <script>/<style>/<head>/<ix:header>; block tags become newlines,
    table cells become spaces; entities decoded; curly quotes -> straight,
    en/em dash -> '-'; runs of spaces/nbsp collapse to one space; every newline
    run (with surrounding spaces) collapses to a single '\\n'; result stripped.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if re.search(r"<(html|body|div|p|table|font)\b", raw[:20000], re.I):
        parser = _Extractor()
        parser.feed(raw)
        parser.close()
        text = "".join(parser.parts)
    else:
        text = html.unescape(raw)
    return normalize(text)


@lru_cache(maxsize=8)
def doc_text(url: str) -> str:
    return html_to_text(edgar.get(url))


def doc_url(cik: str | int, accession: str, filename: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{filename}"


# ---------------- sentences ----------------

_ABBREV = {
    "inc", "corp", "co", "no", "nos", "u.s", "e.g", "i.e", "approx", "ltd", "llc", "l.p", "n.a",
    "mr", "ms", "dr", "jr", "sr", "st", "vs", "etc", "sec", "s.a", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "fig", "ref", "art", "v",
}
_BOUNDARY = re.compile(r"[.!?;]\"?\)?(?=\s+[\"(]?[A-Z(])|\n")


def sentence_bounds(text: str, pos: int, max_len: int = 1200) -> tuple[int, int]:
    """Return (start, end) of the sentence containing `pos`. Ends include the period."""
    start = max(0, pos - max_len)
    end = min(len(text), pos + max_len)
    s = start
    for m in _BOUNDARY.finditer(text, start, pos):
        if _is_real_boundary(text, m):
            s = m.end()
    e = end
    for m in _BOUNDARY.finditer(text, pos, end):
        if _is_real_boundary(text, m):
            e = m.end() if text[m.start()] != "\n" else m.start()
            break
    while s < e and text[s] in " \n":
        s += 1
    while e > s and text[e - 1] in " \n":
        e -= 1
    return s, e


def _is_real_boundary(text: str, m: re.Match) -> bool:
    ch = text[m.start()]
    if ch == "\n":
        return True
    if ch == ";":
        return False  # keep semicolon clauses in the sentence
    if ch != ".":
        return True
    # word before the period
    w = re.search(r"([A-Za-z.]+)$", text[max(0, m.start() - 12) : m.start()])
    if w:
        word = w.group(1).lower().rstrip(".")
        if word in _ABBREV or len(word) == 1:
            return False
    # decimal number like "1.00" never matches since next char must be whitespace
    return True
