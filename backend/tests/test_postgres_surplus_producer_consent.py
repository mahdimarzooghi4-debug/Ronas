"""PostgreSQL integration tests for version-bound producer consent."""
import os
import secrets
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ronas_api.auth import Principal
from ronas_api.domestic_surplus_drafts import SurplusDraftConflict
from ronas_api.domestic_surplus_producer_consent import ProducerConsentConflict
from ronas_api.domestic_surplus_publication import OfferRevision, PublicationAuthorities
from ronas_api.domestic_surplus_publication_api import build_domestic_surplus_publication_router
from ronas_api.household_input_profiles import HouseholdInputField, HouseholdInputSchema
from ronas_api.postgres_surplus_drafts import PostgresSurplusDraftLedger
from ronas_api.postgres_surplus_producer_consent import PostgresSurplusProducerConsentLedger

DSN = os.environ.get("RONAS_TEST_POSTGRES_DSN")
OWNER = "synthetic-pg-consent-" + secrets.token_hex(5)
HOUSEHOLD = "DEMO-H-" + secrets.token_hex(8).upper()
OFFER = "DEMO-OFFER-" + secrets.token_hex(8).upper()
SCHEMA = HouseholdInputSchema("RONAS-SURPLUS-CONSENT-TEST", 1, (
    HouseholdInputField("product", "Product", "text", required=True, max_length=80),
))


@unittest.skipUnless(DSN, "RONAS_TEST_POSTGRES_DSN is not configured")
class PostgresSurplusProducerConsentTests(unittest.TestCase):
    def setUp(self):
        self.owner = OWNER + secrets.token_hex(5)
        self.household = "DEMO-H-" + secrets.token_hex(8).upper()
        self.offer_ref = "DEMO-OFFER-" + secrets.token_hex(8).upper()
        self.authority = lambda principal, ref, schema_ref: (
            principal.subject == self.owner and ref == self.household
            and schema_ref == SCHEMA.schema_ref
        )
        self.drafts = PostgresSurplusDraftLedger(
            DSN, SCHEMA, self.authority, secrets.token_bytes(32),
            secrets.token_bytes(32),
        )
        self.owner_principal = Principal(self.owner, frozenset({"household"}))
        self.other = Principal("other-consent-owner", frozenset({"household"}))
        self.consent = PostgresSurplusProducerConsentLedger(
            DSN, self.drafts, secrets.token_bytes(32), secrets.token_bytes(32),
        )
        self.draft = self.drafts.save(
            self.owner_principal, self.household, self.offer_ref,
            action_id="PG-CONSENT-DRAFT-" + secrets.token_hex(4),
            expected_revision=0, values={"product": "synthetic-product"},
        )

    def record(self, action=None, approved=True, revision=None, digest=None):
        return self.consent.record(
            self.owner_principal, self.household, self.offer_ref,
            expected_offer_revision=(self.draft.revision if revision is None else revision),
            expected_payload_digest=(self.draft.payload_digest if digest is None else digest),
            action_id=action or "PG-CONSENT-" + secrets.token_hex(5),
            approved=approved,
        )

    def test_encrypted_append_only_approval_withdrawal_and_idempotent_replay(self):
        action = "PG-CONSENT-APPROVE-" + secrets.token_hex(4)
        approved = self.record(action=action)
        self.assertEqual(approved.state, "APPROVED")
        self.assertEqual(self.consent.record(
            self.owner_principal, self.household, self.offer_ref,
            expected_offer_revision=self.draft.revision,
            expected_payload_digest=self.draft.payload_digest,
            action_id=action, approved=True,
        ), approved)
        withdrawn = self.record(approved=False)
        self.assertEqual(withdrawn.state, "WITHDRAWN")
        self.assertEqual(withdrawn.revision, approved.revision + 1)
        self.assertEqual(self.consent.current(
            self.owner_principal, self.household, self.offer_ref,
        ), withdrawn)
        with psycopg.connect(DSN) as db:
            stored = db.execute("""
                SELECT producer_hash,producer_ciphertext FROM
                ronas_domestic_surplus_producer_consent WHERE household_ref=%s
            """, (self.household,)).fetchall()
        self.assertNotIn(self.owner.encode(), bytes(stored[0][1]))
        with self.assertRaises(psycopg.errors.RaiseException):
            with psycopg.connect(DSN) as db:
                db.execute("""
                    UPDATE ronas_domestic_surplus_producer_consent
                    SET state='APPROVED' WHERE household_ref=%s
                """, (self.household,))

    def test_exact_revision_owner_isolation_and_old_consent_not_current(self):
        approved = self.record()
        with self.assertRaises(LookupError):
            self.consent.current(self.other, self.household, self.offer_ref)
        with self.assertRaises(ProducerConsentConflict):
            self.record(revision=self.draft.revision + 1)
        self.drafts.save(
            self.owner_principal, self.household, self.offer_ref,
            action_id="PG-CONSENT-DRAFT-UPDATE-" + secrets.token_hex(4),
            expected_revision=self.draft.revision,
            values={"product": "revised-synthetic-product"},
        )
        self.assertIsNone(self.consent.current(
            self.owner_principal, self.household, self.offer_ref,
        ))
        self.assertEqual(approved.offer_revision, 1)

    def test_concurrent_decisions_are_serialized_into_one_revision_chain(self):
        def record(index):
            return self.record(
                action="PG-CONSENT-RACE-" + str(index), approved=(index == 1),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(record, (1, 2)))
        self.assertCountEqual([item.revision for item in receipts], [1, 2])
        current = self.consent.current(
            self.owner_principal, self.household, self.offer_ref,
        )
        self.assertIn(current, receipts)

    def test_draft_edit_winning_lock_rejects_waiting_stale_consent(self):
        entering_connection = threading.Event()
        continue_consent = threading.Event()
        connect = self.consent._connect

        def paused_connect():
            entering_connection.set()
            if not continue_consent.wait(timeout=5):
                raise TimeoutError("consent test synchronization timed out")
            return connect()

        self.consent._connect = paused_connect
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                self.record, "PG-CONSENT-RACE-STALE-" + secrets.token_hex(4),
            )
            self.assertTrue(entering_connection.wait(timeout=5))
            revised = self.drafts.save(
                self.owner_principal, self.household, self.offer_ref,
                action_id="PG-CONSENT-DRAFT-RACE-" + secrets.token_hex(4),
                expected_revision=self.draft.revision,
                values={"product": "new-current-synthetic-product"},
            )
            continue_consent.set()
            with self.assertRaises(ProducerConsentConflict):
                pending.result(timeout=5)

        self.assertEqual(revised.revision, self.draft.revision + 1)
        self.assertIsNone(self.consent.current(
            self.owner_principal, self.household, self.offer_ref,
        ))

    def test_authenticated_api_readiness_keeps_independent_quality_gate(self):
        current = OfferRevision(
            self.draft.offer_ref, self.draft.household_ref,
            self.draft.producer_subject, self.draft.revision,
            self.draft.payload_digest,
        )
        app = FastAPI()
        app.include_router(build_domestic_surplus_publication_router(
            lambda *_: (current, PublicationAuthorities(current_offer=current)),
            lambda: self.owner_principal, self.drafts,
            producer_consent_ledger=self.consent,
        ))
        client = TestClient(app)
        base = (f"/api/v1/domestic/household-intake/my-drafts/{self.household}"
                f"/surplus-offers/{self.offer_ref}")
        response = client.post(
            base + "/producer-publication-consent",
            headers={"Authorization": "Bearer synthetic-test"},
            json={
                "expected_offer_revision": self.draft.revision,
                "expected_payload_digest": self.draft.payload_digest,
                "action_id": "PG-CONSENT-HTTP-" + secrets.token_hex(4),
                "approved": True,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        readiness = client.get(base + "/publication-readiness").json()
        self.assertNotIn("PRODUCER_APPROVAL_REQUIRED", readiness["blockers"])
        self.assertIn("QUALITY_SAFETY_VERIFICATION_REQUIRED", readiness["blockers"])
        self.assertFalse(readiness["can_publish"])
        self.assertFalse(readiness["published"])


if __name__ == "__main__":
    unittest.main()
