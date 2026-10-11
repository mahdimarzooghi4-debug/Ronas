"""Joined unverified evidence, source, AI and specialist context tests."""
from copy import deepcopy
import unittest

from ronas_api.expert_review_questions_sqlite import TRACKS
from ronas_api.internal_expert_review_handoff import (
    prepare_synthetic_review_handoff, SOURCE_NONE,
)
from ronas_api.internal_expert_evidence_comparison import (
    verified_synthetic_evidence_events, synthetic_evidence_timeline,
)
from ronas_api.internal_specialist_scope_contract import (
    SyntheticSpecialistEvidenceRegistry,
)
from ronas_api.internal_specialist_scope_change_impact import (
    project_assigned_specialist_scope_change_impact,
)
from ronas_api.internal_specialist_review_context import (
    VERSION, project_synthetic_specialist_review_context,
)

CASE, ACTOR = "DEMO-D-1", "synthetic-agronomy-one"


def sources():
    ins = [(1, "1"*64, "a"*64, 3)]
    q, reply, sight = [], [], []
    handoff=prepare_synthetic_review_handoff(
        case_ref=CASE,case_version=3,input_snapshot=(1,"1"*64),
        proposal=None,source_state=SOURCE_NONE,
        question_rows=q,response_rows=reply,sighting_rows=sight,
    )
    timeline=synthetic_evidence_timeline(
        case_ref=CASE,case_version=3,
        events=verified_synthetic_evidence_events(
            input_rows=ins,question_rows=q,
            response_rows=reply,sighting_rows=sight,
        ),
    )
    impact=project_assigned_specialist_scope_change_impact(
        registry=SyntheticSpecialistEvidenceRegistry(),
        subject=ACTOR,case_ref=CASE,case_version=3,observed_revision=0,
    )
    return dict(case_ref=CASE,case_version=3,handoff=handoff,
                evidence_timeline=timeline,specialist_impact=impact)


class SyntheticJoinedContextTests(unittest.TestCase):
    def test_empty_proposal_and_specialist_are_non_authorizing(self):
        output=project_synthetic_specialist_review_context(**sources())
        self.assertEqual(output["contract_version"],VERSION)
        self.assertEqual(output["household_input"]["current_revision"],1)
        self.assertEqual(output["household_input"][
            "case_local_immutable_evidence_event_count"],1)
        self.assertEqual(output["internal_ai_proposal"]["current_fixture_state"],
                         "NO_INTERNAL_PROPOSAL_FIXTURE")
        self.assertEqual(output["specialist_evidence"]["current_revision"],0)
        self.assertEqual(output["specialist_evidence"]["current_candidate_state"],
                         "NO_CANDIDATE_RECORDED")
        self.assertFalse(output["fingerprint_is_signature_or_approval"])
        self.assertFalse(output["real_specialist_decision_recorded"])
        self.assertFalse(output["new_cultivation_advice_enabled"])
        self.assertEqual([t["track"] for t in output["tracks"]],list(TRACKS))
        self.assertTrue(all(t["review_outcome"]=="NOT_REVIEWED" and
                            not t["eligible_for_operational_reuse"]
                            for t in output["tracks"]))
        for private in ("1"*64,"a"*64,ACTOR):
            self.assertNotIn(private,str(output))

    def test_same_snapshot_is_deterministic(self):
        source=sources()
        first=project_synthetic_specialist_review_context(**source)
        second=project_synthetic_specialist_review_context(**source)
        self.assertEqual(first,second)
        self.assertEqual(len(first["synthetic_context_fingerprint_sha256"]),64)

    def test_conflicting_case_or_contract_identity_fails_closed(self):
        for name,key,value in (
            ("handoff","case_ref","DEMO-D-2"),
            ("handoff","contract_version","FAKE"),
            ("evidence_timeline","case_version",2),
            ("evidence_timeline","case_state","APPROVED"),
            ("specialist_impact","engine","EXPORT"),
            ("specialist_impact","comparison_scope","WRONG"),
        ):
            data=sources()
            data[name]=deepcopy(data[name])
            data[name][key]=value
            with self.subTest(name=name,key=key),self.assertRaises(ValueError):
                project_synthetic_specialist_review_context(**data)

    def test_no_authority_elevation_in_child_projections(self):
        for name,key in (
            ("handoff","plan_accepted"),
            ("handoff","qualified_specialist_verified"),
            ("handoff","scientific_suitability_verified"),
            ("evidence_timeline","historical_ai_proposal_reconstructible"),
            ("specialist_impact","appointment_authority_verified"),
            ("specialist_impact","conflict_independently_cleared"),
        ):
            data=sources()
            data[name]=deepcopy(data[name])
            data[name][key]=True
            with self.subTest(name=name,key=key),self.assertRaises(ValueError):
                project_synthetic_specialist_review_context(**data)

    def test_track_mismatch_or_false_review_rejected(self):
        for changed in ("track","review_outcome","independent_specialist_review_recorded"):
            data=sources()
            data["handoff"]=deepcopy(data["handoff"])
            data["handoff"]["tracks"][0][changed]=(
                "EXPORT" if changed=="track" else
                "APPROVED" if changed=="review_outcome" else True
            )
            with self.subTest(field=changed),self.assertRaises(ValueError):
                project_synthetic_specialist_review_context(**data)

    def test_current_input_must_equal_verified_journal(self):
        data=sources()
        data["evidence_timeline"]=deepcopy(data["evidence_timeline"])
        data["evidence_timeline"]["revisions"][0]["subject_revision"]=2
        with self.assertRaises(ValueError):
            project_synthetic_specialist_review_context(**data)

    def test_scope_revision_and_fingerprint_shapes_verified(self):
        data=sources()
        data["specialist_impact"]=deepcopy(data["specialist_impact"])
        data["specialist_impact"]["current_evidence_revision"]=-1
        with self.assertRaises(ValueError):
            project_synthetic_specialist_review_context(**data)
        data=sources()
        data["handoff"]=deepcopy(data["handoff"])
        data["handoff"]["context_fingerprint_sha256"]="Z"*64
        with self.assertRaises(ValueError):
            project_synthetic_specialist_review_context(**data)


if __name__=="__main__":
    unittest.main()
