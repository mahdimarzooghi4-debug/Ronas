# PostgreSQL Export research finding drafts (LOCAL/TEST)

The optional `PostgresExportResearchFindingLedger` moves the existing Export
analyst-note journal from the SQLite review ledger to PostgreSQL. It is
composed only when the existing Keycloak BFF and API share the exact same
synthetic case/grant ledger; every write and read rechecks the current Export
operator grant through that ledger. A per-case/question advisory transaction
lock serializes append-only revisions. Notes are AES-GCM encrypted at rest,
and receipt links, note digests, stale revisions, action replay, and database
row mutation are checked.

Both LOCAL/TEST BFF factories accept an explicitly injected
`export_research_finding_ledger` and pass it to the existing Keycloak API and
management UI. Composition is rejected unless the PostgreSQL adapter's
workspace reader is bound to the exact same
`SqliteSyntheticHumanReviewLedger` used for current Export case grants. The
PostgreSQL-session BFF integration test signs in through mocked Keycloak,
records an encrypted finding from the existing Persian Export form on one BFF,
and reads its history from a second BFF instance. The browser form and Bearer
API keep their existing paths and command contract.
History preserves question/evidence binding and source-reference provenance;
stale question or evidence context is rejected. The UI continues to label all
entries `DRAFT_ONLY` and `report_approved=false`. This adapter does not ingest
source bytes, verify source rights, establish market facts, publish a report,
identify a buyer, create a contract, or trigger a trade. The existing SQLite
review ledger remains the authoritative access/grant and workspace source.

This is an explicit LOCAL/TEST adapter. It does not select or activate a
Production persistence topology. CI coverage uses its isolated PostgreSQL 17
service; environments without `RONAS_TEST_POSTGRES_DSN` skip only those
integration cases.
