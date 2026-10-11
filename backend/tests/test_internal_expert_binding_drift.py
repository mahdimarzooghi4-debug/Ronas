"""Read-only historical drift states never authorize a cultivation plan."""
import unittest

from ronas_api.expert_review_questions_sqlite import TRACKS
from ronas_api.internal_cultivation_plan_contract import (
    InternalCultivationProposal, ProposedCultivationStage,
)
from ronas_api.internal_expert_binding_drift import (
    VERSION, project_synthetic_review_binding_drift,
)

INPUT = "1" * 64
SCIENCE = "2" * 64
PLAN = "4" * 64
GOOD = "SOURCE_CANDIDATE_POINTERS_MATCH_UNVERIFIED"
NONE = "NO_SEPARATE_SOURCE_CATALOGUE"
CHANGED = "SOURCE_CANDIDATE_POINTERS_CHANGED"


def proposal(input_rev=1, input_hash=INPUT, science=SCIENCE, plan=PLAN):
    return InternalCultivationProposal(
        household_case_ref="DEMO-D-1", household_case_version=3,
        household_input_revision=input_rev,
        household_input_snapshot_digest=input_hash,
        scientific_basis_manifest_digest=science,
        internal_model_artifact_digest="3" * 64,
        internal_run_ref="DEMO-RUN", proposal_content_digest=plan,
        proposed_stages=(ProposedCultivationStage(
            "DEMO-STAGE-A", "5" * 64, "6" * 64),),
    )


def q(track=TRACKS[0], rev=1, input_rev=1,
      input_hash=INPUT, science=SCIENCE, plan=PLAN):
    return (track, rev, input_rev, input_hash, science, plan)


def project(**changes):
    args = dict(case_ref="DEMO-D-1", case_version=3,
                current_input=(1, INPUT), current_proposal=proposal(),
                source_pointer_state=GOOD,
                question_bindings=[q()], responses=set(), inspections=set())
    args.update(changes)
    return project_synthetic_review_binding_drift(**args)


def status(result, track=0, index=0):
    return result["tracks"][track]["questions"][index]["structural_context"]


class SyntheticBindingDriftProjectionTests(unittest.TestCase):
    def test_all_three_tracks_and_revisions_are_historical_only(self):
        result = project(
            question_bindings=[q(), q(TRACKS[1]), q(rev=2), q(TRACKS[2])],
            responses={(TRACKS[0], 1)}, inspections={(TRACKS[0], 1)},
        )
        self.assertEqual(result["contract_version"], VERSION)
        self.assertEqual([x["track"] for x in result["tracks"]], list(TRACKS))
        self.assertEqual([len(x["questions"]) for x in result["tracks"]], [2, 1, 1])
        self.assertTrue(result["tracks"][0]["questions"][0]["superseded_by_newer_question"])
        self.assertTrue(result["tracks"][0]["questions"][0]
                        ["historical_receipt_sighted_not_reviewed"])
        self.assertEqual(status(result), "STRUCTURAL_FIXTURE_MATCH_ONLY_UNREVIEWED")
        self.assertTrue(all(
            x["eligible_for_operational_reuse"] is False
            and x["independent_specialist_review_recorded"] is False
            for t in result["tracks"] for x in t["questions"]
        ))
        self.assertFalse(result["plan_accepted"])
        self.assertNotIn(INPUT, str(result))
        self.assertNotIn(SCIENCE, str(result))

    def test_input_correction_and_digest_only_change_are_explicit(self):
        for input_snapshot in ((2, "7" * 64), (1, "7" * 64)):
            with self.subTest(snapshot=input_snapshot):
                result = project(current_input=input_snapshot)
                self.assertEqual(status(result),
                                 "HOUSEHOLD_INPUT_REVISION_OR_FINGERPRINT_CHANGED")
                self.assertFalse(result["new_advice_enabled"])
        result = project(current_input=None)
        self.assertEqual(status(result), "NO_CURRENT_SYNTHETIC_OWNER_INPUT")

    def test_proposal_or_science_pointer_drift_never_approve(self):
        for args, expected in [
            ({"current_proposal": None, "source_pointer_state": NONE},
             "NO_CURRENT_SYNTHETIC_PROPOSAL_FIXTURE"),
            ({"current_proposal": proposal(input_rev=2)},
             "CURRENT_PROPOSAL_BOUND_TO_DIFFERENT_INPUT"),
            ({"current_proposal": proposal(plan="7" * 64)},
             "PROPOSAL_OR_SCIENCE_MANIFEST_CHANGED"),
            ({"current_proposal": proposal(science="7" * 64)},
             "PROPOSAL_OR_SCIENCE_MANIFEST_CHANGED"),
            ({"source_pointer_state": CHANGED},
             "SCIENTIFIC_SOURCE_CANDIDATE_POINTERS_CHANGED"),
            ({"source_pointer_state": NONE},
             "SCIENTIFIC_CATALOGUE_NOT_CHECKED"),
        ]:
            with self.subTest(expected=expected):
                r = project(**args)
                self.assertEqual(status(r), expected)
                self.assertFalse(r["rights_for_service_verified"])

    def test_empty_case_three_tracks_without_fake_minimums(self):
        r = project(question_bindings=[], current_input=None,
                    current_proposal=None, source_pointer_state=NONE)
        self.assertEqual([t["historical_question_count"] for t in r["tracks"]],
                         [0, 0, 0])
        self.assertEqual(r["current_synthetic_owner_input_revision"], None)

    def test_malformed_or_orphan_history_fails_closed(self):
        baseline = dict(case_ref="DEMO-D-1", case_version=3,
                        current_input=(1, INPUT), current_proposal=proposal(),
                        source_pointer_state=GOOD, question_bindings=[q()],
                        responses=set(), inspections=set())
        bad = [
            {"case_ref": "EXPORT-1"},
            {"case_version": True},
            {"current_input": (True, INPUT)},
            {"current_input": (1, "BAD")},
            {"source_pointer_state": "APPROVED"},
            {"question_bindings": [q(rev=2)]},
            {"question_bindings": [q(), q()]},
            {"question_bindings": [q(track="EXPORT")]},
            {"question_bindings": [q(input_hash="BAD")]},
            {"responses": {(TRACKS[1], 1)}},
            {"responses": {(TRACKS[0], 2)}},
            {"inspections": {(TRACKS[0], 1)}},
            {"responses": {(TRACKS[0], 1)}, "inspections": {(TRACKS[0], 2)}},
            {"source_pointer_state": GOOD, "current_proposal": None},
            {"current_proposal": proposal(input_rev=1, input_hash="7" * 64,
                                           science=SCIENCE, plan=PLAN),
             "case_version": 2},
        ]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                project_synthetic_review_binding_drift(**{**baseline, **change})


if __name__ == "__main__":
    unittest.main()
