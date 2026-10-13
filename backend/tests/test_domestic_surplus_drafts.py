import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ronas_api.auth import Principal
from ronas_api.domestic_surplus_drafts import (
    SqliteSyntheticSurplusDraftLedger, SurplusDraftConflict,
)
from ronas_api.household_input_profiles import HouseholdInputField, HouseholdInputSchema


def schema(version=1):
    return HouseholdInputSchema(
        "demo-surplus-v1", version,
        (
            HouseholdInputField("product_ref", "Product reference", required=True),
            HouseholdInputField("availability_note", "Availability note", max_length=120),
        ),
    )


class SurplusDraftLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.owner = Principal("producer-demo", frozenset({"household"}))
        self.other = Principal("other-producer", frozenset({"household"}))
        self.ledger = SqliteSyntheticSurplusDraftLedger(
            str(Path(self.tmp.name) / "drafts.sqlite3"), schema(),
        )

    def save(self, action="action-001", expected=0, values=None):
        return self.ledger.save(
            self.owner, "DEMO-H-01", "DEMO-OFFER-01",
            action_id=action, expected_revision=expected,
            values=values or {"product_ref": "DEMO-PRODUCT-01", "availability_note": ""},
        )

    def test_create_and_update_are_private_immutable_versioned_receipts(self):
        first = self.save()
        second = self.save("action-002", 1, {
            "product_ref": "DEMO-PRODUCT-01", "availability_note": "updated",
        })
        self.assertEqual(first.revision, 1)
        self.assertEqual(second.revision, 2)
        self.assertEqual(second.previous_receipt_digest, first.receipt_digest)
        self.assertNotEqual(second.payload_digest, first.payload_digest)
        self.assertFalse(first.published)
        self.assertFalse(second.published)
        self.assertFalse(second.real_data)
        self.assertEqual(self.ledger.read_owned(
            self.owner, "DEMO-H-01", "DEMO-OFFER-01",
        ), second)

    def test_compare_and_swap_rejects_stale_revision_without_mutating_history(self):
        first = self.save()
        with self.assertRaises(SurplusDraftConflict):
            self.save("action-002", 0)
        self.assertEqual(self.ledger.read_owned(
            self.owner, "DEMO-H-01", "DEMO-OFFER-01",
        ), first)

    def test_action_retry_is_idempotent_and_conflicting_replay_is_rejected(self):
        first = self.save()
        self.assertEqual(self.save(), first)
        with self.assertRaises(SurplusDraftConflict):
            self.save(values={"product_ref": "DEMO-PRODUCT-02", "availability_note": ""})

    def test_cross_owner_and_wrong_role_cannot_read_or_write(self):
        with self.assertRaises(LookupError):
            self.ledger.read_owned(self.other, "DEMO-H-01", "DEMO-OFFER-01")
        with self.assertRaises(LookupError):
            self.ledger.save(self.other, "DEMO-H-01", "DEMO-OFFER-01",
                             action_id="action-001", expected_revision=0,
                             values={"product_ref": "DEMO-PRODUCT-01"})
        with self.assertRaises(LookupError):
            self.ledger.read_owned(
                Principal("staff", frozenset({"admin"})),
                "DEMO-H-01", "DEMO-OFFER-01",
            )

    def test_injected_schema_controls_validation_and_is_bound_to_revision(self):
        with self.assertRaises(ValueError):
            self.save(values={"unknown": "must not pass"})
        other_schema = schema(version=2)
        other_ledger = SqliteSyntheticSurplusDraftLedger(
            str(Path(self.tmp.name) / "other.sqlite3"), other_schema,
        )
        record = other_ledger.save(
            self.owner, "DEMO-H-01", "DEMO-OFFER-02",
            action_id="action-003", expected_revision=0,
            values={"product_ref": "DEMO-PRODUCT-01", "availability_note": ""},
        )
        self.assertEqual(record.schema_version, 2)
        self.assertNotEqual(record.schema_digest, self.ledger.schema.digest)

    def test_history_rejects_update_and_delete(self):
        self.save()
        import sqlite3
        with sqlite3.connect(str(Path(self.tmp.name) / "drafts.sqlite3")) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "UPDATE domestic_surplus_draft_revision SET revision=9 "
                    "WHERE action_id='action-001'"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "DELETE FROM domestic_surplus_draft_revision "
                    "WHERE action_id='action-001'"
                )


if __name__ == "__main__":
    unittest.main()
