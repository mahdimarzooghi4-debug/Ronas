# Ronas — Synthetic human-review evidence and decision-reference history

Status: isolated, opt-in, LOCAL/TEST technical candidate (2026-10-10).
Domestic Gate #2, Export Gate #3 and Finance Gate #4 are OPEN.

## No business approval or real case state changes

The only technical states are UNREQUESTED -> EVIDENCE_REVIEW_REQUESTED ->
HUMAN_RESPONSE_RECORDED. The underlying ScopedDraft remains DRAFT_ONLY
at every stage. A recorded synthetic human-note reference is NOT an
approved cultivation plan, scientific recommendation, source-rights
clearance, verified exporter/buyer, actual human signature or contract.
No approval/rejection category, threshold, retention period or
decision-making authority is invented.

## Internal command and verification boundary

Module: ronas_api/human_review_sqlite.py.
Requesting review requires an injected, preverified Keycloak principal,
a current exact-record, exact-engine operations grant, immutable case
version, expected technical-review revision zero and synthetic request
and evidence references. Recording a human response requires the exact
same request reference, revision one, current case version and a distinct
assigned actor additionally accepted by an independently injected human
review authorizer. An ordinary governance/finance role cannot bypass it.
Revoked grants cannot create or complete a review. Neither method has
an HTTP endpoint. No AI, data ingestion, consent or real decision is run.

Both stages are append-only SQLite rows accepted atomically with a linked
audit event in one BEGIN IMMEDIATE transaction; read-only history and
review-state queries validate exact case, stage, actor digests, evidence,
decision reference, command payload hash and audit chain. Identical
actions replay idempotently; changed replay, stale version, missing
request, same-actor response and concurrent conflicting requests fail
closed. Evidence/request/note refs are DEMO-only identifiers, not actual
content, reviewed facts or access rights. A non-review-aware generic
grant ledger refuses to open an audit history with review-specific
events rather than silently ignoring them.

## Currently authorized read facade (internal only)

`read_review_for_operator(engine, ref, principal)` is the opt-in
technical-history read boundary. The caller must already have validated the
Keycloak signature, issuer, audience and client role; a bare Python `Principal`
is **not** proof of signature verification. The ledger checks a current
exact-case and exact-engine operations assignment in the same
`BEGIN IMMEDIATE` transaction as the read and audit append. A previously
valid JWT does not bypass a revoked case grant. Governance, finance,
unassigned and cross-engine actors cannot read technical evidence references.
Unknown case and unauthorized case return the same `None` result.

For a known synthetic record and syntactically valid synthetic subject, each
read attempt appends `READ_ALLOWED` or `READ_DENIED` with the existing
hash-chained audit vocabulary and `TECHNICAL_REVIEW_HISTORY` access mode.
A failed audit insert aborts the entire read, without returning its contents.
Concurrent revocation and read are serialized by SQLite's transaction lock;
a successful read must precede revocation in the audit sequence. Authorized
results contain only engine/ref, case version, immutable `DRAFT_ONLY` status,
technical state/revision and a sequence of DEMO stage, request, evidence,
note and audit-sequence references. They omit actor and command digests,
actual note contents, identity and new approval/denial categories.

`review_state` and `review_history` remain **trusted internal diagnostic
helpers**, without authorization checks. They MUST NOT be exposed through an
HTTP route, used as a session-facing interface or interpreted as an
operational review decision. Downstream UI/BFF integrations must use an
authenticated, exact-case-checked facade and must not trust a client-
supplied `Principal`. No new review endpoint has been mounted. This is
not a Production read/authorization policy and no new user role is granted.

## Tests and exclusions

Tests: backend/tests/test_human_review_sqlite.py (27 offline tests).
Scenarios cover restart/reopen, independent authorization, revoked
grant, cross-engine isolation, request binding, forced SQL insert
rollback, audit tampering, SQLite append-only triggers, concurrent
replay/CAS, missing request and absence of public decision endpoints.
Additional scenarios exercise exact-case read authorization, denied-role/assignment/engine access, immediate revocation, atomic audit-write failure and concurrent read/revocation ordering. Existing Keycloak and synthetic domain tests remain in the same CI.

This is a local single-host SQLite simulation, NOT a production store,
distributed consistent authorizer, tamper-proof independent audit or
real identity/consent/source-rights acceptance. Business Gate decisions,
genuine agronomy expert qualification, actual human decision rights,
operational workflow definitions, lawful case data, production
infrastructure and human QA/security approval remain open.
PR #1 and #9 stay Draft/Open/Unmerged. No Stage or Production.
