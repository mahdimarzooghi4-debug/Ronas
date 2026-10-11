"""Only LOCAL/TEST Ronas-internal science provenance; no actual crop science."""
from dataclasses import FrozenInstanceError, replace
import unittest

from ronas_api.internal_scientific_basis_contract import (
    CONTRACT_VERSION, PURPOSE, SOURCE_STATUS,
    ScientificBasisCandidate, ScientificSourceCandidate,
    inspect_scientific_basis_structure,
)


def source(**changes):
    kwargs = dict(
        ref="DEMO-SOURCE-01", version=1,
        content_sha256="1" * 64,
        rights_document_ref="DEMO-RIGHTS-01",
        rights_document_sha256="2" * 64,
        science_review_request_ref="DEMO-REVIEW-01",
        science_review_material_sha256="3" * 64,
        purpose=PURPOSE, status=SOURCE_STATUS,
    )
    kwargs.update(changes)
    return ScientificSourceCandidate(**kwargs)


def basis(*sources, **changes):
    kwargs = dict(ref="DEMO-BASIS-01", version=1, sources=tuple(sources))
    kwargs.update(changes)
    return ScientificBasisCandidate(**kwargs)


_UNSET = object()


def inspect(value, current_sources=_UNSET, **changes):
    if current_sources is _UNSET:
        current_sources = value.sources
    options = dict(
        expected_manifest_digest=value.manifest_digest,
        current_sources=current_sources,
    )
    options.update(changes)
    return inspect_scientific_basis_structure(value, **options)


class RonasInternalScientificBasisTests(unittest.TestCase):
    def test_single_source_lineage_still_has_zero_rights_or_science(self):
        item = basis(source())
        trace = inspect(item)
        self.assertEqual(trace["contract_version"], CONTRACT_VERSION)
        self.assertEqual(trace["purpose"], PURPOSE)
        self.assertEqual(trace["basis_revision"], 1)
        self.assertEqual(trace["candidate_source_count"], 1)
        self.assertEqual(trace["basis_state"], "PROVENANCE_PINNED_UNVERIFIED")
        for flag in (
            "scientific_validity_verified", "source_material_retrieved_and_attested",
            "rights_for_household_plan_verified", "rights_for_ai_training_verified",
            "internal_expert_qualification_verified", "plan_review_approved",
            "new_advice_enabled", "actual_crop_content_present",
            "business_gate_passed",
        ):
            self.assertIs(trace[flag], False)
        for forbidden in ("DEMO-RIGHTS-01", "DEMO-REVIEW-01", "content_sha256",
                          "rights_document_sha256", "planting_advice"):
            self.assertNotIn(forbidden, str(trace))

    def test_basis_digest_is_canonical_order_independent(self):
        a = source()
        b = source(
            ref="DEMO-SOURCE-02",
            rights_document_ref="DEMO-RIGHTS-02",
            science_review_request_ref="DEMO-REVIEW-02",
        )
        first = basis(a, b)
        second = basis(b, a)
        self.assertEqual(first.manifest_digest, second.manifest_digest)
        self.assertEqual(inspect(first, current_sources=(b, a))["candidate_source_count"], 2)

    def test_any_changed_source_or_rights_or_review_version_changes_digest(self):
        first = basis(source())
        changed = (
            source(version=2),
            source(content_sha256="4" * 64),
            source(rights_document_ref="DEMO-RIGHTS-02"),
            source(rights_document_sha256="5" * 64),
            source(science_review_request_ref="DEMO-REVIEW-02"),
            source(science_review_material_sha256="6" * 64),
        )
        for item in changed:
            with self.subTest(item=item):
                self.assertNotEqual(first.manifest_digest,
                                    basis(item).manifest_digest)
                with self.assertRaises(ValueError):
                    inspect(first, current_sources=(item,))

    def test_basis_version_or_identity_change_changes_manifest_digest(self):
        original = basis(source())
        self.assertNotEqual(original.manifest_digest,
                            replace(original, version=2).manifest_digest)
        self.assertNotEqual(original.manifest_digest,
                            replace(original, ref="DEMO-BASIS-02").manifest_digest)

    def test_missing_or_duplicate_latest_source_never_passes(self):
        a = source()
        original = basis(a)
        with self.assertRaises(ValueError):
            inspect(original, current_sources=())
        with self.assertRaises(ValueError):
            inspect(original, current_sources=(a, a))

    def test_other_unrelated_current_sources_do_not_modify_this_basis(self):
        a = source()
        b = source(ref="DEMO-SOURCE-02",
                   rights_document_ref="DEMO-RIGHTS-02",
                   science_review_request_ref="DEMO-REVIEW-02")
        trace = inspect(basis(a), current_sources=(b, a))
        self.assertEqual(trace["candidate_source_count"], 1)

    def test_stale_and_self_asserted_expected_manifest_fail_closed(self):
        b = basis(source())
        for digest in ("0" * 64, "", "A" * 64, None, True):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                inspect(b, expected_manifest_digest=digest)

    def test_no_source_science_manifest_or_duplicates_allowed(self):
        for values in ((), (source(), source()), ("fake-source",)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                basis(*values)
        for values in ([], None, "fake", (source(), 12)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                basis(sources=values)

    def test_source_identifier_and_version_must_be_explicit_local_values(self):
        for ref in ("", "SOURCE", "DEMO-../bad", "DEMO/SRC", 9, None):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                source(ref=ref)
        for version in (0, -2, True, False, "1", 1.0, None):
            with self.subTest(version=version), self.assertRaises(ValueError):
                source(version=version)
            with self.subTest(basis_version=version), self.assertRaises(ValueError):
                basis(source(), version=version)

    def test_invalid_raw_content_and_evidence_hash_is_denied(self):
        for field in ("content_sha256", "rights_document_sha256",
                      "science_review_material_sha256"):
            for value in ("", "a" * 63, "A" * 64, "z" * 64, None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    source(**{field: value})

    def test_no_rights_or_science_review_ref_can_be_faked_as_real_url(self):
        for field in ("rights_document_ref", "science_review_request_ref"):
            for value in ("", "https://external.example", "../private", 42,
                          "REAL-APPROVED", None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    source(**{field: value})

    def test_training_or_export_scope_and_auto_approved_status_forbidden(self):
        for purpose in ("EXPORT", "AI_TRAINING", "DOMESTIC_AND_EXPORT",
                        "PUBLICATION", "DOMESTIC_CULTIVATION_PLAN_APPROVED",
                        "", None):
            with self.subTest(purpose=purpose), self.assertRaises(ValueError):
                source(purpose=purpose)
            with self.subTest(basis_purpose=purpose), self.assertRaises(ValueError):
                basis(source(), purpose=purpose)
        for status in ("REVIEWED", "LICENSED", "APPROVED", "PROVEN",
                       "SCIENCE_VALIDATED", "RIGHTS_VERIFIED", None):
            with self.subTest(status=status), self.assertRaises(ValueError):
                source(status=status)

    def test_only_immutable_typed_source_snapshot_is_admitted(self):
        item = basis(source())
        for latest in ([], None, "current", (None,), (dict(),)):
            with self.subTest(latest=latest), self.assertRaises(ValueError):
                inspect(item, current_sources=latest)

    def test_versioned_source_records_are_immutable(self):
        obj = source()
        with self.assertRaises(FrozenInstanceError):
            obj.content_sha256 = "f" * 64
        with self.assertRaises(FrozenInstanceError):
            basis(obj).version = 2

    def test_cannot_replace_pure_source_with_plain_dictionary(self):
        obj = basis(source())
        with self.assertRaises(ValueError):
            inspect_scientific_basis_structure(
                {"sources": []}, expected_manifest_digest=obj.manifest_digest,
                current_sources=obj.sources,
            )
        with self.assertRaises(ValueError):
            inspect_scientific_basis_structure(
                obj, expected_manifest_digest=obj.manifest_digest,
                current_sources=({"ref": "DEMO-SOURCE-01"},),
            )


if __name__ == "__main__":
    unittest.main()
