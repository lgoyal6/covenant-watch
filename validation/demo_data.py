"""Demo dataset for exercising the product at volume: 100 fictional companies.

  uv run python -m validation.demo_data          # writes data/demo/
  CW_DATASET=demo uv run uvicorn api.main:app     # serve it

Nothing here describes a real company. Names are invented, CIKs sit in an unused
range (99xxxxxxxx), tickers carry a digit (no real listing does) and every document URL is on example.invalid.
The numbers still go through the real pipeline: contracts are compiled and
computed by engine/, and the eval report is produced by validation/score.py.

Each company follows one of three paths. "stress" companies drift toward their
leverage limit and then disclose a waiver, loosening amendment or default; peers
in the same SIC stay healthy; the rest are steady. Some quarters lack a restructuring
line (so the ratio becomes a range) and some recent quarters are unfiled (refused).
"""

import json
import random
from datetime import date, datetime, timezone

from engine.compiler import LeafValue, compile_terms
from engine.compute import compute_quarter
from shared.paths import DATA
from shared.schema import (
    SCHEMA_VERSION, Agreement, Company, ContractExtraction, Covenant, CovenantArtifact, CovenantEvent, DisclosedRatio,
    Input, QuarterResult, Refusal, Span, TermNode, Threshold, UniverseEntry,
)
from validation.score import build_report

OUT = DATA / "demo"
N = 100
SEED = 20261028
QUARTERS = [date(y, m, d) for y in (2022, 2023, 2024, 2025) for m, d in ((3, 31), (6, 30), (9, 30), (12, 31))][:14]
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)

FIRST = ["Alder", "Basalt", "Cobalt", "Driftwood", "Ember", "Fernhill", "Granite", "Harbor", "Ironvale", "Juniper", "Kestrel", "Larkspur",
         "Meridian", "Northgate", "Oakmont", "Pinecrest", "Quarry", "Redwater", "Silverline", "Tidewell", "Upland", "Vantage", "Westbrook", "Yarrow"]
SECOND = ["Industries", "Holdings", "Logistics", "Foods", "Materials", "Health", "Energy", "Brands", "Systems", "Media", "Hospitality", "Packaging"]
SICS = {"Industries": "3560", "Holdings": "6719", "Logistics": "4731", "Foods": "2000", "Materials": "2800", "Health": "8062",
        "Energy": "1311", "Brands": "2300", "Systems": "7372", "Media": "4841", "Hospitality": "7011", "Packaging": "2650"}
# every first-word/second-word pair, shuffled once: 288 unique names for up to 288 companies
NAMES = [(f, s) for f in FIRST for s in SECOND]
random.Random(7).shuffle(NAMES)
QUOTES = {
    "lev": "Consolidated Leverage Ratio. Permit the Consolidated Leverage Ratio as of the last day of any fiscal quarter to be greater than {v:.2f} to 1.00.",
    "icr": "Consolidated Interest Coverage Ratio. Permit the Consolidated Interest Coverage Ratio for any period of four consecutive fiscal quarters to be less than {v:.2f} to 1.00.",
}


def span(cik: str, acc: str, section: str | None, text: str, pos: list[int]) -> Span:
    start = pos[0]
    pos[0] += len(text) + 120
    return Span(accession=acc, url=f"https://example.invalid/demo/{int(cik)}/{acc}.htm", section=section,
                char_start=start, char_end=start + len(text), text=text)


def make_contract(i: int, rng: random.Random, stress: bool):
    cik = f"99{i:08d}"
    first, second = NAMES[i - 1]
    name = f"{first} {second}"
    sic = SICS[second]
    orig, amend = f"{cik}-22-{i:06d}", f"{cik}-24-{i:06d}"
    pos = [800]
    S = lambda sec, t, acc=orig: span(cik, acc, sec, t, pos)
    terms = [
        TermNode(id="ebitda", label="Consolidated EBITDA", op="sum", children=["ebitda_base", "noncash", "restructuring_capped"],
                 span=S("1.01", '"Consolidated EBITDA" means Consolidated Net Income plus interest, taxes, depreciation and amortization, non-cash charges and capped restructuring charges.')),
        TermNode(id="ebitda_base", label="EBITDA before addbacks", op="sum", children=["net_income", "interest_expense", "taxes", "d_and_a"],
                 span=S("1.01", "Consolidated Net Income plus (a) Consolidated Interest Expense, (b) provision for taxes, (c) depreciation and amortization")),
        TermNode(id="net_income", label="Consolidated Net Income", op="leaf", span=S("1.01", '"Consolidated Net Income" means the net income of the Borrower and its Subsidiaries')),
        TermNode(id="interest_expense", label="Consolidated Interest Expense", op="leaf", span=S("1.01", '"Consolidated Interest Expense" means total interest expense')),
        TermNode(id="taxes", label="provision for taxes", op="leaf", span=S("1.01", "(b) provision for taxes")),
        TermNode(id="d_and_a", label="depreciation and amortization", op="leaf", span=S("1.01", "(c) depreciation and amortization")),
        TermNode(id="noncash", label="non-cash charges", op="leaf", span=S("1.01", "(d) non-cash charges")),
        TermNode(id="restructuring_capped", label="restructuring charges (capped)", op="cap", children=["restructuring"],
                 cap={"kind": "pct_of", "of": "ebitda_base", "pct": rng.choice([0.10, 0.15])}, span=S("1.01", "(e) restructuring charges, capped")),
        TermNode(id="restructuring", label="restructuring charges", op="leaf", span=S("1.01", "(e) restructuring charges")),
        TermNode(id="total_debt", label="Consolidated Total Debt", op="leaf", span=S("1.01", '"Consolidated Total Debt" means all Indebtedness for borrowed money')),
    ]
    lev_thr = round(rng.choice([3.5, 3.75, 4.0, 4.25, 4.5, 5.0, 5.5]), 2)
    icr_thr = round(rng.choice([2.0, 2.5, 3.0, 3.5]), 2)
    lev_ths = [Threshold(effective_from=date(2022, 1, 1), value=lev_thr, source=S("7.11(a)", QUOTES["lev"].format(v=lev_thr)))]
    agreements = [Agreement(accession=orig, url=f"https://example.invalid/demo/{int(cik)}/{orig}.htm", filed=date(2022, 1, 15), kind="original", redacted=False)]
    if stress and rng.random() < 0.6:  # loosening amendment: limit steps up for a year, then back down
        lev_ths[0] = Threshold(effective_from=date(2022, 1, 1), effective_to=date(2024, 3, 30), value=lev_thr, source=lev_ths[0].source)
        up = round(lev_thr + rng.choice([0.5, 0.75, 1.0]), 2)
        lev_ths += [
            Threshold(effective_from=date(2024, 3, 31), effective_to=date(2025, 3, 30), value=up, source=S("2.01", f"replacing {lev_thr:.2f} to 1.00 with {up:.2f} to 1.00", amend)),
            Threshold(effective_from=date(2025, 3, 31), value=lev_thr, source=S("2.01", f"and {lev_thr:.2f} to 1.00 thereafter", amend)),
        ]
        agreements.append(Agreement(accession=amend, url=f"https://example.invalid/demo/{int(cik)}/{amend}.htm", filed=date(2024, 3, 20), kind="amendment", redacted=False))
    covenants = [Covenant(id="lev", kind="max_leverage", direction="max", numerator_term="total_debt", denominator_term="ebitda", test_period="ttm",
                          thresholds=lev_ths, agreement_accession=orig, span=S("7.11(a)", QUOTES["lev"].format(v=lev_thr)))]
    if rng.random() < 0.8:
        covenants.append(Covenant(id="icr", kind="min_interest_coverage", direction="min", numerator_term="ebitda", denominator_term="interest_expense",
                                  test_period="ttm", thresholds=[Threshold(effective_from=date(2022, 1, 1), value=icr_thr, source=S("7.11(b)", QUOTES["icr"].format(v=icr_thr)))],
                                  agreement_accession=orig, span=S("7.11(b)", QUOTES["icr"].format(v=icr_thr))))
    refusals = []
    if rng.random() < 0.06:
        refusals.append(Refusal(scope="agreement", ref=orig, reason="redacted", detail="Schedule 7.11 thresholds redacted ([***]) in the filed exhibit; covenant levels not public."))
    contract = ContractExtraction(schema_version=SCHEMA_VERSION, generated_at=NOW, company=Company(cik=cik, name=name, ticker=f"{first[:2].upper()}{second[0]}{i % 10}", sic=sic),
                                  agreements=agreements, terms=terms, covenants=covenants, refusals=refusals,
                                  extraction_notes=[])
    return contract, lev_thr


def series(rng: random.Random, path: str, lev_thr: float, n: int):
    """TTM leaf values ($M) per quarter. Stress paths walk leverage up through the limit."""
    scale = rng.uniform(80, 900)
    ebitda0 = scale
    # some healthy companies run close to the limit, so the signal has false alarms to find
    target0 = lev_thr * (rng.uniform(0.86, 0.95) if path == "steady" and rng.random() < 0.18 else rng.uniform(0.55, 0.8))
    rows = []
    for k in range(n):
        t = k / max(1, n - 1)
        if path == "stress":
            lev = target0 + (lev_thr * rng.uniform(1.02, 1.18) - target0) * (t ** 1.4) + rng.gauss(0, 0.06)
            e = ebitda0 * (1 - 0.35 * t) * (1 + rng.gauss(0, 0.02))
        elif path == "improving":
            lev = target0 * (1 - 0.25 * t) + rng.gauss(0, 0.05)
            e = ebitda0 * (1 + 0.2 * t) * (1 + rng.gauss(0, 0.02))
        else:
            lev = target0 + rng.gauss(0, 0.08)
            e = ebitda0 * (1 + 0.04 * t) * (1 + rng.gauss(0, 0.02))
        interest = e * rng.uniform(0.12, 0.2) * (1 + (0.6 * t if path == "stress" else 0))
        taxes, da = e * 0.12, e * 0.3
        noncash, restr = e * 0.04, e * rng.uniform(0.0, 0.12)
        ni = e - interest - taxes - da - noncash - min(restr, 0.1 * (e - noncash - restr))
        rows.append(dict(net_income=ni, interest_expense=interest, taxes=taxes, d_and_a=da, noncash=noncash,
                         restructuring=None if rng.random() < 0.12 else restr, total_debt=lev * e))
    return rows


CONCEPTS = {"net_income": "us-gaap:NetIncomeLoss", "interest_expense": "us-gaap:InterestExpense", "taxes": "us-gaap:IncomeTaxExpenseBenefit",
            "d_and_a": "us-gaap:DepreciationDepletionAndAmortization", "noncash": "us-gaap:ShareBasedCompensation",
            "restructuring": "us-gaap:RestructuringCharges", "total_debt": "us-gaap:LongTermDebt"}


def build(n: int = N, seed: int = SEED):
    rng = random.Random(seed)
    arts, disclosed, events, universe = {}, [], [], []
    paths = ["stress"] * 30 + ["improving"] * 15 + ["steady"] * (n - 45)
    rng.shuffle(paths)
    for i in range(1, n + 1):
        path = paths[i - 1]
        contract, lev_thr = make_contract(i, rng, path == "stress")
        cik = contract.company.cik
        nq = rng.randint(9, 14)
        qs = QUARTERS[-nq:]
        vals = series(rng, path, lev_thr, nq)
        roots = [t for c in contract.covenants for t in (c.numerator_term, c.denominator_term) if t]
        g = compile_terms(contract.terms, roots)
        quarters, refusals = [], list(contract.refusals)
        unfiled = rng.random() < 0.15
        for k, (qe, v) in enumerate(zip(qs, vals)):
            for cov in contract.covenants:
                if unfiled and k == nq - 1:
                    quarters.append(QuarterResult(covenant_id=cov.id, period_end=qe, threshold=cov.thresholds[-1].value, status="refused"))
                    continue
                acc = f"{cik}-{qe.year % 100:02d}-{k:06d}"
                inputs = [Input(term_node=leaf, value=None if v[leaf] is None else round(v[leaf] * 1e6), xbrl_concept=CONCEPTS[leaf] if v[leaf] is not None else None,
                                fact_accession=acc if v[leaf] is not None else None, period_end=qe, mapping_confidence=0.9 if v[leaf] is not None else 0.0,
                                validated=v[leaf] is not None, validation_note=None if v[leaf] is not None else "no restructuring line reported this quarter")
                          for leaf in CONCEPTS]
                leaves = {leaf: LeafValue(None if v[leaf] is None else v[leaf] * 1e6) for leaf in CONCEPTS}
                quarters.append(compute_quarter(cov, g, qe, leaves, inputs))
        if unfiled:
            refusals.append(Refusal(scope="quarter", ref=str(qs[-1]), reason="missing_filing", detail="Latest 10-Q not yet filed; no XBRL facts for the quarter."))
        if any(q.missing for q in quarters):
            refusals.append(Refusal(scope="covenant", ref="lev", reason="unmapped_term",
                                    detail='"restructuring charges" missing in some quarters; bounded instead of computed: low case 0, high case its cap.'))
        art = CovenantArtifact(schema_version=SCHEMA_VERSION, generated_at=NOW, contract=contract, quarters=quarters, refusals=refusals)
        arts[cik] = art

        # disclosed ratios: what the company itself reported, rounded, sometimes with a definition gap
        lev_q = [q for q in quarters if q.covenant_id == "lev" and q.ratio_low is not None and q.ratio_high is not None]
        if lev_q and rng.random() < 0.55:
            pos = [100]
            for q in rng.sample(lev_q, min(len(lev_q), rng.randint(1, 3))):
                mid = (q.ratio_low + q.ratio_high) / 2
                rep = round(mid + (rng.gauss(0, 0.35) if rng.random() < 0.12 else rng.gauss(0, 0.012)), 2)
                text = f"As of {q.period_end:%B %-d, %Y}, our Consolidated Leverage Ratio was {rep:.2f} to 1.00, compared to a maximum of {q.threshold:.2f} to 1.00."
                disclosed.append(DisclosedRatio(cik=cik, period_end=q.period_end, covenant_kind="max_leverage", reported_value=rep, reported_threshold=q.threshold,
                                                span=span(cik, f"{cik}-10q-{q.period_end:%y%m}", None, text, pos)))
        role = "disclosed"
        if path == "stress":
            first_bad = next((q.period_end for q in lev_q if q.status in ("warning", "breach", "indeterminate")), None)
            sudden = rng.random() < 0.2  # an event the numbers did not foreshadow (e.g. a missed reporting covenant)
            if (first_bad or sudden) and rng.random() < 0.85:
                when = (date.fromordinal(lev_q[len(lev_q) // 3].period_end.toordinal() + 20) if sudden or not first_bad
                        else date.fromordinal(first_bad.toordinal() + rng.randint(60, 230)))
                kind = rng.choices(["waiver", "amendment_loosening", "default", "acceleration"], [0.45, 0.35, 0.15, 0.05])[0]
                text = {"waiver": "the Lenders agreed to waive any Event of Default arising from the Borrower's failure to comply with Section 7.11(a)",
                        "amendment_loosening": "the Amendment increases the maximum Consolidated Leverage Ratio permitted under Section 7.11(a)",
                        "default": "an Event of Default has occurred and is continuing under Section 7.11(a) of the Credit Agreement",
                        "acceleration": "the Administrative Agent declared all outstanding Loans immediately due and payable"}[kind]
                events.append(CovenantEvent(cik=cik, date=when, kind=kind, span=span(cik, f"{cik}-8k-{when:%y%m%d}", "Item 1.01", text, [50])))
                role = "event"
        universe.append(UniverseEntry(cik=cik, role=role))

    # peers: healthy companies in the same SIC as each event company
    healthy = [u.cik for u in universe if u.role == "disclosed" and paths[int(u.cik[2:]) - 1] != "stress"]
    for u in [u for u in universe if u.role == "event"]:
        sic = arts[u.cik].contract.company.sic
        same = [c for c in healthy if arts[c].contract.company.sic == sic][:2] or rng.sample(healthy, 2)
        for c in same:
            universe.append(UniverseEntry(cik=c, role="peer", peer_of=u.cik))
    return arts, disclosed, events, universe


def write(arts, disclosed, events, universe):
    for sub in ("artifacts", "groundtruth", "eval"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    for f in (OUT / "artifacts").glob("*.json"):
        f.unlink()
    for cik, a in arts.items():
        (OUT / "artifacts" / f"{cik}.json").write_text(a.model_dump_json() + "\n")
    dump = lambda xs: json.dumps([x.model_dump(mode="json") for x in xs], indent=1)
    (OUT / "groundtruth" / "disclosed.json").write_text(dump(disclosed))
    (OUT / "groundtruth" / "events.json").write_text(dump(events))
    (OUT / "universe.json").write_text(dump(universe))
    report, detail = build_report(arts, disclosed, events, universe, labels_dir=OUT / "no-labels", contracts_dir=OUT / "no-contracts")
    report.per_company = [dict(p, note="DEMO") for p in report.per_company]
    (OUT / "eval" / "report.json").write_text(report.model_dump_json(indent=2) + "\n")
    (OUT / "eval" / "detail.json").write_text(json.dumps(detail, indent=1, default=str) + "\n")
    return report


def main():
    arts, disclosed, events, universe = build()
    report = write(arts, disclosed, events, universe)
    q = sum(len(a.quarters) for a in arts.values())
    print(f"wrote {len(arts)} demo companies, {q} covenant-quarters, {len(disclosed)} disclosed ratios, {len(events)} events, {len(universe)} universe rows -> {OUT}")
    print("ratio_accuracy", {k: report.ratio_accuracy[k] for k in ("n", "pct_inside_range", "median_abs_error")})
    print("early_warning", {k: report.early_warning[k] for k in ("events_scored", "hit_rate", "median_lead_quarters", "peers_scored", "peer_false_alarm_rate")})


if __name__ == "__main__":
    main()
