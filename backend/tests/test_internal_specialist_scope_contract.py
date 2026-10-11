"""Unverified evidence candidates, not specialist certification or decisions."""
from dataclasses import FrozenInstanceError, replace
import unittest

from ronas_api.expert_review_questions_sqlite import TRACKS
from ronas_api.internal_specialist_scope_contract import (
    RECORDED, WITHHELD, SpecialistScopeEvidenceCandidate,
    SpecialistScopeEvidenceEvent, SyntheticSpecialistEvidenceRegistry,
)

SUBJECT = "synthetic-agronomy-one"
CASE = "DEMO-D-1"


def candidate(revision=1, **changes):
    props = dict(
        subject=SUBJECT, case_ref=CASE, case_version=3,
        evidence_revision=revision,
        declared_review_tracks=(TRACKS[0], TRACKS[2]),
        qualification_evidence_ref="DEMO-QUAL-A",
        qualification_evidence_sha256="1"*64,
        appointment_evidence_ref="DEMO-APPT-A",
        appointment_evidence_sha256="2"*64,
        conflict_disclosure_ref="DEMO-CONFLICT-A",
        conflict_disclosure_sha256="3"*64,
        conflict_declaration_state="CONFLICT_NOT_ASSESSED",
    )
    props.update(changes)
    return SpecialistScopeEvidenceCandidate(**props)


def recorded(obj=None, action="DEMO-EVIDENCE-A"):
    obj = obj or candidate()
    return SpecialistScopeEvidenceEvent(
        action_ref=action, subject=obj.subject, case_ref=obj.case_ref,
        case_version=obj.case_version,
        evidence_revision=obj.evidence_revision,
        operation=RECORDED, candidate=obj,
    )


def withheld(revision=2, action="DEMO-WITHHOLD-A"):
    return SpecialistScopeEvidenceEvent(
        action_ref=action, subject=SUBJECT, case_ref=CASE, case_version=3,
        evidence_revision=revision, operation=WITHHELD,
        reason_ref="DEMO-WITHHOLD-REASON",
    )


def registry():
    return SyntheticSpecialistEvidenceRegistry((recorded(),))


def projection(catalogue=None):
    return (catalogue or registry()).project_assigned_case(
        subject=SUBJECT, case_ref=CASE, case_version=3,
    )


class SpecialistScopeCandidateTests(unittest.TestCase):
    def test_document_pointers_never_claim_qualification_or_clearance(self):
        r = projection()
        self.assertEqual(r["evidence_state"], "EVIDENCE_POINTERS_PRESENT_UNVERIFIED")
        self.assertEqual([x["track"] for x in r["track_scopes"]], list(TRACKS))
        self.assertEqual([x["declared_candidate_scope_present"] for x
                          in r["track_scopes"]], [True, False, True])
        self.assertTrue(all(x["may_decide_cultivation_plan"] is False
                            for x in r["track_scopes"]))
        for key in ("identity_professional_credential_verified",
                    "appointment_authority_verified",
                    "conflict_independently_cleared",
                    "scope_authorized_for_real_review",
                    "candidate_is_access_grant",
                    "plan_accepted", "new_advice_enabled", "real_data"):
            self.assertIs(r[key], False)
        for confidential in ("DEMO-QUAL-A", "DEMO-APPT-A", "DEMO-CONFLICT-A",
                             "1"*64, "2"*64, "3"*64, SUBJECT):
            self.assertNotIn(confidential, str(r))

    def test_potential_conflict_is_declared_not_independently_cleared(self):
        cand = candidate(conflict_declaration_state="POTENTIAL_CONFLICT_DECLARED")
        r = projection(SyntheticSpecialistEvidenceRegistry((recorded(cand),)))
        self.assertTrue(r["potential_conflict_disclosed"])
        self.assertFalse(r["conflict_independently_cleared"])
        self.assertFalse(r["scope_authorized_for_real_review"])

    def test_withholding_preserves_history_and_does_not_restore_old_scope(self):
        before = registry()
        after = before.with_event(withheld())
        self.assertEqual(projection(after)["evidence_state"],
                         "CANDIDATE_WITHHELD_NOT_AUTHORIZED")
        self.assertTrue(all(not x["declared_candidate_scope_present"]
                            for x in projection(after)["track_scopes"]))
        self.assertEqual(projection(before)["candidate_revision"], 1)
        self.assertEqual(after.snapshot_at(1), before)
        self.assertEqual(after.compare(1,2)["withheld_candidate_event_count"], 1)
        self.assertEqual(after.compare(0,2)["changed_specialist_case_pair_count"], 1)

    def test_reintroduction_requires_version_after_withholding(self):
        withdrawn = registry().with_event(withheld())
        cand = candidate(3, declared_review_tracks=(TRACKS[1],),
                         appointment_evidence_sha256="a"*64)
        updated = withdrawn.with_event(recorded(cand, "DEMO-NEW-A"))
        self.assertEqual(projection(updated)["candidate_revision"], 3)
        self.assertEqual([x["declared_candidate_scope_present"] for x
                          in projection(updated)["track_scopes"]], [False, True, False])
        self.assertFalse(projection(updated)["identity_professional_credential_verified"])

    def test_ordered_versioned_fingerprints_are_reproducible(self):
        first = registry()
        again = SyntheticSpecialistEvidenceRegistry(first.events)
        self.assertEqual(first.fingerprint, again.fingerprint)
        second = first.with_event(recorded(candidate(
            2, appointment_evidence_sha256="f"*64),
            "DEMO-APPT-REVISE"))
        self.assertNotEqual(second.fingerprint, first.fingerprint)
        self.assertNotEqual(second.snapshot_at(1).fingerprint, second.fingerprint)
        self.assertEqual(second.compare(1,2)["added_candidate_event_count"], 1)

    def test_no_candidate_is_not_authorization(self):
        zero = SyntheticSpecialistEvidenceRegistry()
        r = zero.project_assigned_case(
            subject=SUBJECT, case_ref=CASE, case_version=3)
        self.assertEqual(r["evidence_state"], "NO_SYNTHETIC_EVIDENCE_CANDIDATE")
        self.assertIsNone(r["candidate_revision"])
        self.assertFalse(r["candidate_is_access_grant"])

    def test_invalid_credential_refs_purpose_scope_status_fail_closed(self):
        cases = (
            {"subject": "not-synthetic"}, {"case_ref": "DEMO-E-1", "case_version": 0},
            {"evidence_revision": True},
            {"declared_review_tracks": ()},
            {"declared_review_tracks": (TRACKS[2],TRACKS[0])},
            {"declared_review_tracks": (TRACKS[0],TRACKS[0])},
            {"declared_review_tracks": ("EXPORT",)},
            {"declared_review_tracks": [TRACKS[0]]},
            {"qualification_evidence_ref": "https://real.example"},
            {"qualification_evidence_sha256": "Z"*64},
            {"appointment_evidence_ref": "REAL-LICENCE"},
            {"appointment_evidence_sha256": "2"*63},
            {"conflict_disclosure_ref": "../private"},
            {"conflict_disclosure_sha256": "3"*65},
            {"conflict_declaration_state": "NO_CONFLICT_VERIFIED"},
            {"conflict_declaration_state": "APPROVED"},
        )
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ValueError):
                candidate(**change)

    def test_history_rejects_action_replay_gap_stale_version_and_false_withhold(self):
        initial=registry()
        wrong=(
            recorded(candidate(1), "DEMO-ACTION-NEW"),
            recorded(candidate(3), "DEMO-ACTION-NEW"),
            recorded(candidate(2), "DEMO-EVIDENCE-A"),
            recorded(candidate(2, case_version=4), "DEMO-NEW-A"),
            withheld(revision=3),
        )
        for e in wrong:
            with self.subTest(event=e), self.assertRaises(ValueError):
                initial.with_event(e)
        with self.assertRaises(ValueError):
            SyntheticSpecialistEvidenceRegistry((withheld(revision=1),))
        with self.assertRaises(ValueError):
            registry().with_event(withheld()).with_event(withheld(3,"DEMO-WITHHOLD-B"))
        with self.assertRaises(ValueError):
            SpecialistScopeEvidenceEvent(
                action_ref="DEMO-FORGED", subject=SUBJECT, case_ref=CASE,
                case_version=3, evidence_revision=2, operation="APPROVED")

    def test_reject_cross_case_or_stale_actor_projection(self):
        c=registry()
        with self.assertRaises(ValueError):
            c.project_assigned_case(
                subject=SUBJECT, case_ref=CASE, case_version=4)
        hidden=c.project_assigned_case(
            subject="synthetic-different-expert", case_ref=CASE, case_version=3)
        self.assertEqual(hidden["evidence_state"], "NO_SYNTHETIC_EVIDENCE_CANDIDATE")
        with self.assertRaises(ValueError):
            c.project_assigned_case(subject=SUBJECT, case_ref="EXPORT",case_version=3)

    def test_snapshot_immutable_and_boolean_ordinals_invalid(self):
        c=registry()
        with self.assertRaises(FrozenInstanceError):
            c.events=()
        with self.assertRaises(FrozenInstanceError):
            candidate().appointment_evidence_ref="DEMO-FORGED"
        for value in (-1,2,True,"1",None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                c.snapshot_at(value)
        for a,b in ((1,1),(2,3),(-1,1),(True,1),(0,False)):
            with self.subTest(a=a,b=b), self.assertRaises(ValueError):
                c.compare(a,b)


if __name__ == "__main__":
    unittest.main()
