"""Opt-in Keycloak PKCE BFF composition with HTTP mock, no live accounts."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant
from ronas_api.expert_review_questions_sqlite import SqliteSyntheticExpertQuestionLedger
from ronas_api.agronomy_workspace import (
    SyntheticAgronomyWorkspace, SyntheticAgronomyAssignment,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.local_keycloak_bff import (
    LocalBFFConfigurationError, LocalBFFSettings, create_local_test_bff,
)

ISSUER = "https://identity.example.test/realms/ronas"
API = "ronas-api"
WEB = "ronas-web"
CALLBACK = "https://127.0.0.1:8765/api/auth/callback"
ORIGIN = "https://127.0.0.1:8765"


class LocalKeycloakBFFCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.signing.public_key()))
        pub.update({"kid": "lab-key", "alg": "RS256", "use": "sig"})
        cls.realm = KeycloakConfig(
            ISSUER, API, WEB, json.dumps({"keys": [pub]}).encode(),
        )

    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        self.keyfile = self.root / "session.key"
        self.keyfile.write_bytes(secrets.token_bytes(32))
        self.keyfile.chmod(0o600)
        self.settings = LocalBFFSettings(
            self.realm, CALLBACK, self.root / "session.db", self.keyfile,
        )

    def tokens(self, nonce, *, role="household", subject="synthetic-user"):
        now = int(time.time())
        base = {"iss": ISSUER, "sub": subject, "iat": now-5, "exp": now+450}
        access = jwt.encode(
            {**base, "aud": API, "azp": WEB, "typ": "Bearer", "nbf": now-5,
             "resource_access": {API: {"roles": [role]}}},
            self.signing, algorithm="RS256", headers={"kid": "lab-key"},
        )
        identity = jwt.encode(
            {**base, "aud": WEB, "nonce": nonce, "azp": WEB},
            self.signing, algorithm="RS256", headers={"kid": "lab-key"},
        )
        return {"token_type": "Bearer", "access_token": access, "id_token": identity}

    def _client(self, *, role="household", subject="synthetic-user",
                bad_nonce=False, bad_token=False, case_ledger=None,
                agronomy_workspace=None):
        calls = []
        captured = {}

        def serve(req):
            calls.append(req)
            if req.method != "POST" or str(req.url) != (
                ISSUER + "/protocol/openid-connect/token"
            ):
                return httpx.Response(404)
            if b"grant_type=authorization_code" not in req.content:
                return httpx.Response(400)
            nonce = captured.get("nonce", "")
            if bad_nonce:
                nonce += "-bad"
            body = self.tokens(nonce, role=role, subject=subject)
            if bad_token:
                body["access_token"] = "forged"
            return httpx.Response(200, json=body)

        transport = httpx.MockTransport(serve)
        app = create_local_test_bff(
            self.settings, transport=transport, case_ledger=case_ledger,
            agronomy_workspace=agronomy_workspace,
        )
        return TestClient(app, base_url=ORIGIN, follow_redirects=False), calls, captured

    def _start(self, client, captured):
        start = client.get("/api/auth/start")
        self.assertEqual(start.status_code, 303, start.text)
        loc = urlsplit(start.headers["location"])
        self.assertEqual(loc.scheme, "https")
        self.assertEqual(loc.netloc, "identity.example.test")
        self.assertEqual(loc.path, "/realms/ronas/protocol/openid-connect/auth")
        query = parse_qs(loc.query)
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["client_id"], [WEB])
        self.assertEqual(query["redirect_uri"], [CALLBACK])
        self.assertNotIn("password", query)
        self.assertTrue(client.cookies.get("__Host-ronas_login"))
        self.assertIn("Secure", start.headers["set-cookie"])
        self.assertIn("HttpOnly", start.headers["set-cookie"])
        captured["nonce"] = query["nonce"][0]
        return query

    def test_disabled_default_app_does_not_mount_browser_or_create_session(self):
        app = create_app(self.realm)
        client = TestClient(app, base_url=ORIGIN)
        self.assertEqual(client.get("/api/auth/start").status_code, 404)
        self.assertEqual(client.get("/workspace/household").status_code, 404)
        self.assertFalse(self.settings.session_database.exists())

    def test_opt_in_does_not_accept_http_external_or_cloud_bff_origin(self):
        for callback in (
            "http://127.0.0.1:8765/api/auth/callback",
            "https://ronas.example.test/api/auth/callback",
            "https://localhost:8765/other",
            "https://user:pass@localhost/api/auth/callback",
            "https://127.0.0.1:8765/api/auth/callback?debug=yes",
            "https://localhost:abc/api/auth/callback",
        ):
            with self.subTest(callback=callback), self.assertRaises(
                LocalBFFConfigurationError
            ):
                LocalBFFSettings(self.realm, callback,
                                 self.settings.session_database, self.keyfile)

    def test_env_requires_complete_intent_and_operator_keycloak(self):
        values = {
            "RONAS_LOCAL_BFF_CALLBACK_URL": CALLBACK,
            "RONAS_LOCAL_BFF_SESSION_DATABASE": str(self.settings.session_database),
            "RONAS_LOCAL_BFF_SESSION_KEY_FILE": str(self.keyfile),
        }
        with self.assertRaises(LocalBFFConfigurationError):
            LocalBFFSettings.from_environment(values, keycloak=self.realm)
        values["RONAS_LOCAL_BFF_ENABLE"] = "LOCAL_TEST_ONLY"
        self.assertEqual(
            LocalBFFSettings.from_environment(values, keycloak=self.realm),
            self.settings,
        )
        with self.assertRaises(LocalBFFConfigurationError):
            LocalBFFSettings.from_environment(
                {"RONAS_LOCAL_BFF_ENABLE": "LOCAL_TEST_ONLY"}, self.realm,
            )

    def test_secret_file_must_be_owned_private_and_exactly_32_bytes(self):
        self.keyfile.chmod(0o644)
        with self.assertRaises(LocalBFFConfigurationError):
            create_local_test_bff(self.settings)
        self.keyfile.chmod(0o600)
        self.keyfile.write_bytes(b"short")
        with self.assertRaises(LocalBFFConfigurationError):
            create_local_test_bff(self.settings)
        self.keyfile.write_bytes(secrets.token_bytes(32))
        self.keyfile.unlink()
        self.keyfile.symlink_to(self.root / "missing")
        with self.assertRaises(LocalBFFConfigurationError):
            create_local_test_bff(self.settings)

    def test_private_session_directory_is_required_before_database_creation(self):
        public = self.root / "public"
        public.mkdir(mode=0o755)
        public.chmod(0o755)
        settings = LocalBFFSettings(
            self.realm, CALLBACK, public / "session.db", self.keyfile,
        )
        with self.assertRaises(LocalBFFConfigurationError):
            create_local_test_bff(settings)
        self.assertFalse(settings.session_database.exists())

    def test_full_pkce_exchange_real_signed_role_shell_logout_and_replay(self):
        client, calls, captured = self._client(role="household")
        challenge = self._start(client, captured)
        self.assertEqual(calls, [])
        resp = client.get(
            "/api/auth/callback",
            params={"code": "code-1", "state": challenge["state"][0]},
        )
        self.assertEqual(resp.status_code, 303, resp.text)
        self.assertEqual(resp.headers["location"], "/")
        self.assertEqual(len(calls), 1)
        self.assertIn(b"code_verifier=", calls[0].content)
        self.assertNotIn(b"refresh_token=", calls[0].content)
        self.assertIn("Secure", resp.headers["set-cookie"])
        self.assertIn("HttpOnly", resp.headers["set-cookie"])
        session = client.get("/api/auth/session")
        self.assertEqual(session.status_code, 200, session.text)
        self.assertEqual(session.json()["roles"], ["household"])
        self.assertNotIn("access_token", session.text)
        self.assertNotIn("password", session.text)
        self.assertEqual(client.get("/workspace/household").status_code, 200)
        # A household identity can enter the shared shell but must NOT
        # acquire any administration area via a logged-in session.
        self.assertEqual(client.get("/admin").status_code, 403)
        self.assertEqual(client.get("/api/v1/admin/export/research/example").status_code, 403)
        self.assertFalse(client.get("/api/v1/admin/finance/status").status_code == 200)
        self.assertTrue(self.settings.session_database.exists())
        self.assertEqual(stat.S_IMODE(self.settings.session_database.stat().st_mode), 0o600)
        on_disk = self.settings.session_database.read_bytes()
        self.assertNotIn(session.json()["subject"].encode(), on_disk)
        self.assertNotIn(session.json()["csrf"].encode(), on_disk)
        replay = client.get(
            "/api/auth/callback",
            params={"code": "code-1", "state": challenge["state"][0]},
        )
        self.assertEqual(replay.status_code, 401)
        self.assertEqual(len(calls), 1)
        self.assertEqual(client.post("/api/auth/logout", headers={
            "Origin": "https://attacker.test", "X-CSRF-Token": session.json()["csrf"],
        }).status_code, 403)
        self.assertEqual(client.post("/api/auth/logout", headers={
            "Origin": ORIGIN, "X-CSRF-Token": "bad",
        }).status_code, 403)
        logout = client.post("/api/auth/logout", headers={
            "Origin": ORIGIN, "X-CSRF-Token": session.json()["csrf"],
        })
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(client.get("/api/auth/session").status_code, 401)

    def test_invalid_id_nonce_fails_no_session(self):
        client, _, capture = self._client(bad_nonce=True)
        q = self._start(client, capture)
        res = client.get(
            "/api/auth/callback",
            params={"code": "code-2", "state": q["state"][0]},
        )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(client.get("/api/auth/session").status_code, 401)

    def test_invalid_access_signature_and_unknown_client_role_fail_closed(self):
        client, _, capture = self._client(bad_token=True)
        q = self._start(client, capture)
        self.assertEqual(client.get(
            "/api/auth/callback",
            params={"code": "code", "state": q["state"][0]},
        ).status_code, 401)
        client2, _, capture2 = self._client(role="fake-superadmin")
        q2 = self._start(client2, capture2)
        self.assertEqual(client2.get(
            "/api/auth/callback",
            params={"code": "other", "state": q2["state"][0]},
        ).status_code, 401)

    def test_admin_can_enter_one_admin_shell_but_no_business_authority(self):
        client, _, capture = self._client(role="finance")
        q = self._start(client, capture)
        self.assertEqual(client.get(
            "/api/auth/callback", params={"code": "code", "state": q["state"][0]},
        ).status_code, 303)
        admin = client.get("/admin")
        self.assertEqual(admin.status_code, 200)
        self.assertIn("مالی", admin.text)
        self.assertNotIn("تأیید تسویه", admin.text)
        self.assertEqual(client.get("/workspace/household").status_code, 404)
        self.assertEqual(client.post("/api/v1/admin/finance/status", json={
            "payments_enabled": True,
        }).status_code, 405)


    def _case_ledger(self):
        return SqliteSyntheticExpertQuestionLedger(
            self.root / "synthetic-cases.db",
            (
                ScopedDraft("DEMO-D-1", "DOMESTIC",
                            "synthetic-household-one", 3, ()),
                ScopedDraft("DEMO-D-2", "DOMESTIC",
                            "synthetic-household-other", 1, ()),
                ScopedDraft("DEMO-E-1", "EXPORT",
                            "synthetic-export-owner", 2,
                            (ScopedGrant("synthetic-export-operator",
                                         "export_ops"),),
                            source_ref="DEMO-SOURCE-1"),
            ),
            trusted_revoke_authorizer=lambda actor, engine, ref: (
                actor == "synthetic-controller" and engine == "EXPORT"
            ),
            trusted_human_review_authorizer=lambda *_: False,
        )

    def _signed_login(self, *, role, subject, ledger, expert=None):
        client, _, captured = self._client(
            role=role, subject=subject, case_ledger=ledger,
            agronomy_workspace=expert,
        )
        login = self._start(client, captured)
        cb = client.get("/api/auth/callback",
                        params={"code": "test-code", "state": login["state"][0]})
        self.assertEqual(cb.status_code, 303, cb.text)
        session = client.get("/api/auth/session")
        self.assertEqual(session.status_code, 200, session.text)
        self.assertNotIn("access_token", session.text)
        return client, session.json()["csrf"]

    def test_real_oidc_signed_owner_session_writes_audited_current_input(self):
        ledger = self._case_ledger()
        owner, csrf = self._signed_login(
            role="household", subject="synthetic-household-one", ledger=ledger,
        )
        base = "/my-drafts/DEMO-D-1/input-revisions"
        before = owner.get(base)
        self.assertEqual(before.status_code, 200, before.text)
        self.assertIn("ثبت نسخه DEMO", before.text)
        form = {"csrf": csrf, "case_version": "3", "input_revision": "0",
                "scenario": "DEMO-MANIFEST-ALPHA"}
        written = owner.post(
            base + "/demo-correction", data=form, headers={"Origin": ORIGIN},
        )
        self.assertEqual(written.status_code, 303, written.text)
        read = owner.get(base)
        self.assertEqual(read.status_code, 200, read.text)
        self.assertIn("بازنگری آزمایشی 1", read.text)
        self.assertEqual(ledger.read_owned_input_revisions(
            "DEMO-D-1", Principal("synthetic-household-one",
                                 frozenset({"household"})),
        )["input_revisions"], [1])
        self.assertEqual(owner.post(
            base + "/demo-correction", data=form, headers={"Origin": ORIGIN},
        ).status_code, 409)
        self.assertEqual(owner.get("/admin").status_code, 403)
        self.assertTrue(ledger.verify_integrity())

    def test_real_oidc_signed_export_operator_question_revision_and_revocation(self):
        ledger = self._case_ledger()
        admin, csrf = self._signed_login(
            role="export_ops", subject="synthetic-export-operator",
            ledger=ledger,
        )
        base = "/admin/export/research/drafts/DEMO-E-1"
        before = admin.get(base)
        self.assertEqual(before.status_code, 200, before.text)
        self.assertIn("ثبت پرسش آزمایشی", before.text)
        form = {"csrf": csrf, "case_version": "2", "question_revision": "0",
                "product_ref": "DEMO-PRODUCT-ALPHA",
                "destination_ref": "DEMO-DEST-BETA"}
        created = admin.post(
            base + "/local-test-question", data=form,
            headers={"Origin": ORIGIN},
        )
        self.assertEqual(created.status_code, 303, created.text)
        self.assertIn("DEMO-PRODUCT-ALPHA", admin.get(base).text)
        self.assertEqual(admin.post(
            base + "/local-test-question", data=form,
            headers={"Origin": ORIGIN},
        ).status_code, 409)
        response = admin.get(
            "/api/v1/admin/export/research/drafts/DEMO-E-1/workspace",
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["source_rights_verified"])
        self.assertFalse(response.json()["research_report_approved"])
        self.assertIsNone(response.json()["research_question"]["product"])
        ledger.revoke_grant(
            engine="EXPORT", ref="DEMO-E-1",
            subject="synthetic-export-operator", role="export_ops",
            actor="synthetic-controller", expected_grant_revision=0,
            action_id="DEMO-E-REVOCATION", reason_ref="DEMO-REVOKE-REASON",
        )
        self.assertEqual(admin.get(base).status_code, 404)
        self.assertEqual(admin.get(
            "/api/v1/admin/export/research/drafts/DEMO-E-1/workspace",
        ).status_code, 404)
        self.assertTrue(ledger.verify_integrity())

    def test_real_oidc_case_scope_does_not_follow_role_alone(self):
        ledger = self._case_ledger()
        intruder, _ = self._signed_login(
            role="household", subject="synthetic-household-other", ledger=ledger,
        )
        self.assertEqual(intruder.get(
            "/my-drafts/DEMO-D-1/input-revisions",
        ).status_code, 404)
        self.assertEqual(intruder.get("/my-drafts/DEMO-D-2").status_code, 200)
        unassigned, _ = self._signed_login(
            role="export_ops", subject="synthetic-unassigned-export",
            ledger=ledger,
        )
        self.assertEqual(unassigned.get(
            "/admin/export/research/drafts/DEMO-E-1",
        ).status_code, 404)
        self.assertEqual(unassigned.get(
            "/api/v1/admin/export/research/drafts/DEMO-E-1/workspace",
        ).status_code, 404)

    def test_real_oidc_specialist_assignment_is_separate_from_role_and_owner(self):
        ledger = self._case_ledger()
        expert = SyntheticAgronomyWorkspace(
            ledger, (SyntheticAgronomyAssignment(
                "DEMO-D-1", "synthetic-agronomy-one", 3,
            ),),
            trusted_assignment_active=lambda actor, ref, ver: (
                actor == "synthetic-agronomy-one"
                and ref == "DEMO-D-1" and ver == 3
            ),
        )
        authorized, _ = self._signed_login(
            role="agronomy_expert", subject="synthetic-agronomy-one",
            ledger=ledger, expert=expert,
        )
        self.assertEqual(authorized.get(
            "/agronomy/assigned-drafts/DEMO-D-1",
        ).status_code, 200)
        self.assertEqual(authorized.get(
            "/my-drafts/DEMO-D-1",
        ).status_code, 404)
        unassigned, _ = self._signed_login(
            role="agronomy_expert", subject="synthetic-agronomy-other",
            ledger=ledger, expert=expert,
        )
        self.assertEqual(unassigned.get(
            "/agronomy/assigned-drafts/DEMO-D-1",
        ).status_code, 404)
        self.assertEqual(unassigned.get("/admin").status_code, 403)
        self.assertTrue(ledger.verify_integrity())

    def test_local_case_composition_needs_explicit_shared_ledger(self):
        with self.assertRaises(LocalBFFConfigurationError):
            create_local_test_bff(self.settings, case_ledger=object())
        ledger = self._case_ledger()
        workspace = SyntheticAgronomyWorkspace(
            ledger, (), trusted_assignment_active=lambda *_: False,
        )
        with self.assertRaises(LocalBFFConfigurationError):
            create_local_test_bff(self.settings, agronomy_workspace=workspace)
        other = self._case_ledger()
        with self.assertRaises(LocalBFFConfigurationError):
            create_local_test_bff(
                self.settings, case_ledger=other,
                agronomy_workspace=workspace,
            )
        self.assertTrue(ledger.verify_integrity())

if __name__ == "__main__":
    unittest.main()
