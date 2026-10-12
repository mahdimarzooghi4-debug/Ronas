"""Independent review-preparation lanes never constitute real plan approval."""
import unittest

from ronas_api.internal_expert_review_preparation import (
    CONTRACT_VERSION, project_expert_review_preparation,
)


def no_proposal():
    return {
        "contract_version": "ronas.domestic.internal-proposal-handoff.v0",
        "engine": "DOMESTIC", "case_ref": "DEMO-D-001", "case_version": 2,
        "proposal_status": "NO_INTERNAL_PROPOSAL_FIXTURE",
        "input_state": "NOT_RECORDED_IN_DEMO",
        "cultivation_inputs": {
            "crop": None, "growing_area": None, "water": None,
            "soil": None, "location": None,
        },
        "technical_review_state": "UNREQUESTED",
        "plan_state": "NOT_AUTHORED",
        "expert_qualification_verified": False,
        "scientific_review_approved": False,
        "plan_accepted": False,
        "advice_enabled": False, "real_data": False,
    }


def proposal():
    base = no_proposal()
    del base["cultivation_inputs"]
    base.update({
        "proposal_status": "STRUCTURE_ONLY_UNREVIEWED",
        "proposed_stage_refs": ["DEMO-STAGE-A", "DEMO-STAGE-B"],
        "input_revision": 3,
        "scientific_basis_state": "PROVENANCE_PINNED_UNVERIFIED",
    })
    return base


class ThreeIndependentExpertReviewPreparationTests(unittest.TestCase):
    def assert_all_unapproved(self, x):
        self.assertEqual(x["contract_version"], CONTRACT_VERSION)
        self.assertEqual(x["combined_review_status"], "NOT_AUTHORIZED_FOR_DECISION")
        self.assertEqual(x["case_status"], "DRAFT_ONLY")
        self.assertEqual([t["track"] for t in x["tracks"]], [
            "HOUSEHOLD_INPUT_ADEQUACY",
            "SCIENTIFIC_BASIS_AND_USE_RIGHTS",
            "INDIVIDUAL_CULTIVATION_PROPOSAL",
        ])
        self.assertTrue(all(
            t["review_outcome"] == "NOT_REVIEWED" for t in x["tracks"]
        ))
        for part in x["tracks"]:
            for k, v in part.items():
                if k in ("track", "observed_structure",
                         "review_outcome", "synthetic_stage_reference_count"):
                    continue
                self.assertIs(v, False, (part["track"], k))
        for k in (
            "technical_tracking_is_expert_approval",
            "qualified_reviewer_identity_verified",
            "current_expert_assignment_is_qualification",
            "actual_cultivation_plan_exists", "plan_accepted",
            "stages_activated", "new_advice_enabled",
            "marketplace_enabled", "real_data",
        ):
            self.assertIs(x[k], False, k)
        self.assertNotIn("DEMO-STAGE-A", str(x))
        self.assertNotIn("synthetic_household_owner", str(x))

    def test_absent_proposal_produces_three_separate_unreviewed_tracks(self):
        d = project_expert_review_preparation(no_proposal())
        self.assert_all_unapproved(d)
        self.assertEqual(d["tracks"][0]["observed_structure"],
                         "NO_SYNTHETIC_INPUT_BINDING")
        self.assertEqual(d["tracks"][1]["observed_structure"],
                         "NO_PROPOSAL_SCIENCE_BINDING")
        self.assertEqual(d["tracks"][2]["synthetic_stage_reference_count"], 0)

    def test_current_structure_does_not_count_as_real_data_or_approval(self):
        d = project_expert_review_preparation(proposal())
        self.assert_all_unapproved(d)
        self.assertEqual(d["tracks"][0]["observed_structure"],
                         "SYNTHETIC_INPUT_REVISION_BOUND_NOT_VALIDATED")
        self.assertEqual(d["tracks"][1]["observed_structure"],
                         "PROVENANCE_PINNED_UNVERIFIED")
        self.assertEqual(d["tracks"][2]["synthetic_stage_reference_count"], 2)

    def test_technical_review_human_response_not_plan_or_data_approval(self):
        for state in ("UNREQUESTED", "EVIDENCE_REVIEW_REQUESTED",
                      "HUMAN_RESPONSE_RECORDED"):
            with self.subTest(state=state):
                x = proposal()
                x["technical_review_state"] = state
                d = project_expert_review_preparation(x)
                self.assert_all_unapproved(d)
                self.assertEqual(d["technical_case_tracking"], state)

    def test_science_missing_fixture_is_explicitly_unverified(self):
        x = proposal()
        x["scientific_basis_state"] = "SCIENTIFIC_SOURCE_UNVERIFIED"
        d = project_expert_review_preparation(x)
        self.assert_all_unapproved(d)
        self.assertEqual(d["tracks"][1]["observed_structure"],
                         "SCIENTIFIC_SOURCE_UNVERIFIED")

    def test_none_or_nonmapping_or_export_fails_closed(self):
        for bad in (None, [], "", "fake", 123, {"case_ref": "DEMO-D-001"}):
            with self.subTest(value=repr(bad)), self.assertRaises(ValueError):
                project_expert_review_preparation(bad)
        for engine in ("EXPORT", "BOTH", "", None):
            x = proposal()
            x["engine"] = engine
            with self.assertRaises(ValueError):
                project_expert_review_preparation(x)

    def test_changed_consequential_flags_cannot_be_hidden_by_projection(self):
        for flag in ("plan_accepted", "real_data", "advice_enabled",
                     "scientific_review_approved",
                     "expert_qualification_verified"):
            for forged in (True, None, "false", 0):
                with self.subTest(flag=flag, forged=forged):
                    x = proposal()
                    x[flag] = forged
                    with self.assertRaises(ValueError):
                        project_expert_review_preparation(x)

    def test_unapproved_contract_cannot_show_approved_plan_state(self):
        for change in (("plan_state", "ACCEPTED"),
                       ("case_version", True), ("case_version", 0),
                       ("case_version", "2"),
                       ("contract_version", "runtime.v1"),
                       ("case_ref", "EXPORT-OTHER")):
            with self.subTest(change=change):
                x = no_proposal()
                x[change[0]] = change[1]
                with self.assertRaises(ValueError):
                    project_expert_review_preparation(x)

    def test_malformed_stage_list_or_revision_fails_closed(self):
        for key, value in (
            ("input_revision", True), ("input_revision", 0),
            ("input_revision", None), ("input_revision", "3"),
            ("proposed_stage_refs", []), ("proposed_stage_refs", None),
            ("proposed_stage_refs", "DEMO-STAGE-A"),
            ("proposed_stage_refs", ["DEMO-STAGE-A", "DEMO-STAGE-A"]),
            ("proposed_stage_refs", ["REAL-STAGE"]),
        ):
            with self.subTest(key=key, value=value):
                x = proposal()
                x[key] = value
                with self.assertRaises(ValueError):
                    project_expert_review_preparation(x)

    def test_no_proposal_cannot_claim_an_input_or_science_binding(self):
        for key, value in (
            ("input_revision", 1), ("scientific_basis_state",
                                     "PROVENANCE_PINNED_UNVERIFIED"),
            ("proposed_stage_refs", ["DEMO-STAGE-A"]),
            ("input_state", "CONSENT_VERIFIED"),
        ):
            with self.subTest(key=key):
                x = no_proposal()
                x[key] = value
                with self.assertRaises(ValueError):
                    project_expert_review_preparation(x)

    def test_invalid_science_claim_or_input_state_fails_closed(self):
        for key, value in (
            ("scientific_basis_state", "APPROVED"),
            ("scientific_basis_state", "PROVEN"),
            ("scientific_basis_state", None),
            ("input_state", "SUFFICIENT"),
        ):
            with self.subTest(key=key, value=value):
                x = proposal()
                x[key] = value
                with self.assertRaises(ValueError):
                    project_expert_review_preparation(x)

    def test_never_returns_identifiers_or_raw_stage_in_dossier(self):
        d = project_expert_review_preparation(proposal())
        self.assertEqual(set(d.keys()), {
            "contract_version", "engine", "case_ref", "case_version",
            "case_status", "technical_case_tracking",
            "technical_tracking_is_expert_approval", "tracks",
            "qualified_reviewer_identity_verified",
            "current_expert_assignment_is_qualification",
            "combined_review_status", "actual_cultivation_plan_exists",
            "plan_accepted", "stages_activated", "new_advice_enabled",
            "marketplace_enabled", "real_data",
        })
        for illegal in ("source_ref", "scientific_basis_manifest_digest",
                        "internal_model_artifact_digest", "snapshot_digest",
                        "scientific_rights", "proposed_stage_refs",
                        "proposal_content_digest", "input_manifest_digest"):
            self.assertNotIn(illegal, str(d))


if __name__ == "__main__":
    unittest.main()
