# Dat notes

Requests for Laksh. Only Dat edits this file.

## Universe for Laksh

- `data/universe.json` exists (list of `UniverseEntry`, CIKs 10-digit zero-padded, built by `uv run python -m validation.universe`).
- Status: PARTIAL (first cut, 15:15 PT): 20 entries, all role `disclosed` (companies whose 10-K/10-Q reports an actual covenant ratio). Event companies and their peers are still being extracted and will be added; this section will be updated when final.
- Order in the file is the suggested processing order (events, then peers, then disclosed).
