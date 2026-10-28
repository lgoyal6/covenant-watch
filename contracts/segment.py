"""Offset-preserving section segmentation and two complete chunk layouts."""

import html
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    start: int
    end: int
    text: str
    section: str | None = None


def visible_text(text: str) -> str:
    """For discovery/definition inspection only. Never use its offsets for Spans."""
    return html.unescape(re.sub(r"<[^>]*>", " ", text))


def segment(text: str) -> list[Segment]:
    # Block tags create header boundaries; every replacement keeps its length.
    def mask(match):
        raw = match[0]
        block = re.match(r'</?(?:p|div|h[1-6]|tr|br)\b', raw, re.I)
        return ('\n' + ' ' * (len(raw) - 1)) if block else ' ' * len(raw)

    masked = re.sub(r'<[^>]*>', mask, text)
    masked = re.sub(r'&(?:nbsp|#160|#x[aA]0);', lambda m: ' ' * len(m[0]), masked)
    headers = list(re.finditer(
        r"(?im)(?:^|(?<=\n)|(?<=\r))[ \t]*"
        r"(?P<section>(?:ARTICLE\s+[IVXLCDM]+|(?:SECTION\s+)?\d+\.\d+(?:\([a-z0-9]+\))?))\b",
        masked,
    ))
    starts = {m.start('section'): m.group('section').strip() for m in headers}
    starts.setdefault(0, None)
    points = sorted(starts)
    return [Segment(a, b, text[a:b], starts[a])
            for a, b in zip(points, points[1:] + [len(text)]) if b > a]


def chunks(text: str, *, alternate: bool = False, size: int = 28000) -> list[Segment]:
    """Cover every source character; overlap protects definitions split at a boundary."""
    if size < 64:
        raise ValueError('chunk size must be at least 64')
    sections = segment(text)
    if not text:
        return []
    overlap = min(2000, size // 4)
    out = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if not alternate and end < len(text):
            candidates = [s.start for s in sections if start + size // 2 <= s.start <= end]
            if candidates:
                end = max(candidates)
        elif alternate and start == 0:
            end = min(len(text), size * 3 // 4)
        section = next((s.section for s in reversed(sections) if s.start <= start), None)
        out.append(Segment(start, end, text[start:end], section))
        if end == len(text):
            break
        start = end - overlap
    return out


def defined_terms(text: str) -> dict[str, str]:
    """Index quoted definitions for detecting unresolved defined terms at leaves."""
    visible = visible_text(text)
    pattern = r'["“]([^"”\n]{2,140})["”]\s*(?:means|shall mean|has the meaning|:|=)'
    matches = list(re.finditer(pattern, visible, re.I))
    bodies = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(visible), match.end() + 12000)
        body = visible[match.end():end]
        # A distinct plain-text paragraph is not part of the preceding definition.
        # Full cited operative text is independently checked by normalization.
        bodies[match[1].casefold()] = re.split(r'\n[ \t]*\n', body, maxsplit=1)[0]
    return bodies
