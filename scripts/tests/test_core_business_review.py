"""Business decision dossier integrity tests with negative tamper cases."""
from pathlib import Path
import json
import shutil
import tempfile
import unittest

from scripts.check_core_business_review import (
    BUSINESS_SOURCES, MANIFEST, ReviewContractError,
    validate_business_review,
)

BASE = Path(__file__).resolve().parents[2]


class CoreBusinessReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in (*BUSINESS_SOURCES, MANIFEST):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BASE / name, p)

    def replace(self, name, old, new):
        p = self.root / name
        content = p.read_text(encoding="utf-8")
        if old not in content:
            raise AssertionError("fixture replacement unavailable")
        p.write_text(content.replace(old, new, 1), encoding="utf-8")

    def test_source_packet_all_three_domains_stays_draft(self):
        data = validate_business_review(self.root)
        self.assertTrue(data["all_gates_open_at_source"])
        self.assertFalse(data["business_admission_authorized"])
        self.assertFalse(data["payment_authorized"])
        self.assertEqual(data["financial_source_arithmetic"][
            "arithmetic_difference"], 11405)
        self.assertEqual(len(data["source_sha256"]), 7)

    def test_source_manifest_refuses_silent_gate_pass(self):
        self.replace(MANIFEST, '"state": "OPEN"', '"state": "PASS"')
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_source_manifest_refuses_unauthorized_personal_data(self):
        self.replace(MANIFEST, '"live_data_processing_authorized": false',
                     '"live_data_processing_authorized": true')
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_source_manifest_refuses_conflating_domains(self):
        self.replace(MANIFEST, '"domain": "EXPORT"', '"domain": "DOMESTIC"')
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_missing_business_contract_source_is_fatal(self):
        (self.root / BUSINESS_SOURCES[3]).unlink()
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_domestic_public_listing_two_condition_approval_is_pinned(self):
        self.replace(MANIFEST, '"NO_PUBLIC_OFFER_WITHOUT_PRODUCER_AND_QC"',
                     '"PUBLIC_OFFER_BY_AUTOMATION"')
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_finance_numbers_cannot_be_reclassified_by_document_edit(self):
        self.replace(BUSINESS_SOURCES[0], "۱۸٬۹۱۵", "۱۸٬۹۱۶")
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_finance_packet_does_not_override_source(self):
        self.replace(BUSINESS_SOURCES[6], "۱۱٬۴۰۵", "۱۱٬۴۰۶")
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_decision_packet_cannot_relabel_as_approved(self):
        self.replace(BUSINESS_SOURCES[5], "DRAFT DECISION REQUEST",
                     "APPROVED LIVE BUSINESS DECISION")
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_unknown_source_location_and_automatic_approval_disallowed(self):
        p = self.root / MANIFEST
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["dossiers"][0]["source"] = "../../secret.md"
        p.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)


if __name__ == "__main__":
    unittest.main()
