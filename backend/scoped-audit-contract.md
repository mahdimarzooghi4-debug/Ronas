# Ronas — Synthetic case revision, audited reads and scoped-grant revocation

**Status:** opt-in Technical/test-only foundation, 2026-10-10. No actual
customer consent, authorized reviewer/record owner, live case grant source,
security audit provider or operational storage has been configured. Business
Domestic #2, Export #3 and Finance #4 remain OPEN.

## Preserve the two independent engines and their ownership

Domestic household role + exact signed subject remains the only owner-read
path. Domestic and Export operations must have BOTH the specific Keycloak
client role AND explicit grant for the exact record/subject. Roles from a
single admin shell are not an override. Historical D1-A / E0-A samples remain
synthetic and cannot become accepted cultivation plans, approved research,
buyers, orders or payments.

[scoped_audit.py](ronas_api/scoped_audit.py) adds the optional
AuditedSyntheticDraftRegistry subclass of ScopedSyntheticDraftRegistry. It
retains the existing public read routes and only changes access decisions when
an explicit audited registry is injected into create_app. The default runtime
does not inject one or mount these record-scoped endpoints.

### Technical case revision history — no fabricated edits

Earlier immutable ScopedDraft versions must be explicitly supplied when the
registry is constructed; they must share the exact record identity and owner,
be distinct and older than the current immutable snapshot. The history API
case_versions(engine, ref) only returns version numbers for these
pre-seeded synthetic snapshots. It does NOT record newly submitted household
facts, modify research, create real consent, infer missing versions or expose
old sensitive material. An API to edit historical drafts does not exist.

### Audit events — local verification, not regulatory audit proof

Every read of an existing synthetic record under a syntactically valid
synthetic signed subject is logged as READ_ALLOWED or READ_DENIED. Its event
stores sequence, engine, synthetic record ref, current case version,
technical grant revision, access mode and **SHA-256 pseudonym digest of actor
identifier** instead of the raw subject. Actor digests are not anonymous and
must NOT be used for real personal information. A successful revocation adds
GRANT_REVOKED, associated action ID, synthetic reason reference and digest
of the revoked grantee. No JWT, consent text, free text, real address,
owner metadata or actual rights are included.

Each event links the preceding digest. verify_local_chain detects accidental
in-process corruption and ordering errors. **This is NOT a signed, anchored,
tamper-proof, independently durable, audit-grade or multi-replica journal**:
it exists only in process memory. Authentication failures, invalid synthetic
refs and nonexistent cases are not guaranteed to create audit events.
No HTTP audit-export path exists. Retention/deletion and regulated audit
policies remain deliberately undecided.

### Revocation — explicit internal authority, serialized and fail closed

revoke_grant is an **internal Python command, not an HTTP route**. It demands
an injected independent trusted_revoke_authorizer callback: neither
"governance" nor "domestic_ops"/"export_ops" role is itself sufficient.
The test-only callback is a fixed synthetic fixture; it does not define who
has legal authority to revoke production assignments.

The command binds exact engine/record/subject/role, expected technical
grant revision, unique synthetic action ID, synthetic reason reference
and synthetic actor. It only revokes a PRE-SEEDED currently active operations
grant. There is no grant creation/reinstatement, owner removal, transfer,
cross-engine use or live data mutation. A repeated identical action is
idempotent, and conflicting replay or stale version fails closed. A
process-local lock serializes reads, revocations and audit acceptance; after
revocation, even a still-valid signed Keycloak JWT cannot read that case.
Other assignees and the household owner retain their independent scopes.

Revocation and journal append are one logical acceptance step within
a single process; a failed audit append rolls back the tentative revocation
and grant-revision change. This code is **not a distributed CAS transaction**,
not a persistent workflow and not an independent human maker/checker.

## Verification

[tests/test_scoped_audit.py](tests/test_scoped_audit.py) exercises
version lineage, exact-case isolation, independent authorization,
replay idempotency and conflict, cross-engine denial, old JWT rejection,
concurrent same/different revocation requests, audit ordering/hash
verification, post-revocation access, denied access auditing, append-error
rollback, and absence of write/audit APIs.

Run the existing CI suite:
- PYTHONPATH=backend python -m unittest discover -s backend/tests -v
- python -m unittest discover -s prototype/tests -v
- node --test prototype/tests/test_demo_model.mjs

These tests use in-process, synthetic records and ephemeral signing keys.
No real user, service credentials, server purchase or Stage deployment is
required or implied.

## Still required before any real data

Independent approval of authoritative record ownership, actual role/grant
assignment and *revocation decision maker*, persistent transaction/audit
store, audited write lineage, secure pseudonymization, evidence preservation
and lawful retention/erasure, cross-replica synchronization, actual Keycloak
revocation, personal-data consent, verified expert and Export source rights,
and a documented Technical/Business Gate. No such policy has been invented.
Draft PR #9 remains unmerged; no Stage/QA/release/Production.
