import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ronas_api.auth import Principal
from ronas_api.domestic_surplus_drafts import SqliteSyntheticSurplusDraftLedger
from ronas_api.domestic_surplus_publication import PublicationAuthorities
from ronas_api.domestic_surplus_publication import OfferRevision
from ronas_api.domestic_surplus_publication_api import build_domestic_surplus_publication_router
from ronas_api.domestic_surplus_producer_consent import (
    ProducerConsentConflict, ProducerConsentIntegrityError,
    SqliteSyntheticProducerConsentLedger,
)
from ronas_api.household_input_profiles import HouseholdInputField, HouseholdInputSchema


def schema(version=1):
    return HouseholdInputSchema(
        "demo-surplus-v1", version,
        (HouseholdInputField("product_ref", "Product reference", required=True),),
    )


class ProducerConsentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = str(Path(self.tmp.name) / "ledger.sqlite3")
        self.owner = Principal("producer-demo", frozenset({"household"}))
        self.other = Principal("other-producer", frozenset({"household"}))
        authority = lambda p, ref, schema_ref: (
            p.subject == "producer-demo" and ref == "DEMO-H-01"
            and schema_ref == "demo-surplus-v1"
        )
        self.drafts = SqliteSyntheticSurplusDraftLedger(
            self.database, schema(), authority,
        )
        self.consent = SqliteSyntheticProducerConsentLedger(
            str(Path(self.tmp.name) / "consent.sqlite3"), self.drafts,
        )
        self.first = self.drafts.save(
            self.owner, "DEMO-H-01", "DEMO-OFFER-01", action_id="DRAFT-1",
            expected_revision=0, values={"product_ref": "DEMO-PRODUCT-1"},
        )

    def record(self, action="CONSENT-1", approved=True, **overrides):
        values = {
            "expected_offer_revision": self.first.revision,
            "expected_payload_digest": self.first.payload_digest,
            "action_id": action, "approved": approved,
        }
        values.update(overrides)
        return self.consent.record(
            self.owner, "DEMO-H-01", "DEMO-OFFER-01", **values,
        )

    def test_explicit_approval_is_bound_to_exact_owner_and_offer_version(self):
        first = self.record()
        self.assertEqual(first.state, "APPROVED")
        self.assertEqual(first.offer_revision, self.first.revision)
        self.assertEqual(first.payload_digest, self.first.payload_digest)
        self.assertEqual(self.consent.current(
            self.owner, "DEMO-H-01", "DEMO-OFFER-01",
        ), first)
        self.assertEqual(self.record(), first)  # idempotent retry

    def test_withdrawal_appends_and_replaces_current_approval(self):
        approved = self.record()
        withdrawn = self.record("CONSENT-2", False)
        self.assertEqual(withdrawn.state, "WITHDRAWN")
        self.assertEqual(withdrawn.revision, approved.revision + 1)
        self.assertEqual(self.consent.current(
            self.owner, "DEMO-H-01", "DEMO-OFFER-01",
        ), withdrawn)
        with sqlite3.connect(str(Path(self.tmp.name) / "consent.sqlite3")) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM domestic_surplus_producer_consent"
            ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_offer_update_makes_old_consent_non_current_and_rejects_stale_write(self):
        approval = self.record()
        self.drafts.save(
            self.owner, "DEMO-H-01", "DEMO-OFFER-01", action_id="DRAFT-2",
            expected_revision=1, values={"product_ref": "DEMO-PRODUCT-2"},
        )
        self.assertIsNone(self.consent.current(
            self.owner, "DEMO-H-01", "DEMO-OFFER-01",
        ))
        with self.assertRaises(ProducerConsentConflict):
            self.record("CONSENT-STALE")
        self.assertEqual(approval.offer_revision, 1)

    def test_cross_owner_wrong_role_and_forged_replay_fail_closed(self):
        self.record()
        with self.assertRaises(LookupError):
            self.consent.current(self.other, "DEMO-H-01", "DEMO-OFFER-01")
        with self.assertRaises(LookupError):
            self.consent.record(
                Principal("staff", frozenset({"domestic_ops"})),
                "DEMO-H-01", "DEMO-OFFER-01",
                expected_offer_revision=1,
                expected_payload_digest=self.first.payload_digest,
                action_id="CONSENT-STAFF", approved=True,
            )
        with self.assertRaises(ProducerConsentConflict):
            self.record(approved=False)

    def test_consent_history_tampering_and_missing_triggers_fail_closed(self):
        self.record()
        path = str(Path(self.tmp.name) / "consent.sqlite3")
        with sqlite3.connect(path) as db:
            db.execute("DROP TRIGGER producer_consent_no_update")
            db.execute("UPDATE domestic_surplus_producer_consent SET state='WITHDRAWN'")
        with self.assertRaises(ProducerConsentIntegrityError):
            self.consent.current(self.owner, "DEMO-H-01", "DEMO-OFFER-01")

    def test_http_consent_updates_readiness_but_never_bypasses_quality_gate(self):
        draft = self.first
        current = OfferRevision(
            draft.offer_ref, draft.household_ref, draft.producer_subject,
            draft.revision, draft.payload_digest,
        )
        authority = lambda principal, household_ref, offer_ref: (
            current, PublicationAuthorities(current_offer=current),
        )
        app = FastAPI()
        app.include_router(build_domestic_surplus_publication_router(
            authority, lambda: self.owner, self.drafts,
            producer_consent_ledger=self.consent,
        ))
        client = TestClient(app)
        root = ("/api/v1/domestic/household-intake/my-drafts/DEMO-H-01/"
                "surplus-offers/DEMO-OFFER-01")
        command = {
            "expected_offer_revision": draft.revision,
            "expected_payload_digest": draft.payload_digest,
            "action_id": "HTTP-CONSENT-1", "approved": True,
        }
        response = client.post(root + "/producer-publication-consent",
                               json=command,
                               headers={"Authorization": "Bearer local-test"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["state"], "APPROVED")
        approved = client.get(root + "/publication-readiness").json()
        self.assertNotIn("PRODUCER_APPROVAL_REQUIRED", approved["blockers"])
        self.assertIn("QUALITY_SAFETY_VERIFICATION_REQUIRED", approved["blockers"])
        self.assertFalse(approved["can_publish"])
        self.assertFalse(approved["published"])
        command.update(action_id="HTTP-CONSENT-2", approved=False)
        response = client.post(root + "/producer-publication-consent",
                               json=command,
                               headers={"Authorization": "Bearer local-test"})
        self.assertEqual(response.status_code, 201, response.text)
        withdrawn = client.get(root + "/publication-readiness").json()
        self.assertIn("PRODUCER_APPROVAL_REQUIRED", withdrawn["blockers"])
        self.assertIn("QUALITY_SAFETY_VERIFICATION_REQUIRED", withdrawn["blockers"])
        self.assertFalse(withdrawn["published"])

    def test_database_prevents_mutating_or_deleting_approval_history(self):
        self.record()
        path = str(Path(self.tmp.name) / "consent.sqlite3")
        for statement in (
            "UPDATE domestic_surplus_producer_consent SET state='WITHDRAWN'",
            "DELETE FROM domestic_surplus_producer_consent",
        ):
            with sqlite3.connect(path) as db:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(statement)


if __name__ == "__main__":
    unittest.main()
