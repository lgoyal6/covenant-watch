# Dat notes

Requests for Laksh. Only Dat edits this file.

## Universe for Laksh

- `data/universe.json` (list of `UniverseEntry`, CIKs 10-digit zero-padded) is built by `uv run python -m validation.universe`. Because `data/` is gitignored, every build also writes an identical committed copy: **`validation/universe_snapshot.json`**. Read that one.
- Status: PARTIAL (second cut, ~15:30 PT): 66 entries, 42 role `event` (8-K covenant waiver/relief/default/acceleration disclosures), 24 role `disclosed` (10-K/10-Q reports an actual covenant ratio). Peers not yet added. Extraction is still running; this section will be updated when final.
- Order in the file is the suggested processing order (events, then peers, then disclosed).

## Engine expectations for data/contracts (from Dat, 2026-10-28)

What the engine (`engine/`) does with your `ContractExtraction`, so extraction choices land well:

1. **Leaf labels drive XBRL mapping.** Each `op="leaf"` TermNode's `label` (plus its `span.text`) is matched to a us-gaap concept by a pattern table and, when `ANTHROPIC_API_KEY` is set, by claude-sonnet-5-5 choosing from the concepts the company actually reports. Plain line-item labels map best: "Consolidated Net Income", "interest expense", "provision for taxes", "depreciation and amortization", "Consolidated Total Debt".
2. **Required vs bounded leaves.** The first child of every `sum`/`subtract` chain (e.g. Net Income under EBITDA) and any covenant term that is itself a leaf (e.g. Total Debt) are *required*: if unmapped, the quarter is refused. Every other leaf is an *addback*: if unmapped it is bounded (low case 0, high case its cap; uncapped = unbounded). So please keep the base item first in `children`.
3. **Caps**: `op="cap"` with `cap={"kind":"pct_of","of":<node>,"pct":0.10}` or `{"kind":"abs","usd":25000000}`; the `of` node must be computable without the cap (no cycles; the compiler rejects cycles with an `ambiguous_definition` refusal). `op="floor"` with no `cap` floors at 0.
4. **Thresholds** are looked up by quarter end in `[effective_from, effective_to]`. Quarters outside every threshold window are not computed, so the earliest `effective_from` should be the agreement's effective date.
5. **Contract-level refusals**: a `Refusal(scope="covenant", ref=<covenant id>)` in your file makes the engine skip that covenant (e.g. redacted thresholds).
6. `test_period`: `ttm` (default for flows), `quarter`, or `point_in_time` (balances such as liquidity).

## Data handoff (open question for Laksh)

`data/` is gitignored, so `data/contracts/*.json` written on your machine never reaches mine. Options: (a) once `contracts/` is merged, I run `uv run python -m contracts.run --universe` here; (b) you send the files (zip/drive) and I drop them in `data/contracts/`. (a) is simplest if it needs only `ANTHROPIC_API_KEY`. Tell me in notes/laksh.md which you prefer.

## Requirements

No new Python dependencies (engine/validation/api use pydantic, httpx, anthropic, fastapi). FastAPI's TestClient uses httpx, already present.
