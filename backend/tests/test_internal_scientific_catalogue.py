"""LOCAL/TEST Ronas-owned scientific candidate library history contract."""
from dataclasses import FrozenInstanceError, replace
import unittest

from ronas_api.internal_scientific_basis_contract import (
    ScientificSourceCandidate, ScientificBasisCandidate,
)
from ronas_api.internal_scientific_catalogue import (
    SyntheticScientificCatalogue, SyntheticSourceCatalogueEvent,
    RECORDED, WITHHELD,
)


def source(ref="DEMO-SOURCE-A", version=1, **changes):
    obj = dict(
        ref=ref, version=version, content_sha256="1" * 64,
        rights_document_ref="DEMO-RIGHTS-A",
        rights_document_sha256="2" * 64,
        science_review_request_ref="DEMO-SCIENCE-A",
        science_review_material_sha256="3" * 64,
    )
    obj.update(changes)
    return ScientificSourceCandidate(**obj)


def record(candidate, action="DEMO-ADD-A"):
    return SyntheticSourceCatalogueEvent(
        action_ref=action, source_ref=candidate.ref,
        source_revision=candidate.version,
        operation=RECORDED, candidate=candidate,
    )


def withhold(ref="DEMO-SOURCE-A", version=2, action="DEMO-HOLD-A"):
    return SyntheticSourceCatalogueEvent(
        action_ref=action, source_ref=ref, source_revision=version,
        operation=WITHHELD, reason_ref="DEMO-REASON-A",
    )


def make():
    return SyntheticScientificCatalogue().with_event(record(source()))


class SyntheticScientificCatalogueTests(unittest.TestCase):
    def test_first_revision_unverified_and_no_science_or_rights_forged(self):
        c = make()
        self.assertEqual(c.revision, 1)
        self.assertEqual(c.current_sources(), (source(),))
        out = c.redacted_summary()
        self.assertEqual(out["current_source_candidate_count"], 1)
        self.assertEqual(len(out["history_fingerprint_sha256"]), 64)
        self.assertFalse(out["source_bytes_attested"])
        self.assertFalse(out["rights_for_cultivation_service_verified"])
        self.assertFalse(out["rights_for_ai_training_verified"])
        self.assertFalse(out["scientific_suitability_verified"])
        self.assertFalse(out["qualified_specialist_verified"])
        self.assertFalse(out["approval_or_new_advice_authorized"])
        self.assertNotIn("DEMO-RIGHTS-A", str(out))
        self.assertNotIn("1" * 64, str(out))

    def test_deterministic_across_rebuild_and_source_order_in_current_snapshot(self):
        a = record(source(), action="DEMO-ADD-A")
        b = record(source(ref="DEMO-SOURCE-B"), action="DEMO-ADD-B")
        registry = SyntheticScientificCatalogue((a, b))
        again = SyntheticScientificCatalogue((a, b))
        self.assertEqual(registry.fingerprint, again.fingerprint)
        self.assertEqual([item.ref for item in registry.current_sources()],
                         ["DEMO-SOURCE-A", "DEMO-SOURCE-B"])
        self.assertNotEqual(registry.fingerprint,
                            SyntheticScientificCatalogue((b, a)).fingerprint)

    def test_revision_new_content_invalidates_old_basis(self):
        first = make()
        basis = ScientificBasisCandidate("DEMO-BASIS-A", 1, first.current_sources())
        self.assertEqual(first.inspect_basis_candidate(basis)
                         ["basis_state"], "PROVENANCE_PINNED_UNVERIFIED")
        second = first.with_event(record(
            source(version=2, content_sha256="4" * 64),
            action="DEMO-CHANGE-CONTENT",
        ))
        self.assertEqual(first.current_sources(), (source(),))
        self.assertNotEqual(second.fingerprint, first.fingerprint)
        with self.assertRaises(ValueError):
            second.inspect_basis_candidate(basis)
        comparison = second.compare(1, 2)
        self.assertEqual(comparison["changed_content_pointer_count"], 1)
        self.assertFalse(comparison["scientific_validity_verified"])

    def test_rights_and_scientific_material_are_distinct_changes(self):
        first = make()
        second = first.with_event(record(
            source(version=2, rights_document_sha256="5" * 64),
            action="DEMO-RIGHTS-UPDATE",
        ))
        third = second.with_event(record(
            source(version=3, rights_document_sha256="5" * 64,
                   science_review_material_sha256="6" * 64),
            action="DEMO-SCIENCE-UPDATE",
        ))
        self.assertEqual(third.compare(1, 2)
                         ["changed_service_rights_document_pointer_count"], 1)
        self.assertEqual(third.compare(2, 3)
                         ["changed_science_review_material_pointer_count"], 1)
        self.assertEqual(third.compare(1, 3)
                         ["changed_content_pointer_count"], 0)
        self.assertFalse(third.compare(1, 3)["ai_training_rights_verified"])
        self.assertFalse(third.compare(1, 3)["service_use_rights_verified"])

    def test_withheld_candidate_excluded_from_current_not_historical_snapshot(self):
        first = make()
        second = first.with_event(withhold())
        self.assertEqual(second.current_sources(), ())
        self.assertEqual(second.snapshot_at(1).current_sources(), (source(),))
        self.assertEqual(second.compare(1, 2)["withheld_candidate_count"], 1)
        self.assertEqual(len(second.events), 2)
        self.assertFalse(second.compare(1, 2)["historical_record_deleted"])
        basis = ScientificBasisCandidate("DEMO-BASIS-A", 1, (source(),))
        with self.assertRaises(ValueError):
            second.inspect_basis_candidate(basis)

    def test_reintroduce_requires_new_revision_after_withholding(self):
        withheld = make().with_event(withhold())
        newer = withheld.with_event(record(
            source(version=3, content_sha256="9" * 64),
            action="DEMO-RECORD-AGAIN",
        ))
        self.assertEqual(newer.current_sources()[0].version, 3)
        self.assertEqual(newer.compare(1, 3)["changed_content_pointer_count"], 1)
        self.assertEqual(withheld.current_sources(), ())

    def test_reject_duplicate_action_missing_versions_and_noop(self):
        first = make()
        invalid = (
            record(source(version=1), action="DEMO-NEXT"),
            record(source(version=3), action="DEMO-NEXT"),
            record(source(version=2), action="DEMO-ADD-A"),
        )
        for event in invalid:
            with self.subTest(event=event), self.assertRaises(ValueError):
                first.with_event(event)
        with self.assertRaises(ValueError):
            SyntheticScientificCatalogue((withhold(version=1),))
        with self.assertRaises(ValueError):
            make().with_event(withhold(version=3))
        with self.assertRaises(ValueError):
            make().with_event(withhold()).with_event(withhold(version=3))

    def test_invalid_operations_forged_approval_and_cross_purpose_fail_closed(self):
        for kwargs in (
            dict(action_ref="REAL-ACTION"), dict(source_ref="DEMO-OTHER"),
            dict(source_revision=True), dict(operation="APPROVED"),
            dict(operation=WITHHELD, candidate=source(), reason_ref="DEMO-REASON"),
            dict(operation=RECORDED, candidate=None),
            dict(operation=WITHHELD, candidate=None, reason_ref=None),
        ):
            values = dict(action_ref="DEMO-ADD-A", source_ref="DEMO-SOURCE-A",
                          source_revision=1, operation=RECORDED, candidate=source())
            values.update(kwargs)
            with self.subTest(values=values), self.assertRaises(ValueError):
                SyntheticSourceCatalogueEvent(**values)
        with self.assertRaises(ValueError):
            record(source(purpose="AI_TRAINING"))
        with self.assertRaises(ValueError):
            record(source(status="APPROVED"))

    def test_strict_snapshot_revision_validation_and_immutability(self):
        catalogue = make()
        for rev in (-1, 2, True, "1", None):
            with self.subTest(rev=rev), self.assertRaises(ValueError):
                catalogue.snapshot_at(rev)
        for a, b in ((0, 0), (1, 1), (1, 0), (-1, 1), (True, 1), (0, 3)):
            with self.subTest(a=a, b=b), self.assertRaises(ValueError):
                catalogue.compare(a, b)
        with self.assertRaises(FrozenInstanceError):
            catalogue.events = ()
        with self.assertRaises(FrozenInstanceError):
            catalogue.events[0].candidate = source(version=2)

    def test_unrelated_second_source_isolated_from_first_source_basis(self):
        catalogue = make()
        other = source(ref="DEMO-SOURCE-B", version=1,
                       rights_document_ref="DEMO-RIGHTS-B",
                       science_review_request_ref="DEMO-SCIENCE-B")
        c = catalogue.with_event(record(other, action="DEMO-ADD-B"))
        basis = ScientificBasisCandidate("DEMO-BASIS-A", 1, (source(),))
        self.assertEqual(c.inspect_basis_candidate(basis)
                         ["basis_state"], "PROVENANCE_PINNED_UNVERIFIED")
        c2 = c.with_event(record(
            replace(other, version=2, content_sha256="a" * 64),
            action="DEMO-B-REVISION",
        ))
        self.assertEqual(c2.inspect_basis_candidate(basis)
                         ["candidate_source_count"], 1)
