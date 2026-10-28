"""Ground truth A: covenant ratios companies themselves reported in 10-K / 10-Q.

Pipeline:
  1. EDGAR full-text search for phrases that tend to introduce actual ratios.
  2. Fetch each hit's main document, convert with validation.text.doc_text.
  3. Find candidate sentences (ratio name + a "N to 1.00" / "Nx" number).
  4. Extract: Claude (validation.llm) when ANTHROPIC_API_KEY is set, otherwise
     the deterministic parser `parse_sentence` below.
  5. Verify: span text == doc[char_start:char_end], reported value and
     threshold appear verbatim in the span. Anything else is discarded.

Run:  uv run python -m validation.disclosed [--max-docs N] [--no-llm]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime

from shared.paths import GROUNDTRUTH
from shared.schema import DisclosedRatio, Span

from validation import llm
from validation.search import Hit, search_all
from validation.text import doc_text, sentence_bounds

OUT = GROUNDTRUTH / "disclosed.json"

QUERIES = [
    "Leverage Ratio was",
    "leverage ratio was",
    "Interest Coverage Ratio was",
    "Fixed Charge Coverage Ratio was",
    "coverage ratio was",
    "Total Net Leverage Ratio was",
    "Consolidated Leverage Ratio was",
    "Senior Secured Leverage Ratio was",
    "First Lien Leverage Ratio was",
    "net leverage ratio was",
    "leverage ratio of",
    "to 1.00, compared to",
    "to 1.0, compared to",
    "our leverage ratio",
    "our interest coverage ratio",
    "our fixed charge coverage ratio",
    "actual leverage ratio",
    "Debt to EBITDA ratio was",
]
YEAR_WINDOWS = [("2019-01-01", "2020-12-31"), ("2021-01-01", "2022-12-31"), ("2023-01-01", "2024-06-30"), ("2024-07-01", "2025-12-31")]

# ---------------- deterministic parser ----------------

NAME_RE = re.compile(
    r"\b(?P<name>(?:(?:maximum|minimum|required|consolidated|total|net|senior|secured|unsecured|first[- ]lien|"
    r"funded|debt|cash|interest|interest\s+expense|fixed[- ]charges?|ebitdar?|rent|adjusted|gross|lease|"
    r"priority|financial|corporate|company|borrower'?s?|actual|recourse|asset|leverage)\s+){0,6}"
    r"(?:leverage|coverage)\s+ratio)\b"
    r"|\b(?P<name2>(?:total\s+|funded\s+|net\s+)?debt[- ]to[- ](?:consolidated\s+|adjusted\s+)*ebitdar?(?:\s+ratio)?)\b",
    re.I,
)
NUM = r"(?P<v>\d{1,2}(?:\.\d{1,3})?)"
RATIO_SUFFIX = r"(?:\s*to\s*1(?:\.0{1,3})?\b|\s?x\b|\s?:\s?1(?:\.0{1,3})?\b|\s+times\b)"
ACTUAL_VALUE_RE = re.compile(
    r"^(?P<gap>[^.;]{0,140}?)\b(?P<verb>was|were|equaled|equals|stood at|of)\s+(?:approximately\s+|about\s+)?"
    + NUM + RATIO_SUFFIX,
    re.I,
)
VALUE_ANY_RE = re.compile(NUM + RATIO_SUFFIX, re.I)
THRESH_RE = re.compile(
    r"(?P<kw>maximum|minimum|required|requirement|covenant level|limit(?:ation)?|not (?:to )?exceed|"
    r"no (?:greater|more|less) than|not (?:more|greater|less) than|at least|permitted|must not exceed|"
    r"less than or equal to|greater than or equal to)\b[^.;]{0,60}?"
    + NUM + RATIO_SUFFIX,
    re.I,
)
# words in the gap between ratio name and verb that make the value a bound, not an actual
GAP_BAD = re.compile(
    r"\b(must|shall|may|will|would|could|should|required?|requirement|permitted|maximum|minimum|not|"
    r"exceed|exceeds|less|greater|more|below|above|limit|threshold|if|unless|covenant level|step|"
    r"increase|decrease|reduced?|pro forma|then)\b",
    re.I,
)
SENT_BAD = re.compile(
    r"\b(pro forma|would have been|would be|hypothetical|assuming|if we|in the event|projected|"
    r"expect|anticipate|estimated|forecast|could be|would result|until|trigger|is achieved|is required)\b",
    re.I,
)
OF_PREFIX_OK = re.compile(r"\b(our|the company's|its|we had an?|with an?|actual|the borrower's|the borrowers'|and an?)\s+(?:(?:current|then[- ]current|actual|calculated)\s+)?$", re.I)
# the sentence must sit in debt-covenant context (checked on a window around it)
CONTEXT_RE = re.compile(r"covenant|credit agreement|credit facility|loan agreement|lenders?\b|indenture|in compliance|as defined|revolving|term loan|notes", re.I)
NON_COVENANT_RE = re.compile(r"non-GAAP|book value per share|we use .{0,60}financial measure", re.I)

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_RE = re.compile(rf"\b(?P<m>{MONTHS})\s+(?P<d>\d{{1,2}}),\s*(?P<y>(?:19|20)\d\d)\b")
_MONTH_NUM = {m: i + 1 for i, m in enumerate(MONTHS.split("|"))}


def kind_of(name: str) -> str:
    n = name.lower().replace("-", " ")
    if "fixed charge" in n:
        return "min_fixed_charge_coverage"
    if "coverage" in n and "interest" in n:
        return "min_interest_coverage"
    if "coverage" in n:
        return "other"
    if any(k in n for k in ("senior secured", "first lien", "secured leverage", "senior leverage", "secured net leverage")):
        return "max_senior_leverage"
    if "leverage" in n or "debt to" in n:
        return "max_leverage"
    return "other"


@dataclass
class Parsed:
    kind: str
    name: str
    value: float
    value_text: str
    threshold: float | None
    threshold_text: str | None
    period_end: date | None


def _paren_ranges(sentence: str) -> list[tuple[int, int]]:
    out, stack = [], []
    for i, ch in enumerate(sentence):
        if ch == "(":
            stack.append(i)
        elif ch == ")" and stack:
            out.append((stack.pop(), i))
    return out


def _dates(sentence: str) -> list[tuple[int, date]]:
    """Dates in the sentence, ignoring parenthetical ones like '(December 31, 2024: 0.25:1.00)'."""
    out = []
    parens = _paren_ranges(sentence)
    for m in DATE_RE.finditer(sentence):
        if any(a < m.start() < b for a, b in parens):
            continue
        try:
            out.append((m.start(), date(int(m["y"]), _MONTH_NUM[m["m"]], int(m["d"]))))
        except ValueError:
            pass
    return out


def parse_sentence(sentence: str, fallback_period: date | None = None) -> list[Parsed]:
    """Deterministically extract actual reported covenant ratios from one sentence.

    Returns [] when the sentence is a threshold-only, conditional, pro forma or
    ambiguous statement. Never guesses: every returned value text is in the sentence.
    """
    if SENT_BAD.search(sentence) or len(sentence) > 900:
        return []
    names = list(NAME_RE.finditer(sentence))
    if not names:
        return []
    results: list[Parsed] = []
    dates = _dates(sentence)
    distinct_dates = sorted({d for _, d in dates})
    for i, nm in enumerate(names):
        name = nm.group("name") or nm.group("name2")
        if re.match(r"(maximum|minimum|required)\b", name, re.I):
            continue  # "maximum leverage ratio of 4.50" is a threshold
        region_end = names[i + 1].start() if i + 1 < len(names) else len(sentence)
        region = sentence[nm.end():region_end]
        m = ACTUAL_VALUE_RE.match(region)
        if not m:
            continue
        gap = m["gap"]
        if GAP_BAD.search(gap) or DATE_RE.search(gap) and len(gap) > 60:
            continue
        if m["verb"].lower() == "of" and not OF_PREFIX_OK.search(sentence[: nm.start()][-80:] + " "):
            # "a leverage ratio of 3.0" with no possessive is usually a requirement
            continue
        if m["verb"].lower() == "of" and re.search(r"\b(maintain|requires?|covenant|not to exceed|maximum|minimum)\b", sentence[: nm.start()], re.I):
            continue
        # after the value: "respectively" or a second actual value means a multi-period list
        after = region[m.end():]
        if re.match(r"\s*(?:and|,)\s*" + NUM + RATIO_SUFFIX, after, re.I) or re.search(r"respectively", after[:200], re.I):
            continue
        value_text = m.group(0)[m.start("v"):]
        value = float(m["v"])
        if not (0 < value < 100):
            continue
        # threshold: only when exactly one distinct bound appears in the sentence
        threshold = threshold_text = None
        scope = sentence if len(names) == 1 else region
        bounds = {}
        for t in THRESH_RE.finditer(scope):
            tv = t["v"]
            bounds.setdefault(float(tv), t.group(0)[t.start("v") - t.start():])
        if len(bounds) == 1:
            threshold, threshold_text = next(iter(bounds.items()))
        # period: date nearest before value in the sentence, else single date, else filing period
        abs_value_pos = nm.end() + m.start("v")
        before = [d for p, d in dates if p < abs_value_pos]
        after_dates = [d for p, d in dates if p >= abs_value_pos]
        if before:
            period = before[-1]
        elif len(distinct_dates) == 1:
            period = distinct_dates[0]
        elif not distinct_dates:
            period = fallback_period
        elif fallback_period in distinct_dates:
            period = fallback_period
        else:
            period = after_dates[0] if len(after_dates) == 1 else None
        if period is None:
            continue
        results.append(Parsed(kind_of(name), name, value, value_text, threshold, threshold_text, period))
    return results


# ---------------- candidate finding + verification ----------------

CANDIDATE_RE = re.compile(r"(?:leverage|coverage)\s+ratio|debt[- ]to[- ](?:adjusted\s+)?ebitda", re.I)


def candidate_sentences(text: str) -> list[tuple[int, int]]:
    seen = set()
    out = []
    for m in CANDIDATE_RE.finditer(text):
        s, e = sentence_bounds(text, m.start())
        if (s, e) in seen:
            continue
        seen.add((s, e))
        if VALUE_ANY_RE.search(text[s:e]):
            out.append((s, e))
    return out


def _period(hit: Hit) -> date | None:
    try:
        return date.fromisoformat(hit.period_ending) if hit.period_ending else None
    except ValueError:
        return None


def verify(row: DisclosedRatio, text: str, value_text: str | None = None, threshold_text: str | None = None) -> bool:
    sp = row.span
    if text[sp.char_start:sp.char_end] != sp.text:
        return False
    if value_text is not None and value_text not in sp.text:
        return False
    if threshold_text is not None and threshold_text not in sp.text:
        return False
    if not _num_in(row.reported_value, sp.text):
        return False
    if row.reported_threshold is not None and not _num_in(row.reported_threshold, sp.text):
        return False
    return True


def _num_in(v: float, s: str) -> bool:
    """True when some literal number in s equals v (e.g. 3.2 matches '3.20')."""
    return any(abs(float(x) - v) < 1e-9 for x in re.findall(r"\d+(?:\.\d+)?", s))


def extract_doc(hit: Hit, use_llm: bool) -> list[DisclosedRatio]:
    try:
        text = doc_text(hit.url)
    except Exception as exc:  # network / 404
        print(f"  ! {hit.url}: {exc}", file=sys.stderr)
        return []
    fallback = _period(hit)
    filed = date.fromisoformat(hit.file_date) if hit.file_date else None
    rows = []
    for s, e in candidate_sentences(text):
        sent = text[s:e]
        if NON_COVENANT_RE.search(sent) or not CONTEXT_RE.search(text[max(0, s - 800):e + 800]):
            continue
        parsed: list[Parsed]
        if use_llm:
            parsed = llm.extract_disclosed(sent, fallback) or []
        else:
            parsed = parse_sentence(sent, fallback)
        for p in parsed:
            if p.period_end is None or (filed and p.period_end > filed):
                continue
            if fallback and (fallback - p.period_end).days > 800:
                continue  # stale historical mention
            row = DisclosedRatio(
                cik=hit.cik,
                period_end=p.period_end,
                covenant_kind=p.kind,
                reported_value=p.value,
                reported_threshold=p.threshold,
                span=Span(accession=hit.accession, url=hit.url, section=None, char_start=s, char_end=e, text=sent),
            )
            if verify(row, text, p.value_text, p.threshold_text):
                rows.append(row)
    return rows


def collect_hits(max_pages: int = 2) -> list[Hit]:
    hits: dict[tuple[str, str], Hit] = {}
    for q in QUERIES:
        for start, end in YEAR_WINDOWS:
            for h in search_all(q, forms="10-K,10-Q", start=start, end=end, max_pages=max_pages):
                if h.file_type.upper().startswith(("10-K", "10-Q")):
                    hits.setdefault((h.accession, h.filename), h)
    return list(hits.values())


def dedupe(rows: list[DisclosedRatio]) -> list[DisclosedRatio]:
    """One row per (cik, period_end, covenant_kind); keep the earliest-filed source."""
    best: dict[tuple, DisclosedRatio] = {}
    for r in sorted(rows, key=lambda r: (r.span.accession, r.span.char_start)):
        best.setdefault((r.cik, r.period_end, r.covenant_kind), r)
    return sorted(best.values(), key=lambda r: (r.cik, r.period_end, r.covenant_kind))


def run(max_docs: int | None = None, use_llm: bool | None = None, per_company: int = 4, max_pages: int = 2) -> list[DisclosedRatio]:
    if use_llm is None:
        use_llm = llm.available()
    print(f"extractor: {'llm ' + llm.MODEL if use_llm else 'deterministic'}", file=sys.stderr)
    hits = collect_hits(max_pages=max_pages)
    # spread across companies: at most `per_company` docs per CIK, newest first
    hits.sort(key=lambda h: h.file_date, reverse=True)
    by_cik: dict[str, int] = {}
    chosen = []
    for h in hits:
        if by_cik.get(h.cik, 0) >= per_company:
            continue
        by_cik[h.cik] = by_cik.get(h.cik, 0) + 1
        chosen.append(h)
    if max_docs:
        chosen = chosen[:max_docs]
    print(f"{len(hits)} hits, {len(by_cik)} companies, fetching {len(chosen)} docs", file=sys.stderr)
    rows: list[DisclosedRatio] = []
    for i, h in enumerate(chosen):
        got = extract_doc(h, use_llm)
        rows.extend(got)
        if i % 25 == 0:
            print(f"  [{i}/{len(chosen)}] rows={len(rows)} companies={len({r.cik for r in rows})}", file=sys.stderr)
            save(dedupe(rows))
    rows = dedupe(rows)
    save(rows)
    return rows


def save(rows: list[DisclosedRatio]) -> None:
    GROUNDTRUTH.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps([r.model_dump(mode="json") for r in rows], indent=1))
    tmp.replace(OUT)


def load() -> list[DisclosedRatio]:
    if not OUT.exists():
        return []
    return [DisclosedRatio.model_validate(x) for x in json.loads(OUT.read_text())]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-docs", type=int)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--per-company", type=int, default=4)
    ap.add_argument("--max-pages", type=int, default=2)
    a = ap.parse_args()
    rows = run(a.max_docs, False if a.no_llm else None, a.per_company, a.max_pages)
    print(f"{len(rows)} rows, {len({r.cik for r in rows})} companies at {datetime.now():%H:%M}")
