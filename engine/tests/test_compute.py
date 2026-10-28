from datetime import date

import pytest

from engine.compiler import INF, CompileError, LeafValue, compile_terms, divide, evaluate
from engine.compute import compute_quarter, status, threshold_for
from shared.paths import FIXTURES
from shared.schema import ContractExtraction, CovenantArtifact, Span, TermNode

SPAN = Span(accession="x", url="u", char_start=0, char_end=1, text="x")


def node(id, op, children=(), cap=None):
    return TermNode(id=id, label=id, op=op, children=list(children), cap=cap, span=SPAN)


def test_golden_fixture():
    """contract_example + the fixture's leaf values reproduce artifact_example's ratios and statuses."""
    contract = ContractExtraction.model_validate_json((FIXTURES / "contract_example.json").read_text())
    expected = CovenantArtifact.model_validate_json((FIXTURES / "artifact_example.json").read_text())
    covs = {c.id: c for c in contract.covenants}
    roots = [t for c in contract.covenants for t in (c.numerator_term, c.denominator_term) if t]
    g = compile_terms(contract.terms, roots)
    for q in expected.quarters:
        leaves = {i.term_node: LeafValue(i.value) for i in q.inputs}
        got = compute_quarter(covs[q.covenant_id], g, q.period_end, leaves, q.inputs)
        if not q.inputs:
            assert got.status == "refused" == q.status
            continue
        assert got.status == q.status, (q.covenant_id, q.period_end)
        assert got.threshold == q.threshold
        for f in ("ratio_low", "ratio_high", "headroom_low", "headroom_high"):
            assert getattr(got, f) == pytest.approx(getattr(q, f), abs=1e-4), (q.covenant_id, q.period_end, f)
        assert got.missing == q.missing


def test_cap_order_and_unmapped_addback():
    g = compile_terms([
        node("e", "sum", ["base", "capped"]), node("base", "sum", ["ni", "int"]),
        node("capped", "cap", ["r"], {"kind": "pct_of", "of": "base", "pct": 0.1}),
        node("ni", "leaf"), node("int", "leaf"), node("r", "leaf"),
    ], ["e"])
    assert g.order.index("base") < g.order.index("capped")
    v, missing = evaluate(g, {"ni": LeafValue(80), "int": LeafValue(20), "r": LeafValue(50)})
    assert v["e"] == (110, 110) and missing == []  # 50 capped at 10% of 100
    v, missing = evaluate(g, {"ni": LeafValue(80), "int": LeafValue(20)})
    assert v["e"] == (100, 110) and missing == ["r"]  # low: zero, high: the cap
    assert g.required == {"ni"}


def test_uncapped_addback_is_unbounded_and_abs_cap():
    g = compile_terms([node("e", "sum", ["ni", "x", "y"]), node("y", "cap", ["yy"], {"kind": "abs", "usd": 5}),
                       node("ni", "leaf"), node("x", "leaf"), node("yy", "leaf")], ["e"])
    v, _ = evaluate(g, {"ni": LeafValue(10), "yy": LeafValue(9)})
    assert v["e"] == (15, INF)


def test_subtract_and_floor():
    g = compile_terms([node("s", "subtract", ["a", "b"]), node("f", "floor", ["s"]), node("a", "leaf"), node("b", "leaf")], ["f"])
    v, _ = evaluate(g, {"a": LeafValue(3), "b": LeafValue(5)})
    assert v["s"] == (-2, -2) and v["f"] == (0, 0)


def test_cycle_and_undefined_rejected():
    with pytest.raises(CompileError):
        compile_terms([node("a", "sum", ["b"]), node("b", "sum", ["a"])], ["a"])
    with pytest.raises(CompileError):
        compile_terms([node("a", "sum", ["zzz"])], ["a"])


def test_divide():
    assert divide((10, 20), (2, 5)) == (2, 10)
    assert divide((10, 10), (0, 5)) is None
    assert divide((10, 10), (5, INF)) == (0.0, 2.0)


def test_status_and_step_downs():
    assert status("max", 4.0, 4.0, 4.5) == "ok"  # headroom 0.5 >= 10% of 4.5
    assert status("max", 4.1, 4.1, 4.5) == "warning"
    assert status("max", 3.0, 3.0, 4.5) == "ok"
    assert status("max", 4.4, 4.6, 4.5) == "indeterminate"
    assert status("max", 4.6, 4.7, 4.5) == "breach"
    assert status("min", 2.9, 3.5, 3.0) == "indeterminate"
    assert status("min", 3.1, 3.1, 3.0) == "warning"
    contract = ContractExtraction.model_validate_json((FIXTURES / "contract_example.json").read_text())
    lev = next(c for c in contract.covenants if c.id == "lev")
    assert threshold_for(lev, date(2023, 6, 30)) == 4.5
    assert threshold_for(lev, date(2023, 9, 30)) == 5.25
    assert threshold_for(lev, date(2024, 9, 30)) == 4.75
    assert threshold_for(lev, date(2021, 1, 1)) is None
