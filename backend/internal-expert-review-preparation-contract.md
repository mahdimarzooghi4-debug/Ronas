# Ronas — assigned specialist three-track preparation dossier (LOCAL/TEST)

**Status:** Opt-in synthetic read-only in Draft development PR #9; no admitted Domestic D1 operational scope, qualified expert, valid household consent, science-use rights, model execution, programme review, or human approval.

**Business authority unchanged:** RON-DEC-015..021 and 033 require household-origin informed input, separate validation of adequacy, legally usable and scientifically reviewed Ronas-owned source knowledge, internal AI-proposed tailored programme, and genuinely qualified in-house specialist explicit acceptance/modification/rejection of the **individual programme**. No software role, synthetic document or existing `TECH_HUMAN_RESPONSE_RECORDED` technical evidence event is equivalent to these human decisions. Domestic Business Gate #2 remains OPEN.

## One expert workspace, three non-interchangeable checks

GET-only `/api/v1/agronomy/assigned-drafts/{ref}/expert-review-preparation` and Persian RTL `/agronomy/assigned-drafts/{ref}/expert-review-preparation` are linked from the **same** assigned agronomy case in the shared Ronas user/partner shell.

Each authorised, case-exact read uses `SyntheticAgronomyWorkspace.read_assigned_proposal_structure` **once** under its same verified SQL transaction and auditable `READ_ALLOWED` event. Signed `agronomy_expert` + current explicit case assignment are required. A missing/stale household-input revision or a missing/changed independent science-source/rights/review snapshot returns sanitized 503 with no partial dossier disclosure. Wrong actor/case/engine or revoked assignment yields 404; invalid token/cookie 401.

The pure, strict `internal_expert_review_preparation.project_expert_review_preparation` projection separates these **independent preparation tracks**:

1. `HOUSEHOLD_INPUT_ADEQUACY` — only structural input revision present/absent, never real data completeness, consent, or actual independent specialist validation. No required fields or thresholds invented.
2. `SCIENTIFIC_BASIS_AND_USE_RIGHTS` — only a current unverified scientific-basis pointer or unverified absence; lawful service use, lawful separate Training, content retrieval and actual scientific appropriateness remain false, regardless of matched SHA shape.
3. `INDIVIDUAL_CULTIVATION_PROPOSAL` — absent or structural unreviewed internal-AI fixture and count of synthetic stages (never stage content); real model attestation and separate explicit individual-plan approval remain false.

`technical_case_tracking` merely reflects the existing *technical evidence* record (`UNREQUESTED`, `EVIDENCE_REVIEW_REQUESTED`, `HUMAN_RESPONSE_RECORDED`). It **cannot** become data-adequacy review, scientific approval, or plan acceptance. Every track has `review_outcome=NOT_REVIEWED` and every capability/eligibility flag is false: no qualified identity, active programme, advice, stage activation, cross-purpose data sharing, marketplace or real household data.

### Security and testing

- Pure projection rejects forged `APPROVED` state, accidental real-data flag, case/contract mismatch, duplicate/untrusted stages, fake input readiness and scientific validity.
- Specialist API/UI fail closed and preserve role, exact live assignment, expiry/logout, redaction, no-store headers, frame CSP, and no POST/PATCH/PUT/DELETE commands.
- Source/rights revision invalidates entire dossier, not merely a science indicator; a household input correction invalidates the old dossier until a structurally matched new proposal exists; neither change rewrites any prior case, input or source history.
- Technical review history is never silently promoted to expert approval; the one read is audited once, not falsely represented as three independent human decisions.

**What remains truly missing:** Real household consent and minimum real input schema, true data-correction/withdrawal governance, independent source rights and scientific suitability checks, actual qualified Ronas expert credentials/appointment and decision reasons/lineage, actual internal AI inference/training rights, separately approved business scope/technical workflow, and production data-store choice. The team can create these components internally; no external implementation vendor is required, though real legal/scientific evidence is.

No operational expert-review state machine, approval mutation endpoint, payment or deployment is added. PR #1 and #9 stay Draft/Open/Unmerged; Domestic #2, Export #3 and Finance #4 OPEN; no Technical admission, Ready for Review, merge, Stage, QA Gate, Release or Production.
