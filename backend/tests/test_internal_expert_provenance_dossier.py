"""Independent LOCAL/TEST structural provenance dossier invariants."""
from dataclasses import replace
import unittest

from ronas_api.internal_expert_provenance_dossier import (
    CONTRACT_VERSION, project_expert_provenance_dossier,
)
from ronas_api.internal_expert_evidence_index import (
    project_synthetic_review_evidence_index,
)
from ronas_api.internal_cultivation_plan_contract import (
    InternalCultivationProposal, ProposedCultivationStage,
)
from ronas_api.expert_review_questions_sqlite import TRACKS


def proposal(**changes):
    data = dict(
        household_case_ref="DEMO-D-1", household_case_version=3,
        household_input_revision=1,
        household_input_snapshot_digest="1" * 64,
        scientific_basis_manifest_digest="2" * 64,
        internal_model_artifact_digest="3" * 64,
        internal_run_ref="DEMO-RUN-A",
        proposal_content_digest="4" * 64,
        proposed_stages=(
            ProposedCultivationStage("DEMO-STAGE-A", "5" * 64, "6" * 64),
        ),
    )
    data.update(changes)
    return InternalCultivationProposal(**data)


def science(**changed):
    data = dict(
        contract_version="ronas.domestic.internal-science-basis-structure.v0",
        purpose="DOMESTIC_CULTIVATION_PLAN",
        basis_state="PROVENANCE_PINNED_UNVERIFIED",
        basis_revision=2, candidate_source_count=1,
        scientific_validity_verified=False,
        rights_for_household_plan_verified=False,
        rights_for_ai_training_verified=False,
        internal_expert_qualification_verified=False,
        plan_review_approved=False,
        new_advice_enabled=False,
        business_gate_passed=False,
    )
    data.update(changed)
    return data


def dossier(*, current_input=(1, "1" * 64), plan=None, current_science=None,
            questions=None, bindings=None):
    q = questions if questions is not None else []
    p = proposal() if plan is None else (None if plan is False else plan)
    source = science() if current_science is None else (
        None if current_science is False else current_science
    )
    return project_expert_provenance_dossier(
        case_ref="DEMO-D-1", case_version=3, current_input=current_input,
        proposal=p, science_trace=source,
        evidence_index=project_synthetic_review_evidence_index(
            case_ref="DEMO-D-1", case_version=3,
            input_revision=current_input[0] if current_input else None,
            questions=q, responses=set(), inspections=set(),
        ),
        question_bindings=bindings if bindings is not None else [],
    )


def qb(track=TRACKS[0], rev=1, inputrev=1, dig="1" * 64,
       sc="2" * 64, plan="4" * 64):
    return track, rev, inputrev, dig, sc, plan


def question(track=TRACKS[0], rev=1, inputrev=1):
    return track, rev, inputrev, "DEMO-REASON", "DEMO-EVIDENCE"


class ExpertProvenanceDossierTests(unittest.TestCase):
    def test_current_structural_chain_cannot_promote_permissions(self):
        result = dossier(questions=[question()], bindings=[qb()])
        self.assertEqual(result["contract_version"], CONTRACT_VERSION)
        self.assertEqual(result["input"]["current_synthetic_revision"], 1)
        self.assertEqual(result["science"]["basis_candidate_revision"], 2)
        self.assertEqual(result["science"]["source_candidate_count"], 1)
        self.assertEqual(result["proposal"]["synthetic_stage_count"], 1)
        self.assertTrue(result["tracks"][0]["latest_question_fixture_binding_matches"])
        self.assertFalse(result["tracks"][1]["latest_question_fixture_binding_matches"])
        self.assertTrue(all(x["review_outcome"] == "NOT_REVIEWED"
                            for x in result["tracks"]))
        self.assertTrue(all(
            value is False for obj in (result["input"], result["science"],
                                        result["proposal"], result)
            for key, value in obj.items()
            if key.endswith("_verified") or key.endswith("_attested")
            or key.endswith("_accepted") or key.endswith("_enabled")
            or key.endswith("_recorded") or key == "real_data"
        ))
        for forbidden in (
            "DEMO-REASON", "DEMO-EVIDENCE", "DEMO-RUN-A", "DEMO-STAGE-A",
            "1" * 64, "2" * 64, "3" * 64, "4" * 64,
        ):
            self.assertNotIn(forbidden, str(result))

    def test_changed_question_binding_is_historical_only(self):
        r = dossier(questions=[question()], bindings=[qb(plan="7" * 64)])
        self.assertFalse(r["tracks"][0]["latest_question_fixture_binding_matches"])

    def test_all_three_tracks_remain_separate(self):
        questions = [question(x) for x in TRACKS]
        bindings = [qb(x) for x in TRACKS]
        r = dossier(questions=questions, bindings=bindings)
        self.assertEqual([x["track"] for x in r["tracks"]], list(TRACKS))
        self.assertEqual([x["historical_question_count"] for x in r["tracks"]],
                         [1, 1, 1])
        self.assertEqual([x["latest_question_fixture_binding_matches"]
                          for x in r["tracks"]], [True, True, True])

    def test_empty_chain_keeps_everything_unverified(self):
        r = dossier(current_input=None, plan=False, current_science=False)
        self.assertEqual(r["input"]["current_synthetic_revision"], None)
        self.assertEqual(r["science"]["catalogue_fixture_state"],
                         "NO_CURRENT_CATALOGUE_CHECK")
        self.assertEqual(r["proposal"]["fixture_state"],
                         "NO_INTERNAL_PROPOSAL_FIXTURE")
        self.assertEqual(r["tracks"][0]["latest_question_fixture_binding_matches"], False)

    def test_no_catalogue_check_never_claims_full_binding(self):
        r = dossier(questions=[question()], bindings=[qb()], current_science=False)
        self.assertFalse(r["tracks"][0]["latest_question_fixture_binding_matches"])
        self.assertEqual(r["science"]["source_candidate_count"], 0)

    def test_untrusted_scope_evidence_and_science_fail_closed(self):
        known = [question()]
        bindings = [qb()]
        baseline = dict(case_ref="DEMO-D-1", case_version=3,
                        current_input=(1, "1" * 64), proposal=proposal(),
                        science_trace=science(),
                        evidence_index=project_synthetic_review_evidence_index(
                            case_ref="DEMO-D-1", case_version=3, input_revision=1,
                            questions=known, responses=set(), inspections=set(),
                        ), question_bindings=bindings)
        changes = [
            {"case_version": True}, {"case_ref": "NOT-DEMO"},
            {"current_input": (True, "1" * 64)},
            {"current_input": (1, "X" * 64)},
            {"current_input": (2, "1" * 64)},
            {"proposal": replace(proposal(), household_case_version=2)},
            {"science_trace": science(business_gate_passed=True)},
            {"science_trace": science(basis_revision="2")},
            {"science_trace": science(basis_state="LICENSED")},
            {"evidence_index": {"engine": "EXPORT"}},
            {"question_bindings": [qb(rev=2)]},
            {"question_bindings": [qb(track="EXPORT")]},
            {"question_bindings": [qb(), qb()]},
            {"question_bindings": []},
        ]
        for changed in changes:
            with self.subTest(change=changed), self.assertRaises(ValueError):
                project_expert_provenance_dossier(**{**baseline, **changed})


if __name__ == "__main__":
    unittest.main()
