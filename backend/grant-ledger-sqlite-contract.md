# Ronas — Restart-safe synthetic case-grant journal (SQLite reference)

**Scope:** locally durable Technical/test candidate, 2026-10-10. This
does NOT select the Production datastore, approve real record access,
establish lawful collection, satisfy an independent external audit
requirement or authorize Stage/Production. Hosting procurement is excluded.

## Implemented

The new module backend/ronas_api/grant_ledger_sqlite.py defines
SqliteSyntheticGrantLedger: an explicit opt-in subclass of the immutable
synthetic case registry. Existing Keycloak-signed role AND exact-record grant
requirements still apply. No new public mutation endpoint or grant
assignment path exists. The default FastAPI app does not mount this ledger.

The local SQLite database records a SHA-256 fingerprint of all pre-seeded
case definitions, owners, existing grants, and immutable case version
markers. Reopening with changed seed data fails closed. It also stores
per-case grant revisions, accepted revocation commands, and ordered
hash-linked audit events for reads and revocations. Actors/targets are
represented by SHA-256 pseudonymous digests rather than raw subject strings.
No JWT, address, crop details, export transaction or free-text reason is
stored. Source fixture names and case IDs are synthetic only.

## Concurrency and crash/restart recovery

Each read decision and corresponding audit acceptance share a SQLite
BEGIN IMMEDIATE transaction; a failed audit append cannot return a
successful read. A revocation also atomically checks current revision,
records the exact case/grantee/actor/role/action/reason identity, appends its
audit event and advances the grant revision. A failed append rolls back
the entire transaction. Same exact action ID and payload is idempotent
across reopened connections; changed replay, stale version or unseeded
grant fails closed. Independent SQLite connections serialize writers.

An independent, injected revocation-authorizer callback is mandatory;
neither Keycloak governance nor Domestic/Export staff roles create a
revocation authority. After revoking an exact grant, even a previously
issued, still-valid Keycloak-signed JWT cannot read that case on the
same or reopened local database. Other grantees and the household owner
retain their separately justified access. Export and Domestic remain
independent. No permission creation/reinstatement is implemented.

Audit events have ordered sequence numbers and linked SHA-256 digests.
UPDATE and DELETE SQL triggers protect the append-only audit, immutable
seeded history and revocation rows against ordinary SQL edits. At every
repository operation the local chain, stored head, seed, version lineage,
grant revision, and revocation matching are checked. Untrusted state
raises LedgerIntegrityError and denies access.

## Command attestation and per-case audit revision (2026-10-10)

An accepted `GRANT_REVOKED` event now records
`access_mode=REVOCATION_COMMAND_SHA256:<payload_digest>` inside the existing
append-only hash-linked event. This is technical metadata, **not** an
additional grant/authority or Business decision. The synthetic grant table's
`payload_digest` must match this exact event field on every read, reopen,
replay and integrity check; matching SHA-256 length alone is insufficient.
The event's `target_digest` still identifies the hashed revoked grantee;
the exact grantee+role must exist in the immutable seeded case grants.

The audit verifier walks events in sequence and checks `case_version`
against the seeded case and `grant_revision` against the deterministic,
case-local count of **accepted** `GRANT_REVOKED` events. Every other audit
kind (including technical review and reads) must carry the current
revision unchanged. This catches accidental/corrupt row-to-event lineage
drift without promoting a Business case state.

**Intentional version boundary:** an older LOCAL/TEST SQLite ledger with
existing grant-revocation events whose `access_mode` lacks this exact
command binding is *not* silently backfilled or accepted. Its original
command actors are not recoverable from pseudonymous digests; recreating a
hash from guessed values would be a false attestation. Such experimental
data remain unadmitted and require a fresh **synthetic** fixture, never
migration of real grants or user information. This is not a production
upgrade plan.

An optional scoped-case HTTP read whose grant/audit integrity check fails
now responds `503 SYNTHETIC_LEDGER_UNAVAILABLE`, not a misleading
authorized draft or an unhandled error. The existing review GET retains
its own controlled `503 TECHNICAL_REVIEW_UNAVAILABLE` response.
Neither endpoint releases evidence when verification fails. The default
app remains without injected operational case stores.

Six extra regression tests in
`backend/tests/test_grant_ledger_sqlite.py` verify command hash binding,
corrupted digest rejection, legacy-unbound history denial, canonical
but revision-inconsistent audit rejection, forged non-seeded grantee
rejection and controlled HTTP 503 with no leakage.

## Explicit security limitations

This is a **single-host SQLite WAL reference**, not a distributed authority
or Production data store. The file must be a private 0600 regular file.
Audit events are persisted locally, but they are NOT signed, independently
anchored, replicated, or protected against a sufficiently privileged
database/server administrator. SHA-256 digests are pseudonyms, not
anonymization. This database is not application-layer encrypted; NO real
user, household, market data or secret can be written into these fixtures.
Do not confuse it with the separate locally encrypted experimental BFF
session store. Neither represents a selected Production datastore.

History consists of *previously supplied version markers*, not real
record-edit events. Unknown records, invalid identifiers and failed
authentication are not guaranteed to produce audit events. An operational
audit/retention and erasure policy still requires actual business review.
No recovery objectives, actual backup/restore provider or independent
security signoff is claimed.

## Offline verification

Test path: backend/tests/test_grant_ledger_sqlite.py
Run from repo root (Python 3.12):

1. python -m pip install -r backend/requirements-test.txt
2. PYTHONPATH=backend python -m unittest discover -s backend/tests -v
3. PYTHONPATH=backend python -m compileall -q backend/ronas_api
4. python -m unittest discover -s prototype/tests -v
5. node --test prototype/tests/test_demo_model.mjs

Tests exercise reopen, grant-revision CAS, identical/different concurrent
actions, old Keycloak JWT denial, initial-seed drift, forbidden history
UPDATE/DELETE, stored-head tamper, rolled-back audit append, role/engine
separation and absence of public grant mutation. All identity keys,
actors, records and research sources are synthetic.

No real case owner, revocation decision maker, customer consent, qualified
agronomist, Export source rights, actual Keycloak operation, permanent
production DB/audit vendor or hosting has been authorized/connected.
Domestic #2, Export #3, Finance #4 remain OPEN. PR #1 and #9 Draft/Open
and unmerged. No Stage, QA Gate, Release or Production.
