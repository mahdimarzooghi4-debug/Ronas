"""Only offline/local structural guards for INTERNAL AI proposal envelopes.

No real AI, consent, credentials, expert approval, crop, scientific content or
operational advice exists. Every fixture is synthetic and explicitly unreviewed.
"""
from dataclasses import replace
import unittest

from ronas_api.internal_cultivation_plan_contract import (
    CONTRACT_VERSION, InternalCultivationProposal, ProposedCultivationStage,
    inspect_proposal_structure,
)

CASE = "DEMO-H01"
INPUT = "1" * 64
SCIENCE = "2" * 64
MODEL = "3" * 64
PROPOSAL = "4" * 64


def stage(ref="DEMO-STAGE-1", *, instructions="5" * 64,
          observations="6" * 64):
    return ProposedCultivationStage(ref, instructions, observations)


def envelope(**changes):
    kwargs = dict(
        household_case_ref=CASE,
        household_case_version=2,
        household_input_revision=3,
        household_input_snapshot_digest=INPUT,
        scientific_basis_manifest_digest=SCIENCE,
        internal_model_artifact_digest=MODEL,
        internal_run_ref="DEMO-RUN-1",
        proposal_content_digest=PROPOSAL,
        proposed_stages=(stage(), stage("DEMO-STAGE-2")),
        origin="RONAS_INTERNAL_AI",
    )
    kwargs.update(changes)
    return InternalCultivationProposal(**kwargs)


def inspect(value, **changes):
    expected = dict(
        expected_case_engine="DOMESTIC",
        expected_case_ref=CASE,
        expected_case_version=2,
        expected_input_revision=3,
        expected_input_snapshot_digest=INPUT,
    )
    expected.update(changes)
    return inspect_proposal_structure(value, **expected)


class RonasInternalCultivationProposalContractTests(unittest.TestCase):
    def test_pinned_internal_proposal_has_no_approval_or_real_advice(self):
        evidence = inspect(envelope())
        self.assertEqual(evidence["contract_version"], CONTRACT_VERSION)
        self.assertEqual(evidence["engine"], "DOMESTIC")
        self.assertEqual(evidence["case_ref"], CASE)
        self.assertEqual(evidence["case_version"], 2)
        self.assertEqual(evidence["household_input_revision"], 3)
        self.assertEqual(evidence["household_input_snapshot_digest"], INPUT)
        self.assertEqual(evidence["scientific_basis_manifest_digest"], SCIENCE)
        self.assertEqual(evidence["internal_model_artifact_digest"], MODEL)
        self.assertEqual(evidence["proposal_content_digest"], PROPOSAL)
        self.assertEqual(evidence["internal_run_ref"], "DEMO-RUN-1")
        self.assertEqual(evidence["proposal_origin"], "RONAS_INTERNAL_AI")
        self.assertEqual(evidence["proposed_stage_refs"],
                         ["DEMO-STAGE-1", "DEMO-STAGE-2"])
        self.assertEqual(evidence["proposal_status"], "STRUCTURE_ONLY_UNREVIEWED")
        self.assertEqual(evidence["business_plan_state"], "NOT_ACCEPTED")
        for key in (
            "expert_qualification_verified", "expert_plan_approved",
            "scientific_basis_verified", "informed_household_consent_verified",
            "model_attestation_verified", "supervision_stages_activated",
            "new_cultivation_advice_enabled", "commercial_actions_enabled",
            "real_data",
        ):
            self.assertIs(evidence[key], False)
        for forbidden in (
            "crop", "water_amount", "planting_date", "advice", "price",
            "buyer", "soil", "fertilizer", "approval_actor",
        ):
            self.assertNotIn(forbidden, evidence)

    def test_unrelated_export_engine_reference_is_not_a_household_case(self):
        for ref in ("EXPORT-E01", "not-a-demo", "", "DEMO-E01/../bad", 123):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                envelope(household_case_ref=ref)

    def test_external_provider_or_human_authored_substitute_rejected(self):
        for origin in (
            "EXTERNAL_AI", "OPENAI_API", "RONAS_INTERNAL_HUMAN",
            "RONAS_INTERNAL_AI_APPROVED", "", None,
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                envelope(origin=origin)

    def test_invalid_versions_refuse_booleans_zero_negative_or_string(self):
        for field in ("household_case_version", "household_input_revision"):
            for value in (0, -1, True, False, "2", None, 1.0):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    envelope(**{field: value})

    def test_invalid_source_or_model_digests_fail_closed(self):
        for field in (
            "household_input_snapshot_digest",
            "scientific_basis_manifest_digest",
            "internal_model_artifact_digest",
            "proposal_content_digest",
        ):
            for value in ("", "a" * 63, "A" * 64, "z" * 64, None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    envelope(**{field: value})

    def test_model_run_identity_is_local_demo_only(self):
        for ref in ("", "NOT-DEMO", None, "DEMO-RUN/1", 1):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                envelope(internal_run_ref=ref)

    def test_arbitrary_number_of_explicit_unique_stages_not_fixed(self):
        one = inspect(envelope(proposed_stages=(stage(),)))
        self.assertEqual(one["proposed_stage_refs"], ["DEMO-STAGE-1"])
        many = inspect(envelope(proposed_stages=tuple(
            stage("DEMO-STAGE-" + str(i)) for i in range(1, 6)
        )))
        self.assertEqual(len(many["proposed_stage_refs"]), 5)
        self.assertIs(many["supervision_stages_activated"], False)

    def test_duplicate_missing_or_non_tuple_stages_rejected(self):
        for stages in (
            (), [], (stage(), stage()), [stage()],
            (stage(), "DEMO-STAGE-2"), None,
        ):
            with self.subTest(stages=str(stages)), self.assertRaises(ValueError):
                envelope(proposed_stages=stages)

    def test_bad_stage_lineage_rejected(self):
        for ref in ("", "STAGE-1", "DEMO-../bad", None):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                stage(ref)
        for updates in (
            {"instructions": ""}, {"instructions": "A" * 64},
            {"observations": ""}, {"observations": "q" * 64},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                stage(**updates)

    def test_case_and_input_binding_must_match_current_separate_authority(self):
        proposal = envelope()
        for options in (
            {"expected_case_engine": "EXPORT"},
            {"expected_case_engine": ""},
            {"expected_case_ref": "DEMO-OTHER"},
            {"expected_case_version": 1},
            {"expected_case_version": 3},
            {"expected_input_revision": 2},
            {"expected_input_revision": 4},
            {"expected_input_snapshot_digest": "7" * 64},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                inspect(proposal, **options)

    def test_expected_case_input_parameters_validate_strictly(self):
        for options in (
            {"expected_case_ref": "NOT-DEMO"},
            {"expected_case_version": True},
            {"expected_case_version": 0},
            {"expected_input_revision": False},
            {"expected_input_revision": -1},
            {"expected_input_snapshot_digest": "A" * 64},
            {"expected_input_snapshot_digest": None},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                inspect(envelope(), **options)

    def test_no_pseudo_record_or_mutable_proposal_is_accepted(self):
        with self.assertRaises(ValueError):
            inspect({})
        with self.assertRaises(ValueError):
            inspect(None)
        with self.assertRaises(ValueError):
            replace(envelope(), proposed_stages=[stage()])
        self.assertEqual(
            inspect(envelope())["business_plan_state"], "NOT_ACCEPTED"
        )


if __name__ == "__main__":
    unittest.main()
