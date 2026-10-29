# Covenant Watch

Reads a public company's loan agreement from SEC EDGAR, rebuilds each financial covenant exactly as the contract defines it from the company's own filings, and shows quarter by quarter how close the company is to breaking it. Every number traces to its clause and filing line; uncertainty is shown as a range; when it can't compute something, it refuses and says why.

Solix AI Hackathon 2026, AI in Finance track.

## Why

A covenant breach is usually the first step toward default, and the terms that decide it are buried in credit agreements filed as SEC exhibits. Those agreements define their own math: "Consolidated EBITDA" adds back restructuring, stock compensation and more, often capped. Computing leverage from plain GAAP numbers gets it wrong: in our checks it came out above the company's own reported covenant ratio every time. Covenant Watch rebuilds the contract's definitions and computes them from the company's XBRL financials.

## Setup

```bash
uv sync
export SEC_USER_AGENT="Covenant Watch your-email@ucsd.edu"
export ANTHROPIC_API_KEY=...        # contract extraction and LLM concept mapping
uv run pytest                       # whole suite
cd web && npm install && cd ..
```

## Run the pipeline

```bash
uv run python -m validation.disclosed       # ground truth A: company-reported covenant ratios
uv run python -m validation.events          # ground truth B: waivers, defaults, loosening amendments
uv run python -m validation.universe        # data/universe.json from both (also committed as validation/universe_snapshot.json)
uv run python -m contracts.run --universe   # data/contracts/{cik}.json  (see notes/laksh.md for budgets)
uv run python -m engine.run --universe      # data/artifacts/{cik}.json
uv run python -m validation.score           # data/eval/report.json
```

## Run the app

```bash
uv run uvicorn api.main:app --port 8000             # API over data/ (falls back to fixtures/)
cd web && npm run build && npm start                # http://localhost:3000
```

Pages: `/` landing, `/dashboard` portfolio overview, `/companies` list and search, `/company/{cik}` covenants with the headroom timeline and the clause-and-filing drawer, `/eval` accuracy and early-warning results.

## Data sources the API can serve

| Source | How | Label in the UI |
|---|---|---|
| Real pipeline output | `data/artifacts/` has files | none |
| Example company | `data/artifacts/` empty, serves `fixtures/` | "Example data" |
| Synthetic test set | `uv run python -m validation.synthetic`, then start the API with `CW_DATASET=synthetic` | "Synthetic data" |

The synthetic set is 100 fictional companies (names end in "(Synthetic)", CIKs 99xxxxxxxx, URLs on example.invalid) for exercising the product at volume. Their numbers run through the real engine and scorer, but they are not real companies and their scores are not results.

## Layout

- `shared/` the data contract and EDGAR client (frozen)
- `fixtures/` synthetic example data in contract shape (frozen)
- `contracts/` reads loan agreements into covenants and definitions (Laksh)
- `engine/` XBRL series, concept mapping, definition compiler, interval headroom (Dat)
- `validation/` ground truth, gold labels, scoring, synthetic data (Dat)
- `api/` FastAPI, read-only over `data/` (Dat)
- `web/` Next.js app (Dat)

Ownership rules: `AGENTS.md`. Full plan: `docs/PLAN.md`. Notes between the two halves: `notes/dat.md`, `notes/laksh.md`.
