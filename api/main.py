"""Read-only API over data/. Falls back to fixtures/ when data/ has no artifacts.

Run: uv run uvicorn api.main:app --port 8000
Every response that comes from fixtures carries "source": "fixture" so the UI can label it.
"""

import json
import os
from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from shared import edgar
from shared.paths import ARTIFACTS, EVAL, FIXTURES, GROUNDTRUTH, UNIVERSE
from shared.schema import CovenantArtifact

# CW_DATASET=demo serves data/demo/ (validation/demo_data.py, fictional companies) instead of the real pipeline output.
DATASET = os.environ.get("CW_DATASET", "data")
if DATASET == "demo":
    from shared.paths import DATA

    ARTIFACTS, EVAL, GROUNDTRUTH, UNIVERSE = (DATA / "demo" / "artifacts", DATA / "demo" / "eval",
                                              DATA / "demo" / "groundtruth", DATA / "demo" / "universe.json")

app = FastAPI(title="Covenant Watch API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

CONTEXT_CHARS = 600


def _read(path):
    return json.loads(path.read_text()) if path.exists() else None


def load_artifacts() -> tuple[dict[str, CovenantArtifact], str]:
    """All artifacts keyed by CIK, plus "data" or "fixture"."""
    files = sorted(ARTIFACTS.glob("*.json")) if ARTIFACTS.exists() else []
    if files:
        out = {}
        for f in files:
            a = CovenantArtifact.model_validate_json(f.read_text())
            out[a.contract.company.cik] = a
        return out, ("demo" if DATASET == "demo" else "data")
    a = CovenantArtifact.model_validate_json((FIXTURES / "artifact_example.json").read_text())
    return {a.contract.company.cik: a}, "fixture"


def load_groundtruth(source: str) -> dict:
    if source == "fixture":
        gt = _read(FIXTURES / "groundtruth_example.json")
        return {"disclosed": gt["disclosed"], "events": gt["events"]}
    return {"disclosed": _read(GROUNDTRUTH / "disclosed.json") or [], "events": _read(GROUNDTRUTH / "events.json") or []}


def _artifact(cik: str) -> tuple[CovenantArtifact, str]:
    arts, source = load_artifacts()
    key = cik if cik in arts else next((k for k in arts if k.lstrip("0") == cik.lstrip("0")), None)
    if key is None:
        raise HTTPException(404, f"no artifact for CIK {cik}")
    return arts[key], source


def _same_cik(a: str, b: str) -> bool:
    return a.lstrip("0") == b.lstrip("0")


def filing_url(cik: str, accession: str | None) -> str | None:
    if not accession:
        return None
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{accession}-index.htm"


def _document(url: str) -> bytes | None:
    """The filing document: from the EDGAR cache, or fetched (and cached) unless CW_OFFLINE is set."""
    path = edgar._cache_path(url)
    if path.exists():
        return path.read_bytes()
    if os.environ.get("CW_OFFLINE") or "fixture" in url:
        return None
    try:
        return edgar.get(url)
    except Exception:
        return None


def span_context(span: dict) -> dict:
    """The span plus surrounding text. Offsets may index the raw document or its plain-text
    conversion (validation.text.html_to_text); if neither matches, the text is located by search."""
    out = dict(span, context=None, context_basis=None)
    raw = _document(span["url"])
    if raw is None:
        return out
    s, e, text = span["char_start"], span["char_end"], span["text"]
    for basis, doc in (("raw", raw.decode("utf-8", errors="replace")), ("text", None)):
        if doc is None:
            from validation.text import html_to_text

            doc = html_to_text(raw)
        if doc[s:e] == text:
            break
        found = doc.find(text)
        if found >= 0:
            s, e, basis = found, found + len(text), basis + "+search"
            break
    else:
        out["context_note"] = "clause text not found in the source document"
        return out
    lo, hi = max(0, s - CONTEXT_CHARS), min(len(doc), e + CONTEXT_CHARS)
    out["context"] = {"before": doc[lo:s], "match": doc[s:e], "after": doc[e:hi]}
    out["context_basis"] = basis
    return out


def covenant_summary(a: CovenantArtifact, cov_id: str) -> dict:
    qs = [q for q in a.quarters if q.covenant_id == cov_id]
    computed = [q for q in qs if q.status != "refused"]
    latest = computed[-1] if computed else (qs[-1] if qs else None)
    return {
        "latest_period_end": latest.period_end if latest else None,
        "status": latest.status if latest else "refused",
        "ratio_low": latest.ratio_low if latest else None,
        "ratio_high": latest.ratio_high if latest else None,
        "threshold": latest.threshold if latest else None,
        "headroom_low": latest.headroom_low if latest else None,
        "headroom_high": latest.headroom_high if latest else None,
        "quarters": len(qs),
    }


@app.get("/companies")
def companies(q: str | None = Query(None, description="search name, ticker or CIK")):
    arts, source = load_artifacts()
    out = []
    for cik, a in arts.items():
        c = a.contract.company
        if q and q.lower() not in f"{c.name} {c.ticker or ''} {c.cik}".lower():
            continue
        out.append({
            **c.model_dump(),
            "source": source,
            "covenants": [{"id": cv.id, "kind": cv.kind, "direction": cv.direction, **covenant_summary(a, cv.id)} for cv in a.contract.covenants],
            "refusals": len(a.refusals),
        })
    return {"source": source, "companies": sorted(out, key=lambda x: x["name"])}


@app.get("/companies/{cik}")
def company(cik: str):
    a, source = _artifact(cik)
    return {"source": source, "artifact": a.model_dump(mode="json")}


@app.get("/companies/{cik}/covenants/{cov_id}/timeline")
def timeline(cik: str, cov_id: str):
    a, source = _artifact(cik)
    cov = next((c for c in a.contract.covenants if c.id == cov_id), None)
    if cov is None:
        raise HTTPException(404, f"no covenant {cov_id}")
    gt = load_groundtruth(source)
    co_cik = a.contract.company.cik
    quarters = [q.model_dump(mode="json", exclude={"inputs"}) | {"n_inputs": len(q.inputs)} for q in a.quarters if q.covenant_id == cov_id]
    return {
        "source": source,
        "company": a.contract.company.model_dump(),
        "covenant": cov.model_dump(mode="json"),
        "quarters": quarters,
        "thresholds": [t.model_dump(mode="json") for t in cov.thresholds],
        "agreements": [ag.model_dump(mode="json") | {"filing_url": filing_url(co_cik, ag.accession)} for ag in a.contract.agreements],
        "events": [e for e in gt["events"] if _same_cik(e["cik"], co_cik)],
        "disclosed": [d for d in gt["disclosed"] if _same_cik(d["cik"], co_cik) and d["covenant_kind"] == cov.kind],
        "refusals": [r.model_dump() for r in a.refusals if r.scope != "covenant" or r.ref == cov_id],
    }


@app.get("/provenance/{cik}/{cov_id}/{period_end}")
def provenance(cik: str, cov_id: str, period_end: date):
    a, source = _artifact(cik)
    cov = next((c for c in a.contract.covenants if c.id == cov_id), None)
    q = next((q for q in a.quarters if q.covenant_id == cov_id and q.period_end == period_end), None)
    if cov is None or q is None:
        raise HTTPException(404, "no such covenant quarter")
    terms = {t.id: t for t in a.contract.terms}
    used: list[str] = []

    def walk(tid):
        if tid in terms and tid not in used:
            used.append(tid)
            t = terms[tid]
            for ch in t.children:
                walk(ch)
            if t.cap and t.cap.get("kind") == "pct_of":
                walk(t.cap["of"])

    walk(cov.numerator_term)
    if cov.denominator_term:
        walk(cov.denominator_term)
    thr = next((t for t in cov.thresholds if t.effective_from <= period_end and (t.effective_to is None or period_end <= t.effective_to)), None)
    co_cik = a.contract.company.cik
    return {
        "source": source,
        "company": a.contract.company.model_dump(),
        "covenant": cov.model_dump(mode="json", exclude={"span", "thresholds"}),
        "covenant_clause": span_context(cov.span.model_dump()),
        "threshold_clause": span_context(thr.source.model_dump()) if thr else None,
        "quarter": q.model_dump(mode="json", exclude={"inputs"}),
        "inputs": [i.model_dump(mode="json") | {"filing_url": filing_url(co_cik, i.fact_accession), "label": terms[i.term_node].label if i.term_node in terms else i.term_node} for i in q.inputs],
        "terms": [terms[t].model_dump(mode="json", exclude={"span"}) | {"clause": span_context(terms[t].span.model_dump())} for t in used],
        "refusals": [r.model_dump() for r in a.refusals if r.ref in (str(period_end), cov_id)],
    }


@app.get("/eval")
def eval_report():
    rep = _read(EVAL / "report.json")
    _, source = load_artifacts()
    if rep is not None and source != "fixture":  # never pair a real eval with fixture companies
        return {"source": source, "report": rep}
    return {"source": "fixture", "report": _read(FIXTURES / "eval_example.json")}


def _cal_quarter(d: date) -> str:
    """A fiscal period end (e.g. 2024-09-28) labelled by the nearest calendar quarter end."""
    ends = [date(y, m, dd) for y in (d.year - 1, d.year, d.year + 1) for m, dd in ((3, 31), (6, 30), (9, 30), (12, 31))]
    e = min(ends, key=lambda x: abs((x - d).days))
    return f"{e.year}-Q{(e.month - 1) // 3 + 1}"


def _rel(headroom: float | None, threshold: float | None) -> float | None:
    """Worst-case headroom as a fraction of the threshold (positive = room left)."""
    if headroom is None or not threshold:
        return None
    return round(headroom / abs(threshold), 4)


@app.get("/overview")
def overview():
    """Portfolio view across every artifact: status mix over time, closest to breach, events, refusals, eval headlines."""
    arts, source = load_artifacts()
    rep = eval_report()
    return _overview(arts, source, load_groundtruth(source)) | {
        "eval_source": rep["source"],
        "ratio_accuracy": rep["report"].get("ratio_accuracy", {}),
        "early_warning": rep["report"].get("early_warning", {}),
    }


@app.get("/companies/{cik}/overview")
def company_overview(cik: str):
    """The same view for one company. Accuracy and early warning are scored for this company alone
    with validation.score against its own disclosed ratios and events (and its matched peers)."""
    from validation.score import early_warning, ratio_accuracy
    from shared.schema import CovenantEvent, DisclosedRatio, UniverseEntry

    a, source = _artifact(cik)
    arts, _ = load_artifacts()
    gt = load_groundtruth(source)
    co = a.contract.company.cik
    disclosed = [DisclosedRatio.model_validate(d) for d in gt["disclosed"] if _same_cik(d["cik"], co)]
    events = [CovenantEvent.model_validate(e) for e in gt["events"] if _same_cik(e["cik"], co)]
    if source == "fixture":
        universe = [UniverseEntry.model_validate(u) for u in (_read(FIXTURES / "groundtruth_example.json") or {}).get("universe", [])]
    else:
        universe = [UniverseEntry.model_validate(u) for u in (_read(UNIVERSE) or [])]
    universe = [u for u in universe if u.peer_of and _same_cik(u.peer_of, co)]
    norm = {f"{int(k):010d}": v for k, v in arts.items()}
    ra, _ = ratio_accuracy(disclosed, norm)
    ew, _ = early_warning(events, universe, norm)
    return _overview({co: a}, source, gt) | {"eval_source": source, "ratio_accuracy": ra, "early_warning": ew}


def _overview(arts: dict, source: str, gt: dict) -> dict:
    from collections import Counter, defaultdict

    statuses = ("ok", "warning", "breach", "indeterminate", "refused")
    by_q: dict[str, Counter] = defaultdict(Counter)
    latest = Counter()
    covenants = []
    refusals = Counter()
    for cik, a in arts.items():
        for r in a.refusals:
            refusals[r.reason] += 1
        for q in a.quarters:
            by_q[_cal_quarter(q.period_end)][q.status] += 1
        for cv in a.contract.covenants:
            qs = [q for q in a.quarters if q.covenant_id == cv.id]
            s = covenant_summary(a, cv.id)
            latest[s["status"]] += 1
            covenants.append({
                "cik": a.contract.company.cik, "name": a.contract.company.name, "ticker": a.contract.company.ticker,
                "covenant_id": cv.id, "kind": cv.kind, "direction": cv.direction, **s,
                "headroom_pct": _rel(s["headroom_low"], s["threshold"]),
                "history": [{"period_end": q.period_end, "status": q.status, "headroom_pct": _rel(q.headroom_low, q.threshold)} for q in qs],
            })
    names = {k.lstrip("0"): a.contract.company.name for k, a in arts.items()}
    events = sorted(
        ({**e, "name": names[e["cik"].lstrip("0")]} for e in gt["events"] if e["cik"].lstrip("0") in names),
        key=lambda e: str(e["date"]), reverse=True,
    )
    computed = [c for c in covenants if c["status"] != "refused"]
    closest = sorted((c for c in computed if c["headroom_pct"] is not None), key=lambda c: c["headroom_pct"])
    return {
        "source": source,
        "companies": len(arts),
        "covenants": len(covenants),
        "quarters": sum(len(a.quarters) for a in arts.values()),
        "status_latest": {s: latest.get(s, 0) for s in statuses},
        "status_by_quarter": [{"quarter": k, **{s: by_q[k].get(s, 0) for s in statuses}} for k in sorted(by_q)],
        "closest": closest[:8],
        "events": events[:8],
        "events_total": len(events),
        "refusals": dict(refusals.most_common()),
    }
