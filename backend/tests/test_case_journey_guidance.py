"""Pure case journey guidance: no role grants, plan approvals or invented data."""
import unittest
from ronas_api.case_journey_guidance import (
    JourneyEvidenceMismatch, owner_next_action,
    expert_next_action, export_next_action,
)


class CaseJourneyGuidanceTests(unittest.TestCase):
    def owner(self, rev=1):
        return {"engine": "DOMESTIC", "ref": "DEMO-D-1",
                "case_version": 3, "current_input_revision": rev}

    def owner_notes(self, received=False, current=True):
        return {
            "engine": "DOMESTIC", "case_ref": "DEMO-D-1",
            "case_version": 3, "real_data": False, "plan_accepted": False,
            "questions": [{"question_revision": 1, "bound_input_revision": 1,
                           "is_current_input_version": current,
                           "response_state": (
                               "RESPONSE_RECORDED" if received
                               else "MISSING_RESPONSE")}],
        }

    def expert_notes(self, received=False, inspected=False):
        return {"engine": "DOMESTIC", "case_ref": "DEMO-D-1",
                "qualification_verified": False, "plan_accepted": False,
                "real_data": False,
                "questions": [{
                    "track": "HOUSEHOLD_INPUT_ADEQUACY",
                    "bound_input_revision": 1,
                    "question_revision": 1,
                    "synthetic_household_response_received": received,
                    "synthetic_receipt_inspected_not_reviewed": inspected,
                }]}

    def proposal(self):
        return {"case_ref": "DEMO-D-1", "input_revision": 1,
                "proposal_status": "STRUCTURE_ONLY_UNREVIEWED"}

    def export(self, version=0):
        data = {"engine": "EXPORT", "ref": "DEMO-E-001",
                "source_rights_verified": False,
                "research_report_approved": False,
                "buyer_verified": False, "contracted": False, "real_data": False,
                "local_test_draft_question": None,
                "local_test_question_history": []}
        if version:
            data["local_test_draft_question"] = {
                "engine": "EXPORT", "case_ref": "DEMO-E-001",
                "question_revision": version,
                "research_report_approved": False,
            }
            data["local_test_question_history"] = [
                {"question_revision": i, "is_current": i == version}
                for i in range(1, version + 1)]
        return data

    def test_owner_prepares_only_synthetic_input_first(self):
        self.assertEqual(owner_next_action(self.owner(0), None),
                         "PREPARE_OR_REVISE_INPUT_DEMO")

    def test_owner_outstanding_question_deeplinks_without_approval(self):
        self.assertEqual(owner_next_action(self.owner(), self.owner_notes()),
                         "RESPOND_TO_EXPERT_QUESTION_DEMO")

    def test_owner_answer_waits_and_does_not_approve_plan(self):
        self.assertEqual(owner_next_action(
            self.owner(), self.owner_notes(received=True),
        ), "RESPONSE_RECORDED_WAIT_FOR_EXPERT_DEMO")

    def test_owner_input_correction_does_not_reuse_old_question(self):
        self.assertEqual(owner_next_action(
            self.owner(2), self.owner_notes(current=False),
        ), "PREPARE_OR_REVISE_INPUT_DEMO")

    def test_owner_mismatched_ref_fails_closed(self):
        wrong = self.owner_notes()
        wrong["case_ref"] = "DEMO-D-2"
        with self.assertRaises(JourneyEvidenceMismatch):
            owner_next_action(self.owner(), wrong)

    def test_owner_stale_current_input_question_fails_closed(self):
        with self.assertRaises(JourneyEvidenceMismatch):
            owner_next_action(self.owner(2), self.owner_notes(current=True))

    def test_expert_can_request_evidence_but_not_approve(self):
        x = self.expert_notes()
        x["questions"] = []
        self.assertEqual(expert_next_action(x, self.proposal()),
                         "REQUEST_MISSING_EVIDENCE_DEMO")

    def test_expert_unanswered_waits_for_owner(self):
        self.assertEqual(expert_next_action(
            self.expert_notes(), self.proposal(),
        ), "WAIT_FOR_HOUSEHOLD_RESPONSE_DEMO")

    def test_expert_receipt_presence_only(self):
        self.assertEqual(expert_next_action(
            self.expert_notes(received=True), self.proposal(),
        ), "INSPECT_RESPONSE_RECEIPT_DEMO")
        self.assertEqual(expert_next_action(
            self.expert_notes(received=True, inspected=True),
            self.proposal(),
        ), "RECEIPT_OBSERVED_NOT_REVIEWED")

    def test_expert_stale_proposal_never_shows_action(self):
        self.assertEqual(expert_next_action(self.expert_notes(), None),
                         "SOURCE_OR_INPUT_CHANGED_HISTORY_ONLY")

    def test_export_empty_question_is_unverified_not_trade(self):
        self.assertEqual(export_next_action(self.export()),
                         "DEFINE_INITIAL_RESEARCH_QUESTION_DEMO")

    def test_export_edited_question_still_rights_blocked(self):
        self.assertEqual(export_next_action(self.export(2)),
                         "REVISE_QUESTION_RIGHTS_PENDING_DEMO")

    def test_export_approval_or_history_tampering_is_rejected(self):
        x = self.export(1)
        x["source_rights_verified"] = True
        with self.assertRaises(JourneyEvidenceMismatch):
            export_next_action(x)
        y = self.export(2)
        y["local_test_question_history"].pop()
        with self.assertRaises(JourneyEvidenceMismatch):
            export_next_action(y)


if __name__ == "__main__":
    unittest.main()
