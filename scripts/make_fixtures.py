"""Regenerate fixtures/ from one synthetic company. Run: uv run python scripts/make_fixtures.py

Everything here is SYNTHETIC ("Example Holdings, Inc. (FIXTURE)"). It exists so both
sides can build against the contract before real data exists.
"""

import json
from datetime import date, datetime, timezone

from shared.paths import FIXTURES
from shared.schema import (
    SCHEMA_VERSION,
    Agreement,
    Company,
    ContractExtraction,
    Covenant,
    CovenantArtifact,
    CovenantEvent,
    DisclosedRatio,
    EvalReport,
    GroundTruth,
    Input,
    QuarterResult,
    Refusal,
    Span,
    TermNode,
    Threshold,
    UniverseEntry,
)

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
CIK = "0000000001"
ORIG = "0000000001-22-000010"
AMEND = "0000000001-23-000020"
TENK = "0000000001-24-000030"
EIGHTK = "0000000001-24-000040"
URL = "https://www.sec.gov/Archives/edgar/data/1/{acc}/fixture.htm"

_offset = {"n": 1000}


def span(acc: str, section: str, text: str) -> Span:
    start = _offset["n"]
    _offset["n"] += len(text) + 200
    return Span(accession=acc, url=URL.format(acc=acc), section=section, char_start=start, char_end=start + len(text), text=text)


company = Company(cik=CIK, name="Example Holdings, Inc. (FIXTURE)", ticker="EXMP", sic="3711")

agreements = [
    Agreement(accession=ORIG, url=URL.format(acc=ORIG), filed=date(2022, 3, 15), kind="original", redacted=False),
    Agreement(accession=AMEND, url=URL.format(acc=AMEND), filed=date(2023, 8, 1), kind="amendment", redacted=False),
]

terms = [
    TermNode(id="ebitda", label="Consolidated EBITDA", op="sum", children=["ebitda_base", "noncash", "restructuring_capped"],
             span=span(ORIG, "1.01", '"Consolidated EBITDA" means, for any period, Consolidated Net Income for such period plus, without duplication and to the extent deducted in determining Consolidated Net Income, (a) Consolidated Interest Expense, (b) provision for taxes, (c) depreciation and amortization, (d) non-cash charges and (e) restructuring charges in an aggregate amount not to exceed 10% of Consolidated EBITDA (calculated before giving effect to this clause (e)).')),
    TermNode(id="ebitda_base", label="EBITDA before addbacks", op="sum", children=["net_income", "interest_expense", "taxes", "d_and_a"],
             span=span(ORIG, "1.01", "Consolidated Net Income for such period plus, without duplication and to the extent deducted in determining Consolidated Net Income, (a) Consolidated Interest Expense, (b) provision for taxes, (c) depreciation and amortization")),
    TermNode(id="net_income", label="Consolidated Net Income", op="leaf", span=span(ORIG, "1.01", '"Consolidated Net Income" means, for any period, the net income (or loss) of the Borrower and its Subsidiaries on a consolidated basis')),
    TermNode(id="interest_expense", label="Consolidated Interest Expense", op="leaf", span=span(ORIG, "1.01", '"Consolidated Interest Expense" means, for any period, the total interest expense of the Borrower and its Subsidiaries')),
    TermNode(id="taxes", label="provision for taxes", op="leaf", span=span(ORIG, "1.01", "(b) provision for taxes")),
    TermNode(id="d_and_a", label="depreciation and amortization", op="leaf", span=span(ORIG, "1.01", "(c) depreciation and amortization")),
    TermNode(id="noncash", label="non-cash charges", op="leaf", span=span(ORIG, "1.01", "(d) non-cash charges")),
    TermNode(id="restructuring_capped", label="restructuring charges (capped)", op="cap", children=["restructuring"],
             cap={"kind": "pct_of", "of": "ebitda_base", "pct": 0.10},
             span=span(ORIG, "1.01", "(e) restructuring charges in an aggregate amount not to exceed 10% of Consolidated EBITDA (calculated before giving effect to this clause (e))")),
    TermNode(id="restructuring", label="restructuring charges", op="leaf", span=span(ORIG, "1.01", "(e) restructuring charges")),
    TermNode(id="total_debt", label="Consolidated Total Debt", op="leaf", span=span(ORIG, "1.01", '"Consolidated Total Debt" means, as of any date of determination, the aggregate principal amount of all Indebtedness of the Borrower and its Subsidiaries')),
]

leverage_thresholds = [
    Threshold(effective_from=date(2022, 3, 15), effective_to=date(2023, 7, 31), value=4.50,
              source=span(ORIG, "7.11(a)", "permit the Consolidated Leverage Ratio as of the last day of any fiscal quarter to be greater than 4.50 to 1.00")),
    Threshold(effective_from=date(2023, 8, 1), effective_to=date(2024, 6, 30), value=5.25,
              source=span(AMEND, "2.03", "Section 7.11(a) is hereby amended by replacing 4.50 to 1.00 with 5.25 to 1.00 for each fiscal quarter ending on or prior to June 30, 2024")),
    Threshold(effective_from=date(2024, 7, 1), value=4.75,
              source=span(AMEND, "2.03", "and 4.75 to 1.00 for each fiscal quarter ending thereafter")),
]

covenants = [
    Covenant(id="lev", kind="max_leverage", direction="max", numerator_term="total_debt", denominator_term="ebitda", test_period="ttm",
             thresholds=leverage_thresholds, agreement_accession=ORIG,
             span=span(ORIG, "7.11(a)", "Consolidated Leverage Ratio. Permit the Consolidated Leverage Ratio as of the last day of any fiscal quarter to be greater than 4.50 to 1.00.")),
    Covenant(id="icr", kind="min_interest_coverage", direction="min", numerator_term="ebitda", denominator_term="interest_expense", test_period="ttm",
             thresholds=[Threshold(effective_from=date(2022, 3, 15), value=3.00,
                                   source=span(ORIG, "7.11(b)", "permit the Consolidated Interest Coverage Ratio for any period of four consecutive fiscal quarters to be less than 3.00 to 1.00"))],
             agreement_accession=ORIG,
             span=span(ORIG, "7.11(b)", "Consolidated Interest Coverage Ratio. Permit the Consolidated Interest Coverage Ratio for any period of four consecutive fiscal quarters to be less than 3.00 to 1.00.")),
]

contract = ContractExtraction(
    schema_version=SCHEMA_VERSION, generated_at=NOW, company=company, agreements=agreements, terms=terms, covenants=covenants,
    refusals=[], extraction_notes=["FIXTURE: synthetic company for development only."],
)

# TTM values in $ millions per quarter end. restructuring None = unmapped that quarter.
TTM = {
    date(2023, 3, 31): dict(net_income=120, interest_expense=60, taxes=40, d_and_a=80, noncash=15, restructuring=10, total_debt=1200),
    date(2023, 6, 30): dict(net_income=105, interest_expense=64, taxes=35, d_and_a=82, noncash=16, restructuring=12, total_debt=1260),
    date(2023, 9, 30): dict(net_income=90, interest_expense=68, taxes=30, d_and_a=84, noncash=18, restructuring=20, total_debt=1320),
    date(2023, 12, 31): dict(net_income=80, interest_expense=72, taxes=26, d_and_a=85, noncash=18, restructuring=25, total_debt=1380),
    date(2024, 3, 31): dict(net_income=70, interest_expense=75, taxes=22, d_and_a=86, noncash=20, restructuring=28, total_debt=1400),
    date(2024, 6, 30): dict(net_income=62, interest_expense=78, taxes=20, d_and_a=87, noncash=20, restructuring=30, total_debt=1420),
    date(2024, 9, 30): dict(net_income=55, interest_expense=80, taxes=18, d_and_a=88, noncash=22, restructuring=None, total_debt=1330),
    date(2024, 12, 31): None,  # 10-K not filed yet: refused
}
CONCEPTS = {
    "net_income": "us-gaap:NetIncomeLoss",
    "interest_expense": "us-gaap:InterestExpense",
    "taxes": "us-gaap:IncomeTaxExpenseBenefit",
    "d_and_a": "us-gaap:DepreciationDepletionAndAmortization",
    "noncash": "us-gaap:ShareBasedCompensation",
    "restructuring": "us-gaap:RestructuringCharges",
    "total_debt": "us-gaap:LongTermDebt",
}


def threshold_for(cov: Covenant, d: date) -> float:
    for t in cov.thresholds:
        if t.effective_from <= d and (t.effective_to is None or d <= t.effective_to):
            return t.value
    raise ValueError(d)


def ebitda_range(v: dict) -> tuple[float, float]:
    base = v["net_income"] + v["interest_expense"] + v["taxes"] + v["d_and_a"]
    cap = 0.10 * base
    if v["restructuring"] is None:  # unmapped: bound by zero and the cap
        return base + v["noncash"], base + v["noncash"] + cap
    r = min(v["restructuring"], cap)
    return base + v["noncash"] + r, base + v["noncash"] + r


def status(direction: str, lo: float, hi: float, thr: float, margin: float = 0.10) -> str:
    worst, best = (hi, lo) if direction == "max" else (lo, hi)
    bad = (lambda x: x > thr) if direction == "max" else (lambda x: x < thr)
    if bad(worst) and not bad(best):
        return "indeterminate"
    if bad(worst):
        return "breach"
    head = (thr - worst) if direction == "max" else (worst - thr)
    return "warning" if head < margin * thr else "ok"


def inputs_for(d: date, v: dict, leaves: list[str]) -> list[Input]:
    out = []
    for leaf in leaves:
        val = v[leaf]
        out.append(Input(term_node=leaf, value=None if val is None else val * 1e6, xbrl_concept=CONCEPTS[leaf] if val is not None else None,
                         fact_accession=TENK if val is not None else None, period_start=None if leaf == "total_debt" else date(d.year - 1, d.month, 1),
                         period_end=d, mapping_confidence=0.95 if val is not None else 0.0, validated=val is not None,
                         validation_note=None if val is not None else "no reported restructuring line this quarter"))
    return out


quarters: list[QuarterResult] = []
refusals: list[Refusal] = []
EBITDA_LEAVES = ["net_income", "interest_expense", "taxes", "d_and_a", "noncash", "restructuring"]
for d, v in TTM.items():
    for cov in covenants:
        thr = threshold_for(cov, d)
        if v is None:
            quarters.append(QuarterResult(covenant_id=cov.id, period_end=d, threshold=thr, status="refused"))
            continue
        e_lo, e_hi = ebitda_range(v)
        missing = ["restructuring"] if v["restructuring"] is None else []
        if cov.id == "lev":
            lo, hi = v["total_debt"] / e_hi, v["total_debt"] / e_lo
            h_lo, h_hi = thr - hi, thr - lo
            leaves = ["total_debt", *EBITDA_LEAVES]
        else:
            lo, hi = e_lo / v["interest_expense"], e_hi / v["interest_expense"]
            h_lo, h_hi = lo - thr, hi - thr
            leaves = EBITDA_LEAVES
        quarters.append(QuarterResult(covenant_id=cov.id, period_end=d, ratio_low=round(lo, 4), ratio_high=round(hi, 4), threshold=thr,
                                      headroom_low=round(h_lo, 4), headroom_high=round(h_hi, 4), status=status(cov.direction, lo, hi, thr),
                                      inputs=inputs_for(d, v, leaves), missing=missing))
refusals.append(Refusal(scope="quarter", ref="2024-12-31", reason="missing_filing", detail="FY2024 10-K not yet filed; no XBRL facts for the quarter."))

artifact = CovenantArtifact(schema_version=SCHEMA_VERSION, generated_at=NOW, contract=contract, quarters=quarters, refusals=refusals)

groundtruth = GroundTruth(
    disclosed=[DisclosedRatio(cik=CIK, period_end=date(2024, 6, 30), covenant_kind="max_leverage", reported_value=4.87, reported_threshold=5.25,
                              span=span(TENK, None, "As of June 30, 2024, our Consolidated Leverage Ratio was 4.87 to 1.00, compared to a maximum of 5.25 to 1.00."))],
    events=[CovenantEvent(cik=CIK, date=date(2024, 11, 12), kind="waiver",
                          span=span(EIGHTK, "Item 1.01", "the Lenders agreed to waive any Event of Default arising from the Borrower's failure to comply with Section 7.11(a) for the fiscal quarter ending September 30, 2024"))],
    universe=[UniverseEntry(cik=CIK, role="event"), UniverseEntry(cik="0000000002", role="peer", peer_of=CIK)],
)

eval_report = EvalReport(
    schema_version=SCHEMA_VERSION, generated_at=NOW,
    extraction={"covenant_kind": {"precision": 1.0, "recall": 1.0}, "threshold_value": {"precision": 0.95, "recall": 0.9}, "term_structure": {"precision": 0.85, "recall": 0.8}},
    ratio_accuracy={"n": 1, "median_abs_error": 0.002, "pct_within_0_05": 1.0},
    early_warning={"events": 1, "hit_rate": 1.0, "median_lead_quarters": 2, "peer_false_alarm_rate": 0.0},
    refusals={"missing_filing": 1},
    per_company=[{"cik": CIK, "name": company.name, "covenants": 2, "quarters": len(quarters), "note": "FIXTURE"}],
)


def write(name: str, model) -> None:
    FIXTURES.mkdir(exist_ok=True)
    (FIXTURES / name).write_text(model.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    write("contract_example.json", contract)
    write("artifact_example.json", artifact)
    write("groundtruth_example.json", groundtruth)
    write("eval_example.json", eval_report)
    for q in quarters:
        print(q.covenant_id, q.period_end, q.ratio_low, q.ratio_high, q.threshold, q.status)
