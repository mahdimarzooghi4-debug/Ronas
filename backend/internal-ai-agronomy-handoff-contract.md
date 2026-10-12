# Ronas — Internal AI proposal → assigned specialist read-only handoff (LOCAL/TEST)

**Status:** explicitly opt-in, synthetic, read-only handoff rehearsal in Draft PR #9.
This is neither an actual scientific cultivation programme nor the owner-approved
CORE-D1 workflow, actual model inference, live household intake/consent, qualified
expert review, approved stage scheduling or technical/Business gate admission.
Business RON-DEC-015..021 and RON-DEC-033 remain controlling.

## Direct user value — same shared agronomy user workspace

An existing assigned `agronomy_expert` can now open their assigned Domestic DEMO
case `/agronomy/assigned-drafts/{ref}`, then select the additional
`/agronomy/assigned-drafts/{ref}/internal-plan-proposal` Persian view.
The matching GET-only API is
`/api/v1/agronomy/assigned-drafts/{ref}/internal-plan-proposal`.

**With no explicitly supplied proposal fixture (normal default):**
- Only the existing verified assigned-case snapshot is shown, with its existing
  `null` cultivation inputs and observed technical-review state.
- The proposal status is `NO_INTERNAL_PROPOSAL_FIXTURE`, plan state
  `NOT_AUTHORED`, and all specialist approval/advice/real-data flags false.
- No AI call is made, no programme or stage is generated, and no placeholder
  is interpreted as real household information.

**With a deliberately injected LOCAL/TEST proposal envelope (tests only):**
- `SyntheticAgronomyWorkspace` validates the fixture against an existing,
  exact-version DOMESTIC case in the *same verified SQL ledger* and rejects
  duplicate references or non-envelope payloads.
- A **separately injected input snapshot authority** must provide a version
  and SHA256-shaped digest; comparing the proposal digest against itself is
  explicitly forbidden. If the shared ledger is the schema-driven household
  profile ledger, the workspace reads its current profile revision and digest
  inside the same verified case transaction. Profile corrections or a changed
  field schema immediately make a pinned proposal unavailable to the specialist.
  Actual household inputs/consent are not available in this LOCAL/TEST adapter
  and are not inferred by that separate callback.
- Each read re-checks signed `agronomy_expert` role **and** current
  per-case specialist assignment. In one SQL transaction, the ledger
  verifies audit/case/version history, reads only that exact assigned case,
  checks the independent input snapshot revision/digest against the proposal,
  and appends a new auditable READ_ALLOWED/READ_DENIED event.
- Stale/corrected input version, missing snapshot, bad digest, revoked assignment
  or corrupted ledger fail closed (404 unauthorized; 503 authority/integrity
  unavailable). No partially disclosed structural stages on error.
- The assigned specialist sees ONLY the synthetic stage reference names and
  `STRUCTURE_ONLY_UNREVIEWED`, not the internal-run identifier, model artifact
  digest, scientific digest, household identity, input source, technical
  reviewer identities, actual plan content or instructions. An observed
  `TECH_HUMAN_RESPONSE_RECORDED` **never** becomes a cultivation-plan
  specialist decision.
- Neither the HTML nor API exposes POST/PATCH/PUT/DELETE for review/approval,
  upload, publication or stage activation; BFF session expiry/log-out and
  Cache-Control no-store / frame CSP continue to apply.

This connects a **structural internal AI proposal** to the existing independent
case-granted agronomy space while making the difference between structure and
scientific/Business approval unambiguous. A synthetic fixture name
`RONAS_INTERNAL_AI` is not proof a model ran, and a checksum-shaped field is
not proof of sources, model artifacts or licence rights.

## Existing architecture; no fake cross-domain joins

- `backend/ronas_api/internal_cultivation_plan_contract.py`: validated
  immutable internal AI structural proposal, source/model/input digests,
  arbitrary versioned stage refs; remains OFFLINE and unapproved.
- `backend/ronas_api/agronomy_workspace.py`: optional fixture and separate
  input-snapshot authority, current assignment, immutable ledger verification
  and auditable projection.
- `backend/ronas_api/agronomy_workspace_api.py`: signed GET only, 404/503.
- `backend/ronas_api/ui_bff.py`: one Persian RTL review-preparation page,
  inside the original user/partner environment (no extra panel).
- `backend/tests/test_agronomy_workspace.py`: nine new synthetic signed
  Keycloak tests for missing source, successfully bound unreviewed fixture,
  strict role/grant/isolation, immediate revoke, cross-engine rejection,
  input correction / mismatch, independent authority outage, session/token
  invalidation, Persian navigation, and no writes.

**Remaining actual blockers (internal-work-first):** consented household
intake producer; scientific knowledge library and source rights; independently
attested local model generation; qualified Ronas in-house expert authority,
real explicit approval/rejection history; stage-specific report schedule sourced
from accepted program only. These are Ronas-owned implementation/evidence
responsibilities, not a request to select outside implementation vendors.
Legal obligations, rights/consent and true scientific qualification remain
non-negotiable even when handled in-house.

Business Gate Domestic #2, Export #3, Finance #4 OPEN. Business PR #1
and development PR #9 remain Draft/Open/Unmerged; no Stage, QA Gate, Ready
for Review, Release Approval, merge or Production.
