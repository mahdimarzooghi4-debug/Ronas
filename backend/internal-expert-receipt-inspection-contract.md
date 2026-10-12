# Ronas — expert sighting of synthetic owner reply receipt (LOCAL/TEST)

**Status:** D1-REV-04 structural audit only in development Draft PR #9. **Not a real qualified professional assessment, consent, legal source permission, valid cultivation programme, scientific verification or Production feature.** Linked to Business Draft PR #1 [D1-REV-04 candidate](../docs/business/83-expert-receipt-inspection-versus-independent-review.md), still unapproved.

## Three independently recorded events, no hidden approval

1. An assigned `agronomy_expert` registers a question about **HOUSEHOLD_INPUT_ADEQUACY** with immutable DEMO refs and the exact already-versioned owner input, synthetic internal-AI proposal and science-source/rights fingerprints.
2. The verified **owner**, via signed Keycloak Bearer (not cookie), links a synthetic reply/evidence reference to that current question only. Only the owner sees its own reply/evidence references. The expert can see receipt *presence*.
3. The *same currently assigned specialist*, after revalidation of signed role, current assignment, case/input/proposal and optional independently supplied current scientific-source/rights lineage, can record only that the **reply receipt itself was seen**; the expert cannot assess or access response contents through this operation. It is not the answer evaluation.

`POST /api/v1/agronomy/assigned-drafts/{ref}/response-receipt-inspections` accepts only `action_id`, `expected_case_version`, `expected_input_revision`, and `expected_question_revision`; all values strict and the action a `DEMO-` ref. **Signed Bearer-only**. There is no `decision`, `approval`, `reviewed`, `sufficient`, note text, real household field, expert licence, source rights, Training permission or plan mutation.

## Audit and stale safety

The existing same SQLite audit/case/input/question/answer ledger adds one append-only `expert_response_receipt_inspection` row and **one** `SYNTHETIC_EXPERT_RESPONSE_RECEIPT_INSPECTED` audit event per accepted new operation in the **same transaction**. A canonical receipt binds:
- case, engine and version
- exact latest input-adequacy question revision and immutable **question receipt**
- immutable owner **reply receipt**, without disclosing owner reply/evidence references to the specialist
- exact persisted household input revision and digest
- synthetic unverified science-basis and proposal digests
- reviewer actor hash (software identity only), unique action ID, audit sequence and event linkage

Row and event pairing is verified at every ledger read/reopen (including kind OR reserved mode), as are original **input → question → answer → inspection** audit ordering, hash consistency, correct scope and no orphan event. SQLite no-update/no-delete triggers protect posted rows. Repeated identical action is idempotent, changed action and simultaneous different inspections return conflict; failed event write rolls back. Tampering with row/event fails closed; this **does not** claim cryptographic protection against privileged rewriting of all local database anchors.

New inspection is refused on stale input, superseded question, missing owner response, stale model/proposal, revised science-source rights or revoked specialist assignment. Historical inspect events are not deleted when the current context changes and never become an applicable decision. The existing expert question history API and Persian RTL page reveal only `synthetic_receipt_inspected_not_reviewed=true`/“رسید پاسخ مشاهده شد (بدون داوری تخصصی)”, with **no private owner reply or evidence identifiers**. The default app never mounts this opt-in POST.

**All consequential fields remain false:** legal informed consent, professional qualification, input adequacy, actual scientific content/rights, independent specialist decision, plan acceptance, new advice, Training and Production.

## Regression coverage and governance

`backend/tests/test_expert_review_questions_sqlite.py` covers question without response, successful and idempotent inspection, strictly signed Bearer and exact assignment, forbidden owner/other reviewer/Export, extra approval fields, concurrent conflict, stale input/newer question/source rights, durable restart, event/row tamper and orphan, failed audit rollback, and no source/owner response leakage in API/Persian RTL history. Existing contract checks ensure no real AI execution, finance, cultivation advice or accepted case state.

The real decision contract still requires lawful household data, verified consent and rights, actual independently qualified Ronas agronomist, scientific suitability, separate AI Training rights and explicit reasoned approval/modification/rejection of **the programme itself**. Domestic Gate #2, Export #3 and Finance #4 are OPEN; PR #1/#9 Draft/Open/Unmerged, no Ready for Review, Merge, Stage, QA Gate, Release or Production.
