"""Historical LOCAL/TEST evidence comparison: no false review or science."""
import unittest

from ronas_api.expert_review_questions_sqlite import TRACKS
from ronas_api.internal_expert_evidence_comparison import (
    KINDS, VERSION, EvidenceRevisionConflict,
    verified_synthetic_evidence_events, synthetic_evidence_timeline,
    compare_synthetic_evidence_revisions,
)

def rows():
    ins = [(1, "1"*64, "a"*64, 2), (2, "7"*64, "b"*64, 17)]
    qs = [
        (TRACKS[0], 1, 1, "1"*64, "2"*64, "4"*64, "c"*64, 5),
        (TRACKS[1], 1, 1, "1"*64, "2"*64, "4"*64, "d"*64, 8),
        (TRACKS[2], 1, 1, "1"*64, "2"*64, "4"*64, "e"*64, 10),
    ]
    ans = [(TRACKS[0], 1, "f"*64, 12)]
    sightings = [(TRACKS[0], 1, "0"*64, 15)]
    return ins, qs, ans, sightings

def events(**changes):
    data = dict(zip(("input_rows", "question_rows", "response_rows",
                     "sighting_rows"), rows()))
    data.update(changes)
    return verified_synthetic_evidence_events(**data)

def compare(stream=None, earlier=1, later=6):
    return compare_synthetic_evidence_revisions(
        case_ref="DEMO-D-1", case_version=3,
        events=events() if stream is None else stream,
        from_revision=earlier, to_revision=later,
    )

class SyntheticEvidenceComparisonTests(unittest.TestCase):
    def test_per_case_timeline_has_no_global_sequence_or_sensitive_refs(self):
        stream = events()
        timeline = synthetic_evidence_timeline(
            case_ref="DEMO-D-1", case_version=3, events=stream)
        self.assertEqual(timeline["contract_version"], VERSION)
        self.assertEqual(timeline["latest_evidence_revision"], 6)
        self.assertEqual([r["event_kind"] for r in timeline["revisions"]], [
            KINDS[0], KINDS[1], KINDS[1], KINDS[2], KINDS[1], KINDS[3],
        ] if False else [
            KINDS[0], KINDS[1], KINDS[1], KINDS[1], KINDS[2], KINDS[3],
        ])
        self.assertFalse(timeline["global_audit_sequence_exposed"])
        self.assertNotIn("17", str(timeline))
        self.assertTrue(all(not r["independent_specialist_review_recorded"]
                            for r in timeline["revisions"]))

    def test_input_revision_event_changes_case_local_snapshot(self):
        result = compare(earlier=6, later=7)
        self.assertTrue(result["input_revision_changed"])
        self.assertEqual(result["from"]["latest_input_revision"], 1)
        self.assertEqual(result["to"]["latest_input_revision"], 2)
        self.assertEqual(result["track_deltas"][0]["added_question_count"], 0)
        self.assertFalse(result["historical_ai_proposal_reconstructible"])

    def test_question_response_and_sighting_are_distinct_deltas(self):
        a = compare(earlier=1, later=2)
        self.assertEqual(a["track_deltas"][0]["added_question_count"], 1)
        self.assertTrue(a["track_deltas"][0]
                        ["latest_question_pinned_science_manifest_changed"])
        r = compare(earlier=4, later=5)
        self.assertEqual(r["track_deltas"][0]["added_owner_response_count"], 1)
        s = compare(earlier=5, later=6)
        self.assertEqual(s["track_deltas"][0]["added_receipt_sighting_count"], 1)
        self.assertTrue(all(not x["eligible_for_operational_reuse"]
                            for x in s["track_deltas"]))
        self.assertFalse(s["independent_decision_recorded"])

    def test_fingerprint_stable_against_global_audit_sequence_gaps(self):
        a = events()
        input_rows, question_rows, response_rows, sighting_rows = rows()
        # Additional unrelated or read audit events increase gaps, not identity.
        b = verified_synthetic_evidence_events(
            input_rows=[(*r[:-1], r[-1]*3) for r in input_rows],
            question_rows=[(*r[:-1], r[-1]*3) for r in question_rows],
            response_rows=[(*r[:-1], r[-1]*3) for r in response_rows],
            sighting_rows=[(*r[:-1], r[-1]*3) for r in sighting_rows],
        )
        self.assertEqual(
            compare(a)["to"]["evidence_fingerprint_sha256"],
            compare(b)["to"]["evidence_fingerprint_sha256"],
        )
        self.assertNotEqual(
            compare(a, 5, 6)["from"]["evidence_fingerprint_sha256"],
            compare(a, 5, 6)["to"]["evidence_fingerprint_sha256"],
        )

    def test_input_and_cross_track_always_separate(self):
        result = compare(earlier=2, later=6)
        self.assertEqual([t["track"] for t in result["track_deltas"]],
                         list(TRACKS))
        self.assertEqual([t["added_question_count"] for t in result["track_deltas"]],
                         [0, 1, 1])
        self.assertEqual(result["to"]["tracks"][0]["review_outcome"],
                         "NOT_REVIEWED")
        for flag in ("qualified_specialist_verified", "consent_verified",
                     "source_rights_verified", "scientific_validity_verified",
                     "plan_accepted", "real_data", "new_advice_enabled"):
            self.assertIs(result[flag], False)
        for secret in ("1"*64, "2"*64, "4"*64, "f"*64):
            self.assertNotIn(secret, str(result))

    def test_boundaries_must_be_real_case_local_mutation_ordinals(self):
        stream = events()
        for a,b in ((0,1),(1,1),(2,1),(1,8),(-1,4),
                    (True,3),(1,False),("1",2)):
            with self.subTest(a=a,b=b), self.assertRaises(EvidenceRevisionConflict):
                compare(stream,a,b)

    def test_fail_closed_corrupted_or_wrongly_linked_ledger_rows(self):
        input_rows, question_rows, response_rows, sighting_rows = rows()
        variants = [
            {"input_rows": [(2, "1"*64, "a"*64, 2)]},
            {"question_rows": [(*question_rows[0][:2], 2, *question_rows[0][3:])]},
            {"question_rows": [(*question_rows[0][:4], "x"*64,
                                 *question_rows[0][5:])]},
            {"question_rows": [(*question_rows[0][:-1], 1)]},
            {"response_rows": [(TRACKS[1], 1, "f"*64, 12)]},
            {"response_rows": [(TRACKS[0], 2, "f"*64, 12)]},
            {"response_rows": [(TRACKS[0], 1, "f"*64, 4)]},
            {"sighting_rows": [(TRACKS[0], 1, "0"*64, 11)]},
            {"sighting_rows": [(TRACKS[0], 1, "0"*64, 15),
                                (TRACKS[0], 1, "0"*64, 16)]},
        ]
        for change in variants:
            with self.subTest(change=change), self.assertRaises(ValueError):
                events(**change)

if __name__ == "__main__":
    unittest.main()
