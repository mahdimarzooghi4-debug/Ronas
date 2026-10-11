"""Current DEMO case next-step guidance; no authorization/approval state.

Consumes only data from separately permission-checked, audited domain reads.
Never enables a domain command: mutation endpoints recheck grant + CAS.
"""
from __future__ import annotations

from collections.abc import Mapping

class JourneyEvidenceMismatch(ValueError):
    """Impossible/mismatched local test read models; do not render guidance."""


def owner_next_action(input_data: Mapping, notes: Mapping | None) -> str:
    if (input_data.get("engine") != "DOMESTIC"
            or type(input_data.get("case_version")) is not int):
        raise JourneyEvidenceMismatch("invalid owner input projection")
    revision = input_data.get("current_input_revision")
    if type(revision) is not int or revision < 0:
        raise JourneyEvidenceMismatch("invalid input revision")
    if notes is not None:
        if (notes.get("engine") != "DOMESTIC"
                or notes.get("case_ref") != input_data.get("ref")
                or notes.get("case_version") != input_data["case_version"]
                or notes.get("real_data") is not False
                or notes.get("plan_accepted") is not False
                or not isinstance(notes.get("questions"), list)):
            raise JourneyEvidenceMismatch("owner case/question mismatch")
        current = [q for q in notes["questions"]
                   if q.get("is_current_input_version") is True]
        for q in current:
            if (type(q.get("question_revision")) is not int
                    or type(q.get("bound_input_revision")) is not int
                    or q["bound_input_revision"] != revision
                    or q.get("response_state") not in (
                        "MISSING_RESPONSE", "RESPONSE_RECORDED")):
                raise JourneyEvidenceMismatch("invalid current owner question")
        if current:
            last = max(current, key=lambda q: q["question_revision"])
            if last["response_state"] == "MISSING_RESPONSE":
                return "RESPOND_TO_EXPERT_QUESTION_DEMO"
            return "RESPONSE_RECORDED_WAIT_FOR_EXPERT_DEMO"
    return "PREPARE_OR_REVISE_INPUT_DEMO"


def expert_next_action(notes: Mapping, proposal: Mapping | None) -> str:
    if (notes.get("engine") != "DOMESTIC"
            or notes.get("qualification_verified") is not False
            or notes.get("plan_accepted") is not False
            or notes.get("real_data") is not False
            or not isinstance(notes.get("questions"), list)):
        raise JourneyEvidenceMismatch("invalid expert evidence")
    if proposal is None:
        return "SOURCE_OR_INPUT_CHANGED_HISTORY_ONLY"
    if (proposal.get("proposal_status") != "STRUCTURE_ONLY_UNREVIEWED"
            or proposal.get("case_ref") != notes.get("case_ref")
            or type(proposal.get("input_revision")) is not int
            or proposal["input_revision"] < 1):
        raise JourneyEvidenceMismatch("stale or inconsistent proposal")
    questions = [q for q in notes["questions"]
                 if q.get("track") == "HOUSEHOLD_INPUT_ADEQUACY"
                 and q.get("bound_input_revision") == proposal["input_revision"]]
    for q in questions:
        if (type(q.get("question_revision")) is not int
                or q["question_revision"] < 1
                or type(q.get("synthetic_household_response_received")) is not bool
                or type(q.get("synthetic_receipt_inspected_not_reviewed")) is not bool):
            raise JourneyEvidenceMismatch("invalid expert question")
    if questions:
        last = max(questions, key=lambda q: q["question_revision"])
        if last["synthetic_household_response_received"]:
            if not last["synthetic_receipt_inspected_not_reviewed"]:
                return "INSPECT_RESPONSE_RECEIPT_DEMO"
            return "RECEIPT_OBSERVED_NOT_REVIEWED"
        return "WAIT_FOR_HOUSEHOLD_RESPONSE_DEMO"
    return "REQUEST_MISSING_EVIDENCE_DEMO"


def export_next_action(data: Mapping) -> str:
    if (data.get("engine") != "EXPORT"
            or data.get("source_rights_verified") is not False
            or data.get("research_report_approved") is not False
            or data.get("buyer_verified") is not False
            or data.get("contracted") is not False
            or data.get("real_data") is not False):
        raise JourneyEvidenceMismatch("export state cannot authorize trade")
    question = data.get("local_test_draft_question")
    history = data.get("local_test_question_history")
    if not isinstance(history, list):
        raise JourneyEvidenceMismatch("missing question history")
    if question is None:
        if history:
            raise JourneyEvidenceMismatch("orphaned question history")
        return "DEFINE_INITIAL_RESEARCH_QUESTION_DEMO"
    if (question.get("engine") != "EXPORT"
            or question.get("case_ref") != data.get("ref")
            or type(question.get("question_revision")) is not int
            or question["question_revision"] < 1
            or question.get("research_report_approved") is not False
            or len(history) != question["question_revision"]
            or not history[-1].get("is_current")
            or history[-1].get("question_revision") != question["question_revision"]):
        raise JourneyEvidenceMismatch("question revision/source mismatch")
    return "REVISE_QUESTION_RIGHTS_PENDING_DEMO"
