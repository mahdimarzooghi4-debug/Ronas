# Ronas — LOCAL/TEST Household Input Manifest Revisions (no real consent)

**Status:** synthetic, opt-in contract experiment only; **not** actual household
data intake, a real consent service, an approved D1 operational schema, or
production capability. The Business Gate #2/Technical admission remain OPEN.

## Purpose and boundaries

RON-DEC-017..021 define household-supplied informed-consent data, ability to
correct it, AI gap suggestions, expert verification, plan revision, and
preservation of history. RON-DEC-033 assigns creation of this service to
Ronas's own team; it does **not** give permission to invent obligatory
crop/soil/water/area/location fields, consent text, evidence rules or scientific
thresholds. To preserve useful implementation progress **without** inventing
those missing contracts, the present slice accepts **only a synthetic
SHA-256-shaped manifest digest** and a `DEMO-` action identifier; it never
receives a crop, soil/water, real household identifier, scientific instruction,
identity, image, or statement of legal consent. Digest format alone is
*not* proof of a real content snapshot, source rights, model readiness or
informed consent. Do not pass real data into this local test interface.

## Implementation — existing local verified ledger, not parallel storage

`SqliteSyntheticHouseholdInputLedger` extends the **same**
`SqliteSyntheticHumanReviewLedger` used for immutable case/grant history.
It adds only the `household_input_revision` append-only table and its
associated, digest-bound auditable events. The case version is pinned to an
immutable DOMESTIC catalogue record, role must be signed `household`, and the
subject must exactly own the requested case. Export, staff, buyers,
other households and unassigned actors cannot view or modify the record.

Command:
`POST /api/v1/domestic/household-intake/my-drafts/{ref}/input-revisions`
with signed Keycloak **Bearer** (ambient BFF cookie is deliberately forbidden
for this mutation). Accepted JSON keys are only:
`action_id`, `expected_case_version`, `expected_input_revision`,
`synthetic_manifest_digest`. No extra fields accepted. Each successful
command requires the exact current revision (compare-and-swap, revision
starting at zero), creates an immutable new revision and an audit event within
one SQLite `BEGIN IMMEDIATE` transaction, and returns revision metadata.
Repeated identical action/payload returns its same revision idempotently;
conflicting replay, stale case or revision, unchanged digest => 409.

Query:
`GET /api/v1/domestic/household-intake/my-drafts/{ref}/input-revisions`
and Persian RTL owner view `GET /my-drafts/{ref}/input-revisions`, linked from
the existing household case. These **never return digests, audit actor,
household personal information, consent wording or source secrets**; only
owned revision numbers and explicit absence of consent/science/plan approvals.
A missing or unowned case => indistinguishable 404, invalid JWT/cookie => 401,
invalid payload => 422, corrupted/unavailable private ledger => sanitized 503.

`internal_input_snapshot(ref,version)` is an **internal-only** locally verified
source of the current DEMO revision and manifest hash; no public API exposes
it. A later, separately approved internal AI proposal builder may use an
authoritative input snapshot adapter instead of trusting a proposal's own
digest. Its output still cannot approve any programme or source consent.
No new model, training data, AI suggestion, specialist qualification or
scientific plan is created here.

## Integrity and concurrency

- Exact case/version/owner binding, strictly increasing per-case revisions,
  an explicit previous receipt digest and per-action SHA-256 receipt.
- Append-only DB triggers on input rows, cross-check each persisted row to
  the existing tamper-evident audit chain, and reject missing/orphaned or
  modified metadata. The local ledger is **not independently anchored**,
  therefore it does not claim protection against a privileged attacker who
  can rewrite the entire store and all audit anchors.
- A single serialized transaction covers validation, CAS, idempotency, audit,
  and persistence. Concurrent requests for the same expected revision result
  in one success and one conflict.
- All input/consent/scientific approval flags explicitly false; no new advice
  or cultivation-stage activation, even after many synthetic revisions.

The feature requires **explicit** Keycloak Browser + a single injected
`SqliteSyntheticHouseholdInputLedger` as both the scoped case repository
and technical review ledger. Default runtime lacks this feature and the
browser never supplies a real intake/consent submission form. SQLite is
development/test only and must not be selected as Production architecture.
Owner workspaces remain within the first of Ronas's two interface shells.

**Next genuine prerequisite:** separately defined, legally valid and
purpose-specific household consent; versioned allowed real field schema;
exact correction/withdrawal rights and data retention; qualified Ronas
internal specialist evidence; approved technical admission and a real
DB-backed, source-rights-auditable implementation.

**Gates:** Domestic #2, Export #3, Finance #4 OPEN. Both PR #1 and PR #9
remain Draft/Open/Unmerged. No Stage, QA/Release, Ready for Review,
Production or commercial activity authorized.
