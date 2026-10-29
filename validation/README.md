# validation/: ground truth, peers, universe

| Module | Output | What |
|---|---|---|
| `disclosed.py` | `data/groundtruth/disclosed.json` | Ground truth A: covenant ratios companies reported in 10-K/10-Q (`DisclosedRatio`) |
| `events.py` | `data/groundtruth/events.json` | Ground truth B: 8-K covenant waivers, loosening amendments, defaults, accelerations (`CovenantEvent`) |
| `peers.py` | `data/groundtruth/peers.json` | 2-3 matched peers per event company (`UniverseEntry`, role `peer`) |
| `universe.py` | `data/universe.json` + committed copy `validation/universe_snapshot.json` | Run set for contracts/ and engine/ |
| `labels/` | hand gold | see `labels/README.md` |
| `score.py` | `data/eval/report.json` | Dat's scorer |

Rebuild everything (EDGAR responses are cached in `data/cache/`):

```bash
uv run python -m validation.disclosed      # ~20-30 min cold, minutes warm
uv run python -m validation.events
uv run python -m validation.peers
uv run python -m validation.universe
uv run pytest -q validation
```

## How span offsets are defined (reproduce exactly)

Every `Span` written here points into the **plain text of one filing document**:

```python
from validation.text import doc_text
text = doc_text(span.url)          # = html_to_text(shared.edgar.get(span.url))
assert text[span.char_start:span.char_end] == span.text
```

- `span.url` is the filing document itself (`https://www.sec.gov/Archives/edgar/data/{cik}/{accession-no-dashes}/{file}`),
  `span.accession` its accession number. For events, `span.section` holds the 8-K item numbers when EDGAR lists them.
- `html_to_text` (in `validation/text.py`, stdlib only, deterministic): drops `<script>`, `<style>`, `<head>`,
  `<ix:header>`; block tags (`p`, `div`, `br`, `tr`, `li`, `table`, `h1`-`h6`, ...) become newlines and table
  cells a space; HTML entities decoded; curly quotes become straight quotes, en/em dashes become `-`;
  runs of spaces/tabs/nbsp collapse to one space; every run of newlines (with surrounding spaces) collapses to a
  single `\n`; the result is stripped. Offsets are Python `str` indices (code points) into that string.
- Spans are whole sentences (sentence splitter in `text.py`, which does not split on abbreviations such as
  `Inc.` or on decimals).

## Hard rules enforced

- A row is written only if `text[char_start:char_end] == span.text` at write time.
- `reported_value` and `reported_threshold` must each equal a literal number inside `span.text`.
- Threshold-only, conditional ("if the ratio was greater than"), bound ("was less than 4.25"), pro forma,
  hypothetical, forward-looking, "respectively"-lists and non-GAAP metric sentences are rejected.
  Sentences must sit in debt-covenant context (covenant / credit agreement / lenders / indenture ... within ±800 chars).
- Events: risk-factor and hypothetical wording, definitions ("the term ... means"), negated waivers
  ("without waiving"), sentence fragments, and stale recaps (every date mentioned >180 days before the filing)
  are rejected. Dedupe: per company, same kind within 60 days of a kept event is dropped (earliest kept).

## Extraction paths

- **Deterministic (default when no key):** regex parser `disclosed.parse_sentence`, classifier
  `events.classify_sentence`. Unit tests in `tests/test_groundtruth.py` cover positive and negative sentences.
- **Claude (when `ANTHROPIC_API_KEY` is set):** `llm.py`, model `claude-sonnet-5-5`, structured JSON output
  (`output_config.format`), effort low. It only reads candidate sentences that search + regex found; the span is
  still cut by our code and every number it returns must appear verbatim in the sentence, else the row is
  dropped. Note: this model rejects non-default `temperature` (400), so determinism comes from the
  structured schema plus an on-disk response cache (`data/cache/llm_validation/`). Force deterministic with `--no-llm`.

## Known limitations

- `period_end` comes from the date in the sentence (nearest date before the value, parenthetical prior-period
  dates ignored); with no date in the sentence it falls back to the filing's period of report.
- Ratios reported only in tables are not captured (sentence-based).
- Event date is the 8-K filing date, not the agreement's effective date.
- Peers: same 4-digit SIC, total assets 0.5x-2x (widened to 1/3x-3x only when fewer than 2 match) at the last calendar-quarter frame before the first event,
  and zero 8-K body / EX-99 full-text hits for covenant-trouble phrases within ±2 years. Peers are only built for the event companies selected into the universe (`peers.select_event_companies`: XBRL assets >= $250M just before the first event, largest 40). Absence of hits is not proof of no
  covenant stress.
