"""Owner-only Domestic case listing: synthetic, read-only and default disabled."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
from threading import Barrier
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.grant_ledger_sqlite import SqliteSyntheticGrantLedger
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant, ScopedSyntheticDraftRegistry


ISS = "https://id.example.test/realms/ronas"
API, WEB = "ronas-api", "ronas-web"
ORIGIN = "https://ronas.example.test"
OWN = "/api/v1/domestic/household-intake/my-drafts"


def cases():
    return (
        ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-one", 3, (
            ScopedGrant("synthetic-staff-001", "domestic_ops"),
        )),
        ScopedDraft("DEMO-D-002", "DOMESTIC", "synthetic-household-one", 2, (
            ScopedGrant("synthetic-staff-001", "domestic_ops"),
        )),
        ScopedDraft("DEMO-D-003", "DOMESTIC", "synthetic-household-two", 4, (
            ScopedGrant("synthetic-staff-001", "domestic_ops"),
        )),
        ScopedDraft("DEMO-D-004", "DOMESTIC", "synthetic-household-one", 1, (
            ScopedGrant("synthetic-staff-002", "domestic_ops"),
        )),
        ScopedDraft("DEMO-E-001", "EXPORT", "synthetic-household-one", 2, (
            ScopedGrant("synthetic-export-staff", "export_ops"),
        ), source_ref="DEMO-SOURCE-001"),
    )


def revoke_authorizer(actor, engine, ref):
    return actor == "synthetic-controller"


class HouseholdOwnedDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "household-test-key", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "owned.db"
        self.ledger = self.reopen()
        self.client = TestClient(create_app(
            self.config, scoped_registry=self.ledger
        ), base_url=ORIGIN)

    def reopen(self):
        return SqliteSyntheticGrantLedger(
            self.path, cases(), trusted_revoke_authorizer=revoke_authorizer,
        )

    def headers(self, subject="synthetic-household-one", roles=("household",)):
        now = int(time.time())
        token = jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "sub": subject,
            "typ": "Bearer", "iat": now - 5, "nbf": now - 5, "exp": now + 500,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "household-test-key"})
        return {"Authorization": "Bearer " + token}

    def get(self, params=None, *, subject="synthetic-household-one",
            roles=("household",), client=None):
        return (client or self.client).get(
            OWN, params=params, headers=self.headers(subject, roles),
        )

    def own_audit(self):
        return [
            e for e in self.ledger.audit_snapshot()
            if e.access_mode == "HOUSEHOLD_OWNED_WORKLIST"
        ]

    def browser(self, *, subject="synthetic-household-one", roles=("household",),
                with_ledger=True):
        class SessionStore:
            def __init__(self):
                self.sessions = {}
            def get_session(self, sid):
                return self.sessions.get(sid)
            def revoke_session(self, sid):
                self.sessions.pop(sid, None)

        store = SessionStore()
        async def exchange(_code, _verifier):
            raise AssertionError("no real Keycloak is attached")
        flow = BrowserOIDC(
            BrowserOIDCConfig(
                self.config, ORIGIN + "/api/auth/callback",
            ), store, exchange,
        )
        sid = secrets.token_urlsafe(40)
        raw = self.headers(subject, roles)["Authorization"][7:]
        store.sessions[sid] = BrowserSession(
            subject, frozenset(roles), raw, secrets.token_urlsafe(32),
            int(time.time()) + 250,
        )
        registry = self.ledger if with_ledger else ScopedSyntheticDraftRegistry(cases())
        client = TestClient(create_app(
            self.config, flow, scoped_registry=registry,
        ), base_url=ORIGIN)
        client.cookies.set("__Host-ronas_session", sid)
        return client, store, sid

    def test_keyset_pages_reveal_only_exact_own_domestic_records(self):
        first = self.get({"limit": 2})
        self.assertEqual(first.status_code, 200, first.text)
        body = first.json()
        self.assertEqual(body["engine"], "DOMESTIC")
        self.assertEqual([i["ref"] for i in body["items"]],
                         ["DEMO-D-001", "DEMO-D-002"])
        self.assertEqual(body["next_cursor"], "DEMO-D-002")
        self.assertNotIn("DEMO-D-003", first.text)
        self.assertNotIn("DEMO-E-001", first.text)
        self.assertNotIn("total", body)
        for item in body["items"]:
            self.assertEqual(item["status"], "DRAFT_ONLY")
            self.assertFalse(item["purpose_consent_verified"])
            self.assertFalse(item["expert_approved"])
            self.assertFalse(item["plan_accepted"])
            self.assertNotIn("owner_subject", item)
        second = self.get({"limit": 2, "after_ref": body["next_cursor"]})
        self.assertEqual([i["ref"] for i in second.json()["items"]], ["DEMO-D-004"])
        self.assertIsNone(second.json()["next_cursor"])
        self.assertEqual([e.ref for e in self.own_audit()],
                         ["DEMO-D-001", "DEMO-D-002", "DEMO-D-004"])
        self.assertEqual(first.headers["cache-control"], "no-store")
        self.assertTrue(self.reopen().verify_integrity())

    def test_multiple_households_cannot_enumerate_one_another(self):
        other = self.get(subject="synthetic-household-two")
        self.assertEqual(other.status_code, 200)
        self.assertEqual([i["ref"] for i in other.json()["items"]],
                         ["DEMO-D-003"])
        self.assertNotIn("DEMO-D-001", other.text)
        self.assertNotIn("DEMO-E-001", other.text)
        self.assertEqual([e.ref for e in self.own_audit()], ["DEMO-D-003"])
        self.assertTrue(self.reopen().verify_integrity())

    def test_staff_and_nonowners_have_no_implicit_household_scope(self):
        for subject, roles in (
            ("synthetic-staff-001", ("domestic_ops",)),
            ("synthetic-household-one", ("domestic_ops",)),
            ("synthetic-unassigned", ("household",)),
            ("synthetic-export-staff", ("export_ops",)),
        ):
            with self.subTest(subject=subject, roles=roles):
                result = self.get(subject=subject, roles=roles)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["items"], [])
                self.assertIsNone(result.json()["next_cursor"])
        self.assertEqual(self.own_audit(), [])

    def test_household_owner_read_survives_operator_grant_revocation(self):
        self.ledger.revoke_grant(
            engine="DOMESTIC", ref="DEMO-D-001",
            subject="synthetic-staff-001", role="domestic_ops",
            actor="synthetic-controller", expected_grant_revision=0,
            action_id="DEMO-REVOKE-STAFF", reason_ref="DEMO-REASON-STAFF",
        )
        result = self.get()
        self.assertEqual(result.status_code, 200)
        self.assertIn("DEMO-D-001", result.text)
        self.assertNotIn("DEMO-D-003", result.text)
        reopened = TestClient(create_app(
            self.config, scoped_registry=self.reopen(),
        ), base_url=ORIGIN)
        self.assertIn("DEMO-D-001", self.get(client=reopened).text)
        self.assertTrue(self.reopen().verify_integrity())

    def test_invalid_access_token_fails_before_ownership_audit(self):
        self.assertEqual(self.client.get(OWN).status_code, 401)
        self.assertEqual(self.client.get(
            OWN, headers={"Authorization": "Bearer invalid"},
        ).status_code, 401)
        self.assertEqual(self.own_audit(), [])

    def test_invalid_cursor_and_page_size_do_not_leak_owners(self):
        for params in (
            {"limit": 0}, {"limit": 51}, {"limit": "invalid"},
            {"after_ref": "not-demo"},
        ):
            with self.subTest(params=params):
                response = self.get(params)
                self.assertEqual(response.status_code, 422)
                self.assertNotIn("DEMO-D-003", response.text)
        self.assertEqual(self.own_audit(), [])

    def test_audit_insert_failure_rolls_back_entire_owned_page(self):
        before = self.ledger.audit_snapshot()
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER block_owner_worklist BEFORE INSERT ON audit_event
                WHEN NEW.payload LIKE '%HOUSEHOLD_OWNED_WORKLIST%'
                BEGIN SELECT RAISE(ABORT, 'owner audit unavailable'); END;
            """)
        result = self.get()
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json(), {"detail": "SYNTHETIC_LEDGER_UNAVAILABLE"})
        self.assertNotIn("DEMO-D-001", result.text)
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER block_owner_worklist")
        self.assertEqual(self.reopen().audit_snapshot(), before)
        self.assertEqual(self.get().status_code, 200)
        self.assertTrue(self.reopen().verify_integrity())

    def test_corrupted_grant_history_never_returns_owner_data(self):
        self.ledger.revoke_grant(
            engine="DOMESTIC", ref="DEMO-D-001",
            subject="synthetic-staff-001", role="domestic_ops",
            actor="synthetic-controller", expected_grant_revision=0,
            action_id="DEMO-ACTION-BIND", reason_ref="DEMO-REASON-BIND",
        )
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER revocation_no_update")
            db.execute("UPDATE grant_revocation SET payload_digest=?", ("f" * 64,))
        response = self.get()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "SYNTHETIC_LEDGER_UNAVAILABLE"})
        self.assertNotIn("DEMO-D-002", response.text)

    def test_default_runtime_and_plain_registry_do_not_mount_owned_list(self):
        plain = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(plain.get(OWN, headers=self.headers()).status_code, 404)
        scoped = TestClient(create_app(
            self.config, scoped_registry=ScopedSyntheticDraftRegistry(cases()),
        ), base_url=ORIGIN)
        self.assertEqual(scoped.get(OWN, headers=self.headers()).status_code, 404)
        self.assertEqual(scoped.get(
            "/api/v1/domestic/household-intake/drafts/DEMO-D-001",
            headers=self.headers(),
        ).status_code, 200)
        self.assertEqual(self.client.post(
            OWN, headers=self.headers(), json={"status": "APPROVED"},
        ).status_code, 405)
        self.assertEqual(self.own_audit(), [])

    def test_shared_user_shell_lists_owned_cases_not_static_fixture(self):
        client, _, _ = self.browser()
        result = client.get("/")
        self.assertEqual(result.status_code, 200)
        for ref in ("DEMO-D-001", "DEMO-D-002", "DEMO-D-004"):
            self.assertIn(ref, result.text)
        self.assertNotIn("DEMO-D-003", result.text)
        self.assertNotIn("DEMO-E-001", result.text)
        self.assertNotIn("DEMO-H01", result.text)
        self.assertIn("پرونده‌های من", result.text)
        self.assertIn("/drafts/DEMO-D-001", result.text)
        self.assertIn("DRAFT_ONLY", result.text)
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertIn("frame-ancestors 'none'", result.headers["content-security-policy"])
        self.assertTrue(self.reopen().verify_integrity())

    def test_user_shell_only_renders_household_rows_for_owner_role(self):
        staff, _, _ = self.browser(
            subject="synthetic-staff-001", roles=("domestic_ops",),
        )
        content = staff.get("/").text
        self.assertNotIn("DEMO-D-001", content)
        self.assertNotIn("پرونده‌های من", content)
        other, _, _ = self.browser(subject="synthetic-household-two")
        html = other.get("/").text
        self.assertIn("DEMO-D-003", html)
        self.assertNotIn("DEMO-D-001", html)
        empty, _, _ = self.browser(subject="synthetic-unassigned")
        body = empty.get("/").text
        self.assertNotIn("DEMO-D-001", body)
        self.assertIn("متعلق به این حساب وجود ندارد", body)

    def test_explicit_opt_in_required_for_live_household_html(self):
        plain, _, _ = self.browser(with_ledger=False)
        self.assertEqual(plain.get("/").status_code, 200)
        self.assertNotIn("پرونده‌های من", plain.get("/").text)
        self.assertNotIn("DEMO-D-001", plain.get("/").text)
        self.assertIn("DEMO-H01", plain.get("/").text)

    def test_logout_hides_owned_data_and_does_not_append_audit(self):
        client, store, sid = self.browser()
        self.assertEqual(client.get("/").status_code, 200)
        before = len(self.ledger.audit_snapshot())
        store.revoke_session(sid)
        result = client.get("/")
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("DEMO-D-001", result.text)
        self.assertNotIn("پرونده‌های من", result.text)
        self.assertEqual(len(self.ledger.audit_snapshot()), before)

    def test_user_shell_invalid_cursor_and_corrupted_ledger_fail_closed(self):
        client, _, _ = self.browser()
        self.assertEqual(client.get("/?household_after_ref=bad").status_code, 422)
        self.assertEqual(self.own_audit(), [])
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE metadata SET value=? WHERE key='head_digest'",
                       ("f" * 64,))
        response = client.get("/")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("DEMO-D-001", response.text)

    def test_concurrent_household_list_and_staff_revocation_are_ordered(self):
        barrier = Barrier(2)

        def owned_read():
            client = TestClient(create_app(
                self.config, scoped_registry=self.reopen(),
            ), base_url=ORIGIN)
            barrier.wait(timeout=12)
            return client.get(OWN, headers=self.headers())

        def staff_revoke():
            instance = self.reopen()
            barrier.wait(timeout=12)
            return instance.revoke_grant(
                engine="DOMESTIC", ref="DEMO-D-001",
                subject="synthetic-staff-001", role="domestic_ops",
                actor="synthetic-controller", expected_grant_revision=0,
                action_id="DEMO-CONCURRENT-REVOKE", reason_ref="DEMO-CONCURRENT-REASON",
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(owned_read), pool.submit(staff_revoke)
            page, revoked = a.result(), b.result()
        self.assertEqual(page.status_code, 200)
        self.assertIn("DEMO-D-001", page.text)
        events = self.reopen().audit_snapshot()
        self.assertEqual([x for x in events if x.kind == "GRANT_REVOKED"],
                         [revoked])
        self.assertIn("DEMO-D-001", self.get().text)
        self.assertTrue(self.reopen().verify_integrity())


if __name__ == "__main__":
    unittest.main()
