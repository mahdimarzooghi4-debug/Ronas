"""Pure fail-closed synthetic evidence index invariants; no approval."""
import unittest

from ronas_api.internal_expert_evidence_index import (
    CONTRACT_VERSION, NO_QUESTION, QUESTION_ONLY, OWNER_RESPONSE,
    RECEIPT_SEEN, project_synthetic_review_evidence_index,
)
from ronas_api.expert_review_questions_sqlite import TRACKS


def index(questions=None, responses=None, inspections=None, input_revision=1):
    return project_synthetic_review_evidence_index(
        case_ref="DEMO-D-1", case_version=3, input_revision=input_revision,
        questions=[] if questions is None else questions,
        responses=set() if responses is None else responses,
        inspections=set() if inspections is None else inspections,
    )


def q(track=TRACKS[0], revision=1, bound=1):
    return (track, revision, bound, "DEMO-REASON", "DEMO-EVIDENCE")


class EvidenceIndexProjectionTests(unittest.TestCase):
    def test_zero_tracks_and_all_consequential_flags_are_false(self):
        result = index()
        self.assertEqual(result["contract_version"], CONTRACT_VERSION)
        self.assertEqual([r["track"] for r in result["tracks"]], list(TRACKS))
        self.assertEqual([r["latest_evidence_marker"] for r in result["tracks"]],
                         [NO_QUESTION] * 3)
        self.assertEqual(result["case_state"], "DRAFT_ONLY")
        self.assertEqual(result["index_scope"], "HISTORICAL_SYNTHETIC_EVIDENCE_ONLY")
        self.assertTrue(all(
            value is False for key, value in result.items()
            if key.endswith("_verified") or key.endswith("_recorded")
            or key in ("plan_accepted", "new_advice_enabled", "real_data")
        ))

    def test_three_tracks_separate_and_receipts_do_not_promote_review(self):
        entries = [q(), q(TRACKS[1]), q(TRACKS[2])]
        result = index(entries, {(TRACKS[0], 1)}, {(TRACKS[0], 1)})
        self.assertEqual(
            [x["latest_evidence_marker"] for x in result["tracks"]],
            [RECEIPT_SEEN, QUESTION_ONLY, QUESTION_ONLY],
        )
        self.assertEqual([x["historical_owner_response_count"]
                          for x in result["tracks"]], [1, 0, 0])
        self.assertTrue(all(
            x["review_decision_recorded"] is False
            and x["question_is_independent_specialist_review"] is False
            and x["source_lineage_current_verified"] is False
            for x in result["tracks"]
        ))
        for secret in ("DEMO-REASON", "DEMO-EVIDENCE"):
            self.assertNotIn(secret, str(result))

    def test_response_without_sighting_then_sighting_and_stale_correction(self):
        entries = [q()]
        self.assertEqual(
            index(entries)["tracks"][0]["latest_evidence_marker"], QUESTION_ONLY)
        responded = index(entries, {(TRACKS[0], 1)})
        self.assertEqual(responded["tracks"][0]["latest_evidence_marker"],
                         OWNER_RESPONSE)
        sighted = index(entries, {(TRACKS[0], 1)}, {(TRACKS[0], 1)},
                        input_revision=2)
        self.assertEqual(sighted["tracks"][0]["latest_evidence_marker"],
                         RECEIPT_SEEN)
        self.assertFalse(sighted["tracks"][0]
                         ["latest_question_matches_current_input_revision"])
        self.assertEqual(sighted["tracks"][0]["latest_bound_input_revision"], 1)

    def test_per_track_revision_and_latest_only_do_not_erase_history(self):
        entries = [q(), q(TRACKS[1]), q(revision=2)]
        result = index(entries, {(TRACKS[0], 1)}, {(TRACKS[0], 1)})
        t = result["tracks"][0]
        self.assertEqual(t["historical_question_count"], 2)
        self.assertEqual(t["historical_owner_response_count"], 1)
        self.assertEqual(t["historical_receipt_sighting_count"], 1)
        self.assertEqual(t["latest_question_revision"], 2)
        self.assertEqual(t["latest_evidence_marker"], QUESTION_ONLY)

    def test_invalid_scopes_links_and_forged_noninput_response_fail_closed(self):
        base = {"case_ref": "DEMO-D-1", "case_version": 3,
                "input_revision": 1, "questions": [q()],
                "responses": set(), "inspections": set()}
        variants = [
            {"case_ref": "REAL-HOUSEHOLD"},
            {"case_version": True}, {"input_revision": False},
            {"questions": [("FAKE", 1, 1, "DEMO-A", "DEMO-B")]},
            {"questions": [q(revision=2)]},
            {"questions": [q(), q()]},
            {"questions": [q(bound=0)]},
            {"questions": [("HOUSEHOLD_INPUT_ADEQUACY", 1, 1, "private", "DEMO-B")]},
            {"responses": {(TRACKS[0], 2)}},
            {"responses": {(TRACKS[1], 1)}},
            {"inspections": {(TRACKS[0], 1)}},
            {"responses": {(TRACKS[0], 1)}, "inspections": {(TRACKS[0], 2)}},
            {"responses": {(TRACKS[0], True)}},
        ]
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                project_synthetic_review_evidence_index(**{**base, **changed})


if __name__ == "__main__":
    unittest.main()
