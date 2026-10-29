"""Interval headroom per covenant quarter.

The ratio range comes from the compiled definition graph. Headroom is the signed
distance to the threshold in force (positive = room left): for a max covenant
threshold - ratio, for a min covenant ratio - threshold. headroom_low is the worst
case, headroom_high the best.

Unbounded sides are reported as None alongside a non-refused status (the UI draws
them as open-ended); a refused quarter has no ratio at all.
"""

import math
from datetime import date

from engine.compiler import INF, Graph, Interval, LeafValue, divide, evaluate
from shared.schema import Covenant, Input, QuarterResult

WARNING_MARGIN = 0.10  # warning when worst-case headroom is within 10% of the threshold


def threshold_for(cov: Covenant, d: date) -> float | None:
    for t in cov.thresholds:
        if t.effective_from <= d and (t.effective_to is None or d <= t.effective_to):
            return t.value
    return None


def status(direction: str, lo: float, hi: float, thr: float, margin: float = WARNING_MARGIN) -> str:
    worst, best = (hi, lo) if direction == "max" else (lo, hi)
    bad = (lambda x: x > thr) if direction == "max" else (lambda x: x < thr)
    if bad(worst) and not bad(best):
        return "indeterminate"
    if bad(worst):
        return "breach"
    head = (thr - worst) if direction == "max" else (worst - thr)
    return "warning" if head < margin * abs(thr) else "ok"


def covenant_ratio(cov: Covenant, vals: dict[str, Interval]) -> Interval | None:
    num = vals[cov.numerator_term]
    if cov.denominator_term is None:
        return num
    den = vals[cov.denominator_term]
    r = divide(num, den)
    if r is not None:
        return r
    if cov.direction == "max" and num[0] > 0 and den[1] > 0:
        # denominator may be <= 0 in the worst case (e.g. EBITDA): worst case unbounded
        return (num[0] / den[1], INF)
    if cov.direction == "max" and num[0] > 0 and den[1] <= 0:
        return (INF, INF)  # e.g. positive debt over non-positive EBITDA: fails under any reading
    return None


def _fin(x: float) -> float | None:
    return None if math.isinf(x) or math.isnan(x) else round(x, 4)


def compute_quarter(cov: Covenant, g: Graph, period_end: date, leaves: dict[str, LeafValue], inputs: list[Input]) -> QuarterResult:
    thr = threshold_for(cov, period_end)
    vals, missing = evaluate(g, leaves)
    needed = set(g.leaves(cov.numerator_term)) | (set(g.leaves(cov.denominator_term)) if cov.denominator_term else set())
    missing = [m for m in missing if m in needed]
    if any(m in g.required for m in missing) or thr is None:
        return QuarterResult(covenant_id=cov.id, period_end=period_end, threshold=thr, status="refused", inputs=inputs, missing=missing)
    r = covenant_ratio(cov, vals)
    if r is None:
        return QuarterResult(covenant_id=cov.id, period_end=period_end, threshold=thr, status="refused", inputs=inputs, missing=missing)
    lo, hi = r
    st = status(cov.direction, lo, hi, thr)
    if cov.direction == "max":
        h_lo, h_hi = thr - hi, thr - lo
    else:
        h_lo, h_hi = lo - thr, hi - thr
    return QuarterResult(
        covenant_id=cov.id, period_end=period_end, ratio_low=_fin(lo), ratio_high=_fin(hi), threshold=thr,
        headroom_low=_fin(h_lo), headroom_high=_fin(h_hi), status=st, inputs=inputs, missing=missing,
    )
