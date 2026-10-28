# Covenant Watch: rules for every agent in this repo

Two people build this in parallel. Folder ownership is strict so branches never conflict.

| Path | Owner |
|---|---|
| `shared/`, `fixtures/`, `scripts/make_fixtures.py` | Laksh, FROZEN (contract) |
| `contracts/`, `notes/laksh.md` | Laksh |
| `engine/`, `validation/`, `api/`, `web/`, `notes/dat.md` | Dat |
| `docs/`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `pyproject.toml` | Laksh (ask before changing) |

1. Only create or edit files inside your own paths. Never touch the other person's, not even a one-line fix.
2. Need something from the other side? Write it in your own `notes/*.md` file and stop.
3. `shared/schema.py` is the contract. Import it; never edit it unless you are Laksh, and then bump `SCHEMA_VERSION` and log it in `notes/laksh.md`.
4. Each `data/` folder has one writer: `data/contracts/` Laksh; `data/artifacts/`, `data/groundtruth/`, `data/eval/`, `data/universe.json` Dat. `data/cache/` is shared and append-only.
5. Never invent a number or contract text. An honest refusal beats a silent wrong value. Every `Span.text` must be an exact substring of its source document.
6. Dependencies: if you need a new Python package, add it under your own `requirements` note in `notes/*.md` instead of editing `pyproject.toml`; web dependencies live in `web/package.json` (Dat).
7. Run `uv run pytest` before every commit.

Full plan: `docs/PLAN.md`.
