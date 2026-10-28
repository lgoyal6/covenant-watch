# Laksh notes

## Contract reader, October 28, 2026

Implementation is on `laksh/contracts`. No shared schema, dependency, fixture, or Dat-owned file changed. No push or merge has been performed.

Run with the contact header in the environment:

```sh
SEC_USER_AGENT='Covenant Watch lgoyal@ucsd.edu' uv run python -m contracts.run --cik 1590955
SEC_USER_AGENT='Covenant Watch lgoyal@ucsd.edu' uv run python -m contracts.run --universe
```

`ANTHROPIC_API_KEY` must already be set. The CLI checks credentials and availability of `claude-sonnet-5-5` and `claude-opus-5-5` before discovery. It does not silently substitute models. The original environment key was rejected with HTTP 401. A replacement key supplied via the clipboard later authenticated successfully, and both requested model IDs were listed. The replacement was used in process memory only, without displaying or persisting it. A live Sonnet request then revealed that Claude 5.5 rejects forced tool_choice values tool/any. The reader now uses automatic tool choice and still rejects any missing, multiple or truncated structured response. A live table-of-contents chunk returned a valid structured response with no financial items; this does not establish financial extraction accuracy. A full Paycom run is in progress.

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

- `uv run pytest`: 31 passed, including mocked structured transport, two-layout agreement/disagreement handling, evidence retries, Opus escalation, amendment replacement/deletion/restatement, definition integrity, atomic publication, source-change/tamper invalidation, and unchanged-file idempotency.
- The offline golden integration test reproduces the frozen fixture's 2 covenants, 10 terms, capped addback, and amendment schedule. All 16 output spans match reconstructed synthetic source bodies. Claude responses in this test are mocked; this is not evidence of live model accuracy.
- Live SEC dev discovery returned Cumulus Media (0001058623), Boston Scientific (0000885725), Terex (0000097216), SPX Technologies (0000088205), and Take-Two (0000946581). These are candidates, not completed company extractions.
- Live source smoke check: Paycom exhibit `https://www.sec.gov/Archives/edgar/data/1590955/000119312526173704/payc-ex10_1.htm`, 1,662,289 decoded characters, 312 source segments, 72 primary chunks and 65 alternate chunks. A source-bound quote passed the exact-substring check. No financial extraction was run on it.
- Real company extraction totals: 0 completed companies, 0 covenants, 0 terms, 0 output contract files. Refusals by reason and verifier disagreement rate on real companies are not measured because inference did not run. The 30+ company acceptance target remains outstanding.
- End-to-end amendment discovery recall, facility identity consistency, financial meaning, extraction precision/recall, and all real-company output integrity remain unverified. Unsupported/non-text EX-10 documents and failed filing fetches are surfaced as missing_filing refusals.
- No new packages were needed. No standalone research, draft, or conversion files were created. SEC responses were cached only through the shared EDGAR helper.

### Dat handoff context

Read-only inspection of origin/dat/engine at 64f63da confirms a 250-entry validation/universe_snapshot.json. Dat recommends its existing order for the first 30 to 60 companies. Do not write data/universe.json from this branch. The data directory is gitignored, so a code push alone will not deliver contracts. After generating verified outputs, transferring those files avoids repeating paid extraction; Dat can place them in data/contracts/ and run his engine and scorer. No transfer or message to Dat has been performed. Gold labels still require independent human verification; output from this reader is not an independent gold label.
