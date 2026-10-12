import unittest
from dataclasses import replace

from ronas_api.domestic_stage_observation import (
    CurrentStageContext, StageObservationCommand, StageObservationConflict,
    StageRequirement, receipt_is_current, record_stage_observation,
)

D = "a" * 64
E = "b" * 64
F = "c" * 64
G = "d" * 64
H = "e" * 64


def context():
    return CurrentStageContext(
        "DEMO-D-001", 2, 4, D, E,
        (StageRequirement("DEMO-STAGE-01", F),),
    )


def command(**changes):
    values = dict(
        action_id="action-001", expected_case_version=2,
        expected_input_revision=4, expected_input_snapshot_digest=D,
        expected_plan_digest=E, stage_ref="DEMO-STAGE-01",
        expected_observation_requirements_digest=F,
        observed_at="2026-10-12T10:20:30+00:00",
        observation_artifact_digest=G,
    )
    values.update(changes)
    return StageObservationCommand(**values)


class StageObservationContractTests(unittest.TestCase):
    def test_valid_receipt_binds_current_stage_and_never_claims_completion(self):
        receipt = record_stage_observation(command(), current=context(), revision=1)
        self.assertEqual(receipt.stage_ref, "DEMO-STAGE-01")
        self.assertEqual(receipt.observation_requirements_digest, F)
        self.assertEqual(receipt.revision, 1)
        self.assertTrue(receipt_is_current(receipt, context()))
        self.assertEqual(receipt.status, "OBSERVATION_REFERENCE_RECORDED")
        self.assertFalse(receipt.stage_completed)
        self.assertFalse(receipt.scientific_review_approved)
        self.assertFalse(receipt.advice_enabled)
        self.assertFalse(receipt.real_data)

    def test_changed_case_input_or_plan_rejects_new_observation(self):
        for changed in (
            replace(context(), case_version=3),
            replace(context(), input_revision=5),
            replace(context(), input_snapshot_digest=H),
            replace(context(), plan_digest=H),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(StageObservationConflict):
                    record_stage_observation(command(), current=changed, revision=1)

    def test_changed_or_unknown_stage_requirements_reject_submission(self):
        changed = replace(context(), requirements=(StageRequirement(
            "DEMO-STAGE-01", H,
        ),))
        with self.assertRaises(StageObservationConflict):
            record_stage_observation(command(), current=changed, revision=1)
        with self.assertRaises(StageObservationConflict):
            record_stage_observation(command(stage_ref="DEMO-STAGE-02"),
                                     current=context(), revision=1)

    def test_old_receipt_becomes_noncurrent_after_lineage_change(self):
        receipt = record_stage_observation(command(), current=context(), revision=1)
        self.assertFalse(receipt_is_current(receipt, replace(context(), plan_digest=H)))
        self.assertFalse(receipt_is_current(receipt, replace(context(), input_revision=5)))

    def test_receipt_chain_is_deterministic_and_revision_bound(self):
        first = record_stage_observation(command(), current=context(), revision=1)
        second = record_stage_observation(
            command(action_id="action-002"), current=context(), revision=2,
            previous_receipt_digest=first.receipt_digest,
        )
        self.assertEqual(len(first.receipt_digest), 64)
        self.assertNotEqual(first.receipt_digest, second.receipt_digest)
        self.assertEqual(second.previous_receipt_digest, first.receipt_digest)

    def test_rejects_bad_timestamps_and_non_hash_artifact_refs(self):
        for values in (
            {"observed_at": "2026-10-12T10:00:00"},
            {"observation_artifact_digest": "raw private observation"},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                command(**values)


if __name__ == "__main__":
    unittest.main()
