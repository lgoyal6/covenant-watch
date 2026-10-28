"""Score pipeline outputs against ground truth -> data/eval/report.json.

  uv run python -m validation.score

Inputs: data/contracts/ (extraction), data/artifacts/ (engine), data/groundtruth/
disclosed.json + events.json, data/universe.json, validation/labels/ (hand gold).

Metrics
  extraction     precision/recall per field vs hand-labeled agreements (status "labeled" only)
  ratio_accuracy company-reported covenant ratios vs our computed range for the same quarter:
                 inside-range rate, distance from the range (0 when inside), midpoint error
                 where the range is bounded, and threshold agreement (an extraction check)
  early_warning  for each disclosed covenant event: did any quarter ending in the 4 quarters
                 before it show warning/breach (worst case)? lead time in quarters; the same
                 test on matched peers that had no event gives the false alarm rate
  refusals       counts by reason across artifacts
"""

import json
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from shared.paths import ARTIFACTS, CONTRACTS, EVAL, GROUNDTRUTH, UNIVERSE
from shared.schema import SCHEMA_VERSION, ContractExtraction, CovenantArtifact, CovenantEvent, DisclosedRatio, EvalReport, UniverseEntry

LABELS = Path(__file__).resolve().parent / "labels"
ALIGN_DAYS = 10
WINDOW_DAYS = 380  # "the four quarters before the event"
FLAGGED = {"warning", "breach"}
THRESHOLD_TOL = 0.005


def norm_cik(c: str) -> str:
    return f"{int(c):010d}"


def _load(model, path: Path) -> list:
    if not path.exists():
        return []
    return [model.model_validate(x) for x in json.loads(path.read_text())]


def load_artifacts(d: Path = ARTIFACTS) -> dict[str, CovenantArtifact]:
    out = {}
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        a = CovenantArtifact.model_validate_json(f.read_text())
        out[norm_cik(a.contract.company.cik)] = a
    return out


# ---------------- ratio accuracy ----------------


def match_quarter(art: CovenantArtifact, kind: str, period_end: date):
    """The computed quarter for the covenant of this kind closest to period_end (within ALIGN_DAYS)."""
    ids = {c.id for c in art.contract.covenants if c.kind == kind}
    best = None
    for q in art.quarters:
        if q.covenant_id in ids and abs((q.period_end - period_end).days) <= ALIGN_DAYS:
            if best is None or abs((q.period_end - period_end).days) < abs((best.period_end - period_end).days):
                best = q
    return best


def ratio_accuracy(disclosed: list[DisclosedRatio], arts: dict[str, CovenantArtifact]) -> tuple[dict, list[dict]]:
    rows = []
    for d in disclosed:
        a = arts.get(norm_cik(d.cik))
        if a is None:
            continue
        q = match_quarter(a, d.covenant_kind, d.period_end)
        row = {"cik": norm_cik(d.cik), "period_end": str(d.period_end), "kind": d.covenant_kind, "reported": d.reported_value,
               "reported_threshold": d.reported_threshold, "status": q.status if q else "no_quarter"}
        if q is None or q.status == "refused":
            rows.append(row)
            continue
        lo = q.ratio_low if q.ratio_low is not None else float("-inf")
        hi = q.ratio_high if q.ratio_high is not None else float("inf")
        row.update(computed_low=q.ratio_low, computed_high=q.ratio_high, threshold=q.threshold)
        row["inside"] = lo - 1e-9 <= d.reported_value <= hi + 1e-9
        row["distance"] = 0.0 if row["inside"] else min(abs(d.reported_value - lo), abs(d.reported_value - hi))
        if q.ratio_low is not None and q.ratio_high is not None:
            row["midpoint_abs_error"] = abs((q.ratio_low + q.ratio_high) / 2 - d.reported_value)
            row["range_width"] = q.ratio_high - q.ratio_low
        if d.reported_threshold is not None and q.threshold is not None:
            row["threshold_match"] = abs(d.reported_threshold - q.threshold) <= THRESHOLD_TOL * max(1.0, abs(q.threshold))
        rows.append(row)
    scored = [r for r in rows if "inside" in r]
    bounded = [r for r in scored if "midpoint_abs_error" in r]
    thr = [r for r in scored if "threshold_match" in r]
    summary = {
        "disclosed_total": len(disclosed),
        "disclosed_with_artifact": len(rows),
        "n": len(scored),
        "refused_or_unmatched": len(rows) - len(scored),
        "pct_inside_range": round(sum(r["inside"] for r in scored) / len(scored), 4) if scored else None,
        "median_distance_from_range": round(statistics.median(r["distance"] for r in scored), 4) if scored else None,
        "n_bounded": len(bounded),
        "median_abs_error": round(statistics.median(r["midpoint_abs_error"] for r in bounded), 4) if bounded else None,
        "pct_within_0_05": round(sum(r["midpoint_abs_error"] <= 0.05 for r in bounded) / len(bounded), 4) if bounded else None,
        "pct_within_0_25": round(sum(r["midpoint_abs_error"] <= 0.25 for r in bounded) / len(bounded), 4) if bounded else None,
        "threshold_n": len(thr),
        "threshold_agreement": round(sum(r["threshold_match"] for r in thr) / len(thr), 4) if thr else None,
    }
    return summary, rows


# ---------------- early warning ----------------


def quarters_before(art: CovenantArtifact, when: date) -> list:
    return [q for q in art.quarters if when - timedelta(days=WINDOW_DAYS) <= q.period_end < when]


def flagged(art: CovenantArtifact, when: date) -> tuple[bool, int | None, bool]:
    """(any warning/breach in the window, lead in quarters from the earliest flag, any computable quarter)."""
    qs = quarters_before(art, when)
    computable = any(q.status != "refused" for q in qs)
    hits = sorted({q.period_end for q in qs if q.status in FLAGGED})
    if not hits:
        return False, None, computable
    # lead = quarterly reports from the first flag through the last one before the event
    lead = len({q.period_end for q in qs if q.period_end >= hits[0]})
    return True, lead, computable


def first_events(events: list[CovenantEvent]) -> dict[str, CovenantEvent]:
    out = {}
    for e in sorted(events, key=lambda e: e.date):
        out.setdefault(norm_cik(e.cik), e)
    return out


def early_warning(events: list[CovenantEvent], universe: list[UniverseEntry], arts: dict[str, CovenantArtifact]) -> tuple[dict, list[dict]]:
    firsts = first_events(events)
    rows, leads = [], []
    hit = scored = 0
    for cik, e in firsts.items():
        a = arts.get(cik)
        if a is None:
            continue
        f, lead, computable = flagged(a, e.date)
        rows.append({"cik": cik, "role": "event", "event_date": str(e.date), "event_kind": e.kind, "flagged": f, "lead_quarters": lead, "computable": computable})
        if computable:
            scored += 1
            hit += f
            if lead is not None:
                leads.append(lead)
    peer_alarm = peer_scored = 0
    for u in universe:
        if u.role != "peer" or not u.peer_of:
            continue
        a, e = arts.get(norm_cik(u.cik)), firsts.get(norm_cik(u.peer_of))
        if a is None or e is None:
            continue
        f, lead, computable = flagged(a, e.date)
        rows.append({"cik": norm_cik(u.cik), "role": "peer", "peer_of": norm_cik(u.peer_of), "event_date": str(e.date), "flagged": f, "computable": computable})
        if computable:
            peer_scored += 1
            peer_alarm += f
    summary = {
        "events": len(firsts),
        "events_with_artifact": sum(r["role"] == "event" for r in rows),
        "events_scored": scored,
        "hit_rate": round(hit / scored, 4) if scored else None,
        "median_lead_quarters": statistics.median(leads) if leads else None,
        "peers_scored": peer_scored,
        "peer_false_alarm_rate": round(peer_alarm / peer_scored, 4) if peer_scored else None,
        "flag_definition": "worst-case status warning or breach in a quarter ending within 380 days before the first disclosed event",
    }
    return summary, rows


# ---------------- extraction vs gold ----------------


def _prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    return {"precision": round(p, 4) if p is not None else None, "recall": round(r, 4) if r is not None else None, "tp": tp, "fp": fp, "fn": fn}


def _label_norm(s: str) -> str:
    return " ".join(s.lower().replace('"', "").split())


def extraction(labels_dir: Path = LABELS, contracts_dir: Path = CONTRACTS) -> dict:
    counts = defaultdict(lambda: [0, 0, 0])
    n = 0
    for f in sorted(labels_dir.glob("*.json")) if labels_dir.exists() else []:
        gold = json.loads(f.read_text())
        if gold.get("status") != "labeled":
            continue
        cf = contracts_dir / f"{norm_cik(gold['cik'])}.json"
        if not cf.exists():
            continue
        n += 1
        pred = ContractExtraction.model_validate_json(cf.read_text())
        terms = {t.id: t for t in pred.terms}
        g_kinds = Counter(c["kind"] for c in gold["covenants"])
        p_kinds = Counter(c.kind for c in pred.covenants)
        _add(counts["covenant_kind"], g_kinds, p_kinds)
        g_thr = Counter((c["kind"], round(t["value"], 4)) for c in gold["covenants"] for t in c["thresholds"])
        p_thr = Counter((c.kind, round(t.value, 4)) for c in pred.covenants for t in c.thresholds)
        _add(counts["threshold_value"], g_thr, p_thr)
        g_sched = Counter((c["kind"], round(t["value"], 4), t["effective_from"]) for c in gold["covenants"] for t in c["thresholds"])
        p_sched = Counter((c.kind, round(t.value, 4), str(t.effective_from)) for c in pred.covenants for t in c.thresholds)
        _add(counts["threshold_schedule"], g_sched, p_sched)
        g_tp = Counter(c["test_period"] for c in gold["covenants"] if c.get("test_period"))
        p_tp = Counter(c.test_period for c in pred.covenants)
        _add(counts["test_period"], g_tp, p_tp)
        # term structure: (parent label, child label) edges
        g_edges = Counter((_label_norm(t["label"]), _label_norm(ch)) for t in gold.get("terms", []) for ch in t.get("children_labels", []))
        p_edges = Counter((_label_norm(t.label), _label_norm(terms[ch].label)) for t in pred.terms for ch in t.children if ch in terms)
        _add(counts["term_structure"], g_edges, p_edges)
    out = {k: _prf(*v) for k, v in counts.items()}
    out["agreements_labeled"] = n
    return out


def _add(acc: list, gold: Counter, pred: Counter) -> None:
    tp = sum((gold & pred).values())
    acc[0] += tp
    acc[1] += sum(pred.values()) - tp
    acc[2] += sum(gold.values()) - tp


# ---------------- report ----------------


def refusal_counts(arts: dict[str, CovenantArtifact]) -> dict:
    c = Counter(r.reason for a in arts.values() for r in a.refusals)
    c["refused_quarters"] = sum(q.status == "refused" for a in arts.values() for q in a.quarters)
    return dict(c)


def per_company(arts, ratio_rows, ew_rows) -> list[dict]:
    out = []
    for cik, a in sorted(arts.items()):
        st = Counter(q.status for q in a.quarters)
        rr = [r for r in ratio_rows if r["cik"] == cik and "inside" in r]
        ew = next((r for r in ew_rows if r["cik"] == cik), None)
        out.append({
            "cik": cik, "name": a.contract.company.name, "ticker": a.contract.company.ticker,
            "covenants": len(a.contract.covenants), "quarters": len(a.quarters), "status_counts": dict(st),
            "refusals": len(a.refusals), "disclosed_compared": len(rr),
            "disclosed_inside_range": sum(r["inside"] for r in rr),
            "role": ew["role"] if ew else None, "flagged_before_event": ew["flagged"] if ew else None,
            "lead_quarters": ew.get("lead_quarters") if ew else None,
        })
    return out


def build_report(arts, disclosed, events, universe, labels_dir=LABELS, contracts_dir=CONTRACTS) -> tuple[EvalReport, dict]:
    ra, ratio_rows = ratio_accuracy(disclosed, arts)
    ew, ew_rows = early_warning(events, universe, arts)
    report = EvalReport(
        schema_version=SCHEMA_VERSION, generated_at=datetime.now(timezone.utc),
        extraction=extraction(labels_dir, contracts_dir), ratio_accuracy=ra, early_warning=ew,
        refusals=refusal_counts(arts), per_company=per_company(arts, ratio_rows, ew_rows),
    )
    return report, {"ratio_rows": ratio_rows, "early_warning_rows": ew_rows}


def main():
    arts = load_artifacts()
    disclosed = _load(DisclosedRatio, GROUNDTRUTH / "disclosed.json")
    events = _load(CovenantEvent, GROUNDTRUTH / "events.json")
    universe = _load(UniverseEntry, UNIVERSE)
    report, detail = build_report(arts, disclosed, events, universe)
    EVAL.mkdir(parents=True, exist_ok=True)
    (EVAL / "report.json").write_text(report.model_dump_json(indent=2) + "\n")
    (EVAL / "detail.json").write_text(json.dumps(detail, indent=2, default=str) + "\n")
    print(f"artifacts={len(arts)} disclosed={len(disclosed)} events={len(events)} universe={len(universe)}")
    print("ratio_accuracy", json.dumps(report.ratio_accuracy))
    print("early_warning", json.dumps(report.early_warning))
    print("extraction", json.dumps(report.extraction))
    print("refusals", json.dumps(report.refusals))


if __name__ == "__main__":
    main()
