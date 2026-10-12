# Ronas — Household-owned version history in the shared user workspace

**Status:** LOCAL/TEST technical and user-flow prototype, 2026-10-10,
Draft PR #9; actual CORE-D1-A intake/consent business scope **NOT ADMITTED**.
This implements only historical visibility for *immutable seeded DEMO
household cases*. It does not create or modify real or synthetic case
versions, record live cultivation facts, collect consent, authorize an
expert, or make a planting recommendation.

## Product context and user journey

The Domestic user's approved UI *topology* is one shared user/partner
environment. An authenticated household can already browse its own
DOMESTIC `DRAFT_ONLY` synthetic cases. The new links labeled
`تاریخچه نسخه‌ها` on that existing list open a read-only timeline in
the **same** `/` user shell:

`GET /my-drafts/{ref}/versions`

For each actually persisted version in the immutable case-history
fixture, the UI shows its exact version number and whether it is
the current fixture version. It deliberately does **not** imply
an event, date, actor, modification, or review for missing version
numbers. For example, if the fixture lists 1 and 3, version 2 is
not fabricated. Every line is labeled synthetic and `DRAFT_ONLY`.
The existing optional technical-review detail page remains an
**independent** route: `/my-drafts/{ref}` only when the same explicit
review-aware ledger is injected. A base grant ledger may offer
version history while still being unable to offer review progress.

## Contract

`SqliteSyntheticGrantLedger.read_owned_domestic_version_history(
ref, principal)` requires a principal independently verified by
Keycloak at the API/BFF boundary. The method itself never treats a
plain caller-supplied Principal as a JWT. Before any disclosure, it:

1. Validates the DEMO reference format and enters an exclusive
   `BEGIN IMMEDIATE` transaction
2. Verifies the complete existing grant/audit chain and the pinned
   local synthetic case-history seed fingerprint
3. Confirms the immutable record engine is exactly `DOMESTIC`,
   the signed role includes `household` and the exact immutable
   `owner_subject` matches the verified subject
4. Reads only the saved `case_history` versions for this case,
   verifies the exact expected fixture history and current version,
   and returns minimal values `version_numbers`, `versions`
   (`version`, `is_current`, `status=DRAFT_ONLY`),
   `history_source=PRESEEDED_IMMUTABLE_FIXTURES`, and invariant
   `purpose_consent_verified=false`, `expert_approved=false`,
   `plan_accepted=false`, `real_data=false`
5. Appends one `READ_ALLOWED` or `READ_DENIED` event with
   `HOUSEHOLD_VERSION_HISTORY` to the existing hash-linked audit
   inside **that same transaction**; failure to append rolls back
   the whole read

For a record with an invalid ref, missing fixture, Export engine,
other owner, or only staff/admin role, no version history is exposed.
Known-but-unowned refs are audited as denied; nonexistent refs
cannot create a foreign-case audit entry. Returned JSON never
includes the owner's identity, staff grants, source references,
expert review/private evidence, dates, reason or global counts.

The opt-in read-only API is:

`GET /api/v1/domestic/household-intake/my-drafts/{ref}/versions`

It is mounted only when the existing explicit
`SqliteSyntheticGrantLedger` is injected with `KeycloakConfig`.
The owner-only HTML version route further requires the opted-in
browser flow and an active verified session. Missing/bad identity
returns HTTP 401, unknown/unowned/wrong-domain versions return
indistinguishable 404, and tampered history, inconsistent seed or
audit-write failure returns sanitized 503 without partial version
disclosure. Strict CSP, no-store, HTML escaping and no HTTP POST/PUT
or mutation are preserved. Logout invalidates subsequent HTML access.

The client receives no JWT and can never select the owner from a
query/posted field. Staff grant revocation does not change the
household's separate immutable owner identity. Concurrent revoke and
owned version read serialize against one SQLite transaction.

## Tests, boundaries and next core product areas

12 additional cases in
`backend/tests/test_owned_household_drafts.py` cover owner-only
version visibility, exact missing/gap fixture numbers, persistence
after reopen, role/cross-household and Export isolation, invalid
token/reference, read audit rollback, corrupted version history,
HTML navigation/CSP/no-store, session logout, default-off/no POST,
and concurrent operator grant revocation. An existing technical
detail route test is also amended to distinguish its independent
link from the new version-history URL. Both existing and added
tests are run on the entire exact-HEAD GitHub CI.

**No real intake or corrections are enabled**: legal consent fields,
region, crops, authorized agronomist, plan generation/review,
scientific criteria, real identity, real PII storage, retention,
trading, payments and production database remain beyond this slice.
Business Gate #2 Domestic, #3 Export, and #4 Finance remain OPEN.
PR #1/#9 remain Draft/Open/Unmerged; Stage/QA/Release/Production
must not run without explicit authorization.

Further feature prioritization should focus on the main Domestic
case user journey and independently bounded Export research
workspaces, **not** additional gate-evidence plumbing unless it
actually blocks a chosen admitted Business slice.
