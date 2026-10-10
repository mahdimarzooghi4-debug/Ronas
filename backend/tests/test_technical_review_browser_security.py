"""End-to-end offline browser session -> scoped review GET security contract.

All identities, cases, keys and evidence are synthetic; no real Keycloak.
Tests exercise the actual PKCE callback and encrypted SQLite session adapter.
"""
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.human_review_sqlite import SqliteSyntheticHumanReviewLedger
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant
from ronas_api.session_sqlite import SqliteBrowserSessionStore


ISS = "https://id.example.test/realms/ronas"
ORIGIN = "https://ronas.example.test"
API, WEB = "ronas-api", "ronas-web"
DOM = "/api/v1/admin/domestic/household-intake/drafts/DEMO-D-001/technical-review"
EXP = "/api/v1/admin/export/research/drafts/DEMO-E-001/technical-review"
SID_COOKIE = "__Host-ronas_session"


def synthetic_records():
    return (
        ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-001", 3, (
            ScopedGrant("synthetic-domestic-001", "domestic_ops"),
            ScopedGrant("synthetic-domestic-002", "domestic_ops"),
        )),
        ScopedDraft("DEMO-E-001", "EXPORT", "synthetic-export-owner", 2, (
            ScopedGrant("synthetic-export-001", "export_ops"),
        ), source_ref="DEMO-SOURCE-01"),
    )


class BrowserReviewSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.private.public_key()))
        jwk.update({"kid": "local-key-1", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        key = secrets.token_bytes(32)
        self.store1 = SqliteBrowserSessionStore(root / "sessions.db", key)
        self.store2 = SqliteBrowserSessionStore(root / "sessions.db", key)
        self.ledger = SqliteSyntheticHumanReviewLedger(
            root / "review.db", synthetic_records(),
            trusted_revoke_authorizer=lambda actor, engine, ref: actor == "synthetic-authority",
            trusted_human_review_authorizer=lambda actor, engine, ref: (
                actor == "synthetic-domestic-002" and engine == "DOMESTIC"
                and ref == "DEMO-D-001"
            ),
        )
        self.subject = "synthetic-domestic-001"
        self.roles = ("domestic_ops",)
        self.nonce = None
        self.access = None
        opts = BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback", "/admin")

        async def exchange(code, verifier):
            self.access = self.token(self.subject, self.roles)
            identity = self.token(self.subject, (), identity=True, nonce=self.nonce)
            return {"token_type": "Bearer", "access_token": self.access,
                    "id_token": identity}

        self.flow1 = BrowserOIDC(opts, self.store1, exchange)
        self.flow2 = BrowserOIDC(opts, self.store2, exchange)
        self.client1 = TestClient(create_app(
            self.config, self.flow1, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
        ), base_url=ORIGIN, follow_redirects=False)
        self.client2 = TestClient(create_app(
            self.config, self.flow2, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
        ), base_url=ORIGIN, follow_redirects=False)

    def token(self, subject="synthetic-domestic-001", roles=("domestic_ops",),
              *, identity=False, nonce=None, **overrides):
        now = int(time.time())
        data = {
            "iss": ISS, "aud": WEB if identity else API,
            "sub": subject, "typ": "ID" if identity else "Bearer",
            "iat": now - 5, "exp": now + 600,
        }
        if identity:
            data["nonce"] = nonce
        else:
            data.update({
                "azp": WEB, "nbf": now - 5,
                "resource_access": {API: {"roles": list(roles)}},
            })
        data.update(overrides)
        return jwt.encode(data, self.private, algorithm="RS256",
                          headers={"kid": "local-key-1"})

    def login(self, *, subject="synthetic-domestic-001", roles=("domestic_ops",)):
        self.subject = subject
        self.roles = roles
        start = self.client1.get("/api/auth/start")
        self.assertEqual(start.status_code, 303)
        params = parse_qs(urlsplit(start.headers["location"]).query)
        self.nonce = params["nonce"][0]
        callback = self.client1.get("/api/auth/callback", params={
            "code": "synthetic-code", "state": params["state"][0],
        })
        self.assertEqual(callback.status_code, 303, callback.text)
        sid = self.client1.cookies.get(SID_COOKIE)
        self.assertTrue(sid)
        self.client2.cookies.set(SID_COOKIE, sid)
        return sid

    def request_review(self):
        self.ledger.request_evidence_review(
            engine="DOMESTIC", ref="DEMO-D-001",
            actor=Principal("synthetic-domestic-001", frozenset({"domestic_ops"})),
            expected_case_version=3, expected_review_revision=0,
            action_id="DEMO-REQ-ACT", request_ref="DEMO-REQUEST",
            evidence_ref="DEMO-EVIDENCE",
        )

    def test_real_pkce_flow_and_encrypted_session_reopen_scoped_history(self):
        self.request_review()
        sid = self.login()
        first = self.client1.get(DOM)
        second = self.client2.get(DOM)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["case_status"], "DRAFT_ONLY")
        self.assertEqual(second.json()["history"][0]["request_ref"], "DEMO-REQUEST")
        self.assertNotIn(self.access, first.text)
        self.assertNotIn(sid, first.text)
        self.assertNotIn("csrf", first.text)
        self.assertEqual(first.headers["cache-control"], "no-store")
        self.assertEqual(self.client2.get(EXP).status_code, 404)
        self.assertEqual([e.kind for e in self.ledger.audit_snapshot()][-3:],
                         ["READ_ALLOWED", "READ_ALLOWED", "READ_DENIED"])
        self.assertTrue(self.ledger.verify_integrity())

    def test_browser_session_and_keycloak_role_alone_do_not_grant_a_case(self):
        self.login(subject="synthetic-unassigned-001")
        self.assertEqual(self.client1.get("/api/auth/session").status_code, 200)
        self.assertEqual(self.client1.get(DOM).status_code, 404)
        self.assertEqual(self.ledger.audit_snapshot()[-1].kind, "READ_DENIED")
        self.assertEqual(self.client2.get(EXP).status_code, 404)
        self.assertTrue(self.ledger.verify_integrity())

    def test_no_or_forged_or_malformed_cookie_rejected_before_audit(self):
        self.assertEqual(self.client1.get(DOM).status_code, 401)
        self.client1.cookies.set(SID_COOKIE, secrets.token_urlsafe(36))
        self.assertEqual(self.client1.get(DOM).status_code, 401)
        self.client1.cookies.set(SID_COOKIE, "not-such-session")
        self.assertEqual(self.client1.get(DOM).status_code, 401)
        self.assertEqual(self.ledger.audit_snapshot(), ())

    def test_failed_logout_csrf_does_not_revoke_valid_session(self):
        self.login()
        details = self.client1.get("/api/auth/session").json()
        self.assertEqual(self.client1.post("/api/auth/logout", headers={
            "Origin": "https://evil.example", "X-CSRF-Token": details["csrf"],
        }).status_code, 403)
        self.assertEqual(self.client1.post("/api/auth/logout", headers={
            "Origin": ORIGIN, "X-CSRF-Token": "wrong",
        }).status_code, 403)
        self.assertEqual(self.client2.get(DOM).status_code, 200)
        self.assertTrue(self.ledger.verify_integrity())

    def test_logout_revocation_shared_between_separate_sqlite_connections(self):
        sid = self.login()
        self.assertEqual(self.client2.get(DOM).status_code, 200)
        details = self.client2.get("/api/auth/session").json()
        result = self.client2.post("/api/auth/logout", headers={
            "Origin": ORIGIN, "X-CSRF-Token": details["csrf"],
        })
        self.assertEqual(result.status_code, 200)
        before = len(self.ledger.audit_snapshot())
        self.assertEqual(self.client1.get(DOM).status_code, 401)
        self.assertEqual(self.client1.get("/api/auth/session").status_code, 401)
        self.assertIsNone(self.store1.get_session(sid))
        self.assertEqual(len(self.ledger.audit_snapshot()), before)

    def test_active_browser_cookie_loses_case_read_when_grant_is_revoked(self):
        sid = self.login()
        self.assertEqual(self.client2.get(DOM).status_code, 200)
        self.ledger.revoke_grant(
            engine="DOMESTIC", ref="DEMO-D-001",
            subject="synthetic-domestic-001", role="domestic_ops",
            actor="synthetic-authority", expected_grant_revision=0,
            action_id="DEMO-REVOKE-SESSION", reason_ref="DEMO-REVOCATION",
        )
        self.assertIsNotNone(self.store1.get_session(sid))
        self.assertEqual(self.client1.get("/api/auth/session").status_code, 200)
        self.assertEqual(self.client1.get(DOM).status_code, 404)
        self.assertEqual(self.client2.get(DOM).status_code, 404)
        self.assertEqual(self.ledger.audit_snapshot()[-1].kind, "READ_DENIED")
        self.assertTrue(self.ledger.verify_integrity())

    def test_locally_unexpired_session_with_expired_signed_token_is_denied(self):
        now = int(time.time())
        invalid_token = self.token(exp=now - 30, iat=now - 700, nbf=now - 700)
        sid = secrets.token_urlsafe(36)
        self.store1.save_session(sid, BrowserSession(
            "synthetic-domestic-001", frozenset({"domestic_ops"}),
            invalid_token, "synthetic-csrf", now + 200,
        ))
        self.client2.cookies.set(SID_COOKIE, sid)
        self.assertEqual(self.client2.get(DOM).status_code, 401)
        self.assertEqual(self.ledger.audit_snapshot(), ())

    def test_local_session_expiry_denies_even_when_signed_token_is_valid(self):
        now = int(time.time())
        sid = secrets.token_urlsafe(36)
        self.store1.save_session(sid, BrowserSession(
            "synthetic-domestic-001", frozenset({"domestic_ops"}),
            self.token(), "synthetic-csrf", now + 40,
        ))
        self.client1.cookies.set(SID_COOKIE, sid)
        self.flow1.now = lambda: now + 41
        self.assertEqual(self.client1.get(DOM).status_code, 401)
        self.assertEqual(self.ledger.audit_snapshot(), ())

    def test_session_roles_must_match_currently_verified_token_claims(self):
        sid = secrets.token_urlsafe(36)
        self.store1.save_session(sid, BrowserSession(
            "synthetic-domestic-001", frozenset({"finance"}),
            self.token(), "synthetic-csrf", int(time.time()) + 120,
        ))
        self.client2.cookies.set(SID_COOKIE, sid)
        self.assertEqual(self.client2.get(DOM).status_code, 401)
        self.assertEqual(self.ledger.audit_snapshot(), ())

    def test_bad_authorization_header_cannot_fall_back_to_valid_cookie(self):
        self.login()
        self.assertEqual(self.client1.get(DOM).status_code, 200)
        count = len(self.ledger.audit_snapshot())
        bad = self.client1.get(DOM, headers={
            "Authorization": "Bearer invalid", "X-Role": "domestic_ops",
        })
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(len(self.ledger.audit_snapshot()), count)

    def test_damaged_sqlite_session_ciphertext_denied_before_review_audit(self):
        sid = self.login()
        self.assertEqual(self.client2.get(DOM).status_code, 200)
        previous = len(self.ledger.audit_snapshot())
        with sqlite3.connect(self.store1.path) as db:
            db.execute(
                "UPDATE browser_session SET ciphertext=? WHERE sid_hash=?",
                ("damaged-text-instead-of-ciphertext", self.store1._digest(sid)),
            )
        self.assertEqual(self.client1.get(DOM).status_code, 401)
        self.assertEqual(self.client2.get(DOM).status_code, 401)
        self.assertEqual(len(self.ledger.audit_snapshot()), previous)
        self.assertIsNone(self.store2.get_session(sid))

    def test_modified_sqlite_expiry_does_not_extend_browser_session(self):
        sid = self.login()
        self.assertEqual(self.client1.get(DOM).status_code, 200)
        previous = len(self.ledger.audit_snapshot())
        with sqlite3.connect(self.store1.path) as db:
            db.execute(
                "UPDATE browser_session SET expires_at=expires_at+120 "
                "WHERE sid_hash=?",
                (self.store1._digest(sid),),
            )
        self.assertEqual(self.client2.get(DOM).status_code, 401)
        self.assertEqual(self.client1.get(DOM).status_code, 401)
        self.assertEqual(len(self.ledger.audit_snapshot()), previous)
        self.assertIsNone(self.store1.get_session(sid))

    def test_browser_get_cannot_accept_posted_approval_decision(self):
        self.login()
        self.request_review()
        self.assertEqual(self.client1.post(DOM, json={
            "decision": "APPROVED", "case_status": "ACCEPTED",
        }).status_code, 405)
        self.assertEqual(self.ledger.review_state("DOMESTIC", "DEMO-D-001")[
            "case_status"], "DRAFT_ONLY")


if __name__ == "__main__":
    unittest.main()
