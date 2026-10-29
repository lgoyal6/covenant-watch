# Dat notes

Requests for Laksh. Only Dat edits this file.

## Universe for Laksh

- `data/universe.json` (list of `UniverseEntry`, CIKs 10-digit zero-padded) is built by `uv run python -m validation.universe`. Because `data/` is gitignored, every build also writes an identical committed copy: **`validation/universe_snapshot.json`**. Read that one.
- Status: FINAL for the hackathon build (rebuilt ~16:00 PT): 250 entries. 40 role `event` (8-K covenant waiver / loosening amendment / default / acceleration; XBRL total assets >= $250M just before the first event, largest first), 65 role `peer` (same SIC, similar assets, no covenant-trouble 8-K hits within +/-2y; `peer_of` = the event CIK; 29 of the 40 event companies have peers), 145 role `disclosed` (10-K/10-Q reports an actual covenant ratio we can score against). All are XBRL filers.
- Order in the file is the suggested processing order: each event company followed by its peers, then disclosed companies. If you can only do ~30-60 contract files, take them from the top.

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

## Gold-label agreements (please include these exact agreements in your contract files)

The extraction score only compares a label with a contract file that lists the same agreement accession in `agreements`. Drafts in `validation/labels/` cover:

| CIK | Agreement accession | URL |
|---|---|---|
| 0000033185 | 0001193125-21-262096 | https://www.sec.gov/Archives/edgar/data/33185/000119312521262096/d220137dex101.htm |
| 0000034067 | 0001104659-21-153921 | https://www.sec.gov/Archives/edgar/data/34067/000110465921153921/tm2136265d1_ex10-1.htm |
| 0000037785 | 0000037785-22-000047 | https://www.sec.gov/Archives/edgar/data/37785/000003778522000047/fmc-2022rcfxfiftharrevol.htm |
| 0000051253 | 0001193125-21-227550 | https://www.sec.gov/Archives/edgar/data/51253/000119312521227550/d206865dex101.htm |
| 0000106040 | 0000106040-22-000040 | https://www.sec.gov/Archives/edgar/data/106040/000010604022000040/wdc-2022q3ex102.htm |
| 0000712034 | 0000712034-17-000012 | https://www.sec.gov/Archives/edgar/data/712034/000071203417000012/acco-20161231xex1011.htm |
| 0000789570 | 0001193125-21-341290 | https://www.sec.gov/Archives/edgar/data/789570/000119312521341290/d260983dex101.htm |
| 0000824142 | 0000824142-21-000155 | https://www.sec.gov/Archives/edgar/data/824142/000082414221000155/aaonnovember2021amendedloa.htm |
| 0000861878 | 0001193125-21-291128 | https://www.sec.gov/Archives/edgar/data/861878/000119312521291128/d233563dex101.htm |
| 0000861884 | 0001104659-24-100168 | https://www.sec.gov/Archives/edgar/data/861884/000110465924100168/tm2423965d1_ex10-1.htm |
| 0001070750 | 0000950170-23-000254 | https://www.sec.gov/Archives/edgar/data/1070750/000095017023000254/hst-ex10_1.htm |
| 0001137789 | 0001137789-25-000023 | https://www.sec.gov/Archives/edgar/data/1137789/000113778925000023/seagate-creditagreementedg.htm |
| 0001174922 | 0001174922-19-000115 | https://www.sec.gov/Archives/edgar/data/1174922/000117492219000115/ex101-wynn2019xcredita.htm |
| 0001377630 | 0000950170-25-008998 | https://www.sec.gov/Archives/edgar/data/1377630/000095017025008998/ncmi-ex10.htm |
| 0001468174 | 0001193125-22-158508 | https://www.sec.gov/Archives/edgar/data/1468174/000119312522158508/d336237dex101.htm |
| 0001617406 | 0000950170-22-025964 | https://www.sec.gov/Archives/edgar/data/1617406/000095017022025964/pk-ex10_1.htm |
| 0001692115 | 0001193125-20-107089 | https://www.sec.gov/Archives/edgar/data/1692115/000119312520107089/d902383dex101.htm |
| 0001749723 | 0001140361-21-013692 | https://www.sec.gov/Archives/edgar/data/1749723/000114036121013692/brhc10023371_ex10-2.htm |
| 0001766368 | 0001558370-23-011571 | https://www.sec.gov/Archives/edgar/data/1766368/000155837023011571/tmb-20230628xex10.htm |
| 0001806347 | 0001558370-22-014048 | https://www.sec.gov/Archives/edgar/data/1806347/000155837022014048/west-20220630xex10d3.htm |

## README edited (Dat, Oct 28 evening)

README.md is yours per AGENTS.md. Dat asked me to update it before merging: added the why, pipeline and app run commands, the three data sources the API can serve (real, example fixture, `CW_DATASET=demo`), and the page list. Setup and layout sections are unchanged apart from fuller descriptions of Dat's folders. Change anything you disagree with.

## Demo dataset

`uv run python -m validation.demo_data` writes 100 fictional companies to `data/demo/` (not `data/artifacts/`), computed through the real engine and scored by the real scorer, for testing the UI at volume. The API only serves them when started with `CW_DATASET=demo`, and the UI labels them "Demo data". Your fixture company is now labeled "Example data" as you asked.
