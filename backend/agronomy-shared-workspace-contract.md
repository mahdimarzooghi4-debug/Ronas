# Ronas — Agronomy expert shared workspace / plan-preparation preview

**Status:** LOCAL/TEST synthetic, READ-ONLY, Draft PR #9. No real agricultural
service, cultivation advice, scientific approval, household intake/consent,
expert certification or real professional case assignment is enabled.

## Product and interface placement

This slice moves Ronas toward the Domestic core user journey without opening
a third UI environment. The existing shared user/partner shell contains
the `agronomy_expert` role and now optionally shows a case-specific
**synthetic agronomy** worklist and details:

- `GET /workspace/agronomy_expert` — signed shared-user role UI, only
  explicitly assigned DEMO Domestic cases with keyset navigation
- `GET /agronomy/assigned-drafts/{ref}` — Persian RTL synthetic case
  and plan-readiness preview, inside the same shared-user environment
- `GET /api/v1/agronomy/assigned-drafts` — read-only signed list
- `GET /api/v1/agronomy/assigned-drafts/{ref}` — read-only signed
  exact-case preview
- `GET /api/v1/me/user-workspaces/agronomy_expert` — advertises
  `ASSIGNED_SYNTHETIC_AGRONOMY_DRAFTS` ONLY if the opt-in capability
  was actually wired; no claim of active real services

No separate advisor/expert panel, source data entry, cultivation plan
create/publish/accept endpoint, chat, crop recommendation or third
environment is introduced.

## Role, assignment and identity boundaries

The existing `ScopedGrant` supports only `domestic_ops` or
`export_ops`. It is **not** a professional agronomy permission
and must never be reinterpreted as one. To avoid this escalation,
`SyntheticAgronomyWorkspace` requires:

1. **Explicitly injected** `SqliteSyntheticHumanReviewLedger`
   that is the IDENTICAL object provided as both
   `scoped_registry` and `technical_review_ledger` to the
   Keycloak-configured app with a signed browser flow
2. An explicitly seeded `SyntheticAgronomyAssignment` with a valid
   synthetic expert subject, exact `DOMESTIC` case reference and
   exact existing immutable case version. Export or stale version
   assignments fail at construction
3. A Keycloak-verified `Principal` containing the exact
   `agronomy_expert` role and the SAME synthetic actor subject as
   the assignment. Signed `domestic_ops` alone does not grant access,
   nor does a signed but unassigned `agronomy_expert`
4. A separately injected `trusted_assignment_active(subject,ref,version)`
   checker that must return the literal boolean `True` on **every
   read**, otherwise deny or fail closed. It is only a LOCAL/TEST
   revocation/assignment-authority stub, **not** certification,
   licensing or a real durable appointment service

This stage does NOT design a permanent professional registry,
assignment issuance/revocation API, entitlement policy, signature
protocol, real expert-identity verification or case consent policy.
The in-process checker is not a cross-system atomic guarantee;
a real authorization service and persistence need explicit contracts
later. Direct Python callers must only pass previously verified
Principals; these ledger helpers do not themselves parse JWTs.

## Minimal information and non-approval guarantees

The authorized expert can read only the *fixture's* immutable case
reference, current and actually persisted seed version(s), original
`DRAFT_ONLY` status, and redacted technical review stage/revision.
Input placeholders are explicitly `null` for:

- Crop (`crop`)
- Growing area (`growing_area`)
- Water (`water`)
- Soil (`soil`)
- Location (`location`)

The fixture uses `plan_state=NOT_AUTHORED` strictly as a descriptive
synthetic UI label, never as proof that a real cultivation plan has
been evaluated or is ready. All booleans remain `false`:
`agronomist_qualification_verified`,
`purpose_consent_verified`, `scientific_review_approved`,
`plan_accepted`, `real_data`, `business_actions_enabled`.
No household subject, owner, domestic operations grant, evidence
reference, technical reviewer/decision reference, precise geography,
model-generated advice or user-entered field data is disclosed.
A technical human response never means agronomic approval.

## Consistency, audit and access failures

Within the same LOCAL SQLite `BEGIN IMMEDIATE`, the workspace
re-verifies the underlying complete case/grant/review audit and the
immutable seeded version set, checks the exact signed role and the
current explicit assignment, reads only permitted redacted stages,
and appends `READ_ALLOWED` or `READ_DENIED` to the **existing**
append-only audit chain for exact known cases. The worklist appends
audits only for disclosed, assigned cases. Any audit-write failure,
corrupt history or assignment-authority failure returns sanitized
503 without partial disclosure. Unknown, unassigned, wrong-engine
or wrong-role exact cases all return 404; invalid signed identity
or logged-out browser session returns 401. No POST mutation route.
The existing browser CSP, HTML escaping and `Cache-Control: no-store`
apply.

Unlike a permanent database-backed revocation, the checker in this
LOCAL/TEST slice is deliberately injected; tests toggle it between
requests to demonstrate fail-closed **current** enforcement. No
claim of durable multi-replica synchronization or real credentials.

## Tests, gates and next actions

`backend/tests/test_agronomy_workspace.py` has **18 focused synthetic
regressions**, including exact role+case assignment, zero unknown
crop/area/water/soil/location, wrong domain/user, signed token
validity, live assignment revocation, failed authority, grant
independence from Domestic Operations, historical review with no
cultivation approval, exact keyset paging, audited denied/allowed
reads, audit-insert rollback, corrupted historical data 503, signed
RTL UI/CSP/logout, default-off and mismatch rejection, read-only
POST rejection, role-metadata capability flags and UI-link
revocation.

The Domestic consent, actual input schemas, professional
qualification source and approval policy, scientific/cultivation
plan requirements, lawful use and privacy/retention terms remain
**undecided and not implemented**. No hard-coded crop/soil/water
suitability threshold or AI-generated planting plan may be inferred.

Business #2 Domestic / #3 Export / #4 Finance gates remain OPEN.
PR #1 and #9 remain Draft/Open/Unmerged. No Stage, QA Gate,
Release, Production or Merge without explicit authorization.

## Observed technical-state queue filters (LOCAL/TEST, 2026-10-11)

The existing single shared-user agronomy worklist now supports **only**
`technical_state=ALL|UNREQUESTED|EVIDENCE_REVIEW_REQUESTED|HUMAN_RESPONSE_RECORDED`
on `GET /api/v1/agronomy/assigned-drafts` and
`GET /workspace/agronomy_expert`. The default remains `ALL`.

- State comes exclusively from the verified, persisted technical-review
  steps of the *same* synthetic Domestic case used in its detail timeline,
  never predicted or inferred from household inputs.
- The signed `agronomy_expert` role, exact-case/version synthetic assignment
  and literal-true **current** assignment check apply **before** filtering
  and keyset pagination. The response discloses no counts of hidden cases.
- `after_ref` is a synthetic ref cursor over the filtered authorized
  sequence, with `limit` bounded to 1..50; changing a filter starts a new
  page. The Persian RTL links preserve the active filter on next-page
  navigation and never expose private review source/evidence/actor refs.
- Invalid filters/cursors return 422; ledger integrity/current authority
  failure returns 503 without a partial queue. An unassigned or revoked
  case disappears on the next request, including under a still-valid JWT.
- The list and links are **GET-only**, use the existing Keycloak/cookie
  boundaries and append-only read-audit, and remain default-off unless the
  synthetic workspace is explicitly injected.

`HUMAN_RESPONSE_RECORDED` means only that a technical reference was
recorded. It does **not** establish professional qualifications, verified
consent, scientific approval, cultivation readiness or a planting plan.
The fixture crop/area/water/soil/location are still `null`; no form,
write command, trade, real case or new UI environment was added.

Regression suite: `backend/tests/test_agronomy_workspace.py` (six new
filter/lifecycle/pagination/revocation/UI/fail-closed cases). The earlier
security boundaries, Business OPEN gates and Draft PR state are unchanged.

