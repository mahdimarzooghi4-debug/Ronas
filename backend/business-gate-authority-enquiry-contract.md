# Ronas — independent authority enquiry and response-reference ledger

**Status: LOCAL/TEST technical foundation only**, 2026-10-10, Draft PR #9.
The module does **not** integrate an actual authority for origin, legal
usage rights, consent, export sources, agronomist qualifications or
reviewer credentials; no human Business gate decision is implemented.

## Three independent technical enquiry channels

Each of the 19 pinned draft Business requirements may have three
separately versioned technical enquiries:

- `ORIGIN`: source/provenance authenticity enquiry
- `SOURCE_RIGHTS`: consent, source-use and license-rights enquiry
- `REVIEWER_QUALIFICATION`: independent human qualifications/mandate enquiry

The `SqliteSyntheticAuthorityEnquiryLedger` is **composed with the
identical already-injected** `SqliteSyntheticGateEvidenceHandoff` and
uses the same LOCAL/TEST private SQLite database transaction. An enquiry
references the **exact original** handoff `REFERENCE_RECORDED` action
and its SHA-256 event digest; a missing, changed, cross-domain or
unrecognized source fails closed. The enquiry has its own append-only
event table, guarded by UPDATE/DELETE triggers and a versioned SHA-256
event chain/head. On read, command, or reopen, verification checks both
the original handoff history and this full enquiry history, then checks
the pinned Business source files.

Two technical stages are possible per (domain, requirement ID, check
channel), each at most once:

1. `CHECK_REFERENCE_REQUESTED`: a synthetic domain-authorized maker
   records an action ID and `DEMO` enquiry request reference. Nothing
   is dispatched to an external provider.
2. `TECHNICAL_RESPONSE_REF_RECORDED`: a different synthetic reviewer
   with an **explicitly injected**
   `trusted_response_authorizer(actor, domain, evidence_id, check_kind)`
   records a `DEMO` technical response *reference* bound to that
   request. The authorizer is checked even on idempotent replay, so a
   newly revoked test authorization cannot be bypassed.

There is no result such as VERIFIED, ACCEPTED or PASS; response text is
never read or interpreted. This design does not assume any official
provider, reviewer-licence registry, provider credential, consent
policy, jurisdiction, threshold, acceptance rule or source-rights
definition. The development callback is **not** a real certification
authority. For real-world acceptance, owners must first agree the
necessary authoritative sources, evaluation contracts, lawful rights,
reviewer qualification/appointment authority, retention and privacy
rules, and explicit human governance.

## Idempotency, integrity and concurrency

Each command requires an already Keycloak-verified `Principal`
with its exact signed domain role and a synthetic subject; the Python
methods themselves do not parse signed tokens and must **not** be
called with user-constructed Principals. A command requires an allowed
source-domain requirement ID, one of the three check kinds, exactly
bound original `DEMO` source action, `DEMO` action/request/response
references and an exact expected revision. It never stores the actual
source bytes, rights determination, reviewer certificates or user
identity in the public read projection.

`BEGIN IMMEDIATE` serializes actions with the original handoff
ledger and reserves the audit-chain sequence in the same transaction.
Same action + same actor + same input may replay; any changed payload,
stale revision, duplicate action with altered input, same maker/checker,
missing independent reviewer authorization or an unsupported source
must fail closed. A failed insert rolls back the entire new event and
metadata update. Two concurrent identical requests are idempotent
against the same SQLite file. Since external authority integrations
are absent, no cross-system atomicity or live revocation freshness
outside that explicit callback is claimed.

This LOCAL/TEST hash chain is not an externally notarized audit,
cannot defend against a privileged operator rewriting all SQLite rows,
and is not a Production database choice.

## Explicitly opt-in read-only routes

The existing unified Keycloak admin shell may optionally receive the
**same exact handoff object** and the enquiry ledger as an explicit
additional injection. Only then it exposes:

`GET /api/v1/admin/gate-evidence/{domain}/authority-enquiries`

This signed role-scoped GET shows, for each pinned requirement and
check channel, only `NO_REQUEST`,
`CHECK_REFERENCE_REQUESTED` or `TECHNICAL_RESPONSE_REF_RECORDED`
and exact technical revision. The response always declares
`verification_state=NO_TRUSTED_EXTERNAL_AUTHORITY`,
`authority_verified=false`, `source_rights_verified=false`,
`reviewer_qualified=false`, `admission_allowed=false` and
`business_gate_passed=false`. It does not return original handoff
action, claimed SHA, any request/response reference, human actor
digest, provider content or private Business files. The corresponding
existing `/admin/gate-evidence/{domain}` page may show those safe
technical states and a Persian warning **inside the same one admin
environment**.

Invalid/missing identity gets 401, unknown or unassigned domain gets
404, corrupt original/enquiry history or pinned source drift gets a
sanitized 503. **No HTTP mutation endpoint** for request, response,
file upload, qualification, rights grant or Business approval is
mounted. The default app has no enquiry route or admin UI; opt-in
requires Keycloak browser support and a matching exact handoff object.

## Validation and gates

`backend/tests/test_gate_authority_enquiry.py` includes **18**
synthetic offline tests covering the three independent checks and
all 19 Business requirement slots, source-action binding, exact
authorization/role isolation, different maker/checker even under a
deliberately permissive callback, idempotent retries, revocation
check on replay, concurrent duplicate request, history corruption
and transactional rollback, signed read-only API, default-off and
miswired injection rejection, cookie logout, minimal admin display,
and no evidence/legal/Business PASS effect. Tests generate temporary
keys, synthetic references and a LOCAL SQLite database; no actual
provider, credential, consent or real source-rights checking occurs.

Gate #2 Domestic, #3 Export and #4 Finance remain OPEN in the pinned
Business source. PR #1 and #9 remain Draft/Open/Unmerged. Stage, QA,
Release, Production and Merge require future explicit permission and
real, separately authorized human evidence.
