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



from ronas_api.internal_ai_proposal_runtime import (
    CandidateOutput, CandidateStage, ProposalRuntimeContext,
    ProposalRuntimeUnavailable, ProposalRuntimeStale,
    candidate_structure_digest, run_current_synthetic_internal_proposal,
    run_synthetic_internal_proposal,
)


class _InternalModelFixture:
    def __init__(self, output=None, error=None):
        stages = (
            CandidateStage("DEMO-STAGE-A", "5" * 64, "6" * 64),
            CandidateStage("DEMO-STAGE-B", "7" * 64, "8" * 64),
        )
        self.output = output or CandidateOutput(
            model_artifact_digest=MODEL,
            proposal_content_digest=candidate_structure_digest(MODEL, stages),
            stages=stages,
        )
        self.error = error
        self.calls = []

    def generate(self, context):
        self.calls.append(context)
        if self.error:
            raise self.error
        return self.output


def runtime_context(**changes):
    values = dict(
        case_ref=CASE, case_version=2, input_revision=3,
        input_snapshot_digest=INPUT,
        scientific_basis_manifest_digest=SCIENCE,
        model_artifact_digest=MODEL, run_ref="DEMO-RUNTIME-1",
    )
    values.update(changes)
    return ProposalRuntimeContext(**values)


class RonasInternalProposalRuntimeTests(unittest.TestCase):
    def test_internal_adapter_output_is_pinned_and_never_accepted(self):
        adapter = _InternalModelFixture()
        result = run_synthetic_internal_proposal(runtime_context(), adapter)
        self.assertEqual(adapter.calls, [runtime_context()])
        self.assertEqual(result.proposal.household_case_ref, CASE)
        self.assertEqual(result.structural_record["proposal_status"],
                         "STRUCTURE_ONLY_UNREVIEWED")
        self.assertEqual(result.structural_record["business_plan_state"], "NOT_ACCEPTED")
        self.assertEqual(result.structural_record["proposed_stage_refs"],
                         ["DEMO-STAGE-A", "DEMO-STAGE-B"])
        self.assertEqual(len(result.runtime_receipt_digest), 64)
        for key in ("scientific_basis_verified", "expert_plan_approved",
                    "model_attestation_verified", "supervision_stages_activated",
                    "new_cultivation_advice_enabled", "real_data"):
            self.assertIs(result.structural_record[key], False)


    def test_candidate_content_digest_binds_artifact_and_ordered_stage_structure(self):
        original = _InternalModelFixture().output
        self.assertEqual(
            candidate_structure_digest(original.model_artifact_digest,
                                       original.stages),
            original.proposal_content_digest,
        )
        mutations = (
            CandidateOutput(
                MODEL, original.proposal_content_digest,
                (CandidateStage("DEMO-STAGE-X", "5"*64, "6"*64),
                 original.stages[1]),
            ),
            CandidateOutput(
                MODEL, original.proposal_content_digest,
                (CandidateStage(original.stages[0].ref, "9"*64, "6"*64),
                 original.stages[1]),
            ),
            CandidateOutput(
                MODEL, original.proposal_content_digest,
                tuple(reversed(original.stages)),
            ),
            CandidateOutput(
                "9"*64, original.proposal_content_digest, original.stages,
            ),
        )
        for output in mutations:
            with self.subTest(output=output), self.assertRaises(
                ProposalRuntimeUnavailable
            ):
                run_synthetic_internal_proposal(
                    runtime_context(), _InternalModelFixture(output=output),
                )

    def test_runtime_context_rejects_export_real_or_malformed_lineage(self):
        for changes in (
            {"engine": "EXPORT"}, {"case_ref": "DEMO-E-1"},
            {"case_version": True}, {"input_revision": 0},
            {"input_snapshot_digest": "bad"},
            {"scientific_basis_manifest_digest": "z" * 64},
            {"model_artifact_digest": "A" * 64}, {"run_ref": "AI-RUN-1"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                runtime_context(**changes)

    def test_adapter_failure_is_sanitized_and_does_not_fabricate_proposal(self):
        adapter = _InternalModelFixture(error=RuntimeError("private adapter secret"))
        with self.assertRaises(ProposalRuntimeUnavailable) as caught:
            run_synthetic_internal_proposal(runtime_context(), adapter)
        self.assertNotIn("private adapter secret", str(caught.exception))
        self.assertEqual(len(adapter.calls), 1)

    def test_mismatched_model_and_bad_or_duplicate_stage_outputs_fail_closed(self):
        outputs = (
            CandidateOutput("9" * 64, PROPOSAL,
                            (CandidateStage("DEMO-STAGE-A", "5"*64, "6"*64),)),
            CandidateOutput(MODEL, PROPOSAL, ()),
            CandidateOutput(MODEL, PROPOSAL, [
                CandidateStage("DEMO-STAGE-A", "5"*64, "6"*64)
            ]),
            CandidateOutput(MODEL, "bad",
                            (CandidateStage("DEMO-STAGE-A", "5"*64, "6"*64),)),
            CandidateOutput(MODEL, PROPOSAL, (
                CandidateStage("DEMO-STAGE-A", "5"*64, "6"*64),
                CandidateStage("DEMO-STAGE-A", "7"*64, "8"*64),
            )),
        )
        for output in outputs:
            with self.subTest(output=output), self.assertRaises(ProposalRuntimeUnavailable):
                run_synthetic_internal_proposal(
                    runtime_context(), _InternalModelFixture(output=output),
                )

    def test_runtime_requires_a_typed_adapter_and_never_accepts_missing_context(self):
        for context, adapter in ((None, _InternalModelFixture()),
                                 (runtime_context(), object())):
            with self.subTest(context=context, adapter=adapter), self.assertRaises(ValueError):
                run_synthetic_internal_proposal(context, adapter)



class _CurrentProposalContextAuthority:
    def __init__(self, context, *, fail_on_call=None):
        self.context = context
        self.calls = []
        self.fail_on_call = fail_on_call

    def read_current_context(self, case_ref, run_ref):
        self.calls.append((case_ref, run_ref))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("private authority detail")
        return self.context


class CurrentRonasInternalProposalRuntimeTests(unittest.TestCase):
    def test_current_context_is_independently_read_before_and_after_model_run(self):
        context = runtime_context()
        authority = _CurrentProposalContextAuthority(context)
        result = run_current_synthetic_internal_proposal(
            CASE, context.run_ref, authority, _InternalModelFixture(),
        )
        self.assertEqual(authority.calls, [(CASE, context.run_ref)] * 2)
        self.assertEqual(result.proposal.household_input_revision, 3)

    def test_missing_or_mismatched_current_context_stops_before_model_call(self):
        for context in (None, runtime_context(case_ref="DEMO-D-OTHER"),
                        runtime_context(run_ref="DEMO-RUNTIME-OTHER")):
            authority = _CurrentProposalContextAuthority(context)
            adapter = _InternalModelFixture()
            with self.subTest(context=context), self.assertRaises(
                ProposalRuntimeStale
            ):
                run_current_synthetic_internal_proposal(
                    CASE, runtime_context().run_ref, authority, adapter,
                )
            self.assertEqual(adapter.calls, [])

    def test_case_input_source_or_artifact_revision_during_run_discards_result(self):
        context = runtime_context()
        mutations = (
            {"case_version": 3},
            {"input_revision": 4},
            {"input_snapshot_digest": "9" * 64},
            {"scientific_basis_manifest_digest": "8" * 64},
            {"model_artifact_digest": "7" * 64},
        )
        for changes in mutations:
            with self.subTest(changes=changes):
                authority = _CurrentProposalContextAuthority(context)
                class ChangingAdapter:
                    def generate(self, seen):
                        self.assert_context(seen, context)
                        out = _InternalModelFixture().generate(seen)
                        authority.context = replace(context, **changes)
                        return out
                    @staticmethod
                    def assert_context(seen, expected):
                        if seen != expected:
                            raise AssertionError("unexpected context")
                with self.assertRaises(ProposalRuntimeStale):
                    run_current_synthetic_internal_proposal(
                        CASE, context.run_ref, authority, ChangingAdapter(),
                    )
                self.assertEqual(len(authority.calls), 2)

    def test_authority_outage_is_sanitized_before_or_after_generation(self):
        context = runtime_context()
        for failure_call in (1, 2):
            authority = _CurrentProposalContextAuthority(
                context, fail_on_call=failure_call,
            )
            adapter = _InternalModelFixture()
            with self.subTest(failure_call=failure_call), self.assertRaises(
                ProposalRuntimeUnavailable
            ) as caught:
                run_current_synthetic_internal_proposal(
                    CASE, context.run_ref, authority, adapter,
                )
            self.assertNotIn("private authority detail", str(caught.exception))
            self.assertEqual(len(adapter.calls), 1 if failure_call == 2 else 0)

    def test_context_authority_requires_synthetic_domestic_identifiers(self):
        context = runtime_context()
        authority = _CurrentProposalContextAuthority(context)
        for case_ref, run_ref in (
            ("DEMO-E-1", context.run_ref), (CASE, "LIVE-RUN-1"),
        ):
            with self.subTest(case_ref=case_ref, run_ref=run_ref), self.assertRaises(
                ValueError
            ):
                run_current_synthetic_internal_proposal(
                    case_ref, run_ref, authority, _InternalModelFixture(),
                )
        self.assertEqual(authority.calls, [])

if __name__ == "__main__":
    unittest.main()
