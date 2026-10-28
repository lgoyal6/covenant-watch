# Covenant Watch: Team Build Plan (Dat 70 / Laksh 30)

Two people, zero shared files after kickoff. Each person owns whole folders, and the only things that cross between them are data files that follow one frozen contract.

---

## 1. What we're building

Covenant Watch reads a public company's loan agreement from SEC EDGAR, rebuilds every financial covenant exactly as the contract defines it from the company's own filings, and shows quarter by quarter how close the company is to breaking it. Every number traces to its clause and filing line. Uncertainty is shown as a range. When it can't compute something, it refuses and says why.

It's proven two ways:
- **Accuracy:** our computed ratio vs the ratio the company itself reported in its 10-K or 10-Q.
- **Early warning:** headroom falling before companies actually disclosed a covenant waiver, amendment or default, compared with matched peers that never did.

---

## 2. Who owns what

**Laksh (30%): contract understanding.** Turns loan agreements into structured, verified covenants and definitions.

**Dat (70%): numbers, proof and product.** Financial data, the headroom engine, ground truth, scoring, API and web app.

| Area | Owner | Writes to |
|---|---|---|
| `shared/` (contract, EDGAR client, paths) | **Laksh**, at kickoff, then frozen | `shared/` |
| `fixtures/` (sample data in contract shape) | **Laksh**, at kickoff, then frozen | `fixtures/` |
| `contracts/` (agreement reading) | **Laksh** | `data/contracts/` |
| `engine/` (financials + headroom) | **Dat** | `data/artifacts/` |
| `validation/` (ground truth + scoring) | **Dat** | `data/groundtruth/`, `data/universe.json`, `data/eval/` |
| `api/` (backend server) | **Dat** | nothing in `data/` |
| `web/` (frontend) | **Dat** | nothing in `data/` |
| `notes/laksh.md` | **Laksh** | requests and changes for Dat |
| `notes/dat.md` | **Dat** | requests and changes for Laksh |

**Rules**
1. Never edit a file in the other person's folders. Not even a one-line fix. Write the request in your own `notes/` file instead.
2. `shared/` and `fixtures/` are frozen after kickoff. If the contract must change, Laksh changes it, bumps `SCHEMA_VERSION`, and logs it in `notes/laksh.md`.
3. Each data folder has exactly one writer. The EDGAR cache in `data/cache/` is keyed by URL and append-only, so both can write it safely.
4. Each person works on their own branch. Because the paths never overlap, merges cannot conflict.

**Data flow**
```
Dat:   validation/universe.py  ->  data/universe.json         (which companies to run)
Laksh: contracts/              ->  data/contracts/{cik}.json  (reads universe.json)
Dat:   engine/                 ->  data/artifacts/{cik}.json  (reads contracts + XBRL)
Dat:   validation/score.py     ->  data/eval/report.json      (reads artifacts + ground truth)
Dat:   api/ + web/             ->  reads everything above
```

---

## 3. Repo layout

```
covenant-watch/
  shared/                 LAKSH (frozen after kickoff)
    schema.py             pydantic models: THE CONTRACT
    edgar.py              SEC client: User-Agent, rate limit, disk cache
    paths.py              data directory paths
  fixtures/               LAKSH (frozen after kickoff)
    contract_example.json   one company's extracted covenants + definitions
    artifact_example.json   the same company fully computed
    groundtruth_example.json
    eval_example.json
  contracts/              LAKSH
    discover.py           find credit agreements + amendments per company
    segment.py            split agreements into articles/sections
    extract.py            LLM structured extraction with text spans
    verify.py             anti-hallucination checks on extractions
    amendments.py         apply amendments in order
    definitions.py        validate and normalize definition trees
    run.py                CLI: writes data/contracts/{cik}.json
    prompts/
    tests/
  engine/                 DAT
    xbrl.py               companyfacts -> quarterly + trailing-4Q series
    mapping.py            definition leaf -> XBRL concept + validator
    compiler.py           definition trees -> executable graphs
    compute.py            ratios, step-downs, interval headroom, status
    refusals.py           engine-level refusals
    provenance.py         lineage records
    run.py                CLI: writes data/artifacts/{cik}.json
    tests/
  validation/             DAT
    disclosed.py          ground truth A: company-reported covenant ratios
    events.py             ground truth B: waivers, amendments, defaults
    peers.py              matched peer selection
    universe.py           builds data/universe.json
    labels/               hand-labeled extraction gold set
    score.py              outputs vs ground truth -> eval report
    tests/
  api/                    DAT
    main.py               FastAPI server
    tests/
  web/                    DAT
    (Next.js app)
  notes/
    laksh.md              LAKSH only
    dat.md                DAT only
  data/                   (gitignored)
    cache/                shared EDGAR cache, append-only
    contracts/            Laksh's output
    artifacts/            Dat's engine output
    groundtruth/          Dat's validation output
    eval/                 Dat's score output
    universe.json         Dat's validation output
```

---

## 4. The contract (`shared/schema.py`)

Laksh writes this at kickoff. Both sides build against it. Field names below are the contract.

```python
SCHEMA_VERSION = "1.0"

class Span:                      # every claim points to real text
    accession: str               # SEC accession number
    url: str                     # filing document URL
    section: str | None          # e.g. "1.01", "7.11(a)"
    char_start: int
    char_end: int
    text: str                    # must be an exact substring of the document

class Company:
    cik: str
    name: str
    ticker: str | None
    sic: str | None

class Agreement:
    accession: str
    url: str
    filed: date
    kind: Literal["original", "amendment", "restatement"]
    redacted: bool               # redaction detected

class TermNode:                  # one node in a definition tree
    id: str
    label: str                   # "Consolidated EBITDA", "plus: non-cash charges"
    op: Literal["sum", "subtract", "ratio", "leaf", "cap", "floor"]
    children: list[str]          # TermNode ids
    cap: dict | None             # {"kind": "pct_of", "of": node_id, "pct": 0.10} or {"kind": "abs", "usd": ...}
    span: Span

class Threshold:
    effective_from: date
    effective_to: date | None
    value: float
    source: Span

class Covenant:
    id: str
    kind: Literal["max_leverage", "min_interest_coverage", "min_fixed_charge_coverage", "max_senior_leverage", "min_liquidity", "other"]
    direction: Literal["max", "min"]
    numerator_term: str          # TermNode id
    denominator_term: str | None
    test_period: Literal["ttm", "quarter", "point_in_time"]
    thresholds: list[Threshold]  # already reflect amendments
    agreement_accession: str
    span: Span

class Refusal:
    scope: Literal["company", "agreement", "covenant", "quarter"]
    ref: str
    reason: Literal["redacted", "ambiguous_definition", "missing_filing", "unmapped_term", "pro_forma_adjustment", "currency_or_units", "other"]
    detail: str

# ---- written by Laksh: data/contracts/{cik}.json ----

class ContractExtraction:
    schema_version: str
    generated_at: datetime
    company: Company
    agreements: list[Agreement]
    terms: list[TermNode]        # amendments already applied
    covenants: list[Covenant]
    refusals: list[Refusal]      # contract-level only
    extraction_notes: list[str]  # verifier disagreements, resolutions

# ---- written by Dat: data/artifacts/{cik}.json ----

class Input:                     # one leaf value used in a computation
    term_node: str
    value: float | None
    xbrl_concept: str | None     # e.g. "us-gaap:InterestExpense"
    fact_accession: str | None
    period_start: date | None
    period_end: date
    mapping_confidence: float
    validated: bool
    validation_note: str | None

class QuarterResult:
    covenant_id: str
    period_end: date
    ratio_low: float | None
    ratio_high: float | None
    threshold: float | None
    headroom_low: float | None   # signed distance to threshold, worst case
    headroom_high: float | None  # best case
    status: Literal["ok", "warning", "breach", "indeterminate", "refused"]
    inputs: list[Input]
    missing: list[str]           # TermNode ids with no source

class CovenantArtifact:
    schema_version: str
    generated_at: datetime
    contract: ContractExtraction # carried through unchanged
    quarters: list[QuarterResult]
    refusals: list[Refusal]      # contract-level + engine-level

# ---- written by Dat: ground truth, universe, eval ----

class DisclosedRatio:            # data/groundtruth/disclosed.json
    cik: str
    period_end: date
    covenant_kind: str
    reported_value: float
    reported_threshold: float | None
    span: Span

class CovenantEvent:             # data/groundtruth/events.json
    cik: str
    date: date
    kind: Literal["waiver", "amendment_loosening", "default", "acceleration"]
    span: Span

class UniverseEntry:             # data/universe.json
    cik: str
    role: Literal["disclosed", "event", "peer", "dev"]
    peer_of: str | None

class EvalReport:                # data/eval/report.json
    schema_version: str
    generated_at: datetime
    extraction: dict             # field-level precision/recall vs gold labels
    ratio_accuracy: dict         # median abs error, % reported inside computed range
    early_warning: dict          # lead quarters, hit rate, false alarm rate vs peers
    refusals: dict               # counts by reason
    per_company: list[dict]
```

---

## 5. Kickoff (done) and branches

Already in `main`:
- `shared/schema.py` (the contract), `shared/edgar.py` (SEC client), `shared/paths.py`
- `fixtures/` generated by `scripts/make_fixtures.py` from one synthetic company: 2 covenants, an EBITDA tree with a capped addback, a step-down, an amendment, 8 quarters including warning, indeterminate and refused quarters
- `AGENTS.md` / `CLAUDE.md` ownership rules, `notes/`, tests (`uv run pytest`)

Branches:
- `main`: contract and shared setup only. Nobody commits feature work here.
- `laksh/contracts`: Laksh's work (`contracts/`, `notes/laksh.md`).
- `dat/engine`: Dat's work (`engine/`, `validation/`, `api/`, `web/`, `notes/dat.md`).

Both branches merge into `main` by PR; paths never overlap, so neither PR can conflict.

## 6. Laksh (30%): contract understanding (`contracts/`)

**Goal:** for any company in `data/universe.json` (or a dev list until it exists), produce a schema-valid `data/contracts/{cik}.json`.

1. **Discover.** EDGAR full-text search on covenant phrases restricted to the company; pull EX-10 credit agreements and every later amendment and restatement; order chronologically; detect redaction markers ("[***]", "Confidential treatment requested").
2. **Segment.** Split into articles and sections using numbering patterns; keep exact character offsets.
3. **Extract (LLM, structured output, claude-sonnet-5-5; escalate hard definitions to claude-opus-5-5).** Covenants, thresholds and step-down schedules, test periods, and the full recursive definition tree of every term each covenant uses (Consolidated EBITDA refers to Consolidated Net Income, which has its own definition).
4. **Verify.** Every `Span.text` must be an exact substring of the source at its offsets, else drop and retry. Extract twice with different chunking; resolve disagreements with a verifier pass; unresolved ones become `ambiguous_definition` refusals.
5. **Amendments.** Apply in order: replaced definitions, changed thresholds, added covenants. Thresholds carry `effective_from` and `effective_to`.
6. **Definitions.** Normalize trees: every node reachable, no cycles, caps reference real nodes, leaves are atomic line items (not further-defined terms).
7. **CLI.** `python -m contracts.run --cik X` and `--universe`; idempotent; validates before writing.
8. **Tests.** Span substring check, amendment application, tree normalization, golden test against `fixtures/contract_example.json`.

**Done when:** valid contract files for 30+ universe companies, every span passes the substring check, tests pass.

---

## 7. Dat (70%): numbers, proof and product

Build against `fixtures/` first so you never wait on Laksh.

### Engine (`engine/`)
1. **XBRL series (`xbrl.py`).** From data.sec.gov companyfacts: quarterly values with Q4 derived as full year minus nine months; trailing-four-quarter sums for flow items; point-in-time for balance items; fiscal calendar alignment; units and signs normalized.
2. **Mapping (`mapping.py`).** For each definition leaf, the LLM proposes an XBRL concept with a confidence; a deterministic validator checks unit (USD), duration vs instant, sign and availability across quarters. Failures stay unmapped.
3. **Compiler (`compiler.py`).** Turn definition trees into executable graphs: sums, subtractions, caps (percent-of-term or absolute), floors, applied in contract order.
4. **Interval headroom (`compute.py`).** Unmapped addbacks are bounded: low case assumes zero, high case assumes the addback hits its cap (uncapped makes the quarter indeterminate). Compute ratio range and headroom range per quarter against the threshold in force. Status: ok, warning (within a margin), breach, indeterminate (range crosses the threshold), refused.
5. **Refusals and provenance.** Missing filings, pro forma adjustments, currency issues become refusals; every `Input` carries concept, accession, period, confidence and validation note.
6. **CLI.** `python -m engine.run --cik X` and `--universe`; reads `data/contracts/`; validates before writing.
7. **Tests.** Compiler, cap order, Q4 derivation, step-downs, interval logic, golden test from `fixtures/contract_example.json` to `fixtures/artifact_example.json`.

### Validation (`validation/`)
1. **Disclosed ratios (ground truth A).** EDGAR full-text search over 10-K and 10-Q for sentences reporting actual covenant ratios ("our Consolidated Leverage Ratio was 3.2 to 1.00"). Extract value, threshold, period and covenant kind with an LLM; every `Span.text` must be an exact substring. Target 50+ companies.
2. **Events (ground truth B).** 8-K filings disclosing covenant waivers, loosening amendments, defaults and accelerations; classify each with a span; dedupe per company.
3. **Peers.** For each event company, 2 to 3 matched peers: same SIC code, similar total assets, no covenant event in the window.
4. **Universe.** Write `data/universe.json`. Publish a partial version early so Laksh can start on it.
5. **Gold labels.** Hand-label covenants, thresholds and term structures in 20 agreements, independently of any pipeline output.
6. **Score.** Read contracts, artifacts and ground truth; write `data/eval/report.json`: extraction precision and recall per field vs labels; ratio accuracy (median absolute error, percent of reported ratios inside the computed range); early warning (lead quarters, hit rate, false alarm rate on peers); refusals by reason; per-company breakdown.

### API (`api/main.py`, FastAPI, read-only over `data/`)
- `GET /companies` with search
- `GET /companies/{cik}` the full artifact
- `GET /companies/{cik}/covenants/{id}/timeline` quarters plus events overlaid
- `GET /provenance/{cik}/{covenant_id}/{period_end}` inputs, spans, filing links
- `GET /eval` the eval report
- Falls back to `fixtures/` when `data/` is empty.

### Web (`web/`, Next.js)
- **Search and company page:** covenant cards with current status and headroom.
- **Headroom timeline (the hero):** computed range as a band, threshold as a step line, amendments marked, real waiver or default dates overlaid.
- **Provenance drawer:** click any point to see the clause text highlighted in context, each input's XBRL fact with a filing link, and mapping confidence.
- **Refusals panel:** what couldn't be computed and why.
- **Eval page:** accuracy table, early-warning chart, refusal breakdown.
- **Demo mode:** a pinned walkthrough of the chosen demo company.

**Done when:** the engine produces valid artifacts for every universe company with a contract file, ground truth covers 50+ companies, the eval report generates from real data, and the full UI works on fixtures and real data.

---

## 8. Integration

- Dat builds the engine, scoring and UI against `fixtures/` first; real data drops in with no code change.
- Merge order: Laksh's kickoff, then both branches in any order. No shared paths, so no conflicts.
- Pick the demo company together from the eval report: a real event, a clean early-warning signal, and inputs that all trace cleanly.

## 9. Demo script

1. "Covenant breaches are the first domino of default, and investors can't see them coming."
2. Open the demo company: headroom shrinks toward the threshold in the quarters before its real waiver, marked on the chart.
3. Click a quarter: clause text and filing line appear.
4. Eval page: computed vs company-reported ratios; early-warning hit rate vs peers.
5. Open a redacted agreement: refusal with the reason.

---

---

## 10. Agent prompt for Laksh

Run from the repo root on branch `laksh/contracts`.

```text
You are building the contract-reading half of Covenant Watch: read public companies' loan agreements from SEC EDGAR and turn them into structured, verified covenants and definition trees. A teammate (Dat) builds everything downstream: financial data, the headroom engine, validation, API and web app.

Before anything, read AGENTS.md, docs/PLAN.md (sections 2 to 6), shared/schema.py and fixtures/contract_example.json.

BRANCH: laksh/contracts. Commit only there.
YOUR FILES: contracts/ and notes/laksh.md. NEVER create or edit anything else. shared/ and fixtures/ are frozen; if the contract truly must change, stop and tell me.
YOUR OUTPUT: data/contracts/{cik}.json as ContractExtraction, validated before writing. Read data/universe.json if present; otherwise use a dev list of 5 leveraged public companies you find via EDGAR full-text search for "Consolidated Leverage Ratio" in EX-10 exhibits.
EDGAR: use shared/edgar.py only (User-Agent from SEC_USER_AGENT, rate limit, cache).

BUILD contracts/:
1. discover.py: find each company's credit agreements (EX-10) and every later amendment/restatement; order chronologically; detect redaction markers ("[***]", "Confidential treatment requested").
2. segment.py: split into articles/sections, preserving exact character offsets into the original text.
3. extract.py: structured extraction with claude-sonnet-5-5 (escalate hard definitions to claude-opus-5-5): covenants, thresholds with step-down schedules, test periods, and the full recursive definition tree of every term used (Consolidated EBITDA -> Consolidated Net Income -> ...). Caps become op="cap" nodes with cap={"kind": "pct_of"|"abs", ...}. Prompts live in contracts/prompts/.
4. verify.py: every Span.text must be an exact substring of the source at its offsets, else drop and retry. Extract twice with different chunking; resolve disagreements with a verifier pass; anything unresolved becomes a Refusal(reason="ambiguous_definition") plus an extraction_notes entry.
5. amendments.py: apply amendments in order (replaced definitions, changed thresholds with effective_from/effective_to, added covenants).
6. definitions.py: normalize trees: every node reachable, no cycles, caps reference real nodes, leaves are atomic line items.
7. run.py: `uv run python -m contracts.run --cik X` and `--universe`; idempotent.
8. contracts/tests/: span substring check, amendment application, tree normalization, golden test that reproduces fixtures/contract_example.json structure from a synthetic agreement text.

RULES: never invent contract text; an honest refusal beats a guess. Run `uv run pytest` before every commit. Small, meaningful commits.
DONE WHEN: valid contract files for 30+ companies, every span passes the substring check, all tests pass. Report what you verified, with numbers, and what you could not.
```

## 11. Agent prompt for Dat

Run from the repo root on branch `dat/engine`.

```text
You are building most of Covenant Watch, a tool that computes public companies' loan covenant headroom from SEC filings with full provenance. A teammate (Laksh) builds the contract reader that writes data/contracts/{cik}.json. You build everything after that: the financial-data engine that computes headroom, the ground truth that proves it, the scoring, the API and the web app.

Before anything, read AGENTS.md, docs/PLAN.md (sections 2 to 5 and 7 to 9), shared/schema.py and every file in fixtures/.

BRANCH: dat/engine. Commit only there.
YOUR FILES: engine/, validation/, api/, web/, notes/dat.md. NEVER create or edit anything else. Import from shared/ freely; never modify it. If you need a contract change or a new Python dependency, write it in notes/dat.md and stop.
YOUR OUTPUTS: data/artifacts/, data/groundtruth/, data/universe.json, data/eval/. Never write data/contracts/.
Build everything against fixtures/ first so you never wait on Laksh. EDGAR: use shared/edgar.py only.

ENGINE (engine/):
1. xbrl.py: shared.edgar.company_facts -> quarterly series; derive Q4 as FY minus 9M; trailing-4Q for flows, point-in-time for balances; fiscal calendar alignment; units and signs normalized.
2. mapping.py: for each definition leaf, claude-sonnet-5-5 proposes an XBRL concept with confidence; a deterministic validator checks unit (USD), duration vs instant, sign, availability. Failures stay unmapped.
3. compiler.py: definition trees -> executable graphs: sum, subtract, cap (pct_of or abs), floor, applied in contract order.
4. compute.py: interval headroom. Unmapped addbacks bounded (low = 0, high = cap; uncapped makes the quarter indeterminate). Ratio and headroom ranges per quarter against the threshold in force. Status ok / warning (within 10% of threshold) / breach / indeterminate (range crosses threshold) / refused.
5. refusals.py, provenance.py: engine refusals with reason codes; every Input carries concept, accession, period, confidence, validation note.
6. run.py: `uv run python -m engine.run --cik X` and `--universe`; reads data/contracts/; validates; writes data/artifacts/{cik}.json.
7. engine/tests/: compiler, cap order, Q4 derivation, step-downs, interval logic, and a golden test: fixtures/contract_example.json + the fixture TTM values must reproduce the ratios and statuses in fixtures/artifact_example.json.

VALIDATION (validation/):
1. disclosed.py: EDGAR full-text search over 10-K/10-Q for sentences reporting actual covenant ratios ("our Consolidated Leverage Ratio was 3.2 to 1.00"). Extract with claude-sonnet-5-5; Span.text must be an exact substring, else discard. Target 50+ companies. Write data/groundtruth/disclosed.json.
2. events.py: 8-Ks disclosing covenant waivers, loosening amendments, defaults, accelerations; classify with spans; dedupe. Write data/groundtruth/events.json.
3. peers.py: 2 to 3 matched peers per event company (same SIC, similar total assets, no covenant event in the window).
4. universe.py: write data/universe.json. Publish a partial version early and note it in notes/dat.md so Laksh can run on it.
5. labels/: hand-label covenants, thresholds and term structures for 20 agreements, independently of any pipeline output.
6. score.py: read data/contracts/, data/artifacts/, ground truth -> data/eval/report.json: extraction precision/recall per field; ratio accuracy (median absolute error, % of reported ratios inside the computed range); early warning (lead quarters, hit rate, false alarm rate on peers); refusals by reason; per-company breakdown.
7. validation/tests/: span substring check, classification on known examples, scoring math on fixtures.

API (api/main.py, FastAPI, read-only over data/, falls back to fixtures/ when data/ is empty):
GET /companies (search), GET /companies/{cik}, GET /companies/{cik}/covenants/{id}/timeline (quarters + ground-truth events), GET /provenance/{cik}/{covenant_id}/{period_end}, GET /eval.

WEB (web/, Next.js, its own package.json):
- Search and company page with covenant cards (status, current headroom).
- Headroom timeline (hero): computed range as a band, threshold as a step line, amendments marked, real waiver/default dates overlaid.
- Provenance drawer: click a quarter to see the clause text highlighted in context, each input's XBRL fact with a filing link, mapping confidence.
- Refusals panel; eval page (accuracy table, early-warning chart, refusal breakdown); demo mode with a pinned walkthrough.
Clean, serious financial-product look. Light and dark themes. Fixture data is always labeled as fixture in the UI.

RULES: never guess a number; an honest refusal beats a silent wrong value. Run `uv run pytest` before every commit. Small, meaningful commits.
DONE WHEN: artifacts for every company with a contract file, ground truth covers 50+ companies, the eval report generates from real data, and the full UI works on fixtures and real data. Report what you verified, with numbers, and what you could not.
```
