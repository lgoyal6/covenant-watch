"""Compute covenant headroom artifacts from contract extractions + XBRL.

  uv run python -m engine.run --cik 0000012345
  uv run python -m engine.run --universe        # every company with a contract file
  uv run python -m engine.run --contract path.json --out path.json   # explicit files (dev/tests)
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from engine import refusals
from engine.compiler import CompileError, LeafValue, compile_terms
from engine.compute import compute_quarter, threshold_for
from engine.mapping import Mapping, map_leaf
from engine.provenance import input_for
from engine.xbrl import CompanyFacts, align
from shared.paths import ARTIFACTS, CONTRACTS, UNIVERSE
from shared.schema import SCHEMA_VERSION, ContractExtraction, CovenantArtifact, QuarterResult

FILING_GRACE_DAYS = 75  # a quarter is "missing" once its 10-Q/10-K deadline has clearly passed


def flow_kind(test_period: str) -> str:
    return "quarter" if test_period == "quarter" else "ttm"


def merged_series(cf: CompanyFacts, m: Mapping) -> dict:
    """Primary concept's series, with gaps filled from validated alternates (filers change tags over time)."""
    if not m.concept:
        return {}
    out = dict(cf.series(m.concept, m.kind))
    for alt in m.alternates:
        for d, v in cf.series(alt, m.kind).items():
            if d not in out and align(list(out), d, 7) is None:
                out[d] = v
    return out


def build(contract: ContractExtraction, cf: CompanyFacts | None, today: date | None = None, client=None) -> CovenantArtifact:
    today = today or date.today()
    cik = contract.company.cik
    out_refusals = list(contract.refusals)
    quarters: list[QuarterResult] = []
    if cf is None or not cf.facts:
        out_refusals.append(refusals.no_usd(cik) if cf is not None else refusals.no_xbrl(cik, "companyfacts unavailable"))
        return CovenantArtifact(schema_version=SCHEMA_VERSION, generated_at=datetime.now(timezone.utc), contract=contract, quarters=[], refusals=out_refusals)

    contract_refused = {r.ref for r in contract.refusals if r.scope == "covenant"}
    q_ends = cf.quarter_ends()
    terms = {t.id: t for t in contract.terms}
    mappings: dict[tuple[str, str], Mapping] = {}

    for cov in contract.covenants:
        if cov.id in contract_refused:
            continue
        roots = [t for t in (cov.numerator_term, cov.denominator_term) if t]
        try:
            g = compile_terms(contract.terms, roots)
        except CompileError as e:
            out_refusals.append(refusals.bad_definition(cov.id, str(e)))
            continue
        if not cov.thresholds:
            out_refusals.append(refusals.unsupported(cov.id, "No threshold extracted for this covenant."))
            continue
        fk = flow_kind(cov.test_period)
        leaves = sorted({*g.leaves(cov.numerator_term), *(g.leaves(cov.denominator_term) if cov.denominator_term else [])})
        maps: dict[str, Mapping] = {}
        for leaf in leaves:
            key = (leaf, fk)
            if key not in mappings:
                t = terms[leaf]
                mappings[key] = map_leaf(cf, leaf, t.label, t.span.text, fk, client)
            maps[leaf] = mappings[key]
            m = maps[leaf]
            if not m.validated:
                out_refusals.append(refusals.unmapped(cov.id, leaf, terms[leaf].label, m.note, leaf in g.required))
        series = {leaf: merged_series(cf, m) for leaf, m in maps.items()}

        start = min(t.effective_from for t in cov.thresholds)
        cov_ends = [e for e in q_ends if e >= start - timedelta(days=7) and threshold_for(cov, e) is not None]
        for qe in cov_ends:
            vals, inputs = {}, []
            for leaf, m in maps.items():
                s = series[leaf]
                key = qe if qe in s else align(list(s), qe)
                v = s.get(key) if key else None
                inputs.append(input_for(m, v, qe))
                vals[leaf] = LeafValue(None if v is None else v.value * m.sign, partial=m.partial and v is not None)
            if all(v.value is None for leaf, v in vals.items() if maps[leaf].concept):
                continue  # nothing reported for this quarter end at all
            quarters.append(compute_quarter(cov, g, qe, vals, inputs))

        # the next quarter whose filing deadline has passed but which has no data: refused, not silently dropped
        if cov_ends:
            nxt = cov_ends[-1] + timedelta(days=91)
            if (today - nxt).days > FILING_GRACE_DAYS and threshold_for(cov, nxt) is not None:
                quarters.append(QuarterResult(covenant_id=cov.id, period_end=nxt, threshold=threshold_for(cov, nxt), status="refused"))
                ref = str(nxt)
                if not any(r.scope == "quarter" and r.ref == ref for r in out_refusals):
                    out_refusals.append(refusals.unfiled(ref, f"No XBRL facts for the quarter ending about {nxt}; filing deadline has passed."))
        elif cov.thresholds:
            out_refusals.append(refusals.unsupported(cov.id, "No reported quarter falls inside the covenant's threshold schedule."))

    quarters.sort(key=lambda q: (q.period_end, q.covenant_id))
    return CovenantArtifact(schema_version=SCHEMA_VERSION, generated_at=datetime.now(timezone.utc), contract=contract, quarters=quarters, refusals=out_refusals)


def run_file(contract_path: Path, out_path: Path, client=None) -> CovenantArtifact:
    contract = ContractExtraction.model_validate_json(contract_path.read_text())
    try:
        cf = CompanyFacts.load(contract.company.cik)
    except Exception as e:  # 404 for non-XBRL filers, network errors
        print(f"  companyfacts unavailable for {contract.company.cik}: {e}", file=sys.stderr)
        cf = None
    art = build(contract, cf, client=client)
    art = CovenantArtifact.model_validate_json(art.model_dump_json())  # validate the serialized form before writing
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(art.model_dump_json(indent=2) + "\n")
    tmp.replace(out_path)
    return art


def summarize(art: CovenantArtifact) -> str:
    from collections import Counter

    c = Counter(q.status for q in art.quarters)
    return f"{art.contract.company.cik} {art.contract.company.name}: {len(art.contract.covenants)} covenants, {len(art.quarters)} quarters {dict(c)}, {len(art.refusals)} refusals"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--cik")
    p.add_argument("--universe", action="store_true")
    p.add_argument("--contract", type=Path)
    p.add_argument("--out", type=Path)
    a = p.parse_args(argv)
    jobs: list[tuple[Path, Path]] = []
    if a.contract:
        jobs.append((a.contract, a.out or ARTIFACTS / a.contract.name))
    elif a.cik:
        cik = f"{int(a.cik):010d}"
        jobs.append((CONTRACTS / f"{cik}.json", ARTIFACTS / f"{cik}.json"))
    elif a.universe:
        files = sorted(CONTRACTS.glob("*.json")) if CONTRACTS.exists() else []
        if UNIVERSE.exists():
            wanted = {f"{int(e['cik']):010d}" for e in json.loads(UNIVERSE.read_text())}
            files = [f for f in files if f.stem in wanted] or files
        jobs = [(f, ARTIFACTS / f.name) for f in files]
    else:
        p.error("give --cik, --universe or --contract")
    if not jobs:
        print("no contract files found in", CONTRACTS)
    ok = 0
    for src, dst in jobs:
        if not src.exists():
            print(f"missing contract file {src}", file=sys.stderr)
            continue
        try:
            print(summarize(run_file(src, dst)))
            ok += 1
        except Exception as e:
            print(f"FAILED {src.name}: {type(e).__name__}: {e}", file=sys.stderr)
    print(f"{ok}/{len(jobs)} artifacts written")


if __name__ == "__main__":
    main()
