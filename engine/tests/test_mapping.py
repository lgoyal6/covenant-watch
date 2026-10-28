import json
from types import SimpleNamespace

from engine.mapping import map_leaf, table_map, validate
from engine.xbrl import CompanyFacts


def facts():
    """Synthetic companyfacts: 6 quarters of interest expense, net income, a debt balance, one split D&A pair."""
    q = [("2023-01-01", "2023-03-31"), ("2023-04-01", "2023-06-30"), ("2023-07-01", "2023-09-30"),
         ("2023-10-01", "2023-12-31"), ("2024-01-01", "2024-03-31"), ("2024-04-01", "2024-06-30")]
    dur = lambda vals: {"units": {"USD": [{"start": s, "end": e, "val": v, "accn": f"a{i}", "filed": "2024-08-01", "form": "10-Q"} for i, ((s, e), v) in enumerate(zip(q, vals))]}}
    inst = lambda vals: {"units": {"USD": [{"end": e, "val": v, "accn": f"b{i}", "filed": "2024-08-01", "form": "10-Q"} for i, ((_, e), v) in enumerate(zip(q, vals))]}}
    return CompanyFacts({"cik": 7, "entityName": "T", "facts": {"us-gaap": {
        "InterestExpense": dur([10] * 6), "NetIncomeLoss": dur([5, -2, 7, 8, 9, 10]), "LongTermDebt": inst([100] * 6),
        "Depreciation": dur([3] * 6), "OtherDepreciationAndAmortization": dur([1] * 6),
        "InterestIncomeExpenseNonoperatingNet": dur([-4] * 6),
    }}})


def test_ttm_and_table_mapping():
    cf = facts()
    assert [v.value for v in cf.ttm("us-gaap:InterestExpense").values()] == [40, 40, 40]
    m = table_map(cf, "int", "Consolidated Interest Expense", "ttm")
    assert m.concept == "us-gaap:InterestExpense" and m.validated
    assert "-us-gaap:InterestIncomeExpenseNonoperatingNet" in m.alternates or m.alternates == []
    d = table_map(cf, "debt", "Consolidated Total Debt", "instant")
    assert d.concept == "us-gaap:LongTermDebt" and d.kind == "instant"
    da = table_map(cf, "da", "depreciation and amortization", "ttm")
    assert da.concept == "us-gaap:Depreciation+us-gaap:OtherDepreciationAndAmortization"
    assert cf.ttm("us-gaap:Depreciation")[max(cf.ttm("us-gaap:Depreciation"))].value == 12


def test_validator_rejects_wrong_period_type_and_unsourceable():
    cf = facts()
    ok, why = validate(cf, "us-gaap:LongTermDebt", "ttm")
    assert not ok and "instant" in why
    m = table_map(cf, "syn", "projected cost savings and synergies", "ttm")
    assert m.concept is None and not m.validated
    nc = table_map(cf, "nc", "non-cash charges", "ttm")
    assert nc.kind == "ttm"  # "non-cash" is not a balance-sheet "cash" term


class StubClient:
    def __init__(self, answer):
        self.answer = answer
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kw):
        assert kw["model"] == "claude-sonnet-5-5"
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(self.answer))])


def test_llm_proposal_validated_and_merged():
    cf = facts()
    good = map_leaf(cf, "int", "Consolidated Interest Expense", "interest expense of the Borrower", "ttm",
                    client=StubClient({"concept": "us-gaap:InterestExpense", "partial": False, "confidence": 0.8, "reason": "direct"}))
    assert good.proposer == "llm" and good.concept == "us-gaap:InterestExpense" and good.confidence == 0.9  # table agreed
    hallucinated = map_leaf(cf, "int", "Consolidated Interest Expense", "x", "ttm",
                            client=StubClient({"concept": "us-gaap:MadeUpConcept", "partial": False, "confidence": 0.99, "reason": ""}))
    assert hallucinated.proposer == "table" and hallucinated.concept == "us-gaap:InterestExpense"
    assert "not among" in hallucinated.note
    wrong_type = map_leaf(cf, "debt", "Consolidated Total Debt", "x", "ttm",
                          client=StubClient({"concept": "us-gaap:InterestExpense", "partial": False, "confidence": 0.9, "reason": ""}))
    assert wrong_type.concept == "us-gaap:LongTermDebt"  # LLM offered a flow for a balance: rejected, table wins
