"""Business source rights triage: no candidate is an approved dataset or model corpus."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.check_core_business_review import (
    BUSINESS_SOURCES, MANIFEST, SOURCE_SCREEN_REGISTRY, SOURCE_SCREEN_DOC,
    ReviewContractError, validate_business_review,
)

BASE = Path(__file__).resolve().parents[2]


class OfficialSourceScreeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in (*BUSINESS_SOURCES, MANIFEST, SOURCE_SCREEN_DOC,
                     SOURCE_SCREEN_REGISTRY):
            dest = self.root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BASE / name, dest)

    def change(self, fn):
        p = self.root / SOURCE_SCREEN_REGISTRY
        data = json.loads(p.read_text("utf-8"))
        fn(data)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_five_real_source_term_screenings_remain_not_licensed(self):
        result = validate_business_review(self.root)
        self.assertEqual(result["source_screening"]["number_of_candidates"], 5)
        self.assertFalse(result["source_screening"]["authorized_for_ingestion"])
        self.assertFalse(result["source_screening"]["authorized_for_training"])
        self.assertEqual(result["source_screening"]["domestic_sources"], 2)
        self.assertEqual(result["source_screening"]["export_sources"], 3)
        self.assertTrue(result["all_gates_open_at_source"])

    def test_approved_rights_cannot_be_inferred(self):
        self.change(lambda d: d["candidates"][1].update(
            {"rights_for_ronas_verified": True}
        ))
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_licence_conflict_cannot_be_suppressed(self):
        self.change(lambda d: d["candidates"][0].update(
            {"review_flags": ["ATTRIBUTION_REQUIRED"]}
        ))
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_comtrade_cannot_be_marked_open_redistribution(self):
        self.change(lambda d: d["candidates"][4].update({
            "review_flags": ["UNRESTRICTED_REDISTRIBUTION"]
        }))
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_wrong_engine_scope_is_rejected(self):
        self.change(lambda d: d["candidates"][1].update({"domain": "EXPORT"}))
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_undocumented_new_candidate_requires_review(self):
        self.change(lambda d: d["candidates"].append(
            dict(d["candidates"][0], id="DOM-UNREVIEWED")
        ))
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_source_url_injection_is_rejected(self):
        self.change(lambda d: d["candidates"][2].update({
            "official_terms_urls": ["https://example.invalid/fake"]
        }))
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_training_and_download_are_independent_blockers(self):
        self.change(lambda d: d.update({"external_data_downloaded": True}))
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)
        self.change(lambda d: d.update({"external_data_downloaded": False,
                                         "model_training_approved": True}))
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_missing_rights_document_fails_closed(self):
        (self.root / SOURCE_SCREEN_DOC).unlink()
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)

    def test_unapproved_third_party_terms_cannot_be_removed(self):
        self.change(lambda d: d["candidates"][3].update({
            "review_flags": ["DATASET_BY_DATASET_LICENSE"]
        }))
        with self.assertRaises(ReviewContractError):
            validate_business_review(self.root)


if __name__ == "__main__":
    unittest.main()
