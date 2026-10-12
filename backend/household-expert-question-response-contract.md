# Ronas — owner-origin synthetic answer receipt to expert evidence question

**Contract:** `ronas.domestic.synthetic-household-question-response.v0`, LOCAL/TEST only. **Not real informed consent, personal-data input, agronomic adequacy, scientific source rights, a qualified expert decision, model training or plan authorization.** Based on RON-DEC-017..021/033 and Business D1-REV-03 candidate in Draft PR #1.

## What is permitted in the sandbox

**Only the signed exact household owner** may attach a **synthetic reference-only answer** to the *latest* `HOUSEHOLD_INPUT_ADEQUACY` question of its own DOMESTIC case. No answer to `SCIENTIFIC_BASIS_AND_USE_RIGHTS` or `INDIVIDUAL_CULTIVATION_PROPOSAL` is possible through this owner route. Those domains need real, independently qualified source/reviewer authority in a future approved contract.

The deliberately opt-in `SqliteSyntheticExpertQuestionLedger` (same SQL database and audit verifier as owner-case inputs and expert questions) exposes:

- `GET /api/v1/domestic/household-intake/my-drafts/{ref}/question-responses`: **owner-only** read with synthetic question number, versioned input reference, missing/received status, and DEMO answer/evidence refs. No scientific/personal data bytes or source/plan content.
- `POST /api/v1/domestic/household-intake/my-drafts/{ref}/question-responses`: **signed Keycloak Bearer-only**, never ambient browser-cookie authorization. Exactly seven keys: `action_id`, `track`, `expected_question_revision`, `expected_case_version`, `expected_input_revision`, `answer_ref`, `evidence_ref`. All refs must be valid `DEMO-` identifiers; no actual answer text, consent, real household fields, or approval key.
- `GET /my-drafts/{ref}/question-responses`: Persian RTL owner-only read-only history, linked from the original household input revision page. No submit/approval form.
- On the **currently assigned** specialist's existing `GET /api/v1/agronomy/assigned-drafts/{ref}/review-questions` and Persian history, only the fact `synthetic_household_response_received` crosses over; the actual private owner answer/evidence refs never do. Receipt never means qualified review.

No new panel or status transition appears. The existing default application and other ledger configurations have **no** new response API.

## Bound version and non-approval invariants

1. The exact original question **receipt**, case version, DOMESTIC input-adequacy track, question revision and **persisted owner-input version/digest** are pinned in an immutable response row. The original owner's input was already recorded **before** its expert question and verified by the question ledger; the response comes after the question event. The same SQL transaction verifies the complete audit history before accepting the answer.
2. Only the latest still-current question and matching latest owner input can be answered. A household correction or new question makes the *old* question response **ineligible for new processing**; already-recorded responses remain visible as immutable history. A scientific-source change does not turn an input-answer receipt into a plan decision. Future advisory/plan checks still require a *separately current* source/rights/AI/qualified-expert validation.
3. A question receives at most one response; the exact same action and fully bound contents may replay idempotently. A changed action/ref, older expected version or conflicting answer returns 409. Concurrent distinct responses yield one success. No auto re-answer or edit after a changed question.
4. DB no-update/no-delete triggers, paired `SYNTHETIC_HOUSEHOLD_QUESTION_RESPONSE_RECORDED` event and response receipt verify: exact input and question lineage, sequential audit placement, owner digest, case/version, action, answer ref, receipt SHA-256, and event kind/mode. Forged extra events, edited rows, failed audit insertion and broken restart fail closed. The local SHA audit chain is **not independently externally anchored** and does not claim protection against privileged rewrite of all anchors.
5. The only success state is `SYNTHETIC_RESPONSE_RECEIVED_NOT_REVIEWED`. Every consent, adequacy, scientific-rights, expert human decision, program acceptance, new advice and real-data flag stays **false**. GET historical status is `HISTORICAL_RESPONSE_ONLY_NOT_REVIEWED`, not pass/fail/accept.

**Failure semantics:** invalid actor/owner/other engine 404; missing/bad JWT or no Bearer 401; stale/missing question or input, duplicate/conflicting reply 409; non-DEMO values, wrong track or unknown approval/data keys 422; corrupt or unavailable ledger 503. No raw evidence bytes, source digests, actor hashes or stack traces in HTTP replies.

**Tests:** `backend/tests/test_expert_review_questions_sqlite.py` checks signed role + ownership isolation, mismatch/replay/race, ref-only payload, question and input correction, both scopes separate, audited append-only persistence/restart, tamper/orphan/rollback, Persian owner and expert histories, logout, hidden default route and no promotion.

**Real prerequisites:** actual legally appropriate purpose-specific notice/consent, real data schema/provenance, withdrawal/retention and independent qualified in-house agronomy decisions, science use rights distinct from Training, and Business/Technical admission. Business #2 Domestic, #3 Export and #4 Finance OPEN; PR #1/#9 Draft/Open/Unmerged. No Stage, QA Gate, Release or Production.
