"""PostgreSQL integration tests for the private Domestic surplus ledger."""
import os
import secrets
import unittest
from concurrent.futures import ThreadPoolExecutor

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ronas_api.auth import Principal
from ronas_api.domestic_surplus_drafts_api import build_domestic_surplus_drafts_router
from ronas_api.household_input_profiles import HouseholdInputField, HouseholdInputSchema
from ronas_api.postgres_surplus_drafts import PostgresSurplusDraftLedger

DSN = os.environ.get("RONAS_TEST_POSTGRES_DSN")
OWNER = "postgres-surplus-owner"
HOUSEHOLD = "DEMO-H-" + secrets.token_hex(8).upper()
OFFER = "DEMO-OFFER-" + secrets.token_hex(8).upper()
SCHEMA = HouseholdInputSchema("RONAS-SURPLUS-TEST", 1, (
    HouseholdInputField("product", "Product", "text", required=True, max_length=80),
    HouseholdInputField("price", "Producer price", "text", required=True, max_length=40),
))


@unittest.skipUnless(DSN, "RONAS_TEST_POSTGRES_DSN is not configured")
class PostgresSurplusDraftLedgerTests(unittest.TestCase):
    def setUp(self):
        self.owner = OWNER + secrets.token_hex(6)
        self.household = "DEMO-H-" + secrets.token_hex(8).upper()
        self.offer = "DEMO-OFFER-" + secrets.token_hex(8).upper()
        self.authority = lambda principal, ref, schema: (
            principal.subject == self.owner and ref == self.household
            and schema == SCHEMA.schema_ref
        )
        self.key = secrets.token_bytes(32)
        self.scope_key = secrets.token_bytes(32)
        self.ledger = PostgresSurplusDraftLedger(
            DSN, SCHEMA, self.authority, self.key, self.scope_key,
        )
        self.principal = Principal(self.owner, frozenset({"household"}))

    def _save(self, action_id, expected, product="Tomato", price="owner-set"):
        return self.ledger.save(
            self.principal, self.household, self.offer, action_id=action_id,
            expected_revision=expected, values={"product": product, "price": price},
        )

    def test_encrypted_immutable_history_api_and_owner_scope(self):
        first = self._save("PG-SURPLUS-1", 0)
        second = self._save("PG-SURPLUS-2", 1, product="Cucumber")
        self.assertEqual((first.revision, second.revision), (1, 2))
        self.assertEqual(self.ledger.history_owned(
            self.principal, self.household, self.offer,
        ), (first, second))
        self.assertEqual(self.ledger.list_owned(
            self.principal, self.household,
        ), (second,))
        with psycopg.connect(DSN) as db:
            stored = db.execute("""SELECT owner_hash,owner_ciphertext,values_ciphertext
                FROM ronas_domestic_surplus_draft_revision WHERE household_ref=%s""",
                (self.household,)).fetchall()
        with self.assertRaises(psycopg.errors.RaiseException):
            with psycopg.connect(DSN) as db:
                db.execute("UPDATE ronas_domestic_surplus_draft_revision SET revision=9 WHERE household_ref=%s",
                           (self.household,))
        self.assertNotIn(self.owner.encode(), bytes(stored[0][1]))
        self.assertNotIn(b"owner-set", bytes(stored[0][2]))
        self.assertEqual(self.ledger.read_owned(
            self.principal, self.household, self.offer,
        ), second)
        app = FastAPI()
        app.include_router(build_domestic_surplus_drafts_router(
            self.ledger, lambda: self.principal,
        ))
        client = TestClient(app)
        path = (f"/api/v1/domestic/household-intake/my-drafts/{self.household}"
                f"/surplus-offers/{self.offer}")
        self.assertEqual(client.get(path).json()["revision"], 2)
        self.assertEqual(client.get(path + "/revisions").json()["revisions"][-1]["revision"], 2)

    def test_replay_conflict_stale_revision_and_owner_checks(self):
        first = self._save("PG-SURPLUS-REPLAY", 0)
        self.assertEqual(self._save("PG-SURPLUS-REPLAY", 0), first)
        with self.assertRaises(ValueError):
            self._save("PG-SURPLUS-REPLAY", 0, product="Different")
        with self.assertRaises(ValueError):
            self._save("PG-SURPLUS-STALE", 0)
        other = Principal("other-owner", frozenset({"household"}))
        with self.assertRaises(LookupError):
            self.ledger.read_owned(other, self.household, self.offer)

    def test_concurrent_compare_and_swap_allows_one_revision(self):
        def save(index):
            try:
                self._save("PG-SURPLUS-RACE-" + str(index), 0)
                return "saved"
            except ValueError:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, (1, 2)))
        self.assertCountEqual(results, ["saved", "conflict"])
        self.assertEqual(self.ledger.read_owned(
            self.principal, self.household, self.offer,
        ).revision, 1)
