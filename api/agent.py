"""Two agents over the API's own read-only views: the analyst (answers questions) and the risk briefing
(investigates the most at-risk covenants on its own and writes a ranked memo).

Claude decides which data to pull (search, a company's covenants, a covenant's quarter-by-quarter
timeline, the provenance of one quarter, the portfolio view), then answers from what the tools
returned. Every step is returned to the UI so the answer can be checked against its sources.
Nothing here writes data; the tools are the same functions the web app reads.
"""

import json
import os
from datetime import date

MODEL = "claude-opus-5-5"
MAX_ROUNDS = 8

SYSTEM = """You are the analyst agent inside Covenant Watch, a tool that rebuilds public companies' loan covenants from their credit agreements and SEC filings and tracks headroom quarter by quarter.

Answer questions using only what your tools return. Rules:
- Pull data before answering anything about a company, covenant, quarter or the portfolio. Never estimate or recall numbers.
- Quote ratios, thresholds and headroom exactly as the tools give them, with the quarter they belong to.
- A ratio shown as a range (low to high) is uncertain because some contract addback has no public source; say so when it matters. "Indeterminate" means the range straddles the limit.
- Headroom is the distance to the limit: positive is room left, negative is past it. For max covenants (leverage) the ratio must stay below the limit; for min covenants (coverage) above.
- When something was refused, say what and why, from the refusal detail.
- If the tools do not have the answer, say that plainly.
- Be concise: lead with the answer, then the supporting numbers. Not investment advice."""

TOOLS = [
    {
        "name": "search_companies",
        "description": "Find companies by name, ticker or CIK. Returns each company's covenants with latest status, ratio and headroom. Use an empty query to list all.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False},
    },
    {
        "name": "portfolio_overview",
        "description": "The whole portfolio: status counts now, status mix by quarter, the covenants closest to breach (worst-case headroom as a share of the limit), recent disclosed events, refusals by reason, and evaluation headlines.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "covenant_timeline",
        "description": "Quarter-by-quarter history of one covenant: ratio range, threshold in force, headroom range, status, missing inputs; plus the threshold schedule, agreements and amendments, disclosed events and company-reported ratios.",
        "input_schema": {"type": "object", "properties": {"cik": {"type": "string"}, "covenant_id": {"type": "string"}},
                         "required": ["cik", "covenant_id"], "additionalProperties": False},
    },
    {
        "name": "quarter_provenance",
        "description": "Where one covenant-quarter's number comes from: the covenant and threshold clause text, every input's XBRL concept, value, period and filing, mapping confidence, and the definition terms.",
        "input_schema": {"type": "object", "properties": {"cik": {"type": "string"}, "covenant_id": {"type": "string"}, "period_end": {"type": "string", "description": "YYYY-MM-DD"}},
                         "required": ["cik", "covenant_id", "period_end"], "additionalProperties": False},
    },
    {
        "name": "company_refusals",
        "description": "Everything that could not be computed for a company and why (redacted terms, unmapped definitions, missing filings).",
        "input_schema": {"type": "object", "properties": {"cik": {"type": "string"}}, "required": ["cik"], "additionalProperties": False},
    },
]


STRESS_TOOLS = [
    {
        "name": "covenant_breakeven",
        "description": "For each covenant of a company, on its latest computed quarter: the percent change in earnings (EBITDA-like term; negative = fall) and in the other term (debt for leverage, interest or fixed charges for coverage) that would bring the worst case exactly to the limit. Computed by the engine.",
        "input_schema": {"type": "object", "properties": {"cik": {"type": "string"}}, "required": ["cik"], "additionalProperties": False},
    },
    {
        "name": "stress_test",
        "description": "Recompute one covenant's latest quarter under a scenario: earnings_change_pct scales the earnings term (e.g. -25), other_change_pct scales debt (leverage) or interest/fixed charges (coverage). Returns the new ratio range, headroom and status next to the baseline.",
        "input_schema": {"type": "object", "properties": {
            "cik": {"type": "string"}, "covenant_id": {"type": "string"},
            "earnings_change_pct": {"type": "number"}, "other_change_pct": {"type": "number"}},
            "required": ["cik", "covenant_id", "earnings_change_pct", "other_change_pct"], "additionalProperties": False},
    },
]


def _q(q: dict) -> dict:
    keep = ("covenant_id", "period_end", "ratio_low", "ratio_high", "threshold", "headroom_low", "headroom_high", "status", "missing")
    return {k: q.get(k) for k in keep}


def run_tool(name: str, args: dict):
    """Execute one tool against the API's own read functions. Returns (result, is_error)."""
    from fastapi import HTTPException

    import api.main as m

    try:
        if name == "search_companies":
            r = m.companies(args.get("query") or None)
            return {"companies": [{k: c[k] for k in ("cik", "name", "ticker", "covenants")} for c in r["companies"]][:25]}, False
        if name == "portfolio_overview":
            o = m.overview()
            o.pop("status_by_quarter", None)
            for c in o.get("closest", []):
                c.pop("history", None)
            return o, False
        if name == "covenant_timeline":
            t = m.timeline(args["cik"], args["covenant_id"])
            return {
                "company": t["company"]["name"],
                "covenant": {k: t["covenant"][k] for k in ("id", "kind", "direction", "test_period")},
                "quarters": [_q(q) for q in t["quarters"]],
                "thresholds": [{k: x[k] for k in ("effective_from", "effective_to", "value")} | {"clause": x["source"]["text"]} for x in t["thresholds"]],
                "agreements": [{k: a[k] for k in ("accession", "filed", "kind", "redacted")} for a in t["agreements"]],
                "events": [{"date": e["date"], "kind": e["kind"], "text": e["span"]["text"]} for e in t["events"]],
                "company_reported": [{"period_end": d["period_end"], "value": d["reported_value"], "threshold": d.get("reported_threshold")} for d in t["disclosed"]],
            }, False
        if name == "quarter_provenance":
            p = m.provenance(args["cik"], args["covenant_id"], date.fromisoformat(args["period_end"]))
            return {
                "quarter": _q(p["quarter"]),
                "covenant_clause": p["covenant_clause"]["text"],
                "threshold_clause": (p["threshold_clause"] or {}).get("text"),
                "inputs": [{k: i.get(k) for k in ("label", "xbrl_concept", "value", "period_start", "period_end", "fact_accession", "mapping_confidence", "validated", "validation_note")} for i in p["inputs"]],
                "terms": [{k: t.get(k) for k in ("id", "label", "op", "children", "cap")} for t in p["terms"]],
                "refusals": p["refusals"],
            }, False
        if name in ("covenant_breakeven", "stress_test"):
            from engine.stress import breakeven, latest_quarter, stress

            art, _ = m._artifact(args["cik"])
            covs = {c.id: c for c in art.contract.covenants}
            if name == "covenant_breakeven":
                return {"company": art.contract.company.name, "covenants": [breakeven(art, c, q) for c in covs.values() if (q := latest_quarter(art, c.id))]}, False
            cov = covs.get(args["covenant_id"])
            q = latest_quarter(art, args["covenant_id"]) if cov else None
            if q is None:
                return {"error": f"no computed quarter for covenant {args['covenant_id']}"}, True
            return stress(art, cov, q, float(args.get("earnings_change_pct", 0)), float(args.get("other_change_pct", 0))), False
        if name == "company_refusals":
            a = m.company(args["cik"])["artifact"]
            return {"company": a["contract"]["company"]["name"], "refusals": a["refusals"]}, False
        return {"error": f"unknown tool {name}"}, True
    except HTTPException as e:
        return {"error": e.detail}, True
    except (KeyError, ValueError) as e:
        return {"error": f"bad input: {e}"}, True


def api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:  # the project key Laksh stored in macOS Keychain, when on that machine
        from contracts.credentials import load_api_key

        return load_api_key()
    except Exception:
        return None


def _create(client, **kw):
    """Messages call with the server-side refusal fallback; plain call if the SDK or account rejects it."""
    import anthropic

    try:
        return client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
    except (TypeError, anthropic.BadRequestError):
        return client.messages.create(**kw)


BRIEF_SYSTEM = """You are the risk briefing agent inside Covenant Watch, a tool that rebuilds public companies' loan covenants from their credit agreements and SEC filings and tracks headroom quarter by quarter.

Your job: produce a risk briefing for a credit analyst, on your own, using only your tools.
1. Call portfolio_overview to find the covenants closest to breach.
2. For each of the most at-risk covenants (up to the number requested), call covenant_timeline to see the trend, the threshold schedule, amendments and any disclosed waiver or default.
3. For each, call quarter_provenance on its latest computed quarter to see which inputs drive the ratio and whether any are unsourced.
4. Write the briefing.

Briefing format (markdown, no tables):
## Risk briefing
One sentence on the portfolio: how many covenants need attention now.
Then one section per company, most urgent first:
### <Company>: <covenant kind>
- **Now:** ratio and limit in the latest quarter, worst-case headroom, status.
- **Trend:** how headroom moved over the last four quarters, with the quarters named.
- **Drivers:** the inputs behind it (e.g. EBITDA falling, debt rising), and any unsourced addback that makes it a range.
- **Signals:** amendments, limit step-ups or step-downs, disclosed waivers or defaults, with dates.
- **Watch next:** the next test date and the specific thing that would trip it.

Use only numbers your tools returned, exactly as given. If a lookup fails, say so in that section. Not investment advice."""


def run_agent(system: str, user: str, history: list[dict] | None = None, client=None, max_rounds: int = MAX_ROUNDS,
              effort: str = "medium", max_tokens: int = 8000, tools: list[dict] | None = None) -> dict:
    """The shared tool loop: Claude calls the read-only tools until it answers. Returns the answer and every step."""
    if client is None:
        import anthropic

        key = api_key()
        if not key:
            raise RuntimeError("No Anthropic API key: set ANTHROPIC_API_KEY for the API process.")
        client = anthropic.Anthropic(api_key=key)
    messages = [{"role": h["role"], "content": h["content"]} for h in (history or [])[-8:] if h.get("content")]
    messages.append({"role": "user", "content": user})
    steps = []
    response = None
    for _ in range(max_rounds):
        response = _create(client, model=MODEL, max_tokens=max_tokens, system=system, tools=tools or TOOLS, messages=messages,
                           output_config={"effort": effort})
        if response.stop_reason != "tool_use":
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            out, err = run_tool(block.name, dict(block.input))
            steps.append({"tool": block.name, "input": dict(block.input), "ok": not err})
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out, default=str)[:60000], "is_error": err})
        messages.append({"role": "user", "content": results})
    if response is None:
        raise RuntimeError("agent made no request")
    if response.stop_reason == "refusal":
        answer = "I can't help with that request."
    else:
        answer = "\n".join(b.text for b in response.content if b.type == "text").strip()
        if response.stop_reason == "tool_use":
            answer = (answer + "\n\n" if answer else "") + "(Stopped after the maximum number of lookups; ask a narrower question.)"
    return {"answer": answer or "No answer.", "steps": steps, "model": getattr(response, "model", MODEL)}


def ask(question: str, cik: str | None = None, history: list[dict] | None = None, client=None) -> dict:
    """Analyst agent: answer one question. history: prior turns as [{"role": "user"|"assistant", "content": str}]."""
    context = f"\n\n(The user is looking at company CIK {cik}.)" if cik else ""
    return run_agent(SYSTEM, question + context, history, client)


def brief(top: int = 5, client=None) -> dict:
    """Risk briefing agent: investigates the most at-risk covenants on its own and writes a ranked memo."""
    top = max(1, min(int(top), 8))
    return run_agent(BRIEF_SYSTEM, f"Write the risk briefing for the {top} most at-risk covenants.", client=client,
                     max_rounds=4 + 2 * top, effort="high", max_tokens=16000)


STRESS_SYSTEM = """You are the stress-test agent inside Covenant Watch. For one company you find out how much bad news its loan covenants can absorb, using the engine's own math through your tools.

1. Call covenant_breakeven for the company: how far earnings can fall, or debt / interest can rise, before each covenant's worst case breaches.
2. Call covenant_timeline for the covenant with the least cushion to see the trend and the limit schedule (step-downs ahead matter).
3. Run stress_test for the scenarios requested (or, if none: mild = earnings -10%; downturn = earnings -25%; severe = earnings -40% with debt or interest +20%) on every covenant.
4. Write the result.

Format (markdown, no tables):
## Stress test: <Company>
One sentence: which covenant trips first and at roughly what earnings decline.
### Cushion today
- one bullet per covenant: limit, worst-case ratio now, earnings decline to breach, debt/interest rise to breach.
### Scenarios
- one bullet per scenario: what each covenant's ratio range and status become.
### What to watch
- the limit step-downs ahead and the inputs that would move the answer (unsourced addbacks, rising debt).

Use only numbers from your tools, rounded to one decimal for percentages and two for ratios. A positive "earnings change to breach" means the worst case is already past the limit. Not investment advice."""


def stress_agent(cik: str, scenario: str | None = None, client=None) -> dict:
    """Stress-test agent: breakevens and scenarios for one company, computed by the engine, written up by Claude."""
    tools = [t for t in TOOLS if t["name"] in ("covenant_timeline", "company_refusals")] + STRESS_TOOLS
    ask_ = f"Stress-test the covenants of company CIK {cik}." + (f" Scenario requested: {scenario}" if scenario else " Use the standard scenarios.")
    return run_agent(STRESS_SYSTEM, ask_, client=client, max_rounds=10, effort="high", max_tokens=12000, tools=tools)
