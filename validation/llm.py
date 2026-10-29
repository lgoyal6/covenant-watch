"""Optional Claude extraction/classification path (runs only when ANTHROPIC_API_KEY is set).

The LLM only *reads* a candidate sentence that full-text search + regex already
found. Its output is never trusted on its own: callers verify every number
appears verbatim in the span text, and the span is cut from the document by us,
not by the model. Anything failing verification is discarded.

Notes on API usage (claude-sonnet-5-5): non-default `temperature` returns a 400
on this model, so determinism comes from structured JSON output
(`output_config.format`) and low effort instead of temperature=0. Results are
memoized on disk by sentence hash so reruns are reproducible.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import date

from shared.paths import DATA

MODEL = "claude-sonnet-5-5"
CACHE_DIR = DATA / "cache" / "llm_validation"

KINDS = ["max_leverage", "min_interest_coverage", "min_fixed_charge_coverage", "max_senior_leverage", "min_liquidity", "other"]
EVENT_KINDS = ["waiver", "amendment_loosening", "default", "acceleration", "none"]

_client = None


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic()
    return _client


def _call(system: str, user: str, schema: dict) -> dict | None:
    key = hashlib.sha256(json.dumps([MODEL, system, user, schema], sort_keys=True).encode()).hexdigest()
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    import anthropic

    params = dict(
        model=MODEL,
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
    )
    client = _get_client()
    try:
        try:
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
        except anthropic.BadRequestError:
            resp = client.messages.create(**params)
    except Exception as exc:  # network, auth, rate limits after SDK retries
        print(f"  ! llm error: {exc}", file=sys.stderr)
        return None
    if resp.stop_reason != "end_turn":
        return None
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        return None
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


# ---------------- disclosed ratios ----------------

DISCLOSED_SYSTEM = """You read one sentence from a company's SEC 10-K or 10-Q and extract covenant ratios the company ACTUALLY ACHIEVED for a specific period.
Rules:
- Only actual measured values ("our Consolidated Leverage Ratio was 3.2 to 1.00"). NOT thresholds/requirements ("shall not exceed 4.50 to 1.00"), NOT bounds ("was less than 4.25:1.00"), NOT conditional/pricing-grid text ("if the ratio was greater than 2.00"), NOT pro forma or hypothetical values.
- value_text and threshold_text must be copied character-for-character from the sentence (e.g. "3.2 to 1.00", "2.45x").
- threshold is the covenant limit stated in the same sentence for that same ratio, else null.
- period_end: ISO date the value is measured at, only if stated in the sentence; else null.
- kind: max_leverage (total/net leverage, debt to EBITDA), max_senior_leverage (senior/secured/first lien leverage), min_interest_coverage, min_fixed_charge_coverage, min_liquidity, other.
- If none qualify or anything is ambiguous, return an empty list."""

DISCLOSED_SCHEMA = {
    "type": "object",
    "properties": {
        "ratios": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ratio_name": {"type": "string"},
                    "kind": {"type": "string", "enum": KINDS},
                    "value": {"type": "number"},
                    "value_text": {"type": "string"},
                    "threshold": {"type": ["number", "null"]},
                    "threshold_text": {"type": ["string", "null"]},
                    "period_end": {"type": ["string", "null"]},
                },
                "required": ["ratio_name", "kind", "value", "value_text", "threshold", "threshold_text", "period_end"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ratios"],
    "additionalProperties": False,
}


def _first_num(s: str) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", s or "")
    return float(m.group(0)) if m else None


def extract_disclosed(sentence: str, fallback_period: date | None):
    from validation.disclosed import Parsed  # local import avoids a cycle

    out = _call(DISCLOSED_SYSTEM, f"Filing period end: {fallback_period}\nSentence:\n{sentence}", DISCLOSED_SCHEMA)
    if not out:
        return None
    parsed = []
    for r in out.get("ratios", []):
        vt = r.get("value_text") or ""
        if not vt or vt not in sentence or _first_num(vt) != r.get("value"):
            continue
        tt = r.get("threshold_text")
        th = r.get("threshold")
        if th is not None and (not tt or tt not in sentence or _first_num(tt) != th):
            th = tt = None
        pe = None
        if r.get("period_end"):
            try:
                pe = date.fromisoformat(r["period_end"])
            except ValueError:
                pe = None
        parsed.append(Parsed(r["kind"], r.get("ratio_name", ""), float(r["value"]), vt, th, tt, pe or fallback_period))
    return parsed


# ---------------- events ----------------

EVENT_SYSTEM = """You read one sentence from an SEC filing and decide whether it discloses a covenant event that HAPPENED to the filing company under its own credit facility:
- waiver: lenders waived a covenant breach/default or a financial covenant test
- amendment_loosening: an amendment that relaxes financial covenants (higher max leverage, lower min coverage, covenant holiday/suspension, covenant relief period)
- default: the company failed/expects to fail a covenant, or an event of default occurred
- acceleration: lenders accelerated or declared the debt immediately due
- none: generic risk-factor language, boilerplate definitions, hypotheticals, or about another party.
Answer kind and a short reason."""

EVENT_SCHEMA = {
    "type": "object",
    "properties": {"kind": {"type": "string", "enum": EVENT_KINDS}, "reason": {"type": "string"}},
    "required": ["kind", "reason"],
    "additionalProperties": False,
}


def classify_event(sentence: str) -> str | None:
    out = _call(EVENT_SYSTEM, sentence, EVENT_SCHEMA)
    if not out:
        return None
    k = out.get("kind")
    return None if k in (None, "none") else k
