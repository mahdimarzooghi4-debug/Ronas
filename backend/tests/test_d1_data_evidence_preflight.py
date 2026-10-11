"""Hard-fail preparation-only D1 evidence trace. No consent or runtime."""
from dataclasses import FrozenInstanceError, replace
import unittest

from ronas_api.d1_data_evidence_preflight import (
    CONTRACT_VERSION, D1_EVIDENCE_IDS, InternalEvidencePointer,
    PURPOSES, evidence_preflight,
)


def pointer(evidence="D1-DATA-E01", purpose="HOUSEHOLD_CULTIVATION_PLAN",
            ref="DEMO-DOC-001", **overrides):
    values = {
        "evidence_id": evidence,
        "document_ref": ref,
        "version": 1,
        "manifest_sha256": "a" * 64,
        "purpose": purpose,
    }
    values.update(overrides)
    return InternalEvidencePointer(**values)


class D1DataEvidencePreflightTests(unittest.TestCase):
    def assert_blocked(self, report):
        self.assertEqual(report["contract_version"], CONTRACT_VERSION)
        self.assertEqual(report["engine"], "DOMESTIC")
        self.assertEqual(report["inventory_state"], "INTERNAL_PREPARATION_NOT_ADMITTED")
        self.assertFalse(report["source_rights_verified"])
        self.assertFalse(report["service_purpose_consent_verified"])
        self.assertFalse(report["training_purpose_rights_verified"])
        self.assertFalse(report["expert_qualification_verified"])
        self.assertFalse(report["scientific_quality_verified"])
        self.assertFalse(report["business_gate_2_passed"])
        self.assertFalse(report["stage_or_production_admitted"])
        for action in (
            "allow_real_household_data_ingest", "allow_household_plan_ai",
            "allow_ai_training", "allow_specialist_plan_approval",
            "allow_cross_engine_data_use", "allow_marketplace_publication",
        ):
            self.assertIs(report[action], False, action)
        self.assertTrue(all(
            row["independent_review_verified"] is False
            and row["usable_authority"] is False
            for row in report["evidence_items"]
        ))

    def test_no_evidence_is_blocked_with_explicit_missing_slots(self):
        report = evidence_preflight()
        self.assertEqual(report["provided_pointer_count"], 0)
        self.assertEqual(report["candidate_review_slots"], len(D1_EVIDENCE_IDS) * 2)
        self.assertEqual(len(report["evidence_items"]), 14)
        self.assertTrue(all(
            row["preparation_status"] == "MISSING"
            for row in report["evidence_items"]
        ))
        self.assert_blocked(report)

    def test_single_draft_in_service_scope_does_not_authorize_service(self):
        report = evidence_preflight((pointer(),))
        self.assertEqual(report["provided_pointer_count"], 1)
        self.assertEqual(
            [row["preparation_status"] for row in report["evidence_items"]].count(
                "SUBMITTED_UNVERIFIED"
            ), 1,
        )
        service_item = next(row for row in report["evidence_items"]
                            if row["id"] == "D1-DATA-E01"
                            and row["purpose"] == "HOUSEHOLD_CULTIVATION_PLAN")
        training_item = next(row for row in report["evidence_items"]
                             if row["id"] == "D1-DATA-E01"
                             and row["purpose"] == "AI_TRAINING")
        self.assertEqual(service_item["draft_document_ref"], "DEMO-DOC-001")
        self.assertIsNone(training_item["draft_document_ref"])
        self.assert_blocked(report)

    def test_all_service_and_training_document_slots_cannot_auto_approve(self):
        refs = []
        for pi, purpose in enumerate(PURPOSES):
            for ix, identifier in enumerate(D1_EVIDENCE_IDS):
                refs.append(pointer(
                    identifier, purpose,
                    ref=f"DEMO-DOC-{pi}{ix}",
                    manifest_sha256=f"{pi + ix + 1:064x}",
                ))
        report = evidence_preflight(tuple(refs))
        self.assertEqual(report["provided_pointer_count"], 14)
        self.assertEqual(len(report["evidence_items"]), 14)
        self.assertTrue(all(
            row["preparation_status"] == "SUBMITTED_UNVERIFIED"
            for row in report["evidence_items"]
        ))
        self.assert_blocked(report)

    def test_same_document_identity_cannot_be_reused_to_assert_other_purpose(self):
        with self.assertRaises(ValueError):
            evidence_preflight((
                pointer(),
                pointer("D1-DATA-E01", "AI_TRAINING", "DEMO-DOC-001"),
            ))

    def test_per_purpose_distinct_docs_are_allowed_but_never_licensed(self):
        report = evidence_preflight((
            pointer(),
            pointer("D1-DATA-E01", "AI_TRAINING", "DEMO-DOC-002"),
        ))
        self.assertEqual(report["provided_pointer_count"], 2)
        self.assert_blocked(report)

    def test_identical_slot_or_repeated_object_refuses_duplicate_injection(self):
        first = pointer()
        for pair in (
            (first, first),
            (first, pointer(ref="DEMO-DOC-002")),
            (first, pointer(evidence="D1-DATA-E02")),
        ):
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                evidence_preflight(pair)

    def test_manifest_digest_and_version_change_snapshot_fingerprint(self):
        first = pointer()
        one = evidence_preflight((first,))["snapshot_digest"]
        two = evidence_preflight((replace(first, version=2),))["snapshot_digest"]
        three = evidence_preflight((
            replace(first, manifest_sha256="b" * 64),
        ))["snapshot_digest"]
        self.assertEqual(len(one), 64)
        self.assertNotEqual(one, two)
        self.assertNotEqual(one, three)
        self.assertNotEqual(two, three)
        self.assert_blocked(evidence_preflight((first,)))

    def test_snapshot_hash_is_deterministic_across_pointer_order(self):
        items = (
            pointer("D1-DATA-E02", ref="DEMO-DOC-002"),
            pointer("D1-DATA-E01", ref="DEMO-DOC-001"),
        )
        self.assertEqual(
            evidence_preflight(items)["snapshot_digest"],
            evidence_preflight(tuple(reversed(items)))["snapshot_digest"],
        )

    def test_unknown_evidence_id_cannot_claim_business_acceptance(self):
        for evidence in ("D1-DATA-E00", "D1-DATA-E08", "GATE-APPROVED",
                         "D1-DATA-E01\nPASS", None, True):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                pointer(evidence)

    def test_bad_digests_do_not_certify_real_science_or_rights(self):
        for d in ("", "A" * 64, "z" * 64, "a" * 63, "a" * 65,
                  "0x" + "a" * 64, None, 1):
            with self.subTest(digest=d), self.assertRaises(ValueError):
                pointer(manifest_sha256=d)

    def test_no_paths_or_freeform_actor_identifiers(self):
        for ref in ("", "../rights", "DEMO/001", "user@mail.com", "REAL-DOC",
                    "DEMO-DOC-A\n", None, 123, "DEMO-" + "Z" * 49):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                pointer(ref=ref)

    def test_status_cannot_be_self_asserted_as_verified(self):
        for status in ("VERIFIED", "APPROVED", "CONSENTED",
                       "RIGHTS_CLEARED", "ACTIVE", "WITHDRAWN",
                       "MISSING", None, True):
            with self.subTest(status=status), self.assertRaises(ValueError):
                pointer(status=status)

    def test_purposes_are_not_interchangeable_or_auto_extended(self):
        for purpose in ("DOMESTIC", "EXPORT", "PUBLIC_LISTING", "MARKETING",
                        "AI_TRAINING_AND_PLAN", None, True):
            with self.subTest(purpose=purpose), self.assertRaises(ValueError):
                pointer(purpose=purpose)

    def test_version_is_strict_positive_integer(self):
        for version in (True, False, 0, -1, 1.0, "1", None):
            with self.subTest(version=version), self.assertRaises(ValueError):
                pointer(version=version)

    def test_inventory_is_immutable_input_and_rejects_arbitrary_payload(self):
        for payload in ([], [pointer()], None, {}, (), ("D1-DATA-E01",), (None,)):
            if payload == ():
                continue
            with self.subTest(payload=repr(payload)), self.assertRaises(ValueError):
                evidence_preflight(payload)

    def test_dataclass_is_frozen_and_no_real_evidence_bytes_in_report(self):
        doc = pointer()
        with self.assertRaises(FrozenInstanceError):
            doc.status = "VERIFIED"
        report = evidence_preflight((doc,))
        self.assertNotIn("a" * 64, str(report))
        self.assertNotIn("owner_subject", str(report))
        self.assertNotIn("consent_signed", str(report))
        self.assert_blocked(report)


if __name__ == "__main__":
    unittest.main()
