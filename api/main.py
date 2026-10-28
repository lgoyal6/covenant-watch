"""Read-only API over data/. Falls back to fixtures/ when data/ has no artifacts.

Run: uv run uvicorn api.main:app --port 8000
Every response that comes from fixtures carries "source": "fixture" so the UI can label it.
"""

import json
from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from shared import edgar
from shared.paths import ARTIFACTS, EVAL, FIXTURES, GROUNDTRUTH
from shared.schema import CovenantArtifact

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
        return out, "data"
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


def span_context(span: dict) -> dict:
    """The span plus surrounding text if the source document is already in the EDGAR cache (never fetches)."""
    out = dict(span)
    path = edgar._cache_path(span["url"])
    if not path.exists():
        out["context"] = None
        return out
    doc = path.read_bytes().decode("utf-8", errors="replace")
    s, e = span["char_start"], span["char_end"]
    if doc[s:e] != span["text"]:
        out["context"] = None
        out["context_note"] = "span offsets do not match the cached document"
        return out
    lo, hi = max(0, s - CONTEXT_CHARS), min(len(doc), e + CONTEXT_CHARS)
    out["context"] = {"before": doc[lo:s], "match": doc[s:e], "after": doc[e:hi]}
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
    if rep is not None:
        return {"source": "data", "report": rep}
    return {"source": "fixture", "report": _read(FIXTURES / "eval_example.json")}
