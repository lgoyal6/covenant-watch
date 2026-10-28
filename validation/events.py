"""Ground truth B: disclosed covenant events (waivers, loosening amendments, defaults, accelerations).

Pipeline:
  1. EDGAR full-text search over 8-K filings (main document and EX-99 press
     releases; EX-10 agreement exhibits are skipped because their boilerplate
     defines defaults rather than reporting them), 2018-2025.
  2. For each phrase hit, cut the sentence around it from validation.text.doc_text.
  3. Classify the sentence: Claude (validation.llm) when ANTHROPIC_API_KEY is set,
     else the deterministic `classify_sentence` below. Hypothetical / risk-factor
     language is rejected.
  4. Event date = 8-K filing date. Dedupe per company: same kind within 60 days
     is one event (keep earliest).

Run:  uv run python -m validation.events [--no-llm] [--max-docs N]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date

from shared.paths import GROUNDTRUTH
from shared.schema import CovenantEvent, Span

from validation import llm
from validation.search import Hit, search_all
from validation.text import doc_text, sentence_bounds

OUT = GROUNDTRUTH / "events.json"
START, END = "2018-01-01", "2025-12-31"

QUERIES = [
    # waivers
    "agreed to waive", "waiver of the financial covenant", "Limited Waiver", "Waiver and Amendment",
    "Amendment and Waiver", "waive the Company's compliance", "temporary waiver", "covenant waiver",
    "waived compliance with",
    # loosening amendments
    "covenant relief", "increase the maximum total leverage ratio", "increase the maximum leverage ratio",
    "increase the maximum consolidated leverage ratio", "increase the maximum total net leverage ratio",
    "reduce the minimum fixed charge coverage ratio", "reduce the minimum interest coverage ratio",
    "suspend the financial covenants", "suspension of the financial covenants", "covenant holiday",
    "financial covenant relief", "relief from the financial covenants",
    # defaults
    "not in compliance with the financial covenant", "failed to comply with the financial covenant",
    "notice of default", "Event of Default has occurred", "forbearance agreement",
    "not in compliance with the leverage ratio", "breach of the financial covenant",
    # accelerations
    "notice of acceleration", "declared all amounts outstanding", "accelerated the maturity",
    "declared the outstanding", "immediately due and payable",
]

HYPOTHETICAL = re.compile(
    r"\b(may|might|could|if|unless|in the event|any failure|no assurance|potential(?:ly)?|risks?|"
    r"would (?:be|constitute|result|permit|allow|cause)|upon the occurrence|subject to|whether|"
    r"there can be|could result|in order to avoid|to avoid|could cause|will be required|as long as|so long as|"
    r"at any time|provided that|believe|can elect|may elect)\b",
    re.I,
)
COVENANT_CTX = re.compile(r"covenant|\bratios?\b|event of default|credit agreement|credit facility|loan agreement|indenture|lenders?\b", re.I)
WAIVER = re.compile(
    r"\b(agreed to waive|waived|waives|waiving|grant(?:ed|s)? (?:a |the )?waiver|provides? for (?:a |the )?waiver|"
    r"(?:entered into|executed|obtained|received)[^.]{0,120}\bwaiver)\b",
    re.I,
)
LOOSEN = re.compile(
    r"\b(increas\w*|rais\w*)\b[^.]{0,100}\b(maximum|permitted)\b[^.]{0,80}\b(leverage|ratio)\b"
    r"|\b(decreas\w*|reduc\w*|lower\w*)\b[^.]{0,100}\bminimum\b[^.]{0,80}\b(coverage|ratio)\b"
    r"|\b(suspend\w*|suspension|holiday|relief)\b[^.]{0,80}\b(financial )?covenants?\b"
    r"|\bcovenant (?:relief|holiday|suspension)\b",
    re.I,
)
AMEND = re.compile(r"\bamend", re.I)
DEFAULT = re.compile(
    r"\b(was|were|is|are|has been|had been|remains?)\s+not\s+in\s+compliance\b"
    r"|\b(failed|did not|has not|had not)\s+(?:to\s+)?compl\w*\b"
    r"|\bnotice of (?:default|event of default)\b"
    r"|\bevents? of default (?:has|have|had) occurred\b"
    r"|\bforbear\w*\b"
    r"|\b(?:breached|is in breach|was in breach|were in breach)\b",
    re.I,
)
ACCEL = re.compile(
    r"\b(?:declared|declaring)\b[^.]{0,160}\b(?:immediately due and payable|due and payable)\b"
    r"|\bnotice of acceleration\b|\baccelerated (?:the|all|its|our)\b",
    re.I,
)


DEFINITIONAL = re.compile(r"\b(the term|means|shall mean|is defined as|as used herein|for purposes hereof)\b", re.I)
NEGATED_WAIVER = re.compile(r"without waiving|not waive|no waiver|not to waive|did not waive|reservation of rights|reserv\w* (?:all|its|their) rights", re.I)
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
MONTH_YEAR = re.compile(rf"\b({MONTHS})(?:\s+\d{{1,2}},)?\s+((?:19|20)\d\d)\b")
_MNUM = {m: i + 1 for i, m in enumerate(MONTHS.split("|"))}


NOT_CREDIT = re.compile(r"employment|compensation|restrictive covenant agreement|non-?compet|board of directors|director|officer|executive|asset sale offer|change of control offer|consent solicitation|listing (?:rule|standard)|nasdaq|nyse", re.I)
LENDER_CTX = re.compile(r"lenders?|agent|bank|credit agreement|credit facility|loan agreement|noteholders|holders", re.I)
WAIVER_SUBJECT = re.compile(r"financial covenant|\bratios?\b|events? of default|defaults?\b|non-?compliance|covenant waiver|compliance with (?:certain|the) (?:financial )?covenants", re.I)
RELIEF_VERB = re.compile(r"\b(provides?|provided|providing|implement\w*|establish\w*|obtain\w*|extend\w*|grant\w*|receiv\w*|suspend\w*|increas\w*|reduc\w*|decreas\w*|rais\w*|lower\w*|amend\w*)\b", re.I)
RELIEF_TWEAK = re.compile(r"carve-?out|excludes? from|investment limitation|terminat\w* the covenant relief|end of the covenant relief|exit\w* the covenant relief", re.I)


# covenant step-ups granted for an acquisition are strategic, not distress; exclude them from loosening
ACQUISITION = re.compile(r"acqui\w*|merger|in connection with the [A-Z]\w* (?:and [A-Z]\w* )?transaction", re.I)


def is_stale(sentence: str, filed: date, max_days: int = 180) -> bool:
    """True if every month/year mentioned is > max_days before the filing (a historical recap).

    Sentences with no dates are not stale. Future dates (relief periods ending later) don't count as stale.
    """
    mentions = [date(int(y), _MNUM[m], 1) for m, y in MONTH_YEAR.findall(sentence)]
    if not mentions:
        return False
    return all((filed - d).days > max_days for d in mentions)


def classify_sentence(sentence: str, filed: date | None = None) -> str | None:
    """Deterministic event classification of one sentence; None when not a clear event."""
    if len(sentence) > 1200 or len(sentence) < 60 or not COVENANT_CTX.search(sentence):
        return None
    if not re.match(r"[\"(A-Z0-9\u2012-\u2015-]", sentence):
        return None  # fragment (sentence split mid-clause)
    if DEFINITIONAL.search(sentence) or NOT_CREDIT.search(sentence):
        return None
    if sentence.rstrip()[-1] not in '.:;)"':
        return None  # cut off by a line break: too little context to classify
    if filed and is_stale(sentence, filed):
        return None
    hypo = HYPOTHETICAL.search(sentence)
    if ACCEL.search(sentence) and not hypo:
        return "acceleration"
    if DEFAULT.search(sentence) and not hypo and not re.search(r"\b(waiv|forbear)", sentence, re.I):
        return "default"
    if WAIVER.search(sentence) and not NEGATED_WAIVER.search(sentence) and WAIVER_SUBJECT.search(sentence) and LENDER_CTX.search(sentence):
        # "would otherwise" is fine in waiver language; reject only clear hypotheticals
        if not re.search(r"\b(may|might|could|if we|no assurance|seek|intend|expect)\b", sentence, re.I):
            return "waiver"
    if re.search(r"\bforbear\w*\b", sentence, re.I) and re.search(r"\b(entered into|executed|agreed)\b", sentence, re.I) and not hypo:
        return "default"  # forbearance presupposes an existing default
    if (LOOSEN.search(sentence) and AMEND.search(sentence) and RELIEF_VERB.search(sentence)
            and not RELIEF_TWEAK.search(sentence) and not ACQUISITION.search(sentence)
            and not re.search(r"\b(may|might|could|if|no assurance|seek|in the event|can elect|may elect|believe|would)\b", sentence, re.I)):
        return "amendment_loosening"
    return None


def collect_hits(max_pages: int = 2) -> list[Hit]:
    hits: dict[tuple[str, str], tuple[Hit, set[str]]] = {}
    for q in QUERIES:
        for h in search_all(q, forms="8-K", start=START, end=END, max_pages=max_pages):
            ft = h.file_type.upper()
            if not (ft.startswith("8-K") or ft.startswith("EX-99")):
                continue
            key = (h.accession, h.filename)
            if key not in hits:
                hits[key] = (h, set())
            hits[key][1].add(q)
    out = []
    for h, qs in hits.values():
        object.__setattr__(h, "_queries", tuple(sorted(qs)))
        out.append(h)
    return out


def extract_doc(hit: Hit, use_llm: bool) -> list[CovenantEvent]:
    try:
        text = doc_text(hit.url)
    except Exception as exc:
        print(f"  ! {hit.url}: {exc}", file=sys.stderr)
        return []
    filed = date.fromisoformat(hit.file_date)
    low = text.lower()
    found: list[CovenantEvent] = []
    seen = set()
    for q in getattr(hit, "_queries", QUERIES):
        for m in re.finditer(re.escape(q.lower()), low):
            s, e = sentence_bounds(text, m.start())
            if (s, e) in seen:
                continue
            seen.add((s, e))
            sent = text[s:e]
            if use_llm:
                kind = None if (DEFINITIONAL.search(sent) or is_stale(sent, filed)) else llm.classify_event(sent)
            else:
                kind = classify_sentence(sent, filed)
            if not kind:
                continue
            ev = CovenantEvent(
                cik=hit.cik, date=filed, kind=kind,
                span=Span(accession=hit.accession, url=hit.url, section=_item(hit), char_start=s, char_end=e, text=sent),
            )
            if text[ev.span.char_start:ev.span.char_end] == ev.span.text:
                found.append(ev)
    return found


def _item(hit: Hit) -> str | None:
    return ("Item " + ",".join(hit.items)) if hit.items else None


KIND_RANK = {"acceleration": 0, "default": 1, "waiver": 2, "amendment_loosening": 3}


def dedupe(events: list[CovenantEvent], window_days: int = 60) -> list[CovenantEvent]:
    """Per company and kind, events within `window_days` of the kept one collapse into it (earliest kept)."""
    out: list[CovenantEvent] = []
    last: dict[tuple[str, str], date] = {}
    seen_text: set[tuple[str, str]] = set()
    for ev in sorted(events, key=lambda e: (e.cik, e.kind, e.date, e.span.accession, e.span.char_start)):
        k = (ev.cik, ev.kind)
        # the same sentence repeated in later filings (e.g. quarterly earnings releases) is one event
        norm = (ev.cik, re.sub(r"[^a-z]", "", ev.span.text.lower())[-160:])
        if (k in last and (ev.date - last[k]).days <= window_days) or norm in seen_text:
            continue
        last[k] = ev.date
        seen_text.add(norm)
        out.append(ev)
    return sorted(out, key=lambda e: (e.cik, e.date, KIND_RANK[e.kind]))


def run(max_docs: int | None = None, use_llm: bool | None = None, per_company: int = 6, max_pages: int = 2) -> list[CovenantEvent]:
    if use_llm is None:
        use_llm = llm.available()
    print(f"classifier: {'llm ' + llm.MODEL if use_llm else 'deterministic'}", file=sys.stderr)
    hits = collect_hits(max_pages)
    hits.sort(key=lambda h: (-len(getattr(h, "_queries", ())), h.file_date))
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
    evs: list[CovenantEvent] = []
    for i, h in enumerate(chosen):
        evs.extend(extract_doc(h, use_llm))
        if i % 50 == 0:
            d = dedupe(evs)
            print(f"  [{i}/{len(chosen)}] events={len(d)} companies={len({e.cik for e in d})}", file=sys.stderr)
            save(d)
    evs = dedupe(evs)
    save(evs)
    return evs


def save(evs: list[CovenantEvent]) -> None:
    GROUNDTRUTH.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps([e.model_dump(mode="json") for e in evs], indent=1))
    tmp.replace(OUT)


def load() -> list[CovenantEvent]:
    if not OUT.exists():
        return []
    return [CovenantEvent.model_validate(x) for x in json.loads(OUT.read_text())]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-docs", type=int)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--per-company", type=int, default=6)
    ap.add_argument("--max-pages", type=int, default=2)
    a = ap.parse_args()
    evs = run(a.max_docs, False if a.no_llm else None, a.per_company, a.max_pages)
    kinds: dict[str, int] = {}
    for e in evs:
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
    print(f"{len(evs)} events {kinds}, {len({e.cik for e in evs})} companies")
