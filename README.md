# Covenant Watch

Reads a public company's loan agreement from SEC EDGAR, rebuilds each financial covenant exactly as the contract defines it from the company's own filings, and shows quarter by quarter how close the company is to breaking it. Every number traces to its clause and filing line; uncertainty is shown as a range; when it can't compute something, it refuses and says why.

Solix AI Hackathon 2026, AI in Finance track.

## Setup

```bash
uv sync
export SEC_USER_AGENT="Covenant Watch your-email@ucsd.edu"
export ANTHROPIC_API_KEY=...
uv run pytest
```

## Layout

- `shared/` the data contract and EDGAR client (frozen)
- `fixtures/` synthetic example data in contract shape (frozen)
- `contracts/` reads loan agreements into covenants and definitions (Laksh)
- `engine/` financial data and covenant headroom (Dat)
- `validation/` ground truth and scoring (Dat)
- `api/`, `web/` the product (Dat)

Ownership rules: `AGENTS.md`. Full plan: `docs/PLAN.md`.
