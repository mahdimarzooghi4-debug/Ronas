"""PostgreSQL integration tests for the private Domestic surplus ledger."""
import os
import json
import secrets
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.domestic_surplus_drafts_api import build_domestic_surplus_drafts_router
from ronas_api.household_input_profiles import (
    HouseholdInputField, HouseholdInputSchema,
    SqliteSyntheticHouseholdProfileLedger,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.postgres_surplus_drafts import PostgresSurplusDraftLedger
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant

DSN = os.environ.get("RONAS_TEST_POSTGRES_DSN")
OWNER = "synthetic-postgres-surplus-owner"
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

    def _save(self, action_id, expected, product="Tomato", price="owner-set",
              input_revision=None):
        return self.ledger.save(
            self.principal, self.household, self.offer, action_id=action_id,
            expected_revision=expected, values={"product": product, "price": price},
            input_revision=input_revision,
        )

    def test_receipt_binds_household_input_revision_and_replay(self):
        first = self._save("PG-SURPLUS-INPUT-LINEAGE", 0, input_revision=4)
        self.assertEqual(first.input_revision, 4)
        self.assertEqual(self._save(
            "PG-SURPLUS-INPUT-LINEAGE", 0, input_revision=4,
        ), first)
        with self.assertRaises(ValueError):
            self._save("PG-SURPLUS-INPUT-LINEAGE", 0, input_revision=5)

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

    def test_postgres_ledger_completes_authenticated_household_bff_flow(self):
        """The shared household UI can create, save, and read PG revisions."""
        origin = "https://ronas.example.test"
        signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing.public_key()))
        jwk.update({"kid": "pg-surplus-ui", "alg": "RS256", "use": "sig"})
        issuer, api, web = "https://identity.example.test/realms/ronas", "ronas-api", "ronas-web"
        config = KeycloakConfig(
            issuer, api, web, json.dumps({"keys": [jwk]}).encode(),
        )
        now = int(time.time())
        token = jwt.encode({
            "iss": issuer, "aud": api, "azp": web, "typ": "Bearer",
            "sub": self.owner, "iat": now - 5, "nbf": now - 5,
            "exp": now + 300,
            "resource_access": {api: {"roles": ["household"]}},
        }, signing, algorithm="RS256", headers={"kid": "pg-surplus-ui"})
        session = BrowserSession(
            self.owner, frozenset({"household"}), token, "csrf-pg-surplus",
            now + 300,
        )

        class SessionStore:
            def get_session(_self, sid):
                return session if sid == "pg-surplus-session" else None

            def revoke_session(_self, _sid):
                return None

        flow = BrowserOIDC(
            BrowserOIDCConfig(config, origin + "/api/auth/callback"),
            SessionStore(), lambda *_: None,
        )
        with tempfile.TemporaryDirectory() as directory:
            cases = SqliteSyntheticHouseholdProfileLedger(
                Path(directory) / "household.sqlite3",
                (ScopedDraft(
                    self.household, "DOMESTIC", self.owner, 1,
                    (ScopedGrant("synthetic-domestic-ops", "domestic_ops"),),
                ),),
                profile_schema=SCHEMA,
                trusted_revoke_authorizer=lambda *_: False,
                trusted_human_review_authorizer=lambda *_: False,
            )
            cases.append_owned_input_manifest(
                self.household, self.principal,
                action_id="DEMO-PG-INPUT-INITIAL", expected_case_version=1,
                expected_input_revision=0, synthetic_manifest_digest="a" * 64,
            )
            app = create_app(
                config, browser_flow=flow, scoped_registry=cases,
                technical_review_ledger=cases,
                household_profile_schema=SCHEMA,
                household_profile_access_authority=self.authority,
                household_surplus_draft_ledger=self.ledger,
            )
            client = TestClient(app, base_url=origin, follow_redirects=False)
            client.cookies.set("__Host-ronas_session", "pg-surplus-session")
            listing_path = f"/my-drafts/{self.household}/surplus-offers"
            listing = client.get(listing_path)
            self.assertEqual(listing.status_code, 200, listing.text)
            self.assertIn("شروع پیش‌نویس مازاد جدید", listing.text)
            started = client.get(listing_path + "/new")
            self.assertEqual(started.status_code, 303, started.text)
            edit_path = started.headers["location"]
            form_page = client.get(edit_path)
            self.assertEqual(form_page.status_code, 200, form_page.text)
            import re
            action_id = re.search(r'name="action_id" value="([^"]+)"', form_page.text)[1]
            offer_ref = re.search(r'name="offer_ref" value="([^"]+)"', form_page.text)[1]
            response = client.post(
                listing_path,
                data={
                    "csrf": session.csrf, "offer_ref": offer_ref,
                    "action_id": action_id, "expected_revision": "0",
                    "input_revision": "1",
                    "product": "Tomato", "price": "producer-owned",
                },
                headers={"Origin": origin},
            )
            self.assertEqual(response.status_code, 303, response.text)
            self.assertEqual(response.headers["location"], listing_path)
            saved_list = client.get(listing_path)
            self.assertEqual(saved_list.status_code, 200, saved_list.text)
            self.assertIn(offer_ref, saved_list.text)
            self.assertNotIn("producer-owned", saved_list.text)
            edit = client.get(edit_path)
            self.assertEqual(edit.status_code, 200, edit.text)
            self.assertIn("producer-owned", edit.text)
            history_path = f"/my-drafts/{self.household}/surplus-offers/{offer_ref}/revisions"
            history = client.get(history_path)
            self.assertEqual(history.status_code, 200, history.text)
            self.assertIn("producer-owned", history.text)
            saved = self.ledger.read_owned(
                self.principal, self.household, offer_ref,
            )
            self.assertEqual((saved.revision, saved.input_revision), (1, 1))
            cases.append_owned_input_manifest(
                self.household, self.principal,
                action_id="PG-INPUT-CORRECTED", expected_case_version=1,
                expected_input_revision=1, synthetic_manifest_digest="b" * 64,
            )
            stale_listing = client.get(listing_path)
            self.assertIn("اطلاعات خانوار تغییر کرده", stale_listing.text)
            self.assertNotIn("producer-owned", stale_listing.text)
            stale_post = client.post(
                listing_path,
                data={
                    "csrf": session.csrf, "offer_ref": offer_ref,
                    "action_id": action_id + "-STALE", "expected_revision": "1",
                    "input_revision": "1", "product": "Tomato",
                    "price": "producer-owned",
                },
                headers={"Origin": origin},
            )
            self.assertEqual(stale_post.status_code, 409, stale_post.text)
            self.assertEqual(self.ledger.read_owned(
                self.principal, self.household, offer_ref,
            ).revision, 1)
