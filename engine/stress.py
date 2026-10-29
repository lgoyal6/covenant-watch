"""Covenant stress math on the engine's own intervals.

For a covenant quarter we evaluate the definition graph to get the earnings term (EBITDA-like:
the denominator of a max covenant, the numerator of a min covenant) and the other term (debt for
leverage, interest or fixed charges for coverage) as intervals, then:

  breakeven   how far earnings can fall, or the other term can rise, before the worst case breaches
  stress      the ratio range, headroom and status after scaling either term

Exact algebra on the same intervals the headroom uses, so caps and unsourced addbacks carry through.
"""

import math
from datetime import date

from engine.compiler import Graph, LeafValue, compile_terms, divide, evaluate
from engine.compute import status, threshold_for
from shared.schema import Covenant, CovenantArtifact, QuarterResult


def _fin(x):
    return None if x is None or math.isinf(x) or math.isnan(x) else round(x, 4)


def _terms(cov: Covenant) -> tuple[str, str | None]:
    """(earnings term, other term)."""
    if cov.direction == "max":
        return cov.denominator_term or cov.numerator_term, cov.numerator_term if cov.denominator_term else None
    return cov.numerator_term, cov.denominator_term


def latest_quarter(a: CovenantArtifact, cov_id: str, period_end: date | None = None) -> QuarterResult | None:
    qs = [q for q in a.quarters if q.covenant_id == cov_id and q.status != "refused" and q.inputs]
    if period_end:
        qs = [q for q in qs if q.period_end == period_end]
    return qs[-1] if qs else None


def _intervals(a: CovenantArtifact, cov: Covenant, q: QuarterResult):
    roots = [t for t in (cov.numerator_term, cov.denominator_term) if t]
    g: Graph = compile_terms(a.contract.terms, roots)
    leaves = {i.term_node: LeafValue(i.value) for i in q.inputs}
    vals, _ = evaluate(g, leaves)
    earn, other = _terms(cov)
    return vals[earn], (vals[other] if other else None)


def _ratio(cov: Covenant, earn, other):
    if other is None:
        return earn
    return divide(other, earn) if cov.direction == "max" else divide(earn, other)


def breakeven(a: CovenantArtifact, cov: Covenant, q: QuarterResult) -> dict:
    """Percent change in earnings (negative = fall) or in the other term that brings the worst case to the limit."""
    thr = threshold_for(cov, q.period_end)
    earn, other = _intervals(a, cov, q)
    out = {"covenant_id": cov.id, "kind": cov.kind, "direction": cov.direction, "period_end": str(q.period_end), "threshold": thr,
           "earnings_change_to_breach_pct": None, "other_change_to_breach_pct": None, "note": None}
    e_lo = earn[0]
    if not thr or e_lo <= 0 or math.isinf(e_lo):
        out["note"] = "earnings are non-positive or unbounded in the worst case; no breakeven"
        return out
    if other is None:  # single-term test, e.g. minimum liquidity
        out["earnings_change_to_breach_pct"] = _fin((thr / e_lo - 1) * 100)
        return out
    o_hi = other[1]
    if o_hi <= 0 or math.isinf(o_hi):
        out["note"] = "the other term is non-positive or unbounded; no breakeven"
        return out
    if cov.direction == "max":  # other / earn <= thr
        out["earnings_change_to_breach_pct"] = _fin((o_hi / (thr * e_lo) - 1) * 100)
        out["other_change_to_breach_pct"] = _fin((thr * e_lo / o_hi - 1) * 100)
    else:  # earn / other >= thr
        out["earnings_change_to_breach_pct"] = _fin((thr * o_hi / e_lo - 1) * 100)
        out["other_change_to_breach_pct"] = _fin((e_lo / (thr * o_hi) - 1) * 100)
    return out


def stress(a: CovenantArtifact, cov: Covenant, q: QuarterResult, earnings_change_pct: float = 0.0, other_change_pct: float = 0.0) -> dict:
    thr = threshold_for(cov, q.period_end)
    earn, other = _intervals(a, cov, q)
    fe, fo = 1 + earnings_change_pct / 100, 1 + other_change_pct / 100
    earn2 = (earn[0] * fe, earn[1] * fe)
    other2 = (other[0] * fo, other[1] * fo) if other else None
    r = _ratio(cov, earn2, other2)
    if r is None or thr is None:
        return {"covenant_id": cov.id, "period_end": str(q.period_end), "status": "refused", "note": "ratio undefined under this scenario"}
    lo, hi = r
    st = status(cov.direction, lo, hi, thr)
    h = (thr - hi, thr - lo) if cov.direction == "max" else (lo - thr, hi - thr)
    return {"covenant_id": cov.id, "kind": cov.kind, "period_end": str(q.period_end), "threshold": thr,
            "earnings_change_pct": earnings_change_pct, "other_change_pct": other_change_pct,
            "baseline": {"ratio_low": q.ratio_low, "ratio_high": q.ratio_high, "status": q.status},
            "ratio_low": _fin(lo), "ratio_high": _fin(hi), "headroom_low": _fin(h[0]), "headroom_high": _fin(h[1]), "status": st}
