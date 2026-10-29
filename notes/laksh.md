# Laksh notes

## Contract reader, October 28, 2026

Implementation is on `laksh/contracts`. No shared schema, dependency, fixture, or Dat-owned file changed. No push or merge has been performed.

Run with the contact header in the environment. Planning does not construct a model client or require an Anthropic key:

```sh
SEC_USER_AGENT='Covenant Watch lgoyal@ucsd.edu' uv run python -m contracts.run --cik 1590955 --pilot --plan-only
```

Paid extraction now requires an explicit `--max-cost-usd` amount and a working `ANTHROPIC_API_KEY`. The amount is one shared budget for the entire invocation, including both passes, retries, and Opus. The user approved a $0.50 pilot limit, then authorized raising it. A $3 cumulative pilot ceiling was chosen and announced. The completed new pilot attempts totaled $2.291430 from reported usage at the verified model prices, excluding the earlier user-reported $8 incident. The user subsequently explicitly authorized storing the working key. It was saved in macOS Keychain under service covenant-watch.anthropic, account covenant-watch, and storage/readback were verified without displaying it. contracts.credentials.load_api_key reads that project item before the stale inherited environment key. On other platforms or if Keychain is unavailable, it uses ANTHROPIC_API_KEY. No key is stored in repository files or request checkpoints.

Historical incident: the original full Paycom scan used raw-HTML windows without partial-result checkpoints or a spend limit. The user reported $8 in charges. Both processes were stopped; zero finished company files were produced. The original partial responses were in memory and cannot be reconstructed from saved output. The reader has now been changed as described below. No paid model requests were made while implementing these fixes.

### Retrieval, checkpoints, and spending controls

- `contracts/context.py` builds readable text with a character map back to the original HTTP body. Only locally found covenant sections, their recursive definition references, and a bounded agreement header are selected. Entire financial sections retain conditions and threshold tables. Amendments retain their complete readable body. Oversized or unidentifiable units cause a refusal before any model fallback; there is no automatic whole-document scan.
- Both extraction passes remain required and use different ordering/grouping. Plain caps alone no longer trigger Opus; unresolved/deep definitions and verifier disagreements can escalate, always through the same budget gate.
- `--pilot` requires one CIK, selects one locally plannable original/restated document, and retains at most one normalized covenant. Outputs go to `data/contracts/_pilots/`, with an explicit note that this is one agreement only and not a current company-level artifact. Later amendments and other facilities are not certified by a pilot.
- `contracts/runtime.py` retrieves fresh standard prices from https://platform.claude.com/docs/en/about-claude/pricing and fails closed if both model prices cannot be verified. The documentation checked October 28 lists Sonnet 5.5 at $2/$10 per million input/output tokens and Opus 5.5 at $4/$20. Cache-write/read prices are also accounted for. Only the official Anthropic API, standard service, global inference routing, and inputs within the supported standard-context envelope are used.
- Before inference, the free token-count endpoint is called. Since Anthropic documents it as approximate, the reservation uses at least the serialized UTF-8 request size plus format headroom, the most expensive applicable input/cache rate, and the maximum permitted output. This is a conservative local budget guard at verified published rates, not an account-wide provider billing limit or a guarantee against a provider changing its billing behavior.
- SDK inference retries are disabled. Each inference attempt has its own durable reservation. Valid reported usage settles the reservation; missing usage retains its full amount. Usage exceeding the reservation halts the run for review. A request that would exceed the remaining budget is not sent.
- `data/contracts/_checkpoints/` stores the exact model request, source hash, response, and verification status, with a checksum. Authentication headers and keys are never stored. Responses are persisted before schema/span verification, including rejected or truncated responses. Completed requests are reused after restart without another inference call. Truncated output does not trigger automatic paid retries.
- Exclusive checkpoint creation prevents concurrent runs from billing the same request. Interrupted or uncertain pending requests block automatic replay and require review. Corrupt checkpoints also fail closed instead of being discarded and rebilled.
- `data/contracts/_runs/` stores each invocation's budget, pricing evidence, per-request reservations and usage. A fresh invocation with a new explicit budget can reuse finished checkpoints, but does not silently retry uncertain calls from the previous run.

### Interface for Dat

- Outputs use the unchanged `shared.schema.ContractExtraction`, schema version 1.0.
- Every span indexes the exact UTF-8 decoded exhibit HTTP body, including HTML markup. Do not calculate these offsets against rendered text, decoded entities, or normalized whitespace. Retrieve the original URL through `shared.edgar`.
- Node and covenant IDs are prefixed with a cited facility identity and a colon. All graph references, including percentage-cap bases, use those complete IDs.
- Threshold intervals are inclusive. Temporary amendments preserve the original schedule after expiry. Threshold-only amendments retain the original covenant clause provenance; each changed threshold cites its own amendment.
- The output contains only reachable nodes in dependency order. Cap bases participate in cycle checks. Unexpanded definitions and non-atomic leaves cause refusals.
- Incomplete discovery, redactions, unknown facility lineage, unsupported conditions, and unresolved amendments cause conservative refusals. An empty amendment extraction does not prove unchanged financial terms. This can reduce recall; it is intentional and must be evaluated on real agreements.
- `data/contracts/_evidence/{cik}.json` holds source, pipeline, and output fingerprints for idempotency. It contains no API credentials. The top-level `{cik}.json` is the artifact Dat reads.
- `contracts.metrics=` in extraction_notes contains compared item count, disputed item count, verifier calls, and rejected-evidence retries. Disagreement rate is disputed items divided by the union of compared node/covenant/identity/removal IDs across the two layouts, including conflicts within a layout. It is not field-level extraction accuracy. Null means no comparisons were performed.
- Existing `data/universe.json` is read-only. Without it, `--universe` discovers five public dev borrowers through EX-10 search hits; it does not write a universe file or claim to satisfy the 30-company target.

### Verification and outstanding work

- `uv run pytest`: 62 passed, including mocked structured transport, two-layout agreement/disagreement handling, evidence retries, Opus escalation, amendment replacement/deletion/restatement, definition integrity, atomic publication, source-change/tamper invalidation, and unchanged-file idempotency.
- The offline golden integration test reproduces the frozen fixture's 2 covenants, 10 terms, capped addback, and amendment schedule. All 16 output spans match reconstructed synthetic source bodies. Claude responses in this test are mocked; this is not evidence of live model accuracy.
- Live SEC dev discovery returned Cumulus Media (0001058623), Boston Scientific (0000885725), Terex (0000097216), SPX Technologies (0000088205), and Take-Two (0000946581). These are candidates, not completed company extractions.
- Live source smoke check: Paycom exhibit `https://www.sec.gov/Archives/edgar/data/1590955/000119312526173704/payc-ex10_1.htm`, 1,662,289 decoded characters, 312 source segments, 72 primary chunks and 65 alternate chunks. A source-bound quote passed the exact-substring check. These are historical full-scan counts; the new reader uses targeted readable units.
- Real company extraction totals: 0 completed companies, 0 covenants, 0 terms, 0 output contract files. Refusals by reason and verifier disagreement rate on real companies are not measured from any completed artifact. The earlier interrupted run did make paid requests. The 30+ company acceptance target remains outstanding.
- End-to-end amendment discovery recall, facility identity consistency, financial meaning, extraction precision/recall, and all real-company output integrity remain unverified. Unsupported/non-text EX-10 documents and failed filing fetches are surfaced as missing_filing refusals.
- The updated golden test also exercises a complete synthetic one-covenant pilot through the real budget/checkpoint transport with mocked API responses. Its normalized graph and more than 10 spans pass validation; restarting with no new budget reuses responses and produces the same graph without additional mocked inference calls. This does not establish live accuracy.
- A fresh real CLI `--pilot --plan-only` run for Paycom completed with `inference_started=false`, no failures, and a selected 2022 agreement: https://www.sec.gov/Archives/edgar/data/1590955/000119312522210029/d362080dex101.htm. It selected 84,841 readable characters from 849,965 raw characters, 147 source units and 142 referenced definitions, with 5/8 planned groups for the two layouts. This is a retrieval plan, not a live extracted covenant or a cost guarantee.
- No new packages were needed. No standalone research, draft, or conversion files were created. SEC responses were cached only through the shared EDGAR helper.

### Dat handoff context

Read-only inspection of origin/dat/engine at 64f63da confirms a 250-entry validation/universe_snapshot.json. Dat recommends its existing order for the first 30 to 60 companies. Do not write data/universe.json from this branch. The data directory is gitignored, so a code push alone will not deliver contracts. After generating verified outputs, transferring those files avoids repeating paid extraction; Dat can place them in data/contracts/ and run his engine and scorer. No transfer or message to Dat has been performed. Gold labels still require independent human verification; output from this reader is not an independent gold label.

### Demo handoff, ready now

The user switched the immediate goal from the 30-company batch to an example-data demo with real SEC source material. No additional paid batch has been started.

Run `SEC_USER_AGENT='Covenant Watch lgoyal@ucsd.edu' uv run python -m contracts.demo`. It makes no Anthropic calls. Outputs are in `data/contracts/_demo/`:

- `example_contract.json` and `example_artifact.json`: one explicitly identified example company, 2 covenants, 10 terms, 8 quarter ends and 16 covenant-quarter records. Status counts are 11 ok, 2 warning, 1 indeterminate, 2 refused. The synthetic source documents are reconstructed under `example_sources/`; all 16 contract spans pass exact source checks. Example document URLs use the reserved example.invalid domain and financial input accessions are absent, so they are not represented as real SEC facts.
- `real_sec_thresholds.json`: 14 real Paycom leverage-threshold observations from the 2022 SEC agreement, with exact raw source quotes and offsets. These are document-specific contractual thresholds, not measured company ratios, not headroom, and not a certification of current amended terms. All 14 source spans pass verification after publication.
- `manifest.json`: clear origins, counts and display labels. Use “Example data” and “SEC contract thresholds”. Do not put the example company's financial values under Paycom's name or claim a measured accuracy score from the example.
- `covenant_watch_demo_bundle.zip`: the finished handoff package, limited to these example files, source text and real threshold observations. It excludes credentials, request checkpoints and billing ledgers.

Read-only inspection confirms Dat's API already serves the frozen example artifact automatically when data/artifacts has no real files. This makes the timeline demo available without waiting for our batch. Its UI currently displays FIXTURE DATA badges/banner. Product wording can be changed to Example data while retaining clear origin; those visible label changes and integration of the real SEC observations belong to Dat's web/api paths and were not edited here. Do not move synthetic artifacts into the production folder and let the API call them real data.

The live Paycom pilot completed as a refusal artifact at `data/contracts/_pilots/0001590955.json`: 0 computable covenants, 0 terms and 22 refusals (15 ambiguous_definition, 2 pro_forma_adjustment, 2 unmapped_term, 2 other, 1 missing_filing). All 35 compared item IDs disagreed, and 35 verifier calls ran. This is not extraction accuracy; intermediate node alignment and unsupported definitions remain unresolved. The real SEC table observations above were independently checked against the same source body. No verified real financial ratios were produced.

The collaborator invitation for aaronmarasco was created and verified by the requested subagent: invitation 340262027, standard write access, pending acceptance when checked. No branch push or merge has been performed.
