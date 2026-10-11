"""Deterministic synthetic handoff identity never grants approval."""
import unittest

from ronas_api.internal_expert_review_handoff import (
    VERSION, SOURCE_NONE, SOURCE_PINNED, prepare_synthetic_review_handoff,
)
from ronas_api.internal_cultivation_plan_contract import (
    InternalCultivationProposal, ProposedCultivationStage,
)
from ronas_api.expert_review_questions_sqlite import TRACKS

def proposal(**changes):
    data = dict(
        household_case_ref="DEMO-D-1", household_case_version=3,
        household_input_revision=1, household_input_snapshot_digest="1" * 64,
        scientific_basis_manifest_digest="2" * 64,
        internal_model_artifact_digest="3" * 64, internal_run_ref="DEMO-RUN",
        proposal_content_digest="4" * 64,
        proposed_stages=(ProposedCultivationStage(
            "DEMO-STAGE-A", "5" * 64, "6" * 64),),
    )
    data.update(changes)
    return InternalCultivationProposal(**data)

def question(track=TRACKS[0], rev=1, seq=4):
    return (track, rev, 1, "1" * 64, "2" * 64,
            "4" * 64, "a" * 64, seq)

def packet(**overrides):
    base = dict(
        case_ref="DEMO-D-1", case_version=3,
        input_snapshot=(1, "1" * 64), proposal=proposal(),
        source_state=SOURCE_PINNED,
        question_rows=[question()], response_rows=[], sighting_rows=[],
    )
    base.update(overrides)
    return prepare_synthetic_review_handoff(**base)

class ReviewHandoffFingerprintTests(unittest.TestCase):
    def test_repeated_identical_context_is_deterministic_without_approval(self):
        a, b = packet(), packet()
        self.assertEqual(a, b)
        self.assertEqual(a["contract_version"], VERSION)
        self.assertEqual(len(a["context_fingerprint_sha256"]), 64)
        self.assertTrue(a["tracks"][0]["latest_question_fixture_binding_matches"])
        self.assertFalse(a["fingerprint_is_persisted_or_signed"])
        self.assertFalse(a["fingerprint_is_independent_attestation"])
        for k in ("qualified_specialist_verified",
                  "purpose_consent_verified", "scientific_suitability_verified",
                  "service_use_rights_verified", "training_rights_verified",
                  "model_execution_verified", "independent_decision_recorded",
                  "plan_accepted", "new_advice_enabled", "real_data"):
            self.assertIs(a[k], False)
        for secret in ("DEMO-RUN", "DEMO-STAGE-A",
                       "1" * 64, "2" * 64, "4" * 64):
            self.assertNotIn(secret, str(a))

    def test_response_and_sighting_change_fingerprint_and_not_review_status(self):
        before = packet()
        response = packet(response_rows=[(TRACKS[0], 1, "b" * 64, 6)])
        sighted = packet(
            response_rows=[(TRACKS[0], 1, "b" * 64, 6)],
            sighting_rows=[(TRACKS[0], 1, "c" * 64, 8)],
        )
        self.assertEqual(len({x["context_fingerprint_sha256"]
                              for x in (before, response, sighted)}), 3)
        self.assertTrue(sighted["tracks"][0]
                        ["latest_specialist_receipt_sighting_present"])
        self.assertFalse(sighted["tracks"][0]
                         ["independent_specialist_review_recorded"])

    def test_track_separation_and_later_question_version_change_fingerprint(self):
        a = packet()
        b = packet(question_rows=[
            question(), question(TRACKS[1], 1, 7),
            question(TRACKS[2], 1, 9),
        ])
        c = packet(question_rows=[
            question(), question(TRACKS[1], 1, 7),
            question(TRACKS[2], 1, 9),
            question(TRACKS[0], 2, 11),
        ])
        self.assertEqual([x["historical_question_count"] for x in b["tracks"]],
                         [1, 1, 1])
        self.assertEqual([x["historical_question_count"] for x in c["tracks"]],
                         [2, 1, 1])
        self.assertEqual(len({x["context_fingerprint_sha256"]
                              for x in (a, b, c)}), 3)

    def test_absent_input_proposal_and_catalogue_is_not_fabricated(self):
        result = packet(
            input_snapshot=None, proposal=None, source_state=SOURCE_NONE,
            question_rows=[],
        )
        self.assertEqual(result["proposal_fixture_state"],
                         "NO_INTERNAL_PROPOSAL_FIXTURE")
        self.assertFalse(result["tracks"][0]
                         ["latest_question_fixture_binding_matches"])
        self.assertEqual(result["current_input_revision"], None)
        self.assertFalse(result["scientific_suitability_verified"])

    def test_unchecked_source_cannot_claim_verified_binding(self):
        r = packet(source_state=SOURCE_NONE)
        self.assertFalse(r["tracks"][0]["latest_question_fixture_binding_matches"])
        self.assertNotEqual(
            r["context_fingerprint_sha256"], packet()["context_fingerprint_sha256"])

    def test_changed_input_model_stage_content_alter_snapshot_identity(self):
        original = packet()["context_fingerprint_sha256"]
        mutated = [
            packet(input_snapshot=(2, "7" * 64), proposal=proposal(
                household_input_revision=2, household_input_snapshot_digest="7" * 64)),
            packet(proposal=proposal(internal_model_artifact_digest="7" * 64)),
            packet(proposal=proposal(proposed_stages=(
                ProposedCultivationStage("DEMO-STAGE-A", "7" * 64, "6" * 64),))),
            packet(proposal=proposal(proposal_content_digest="7" * 64)),
        ]
        self.assertTrue(all(x["context_fingerprint_sha256"] != original
                            for x in mutated))

    def test_bad_authority_and_receipt_links_fail_closed(self):
        baseline = dict(
            case_ref="DEMO-D-1", case_version=3,
            input_snapshot=(1, "1" * 64), proposal=proposal(),
            source_state=SOURCE_PINNED,
            question_rows=[question()], response_rows=[], sighting_rows=[],
        )
        changes = [
            {"case_ref": "EXPORT-CASE"},
            {"case_version": True},
            {"input_snapshot": (True, "1" * 64)},
            {"input_snapshot": (1, "bad")},
            {"proposal": None, "source_state": SOURCE_PINNED},
            {"proposal": proposal(household_case_version=2)},
            {"proposal": proposal(household_input_snapshot_digest="7" * 64)},
            {"source_state": "LICENSED"},
            {"question_rows": [question(rev=2)]},
            {"question_rows": [question(), question()]},
            {"question_rows": [question(track="EXPORT")]},
            {"question_rows": [question(seq=True)]},
            {"question_rows": [question(), question(TRACKS[1], 1, 3)]},
            {"response_rows": [(TRACKS[1], 1, "b" * 64, 8)]},
            {"response_rows": [(TRACKS[0], 2, "b" * 64, 8)]},
            {"response_rows": [(TRACKS[0], 1, "b" * 64, 3)]},
            {"sighting_rows": [(TRACKS[0], 1, "c" * 64, 7)]},
            {"response_rows": [(TRACKS[0], 1, "b" * 64, 8)],
             "sighting_rows": [(TRACKS[0], 1, "c" * 64, 7)]},
        ]
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                prepare_synthetic_review_handoff(**{**baseline, **changed})

if __name__ == "__main__":
    unittest.main()
