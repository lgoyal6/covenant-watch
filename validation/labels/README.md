# Hand-labeled gold set (agreement extraction)

These files are the gold standard that `validation/score.py` uses to measure how well
`contracts/` extracts covenants and definitions. They must be written **by hand by a
person reading the credit agreement**, independently of any pipeline output. Never
copy values from `data/contracts/` or from an LLM. A missing label is fine; a guessed
one is not.

## Files

- One file per agreement: `validation/labels/{cik}_{agreement_accession}.json`
  (`cik` 10-digit zero-padded, accession with dashes, e.g. `0000123456_0000123456-24-000012.json`).
- Start from `_template.json` (copy and rename). The scorer only counts files whose
  `"status"` is `"labeled"`; `"template"` and `"in_progress"` files are ignored.

## Format

```json
{"cik": "0000123456", "agreement_accession": "...", "agreement_url": "...",
 "labeled_by": "Dat", "labeled_at": "2026-10-28", "status": "labeled",
 "covenants": [{"kind": "max_leverage", "direction": "max", "test_period": "ttm",
   "thresholds": [{"value": 4.5, "effective_from": "2024-03-31", "effective_to": "2024-12-30"},
                  {"value": 4.0, "effective_from": "2024-12-31", "effective_to": null}],
   "numerator_label": "Consolidated Total Debt", "denominator_label": "Consolidated EBITDA"}],
 "terms": [{"label": "Consolidated EBITDA", "op": "sum",
            "children_labels": ["Consolidated Net Income", "Consolidated Interest Expense", "..."], "cap": null}]}
```

Field rules:

| Field | Values |
|---|---|
| `kind` | `max_leverage`, `max_senior_leverage`, `min_interest_coverage`, `min_fixed_charge_coverage`, `min_liquidity`, `other` (same as `shared/schema.py` `Covenant.kind`) |
| `direction` | `max` or `min` |
| `test_period` | `ttm` (four fiscal quarters), `quarter`, `point_in_time` (balance-sheet / liquidity tests) |
| `thresholds` | every level in the step-down schedule, in order. `effective_from` is the first test date the level applies to; `effective_to` the last one (null if open-ended). Ratios as plain numbers (`4.50:1.00` -> `4.5`); liquidity in USD (`$25,000,000` -> `25000000`). |
| `numerator_label` / `denominator_label` | the defined term exactly as capitalized in the agreement; `denominator_label` null for liquidity tests |
| `terms[].op` | `sum`, `subtract`, `ratio`, `leaf`, `cap`, `floor` (as in `TermNode.op`) |
| `terms[].children_labels` | defined terms or line items the definition adds/subtracts, in contract order, base item first (e.g. Net Income first under EBITDA) |
| `terms[].cap` | `{"kind": "pct_of", "of": "<label>", "pct": 0.10}` or `{"kind": "abs", "usd": 25000000}` or null |

## Labeling guide

1. Open the agreement exhibit (EX-10) on EDGAR. Use the **latest amended** version effective
   for the period you label; record later amendments' threshold changes as separate
   `thresholds` entries with dates.
2. Find the financial covenant section (usually "Financial Covenants", Section 6.x/7.x).
   One `covenants` entry per tested ratio or liquidity floor. Skip incurrence-only tests
   (ratios used only as conditions for debt/RP baskets) and pricing grids.
3. Copy step-downs exactly. "for the fiscal quarter ending June 30, 2024 and thereafter"
   means `effective_from` = 2024-06-30. If a level only applies after an optional event (e.g. an
   "Acquisition Holiday" step-up), list the base schedule only.
4. Terms: label the definition tree for each covenant's numerator and denominator, down
   to items that are not further defined. Record caps on addbacks ("not to exceed 10% of
   Consolidated EBITDA" -> `pct_of`).
5. If the agreement is redacted or ambiguous, don't label that field; leave the covenant
   out rather than guessing, and keep `status` as `in_progress` if the file is incomplete.
6. When done, set `status` to `labeled`, fill `labeled_by` and `labeled_at` (YYYY-MM-DD).

Target per `docs/PLAN.md`: 20 agreements, picked from `validation/universe_snapshot.json`.
