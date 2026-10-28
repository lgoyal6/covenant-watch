"""XBRL companyfacts -> quarterly and trailing-four-quarter series with provenance.

Flow concepts (income statement, cash flow) are reported as 3-month, 6/9-month
year-to-date and full-year durations. We keep discrete quarters, derive missing
ones (Q4 = FY - 9M, Q2 = 6M - Q1, Q3 = 9M - 6M) and sum four contiguous quarters
for TTM. Balance concepts are instants, read as of the quarter end.

When a period was reported more than once (later filings restate), the most
recently filed value wins and its accession is the provenance.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from shared import edgar

QUARTER_DAYS = (80, 100)
HALF_DAYS = (170, 195)
NINE_DAYS = (260, 285)
YEAR_DAYS = (350, 380)
CONTIGUOUS_GAP_DAYS = 5  # fiscal calendars (52/53-week) leave small gaps between periods


@dataclass(frozen=True)
class Fact:
    concept: str  # "us-gaap:InterestExpense"
    value: float
    start: date | None
    end: date
    accession: str
    filed: date
    form: str


@dataclass
class Value:
    """A value used in a computation, with every fact it came from."""

    concept: str
    value: float
    start: date | None
    end: date
    accession: str  # the latest filing among the sources
    sources: list[Fact] = field(default_factory=list)
    derived: str | None = None  # how it was derived, e.g. "Q4 = FY - 9M"

    def note(self) -> str | None:
        parts = []
        if self.derived:
            parts.append(self.derived)
        if len(self.sources) > 1:
            parts.append("sources: " + ", ".join(f"{f.start or ''}..{f.end} {f.accession}" for f in self.sources))
        return "; ".join(parts) or None


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _days(f: Fact) -> int:
    return (f.end - f.start).days if f.start else 0


def _in(n: int, rng: tuple[int, int]) -> bool:
    return rng[0] <= n <= rng[1]


def _close(a: date, b: date, days: int = CONTIGUOUS_GAP_DAYS) -> bool:
    return abs((a - b).days) <= days


class CompanyFacts:
    """All USD facts for one company, indexed by concept."""

    def __init__(self, raw: dict):
        self.cik = f"{int(raw.get('cik', 0)):010d}"
        self.name = raw.get("entityName")
        self.facts: dict[str, list[Fact]] = {}
        for taxonomy, concepts in raw.get("facts", {}).items():
            for name, body in concepts.items():
                usd = body.get("units", {}).get("USD")
                if not usd:
                    continue
                key = f"{taxonomy}:{name}"
                out = []
                for r in usd:
                    if r.get("val") is None or not r.get("end"):
                        continue
                    out.append(Fact(key, float(r["val"]), _d(r.get("start")), _d(r["end"]), r.get("accn", ""), _d(r.get("filed")) or date.min, r.get("form", "")))
                if out:
                    self.facts[key] = out

    @classmethod
    def load(cls, cik: str) -> "CompanyFacts":
        return cls(edgar.company_facts(cik))

    def concepts(self) -> list[str]:
        return sorted(self.facts)

    def is_instant(self, concept: str) -> bool | None:
        fs = self.facts.get(concept)
        if not fs:
            return None
        return sum(f.start is None for f in fs) > len(fs) / 2

    # ---- flows ----

    def _latest(self, facts: list[Fact]) -> dict[tuple[date, date], Fact]:
        out: dict[tuple[date, date], Fact] = {}
        for f in facts:
            k = (f.start, f.end)
            if k not in out or f.filed > out[k].filed:
                out[k] = f
        return out

    def quarters(self, concept: str) -> dict[date, Value]:
        """Discrete fiscal-quarter values keyed by quarter end."""
        facts = [f for f in self.facts.get(concept, []) if f.start]
        by_period = self._latest(facts)
        q: dict[date, Value] = {}
        for (s, e), f in by_period.items():
            if _in(_days(f), QUARTER_DAYS):
                q[e] = Value(concept, f.value, s, e, f.accession, [f])
        longer = [f for f in by_period.values() if _days(f) > QUARTER_DAYS[1]]
        # Derive missing quarters from year-to-date differences, repeated until nothing changes.
        changed = True
        while changed:
            changed = False
            for big in longer:
                if big.end in q:
                    continue
                n = _days(big)
                if not (_in(n, HALF_DAYS) or _in(n, NINE_DAYS) or _in(n, YEAR_DAYS)):
                    continue
                # the shorter YTD period with the same start that ends one quarter earlier
                for small in by_period.values():
                    if small.start != big.start or small.end >= big.end:
                        continue
                    gap = (big.end - small.end).days
                    if not _in(gap, QUARTER_DAYS):
                        continue
                    label = {HALF_DAYS: "Q2 = 6M - Q1", NINE_DAYS: "Q3 = 9M - 6M", YEAR_DAYS: "Q4 = FY - 9M"}
                    rule = next(v for k, v in label.items() if _in(n, k))
                    start = small.end + timedelta(days=1)
                    latest = max((big, small), key=lambda f: f.filed)
                    q[big.end] = Value(concept, big.value - small.value, start, big.end, latest.accession, [big, small], rule)
                    changed = True
                    break
                else:
                    # YTD whose start is itself a quarter we know: big = sum of known quarters + one missing
                    pass
        return dict(sorted(q.items()))

    def ttm(self, concept: str) -> dict[date, Value]:
        """Trailing four contiguous quarters, keyed by the last quarter end."""
        qs = self.quarters(concept)
        ends = sorted(qs)
        out: dict[date, Value] = {}
        for i in range(3, len(ends)):
            chain = [qs[e] for e in ends[i - 3 : i + 1]]
            ok = all(chain[j].start and _close(chain[j].start, chain[j - 1].end + timedelta(days=1)) for j in range(1, 4))
            if not ok:
                continue
            srcs = [f for v in chain for f in v.sources]
            latest = max(srcs, key=lambda f: f.filed)
            derived = [v.derived for v in chain if v.derived]
            note = "TTM = sum of quarters ending " + ", ".join(str(v.end) for v in chain)
            if derived:
                note += " (" + "; ".join(derived) + ")"
            out[ends[i]] = Value(concept, sum(v.value for v in chain), chain[0].start, ends[i], latest.accession, srcs, note)
        return out

    # ---- balances ----

    def instants(self, concept: str) -> dict[date, Value]:
        facts = [f for f in self.facts.get(concept, []) if f.start is None]
        out: dict[date, Value] = {}
        for f in facts:
            if f.end not in out or f.filed > out[f.end].sources[0].filed:
                out[f.end] = Value(concept, f.value, None, f.end, f.accession, [f])
        return dict(sorted(out.items()))

    def series(self, concept: str, kind: str) -> dict[date, Value]:
        """kind: "ttm" | "quarter" | "instant"."""
        if kind == "instant":
            return self.instants(concept)
        if kind == "quarter":
            return self.quarters(concept)
        return self.ttm(concept)

    def quarter_ends(self) -> list[date]:
        """Quarter ends this company reports, from its income-statement facts."""
        ends: set[date] = set()
        for c in ("us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss", "us-gaap:OperatingIncomeLoss", "us-gaap:Revenues"):
            ends |= set(self.quarters(c))
        return sorted(ends)


def align(ends: list[date], target: date, tolerance_days: int = 7) -> date | None:
    """Match a fiscal quarter end (e.g. 2024-09-28) to a target date within a tolerance."""
    best = min(ends, key=lambda e: abs((e - target).days), default=None)
    return best if best and abs((best - target).days) <= tolerance_days else None
