"""Pure case-local specialist evidence drift: no inferred expiry or clearance."""
from dataclasses import replace
import unittest

from ronas_api.expert_review_questions_sqlite import TRACKS
from ronas_api.internal_specialist_scope_contract import (
    RECORDED, WITHHELD, SpecialistScopeEvidenceCandidate,
    SpecialistScopeEvidenceEvent, SyntheticSpecialistEvidenceRegistry,
)
from ronas_api.internal_specialist_scope_change_impact import (
    SpecialistEvidenceRevisionConflict,
    project_assigned_specialist_scope_change_impact,
)

ACTOR, REF = "synthetic-agronomy-one", "DEMO-D-1"


def candidate(revision=1, **values):
    data = dict(
        subject=ACTOR, case_ref=REF, case_version=3,
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
    data.update(values)
    return SpecialistScopeEvidenceCandidate(**data)


def record(item=None, action="DEMO-RECORD-A"):
    item = item or candidate()
    return SpecialistScopeEvidenceEvent(
        action_ref=action, subject=item.subject, case_ref=item.case_ref,
        case_version=item.case_version, evidence_revision=item.evidence_revision,
        operation=RECORDED, candidate=item,
    )


def withhold(revision=2):
    return SpecialistScopeEvidenceEvent(
        action_ref="DEMO-WITHHOLD-A", subject=ACTOR, case_ref=REF,
        case_version=3, evidence_revision=revision,
        operation=WITHHELD, reason_ref="DEMO-REASON-A",
    )


def registry():
    return SyntheticSpecialistEvidenceRegistry((record(),))


def assess(reg=None, observed=0, **values):
    data = dict(registry=registry() if reg is None else reg,
                subject=ACTOR, case_ref=REF, case_version=3,
                observed_revision=observed)
    data.update(values)
    return project_assigned_specialist_scope_change_impact(**data)


class SpecialistScopeImpactTests(unittest.TestCase):
    def test_same_revision_still_unverified_and_no_expiration_invented(self):
        a = assess(observed=1)
        b = assess(observed=1)
        self.assertEqual(a, b)
        self.assertFalse(a["version_changed"])
        self.assertEqual(a["structural_relationship"],
                         "UNCHANGED_STRUCTURAL_CANDIDATE_UNVERIFIED")
        self.assertEqual(a["current_conflict_diagnostic"],
                         "CONFLICT_NOT_INDEPENDENTLY_ASSESSED")
        self.assertFalse(a["scope_authorized_for_real_review"])
        self.assertFalse(a["professional_qualification_verified"])
        self.assertFalse(a["conflict_independently_cleared"])
        self.assertNotIn("expires_at", a)
        self.assertNotIn("valid_until", a)
        for private in ("DEMO-QUAL-A", "DEMO-APPT-A", "DEMO-CONFLICT-A",
                        ACTOR, "1"*64, "2"*64, "3"*64):
            self.assertNotIn(private, str(a))

    def test_qualification_appointment_scope_and_conflict_independent(self):
        second = candidate(
            2, qualification_evidence_sha256="a"*64,
            appointment_evidence_sha256="b"*64,
            declared_review_tracks=(TRACKS[1],),
            conflict_disclosure_sha256="c"*64,
            conflict_declaration_state="POTENTIAL_CONFLICT_DECLARED",
        )
        r = registry().with_event(record(second, "DEMO-RECORD-B"))
        impact = assess(r, observed=1)
        self.assertEqual(impact["structural_relationship"],
                         "CANDIDATE_EVIDENCE_REVISED_UNVERIFIED")
        self.assertTrue(impact["qualification_evidence_pointer_changed"])
        self.assertTrue(impact["appointment_evidence_pointer_changed"])
        self.assertTrue(impact["conflict_disclosure_pointer_changed"])
        self.assertTrue(impact["conflict_declaration_changed"])
        self.assertEqual(impact["current_conflict_diagnostic"],
                         "POTENTIAL_CONFLICT_DISCLOSED_UNRESOLVED")
        self.assertEqual([x["scope_declaration_changed"] for x in
                          impact["declared_track_scope_changes"]],
                         [True, True, True])
        self.assertEqual([x["current_candidate_scope_declared"] for x in
                          impact["declared_track_scope_changes"]],
                         [False, True, False])
        self.assertTrue(all(not x["may_decide_cultivation_plan"] for x in
                            impact["declared_track_scope_changes"]))

    def test_only_appointment_pointer_change_does_not_verify_qualification(self):
        later = registry().with_event(record(candidate(
            2, appointment_evidence_sha256="a"*64,
        ), "DEMO-APPOINTMENT-REVISION"))
        r = assess(later, observed=1)
        self.assertFalse(r["qualification_evidence_pointer_changed"])
        self.assertTrue(r["appointment_evidence_pointer_changed"])
        self.assertFalse(r["conflict_disclosure_pointer_changed"])
        self.assertFalse(r["scope_authorized_for_real_review"])

    def test_withheld_then_rerecorded_remains_historical_changed(self):
        later = registry().with_event(withhold())
        missing = assess(later, observed=1)
        self.assertEqual(missing["structural_relationship"],
                         "CURRENT_CANDIDATE_WITHHELD_NO_REUSE")
        self.assertTrue(missing["appointment_evidence_pointer_changed"])
        self.assertEqual(missing["current_conflict_diagnostic"],
                         "NO_CURRENT_CANDIDATE_CONFLICT_UNKNOWN")
        self.assertEqual(missing["candidate_withheld_since_observed_count"], 1)
        newer = later.with_event(record(candidate(3), "DEMO-RECORD-C"))
        report = assess(newer, observed=1)
        self.assertEqual(report["candidate_withheld_since_observed_count"], 1)
        self.assertEqual(report["candidate_recorded_since_observed_count"], 1)
        self.assertTrue(report["version_changed"])
        self.assertFalse(report["qualification_evidence_pointer_changed"])
        self.assertFalse(report["scope_authorized_for_real_review"])

    def test_no_candidate_and_initial_version_zero_are_distinct(self):
        empty = SyntheticSpecialistEvidenceRegistry()
        r = assess(empty, observed=0)
        self.assertEqual(r["current_evidence_revision"], 0)
        self.assertEqual(r["structural_relationship"],
                         "NO_SPECIALIST_EVIDENCE_CANDIDATE")
        self.assertFalse(r["candidate_is_access_grant"])
        created = assess(registry(), observed=0)
        self.assertTrue(created["qualification_evidence_pointer_changed"])
        self.assertEqual(created["observed_candidate_state"],
                         "NO_CANDIDATE_RECORDED")

    def test_scoped_fingerprint_ignores_other_cases_and_specialists(self):
        first = registry()
        unrelated = candidate(1, subject="synthetic-other-expert",
                              case_ref="DEMO-D-2", case_version=1)
        expanded = first.with_event(record(unrelated, "DEMO-UNRELATED"))
        a = assess(first, observed=0)
        b = assess(expanded, observed=0)
        self.assertEqual(a, b)
        self.assertNotEqual(expanded.fingerprint, first.fingerprint)

    def test_unknown_revision_boolean_and_stale_case_fail_closed(self):
        first = registry()
        for observed in (-1, 2, True, "1", None):
            with self.subTest(observed=observed), self.assertRaises(
                SpecialistEvidenceRevisionConflict
            ):
                assess(first, observed=observed)
        with self.assertRaises(ValueError):
            assess(first, observed=1, case_version=4)
        with self.assertRaises(ValueError):
            assess(first, observed=0, case_ref="EXPORT")
        with self.assertRaises(ValueError):
            assess(first, observed=0, subject="other-user")

    def test_revision_scoped_hash_not_global_or_actual_signature(self):
        first = registry()
        revised = first.with_event(record(candidate(
            2, qualification_evidence_sha256="a"*64,
        ), "DEMO-RECORD-B"))
        old = assess(first, observed=1)
        new = assess(revised, observed=1)
        self.assertEqual(old["current_scope_fingerprint_sha256"],
                         new["observed_scope_fingerprint_sha256"])
        self.assertNotEqual(new["observed_scope_fingerprint_sha256"],
                            new["current_scope_fingerprint_sha256"])
        for key in ("historical_case_access_reconstructed",
                    "current_candidate_matches_authority",
                    "appointment_authority_verified",
                    "independent_specialist_decision_recorded",
                    "plan_accepted", "new_advice_enabled", "real_data"):
            self.assertIs(new[key], False)


if __name__ == "__main__":
    unittest.main()
