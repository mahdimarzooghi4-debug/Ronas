# Ronas — durable internal specialist evidence questions, not decisions (LOCAL/TEST)

**Status: opt-in LOCAL/TEST ONLY, D1-REV-02 review foundation, NOT real professional review or approval.** Based on RON-DEC-015..021/033, plus nonapproved Business D1-REV-01, D1-SCI-01. No real household, consent, source knowledge/rights, agronomy advice, qualified staff certificate, AI training, programme approval or Production.

## New scoped capability

`SqliteSyntheticExpertQuestionLedger` extends the **same verified, local SQLite case/input/technical-audit ledger**; it does not create a parallel identity store. The new table `expert_review_question` holds an immutable **question about missing evidence** in one of the three existing tracks:

- `HOUSEHOLD_INPUT_ADEQUACY`
- `SCIENTIFIC_BASIS_AND_USE_RIGHTS`
- `INDIVIDUAL_CULTIVATION_PROPOSAL`

Each question requires an explicit DEMO action ID, separate DEMO reason/evidence refs (not free-form personal or scientific content), current DOMESTIC case/version, **exact latest household-owned input revision/digest**, and the exact synthetic proposal/scientific-basis fingerprints. The actor's signed Keycloak `agronomy_expert` role and **current case-specific assignment** are rechecked on each write, in the same serialized SQLite transaction, along with current science-source/rights lineage if a pinned science basis was explicitly configured.

**Opt-in only:** the API routes appear only if the exact same `SqliteSyntheticExpertQuestionLedger` instance is explicitly mounted as scoped case ledger, human-review ledger, and assigned agronomy workspace. Default installations and the ordinary `SqliteSyntheticHouseholdInputLedger` expose no question writer.

- `POST /api/v1/agronomy/assigned-drafts/{ref}/review-questions`: explicit **signed Bearer token only**; ambient browser cookie does **not** authorize mutation. Strict keys: `action_id`, `track`, `expected_case_version`, `expected_input_revision`, `expected_question_revision`, `reason_ref`, `evidence_ref`. No `decision`, `approve`, legal consent, user input data, crop, scientific instruction, note body, or actual evidence bytes may be posted. Returns `SYNTHETIC_QUESTION_ONLY_NOT_REVIEWED`, never acceptance.
- `GET /api/v1/agronomy/assigned-drafts/{ref}/review-questions`: current signed, assigned expert only; immutable history with question track, revision, bound input version and synthetic reason/evidence refs; flags all false.
- `GET /agronomy/assigned-drafts/{ref}/review-questions`: read-only Persian RTL history linked from existing three-track case page; browser session validity and live case assignment checked. No submission form, approval or science content.

## Concurrency and audit

The table has DB no-update/no-delete triggers, deterministic **per-case-and-track** receipt chain, exact compare-and-swap revision, replay of the same fully bound action, conflict on changed action/reason/input or older revision. Each inserted question creates **one distinct** `SYNTHETIC_EXPERT_REVIEW_QUESTION_RECORDED` event in the existing audit chain and in the same SQLite transaction. Base/default ledgers reject that event kind; this subclass verifies **both** event-kind and reserved-mode pairing, case/version, actor hash, action, reason, receipt, prior receipt, and the **earlier persisted household input manifest revision**. Orphaned events, edited history, forged receipts, missing inputs and interrupted audit writes fail closed; committed input edits never delete old questions.

All errors are sanitized: unauthorized case/role/assignment 404; invalid JWT/session 401; stale case/input/proposal/rights, replay conflict, or changed question CAS 409; invalid DEMO body/unknown keys 422; corrupted or unavailable ledger 503. **Never claim a local hash chain alone resists a privileged rewrite of all anchors. SQLite is not a chosen Production database.** If the referenced input/source later changes, the previous question remains visible only as **historical, not an approved decision or currently applicable review**; writing another question requires a newly pinned proposal matching the current source/input.

**No promotion path:** `review_outcome=NOT_REVIEWED`, `plan_approved=false`, `science_rights_approved=false`, `data_adequacy_approved=false`, `professional_qualification_verified=false`. No expert decision/approval command, no new agricultural advice or supervision stages, no actual AI and no business state mutation.

## What still requires approved real contracts

Purpose-specific informed consent/withdrawal, exact minimal household schema, genuine identifiable evidence and retention/rights, verified qualified Ronas internal specialist for each authority/scope, independent legal source-use and agronomic correctness reviews, internal AI provenance, precise case-specific approve/modify/reject with reasons and versioned human review, independent QA and Business Gate #2. These are still subject to Business Draft PR #1 and must not be inferred from this synthetic reference implementation. Gates Domestic #2 / Export #3 / Finance #4 OPEN; PR #1 and PR #9 Draft/Open/Unmerged; no Ready for Review, merge, Stage, QA, Release or Production.
