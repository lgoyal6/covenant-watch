import pytest

from engine.stress import breakeven, latest_quarter, stress
from shared.paths import FIXTURES
from shared.schema import CovenantArtifact


def fixture():
    a = CovenantArtifact.model_validate_json((FIXTURES / "artifact_example.json").read_text())
    return a, {c.id: c for c in a.contract.covenants}


def test_breakeven_matches_hand_math():
    a, covs = fixture()
    q = latest_quarter(a, "lev")  # 2024-09-30: debt 1330, EBITDA low 263 (restructuring unsourced), limit 4.75
    b = breakeven(a, covs["lev"], q)
    ebitda_lo = 55 + 80 + 18 + 88 + 22
    assert b["earnings_change_to_breach_pct"] == pytest.approx((1330 / (4.75 * ebitda_lo) - 1) * 100, abs=1e-3)
    assert b["earnings_change_to_breach_pct"] > 0  # worst case is already past the limit
    q2 = latest_quarter(a, "icr")
    b2 = breakeven(a, covs["icr"], q2)
    assert b2["earnings_change_to_breach_pct"] == pytest.approx((3.0 * 80 / ebitda_lo - 1) * 100, abs=1e-3)  # about -8.7%


def test_stress_moves_ratio_and_status():
    a, covs = fixture()
    q = latest_quarter(a, "icr")
    base = stress(a, covs["icr"], q)
    assert base["ratio_low"] == pytest.approx(q.ratio_low, abs=1e-4) and base["status"] == q.status
    hit = stress(a, covs["icr"], q, earnings_change_pct=-25)
    assert hit["ratio_low"] == pytest.approx(q.ratio_low * 0.75, abs=1e-3) and hit["status"] in ("breach", "indeterminate")
    lev = stress(a, covs["lev"], latest_quarter(a, "lev"), earnings_change_pct=10)
    assert lev["ratio_high"] < latest_quarter(a, "lev").ratio_high
