"""End-to-end PostgreSQL-backed LOCAL/TEST Keycloak BFF composition."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.keycloak import KeycloakConfig
from ronas_api.local_keycloak_bff import (
    LocalBFFConfigurationError,
    PostgresLocalBFFSettings,
    create_postgres_local_test_bff,
)

ISSUER = "https://identity.example.test/realms/ronas"
API = "ronas-api"
WEB = "ronas-web"
CALLBACK = "https://127.0.0.1:8765/api/auth/callback"
ORIGIN = "https://127.0.0.1:8765"
DSN = os.environ.get("RONAS_TEST_POSTGRES_DSN", "")


class PostgresBFFCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(
            cls.signing.public_key(),
        ))
        public_jwk.update({"kid": "pg-bff-test-key", "alg": "RS256", "use": "sig"})
        cls.realm = KeycloakConfig(
            ISSUER, API, WEB, json.dumps({"keys": [public_jwk]}).encode(),
        )

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.key_file = self.root / "session.key"
        self.key_file.write_bytes(secrets.token_bytes(32))
        self.key_file.chmod(0o600)

    def test_postgres_settings_fail_closed_and_require_explicit_local_test_opt_in(self):
        with self.assertRaises(LocalBFFConfigurationError):
            PostgresLocalBFFSettings(self.realm, CALLBACK, "", self.key_file)
        with self.assertRaises(LocalBFFConfigurationError):
            PostgresLocalBFFSettings(
                self.realm, "https://ronas.example.test/api/auth/callback",
                DSN or "postgresql://local/test", self.key_file,
            )
        values = {
            "RONAS_LOCAL_BFF_CALLBACK_URL": CALLBACK,
            "RONAS_LOCAL_BFF_POSTGRES_DSN": DSN or "postgresql://local/test",
            "RONAS_LOCAL_BFF_SESSION_KEY_FILE": str(self.key_file),
        }
        with self.assertRaises(LocalBFFConfigurationError):
            PostgresLocalBFFSettings.from_environment(values, self.realm)
        values["RONAS_LOCAL_BFF_ENABLE"] = "LOCAL_TEST_ONLY"
        configured = PostgresLocalBFFSettings.from_environment(values, self.realm)
        self.assertEqual(configured.postgres_dsn, values["RONAS_LOCAL_BFF_POSTGRES_DSN"])

    @unittest.skipUnless(DSN, "CI PostgreSQL service is required for this integration test")
    def test_pkce_callback_and_session_cross_independent_bff_instances(self):
        settings = PostgresLocalBFFSettings(
            self.realm, CALLBACK, DSN, self.key_file,
        )
        calls = []

        def token_response(req):
            calls.append(req)
            self.assertEqual(req.method, "POST")
            self.assertEqual(str(req.url), ISSUER + "/protocol/openid-connect/token")
            self.assertIn(b"grant_type=authorization_code", req.content)
            self.assertIn(b"code_verifier=", req.content)
            body = req.content.decode()
            # The nonce is decoded from the ID token expectation captured below.
            nonce = self.nonce
            now = int(time.time())
            claims = {"iss": ISSUER, "sub": "synthetic-household-1",
                      "iat": now - 5, "exp": now + 450}
            access = jwt.encode(
                {**claims, "aud": API, "azp": WEB, "typ": "Bearer",
                 "nbf": now - 5,
                 "resource_access": {API: {"roles": ["household"]}}},
                self.signing, algorithm="RS256",
                headers={"kid": "pg-bff-test-key"},
            )
            identity = jwt.encode(
                {**claims, "aud": WEB, "azp": WEB, "nonce": nonce},
                self.signing, algorithm="RS256",
                headers={"kid": "pg-bff-test-key"},
            )
            return httpx.Response(200, json={
                "token_type": "Bearer", "access_token": access,
                "id_token": identity,
            })

        app_a = create_postgres_local_test_bff(
            settings, transport=httpx.MockTransport(token_response),
        )
        app_b = create_postgres_local_test_bff(
            settings, transport=httpx.MockTransport(token_response),
        )
        with TestClient(app_a, base_url=ORIGIN, follow_redirects=False) as browser_a, \
             TestClient(app_b, base_url=ORIGIN, follow_redirects=False) as browser_b:
            start = browser_a.get("/api/auth/start")
            self.assertEqual(start.status_code, 303, start.text)
            query = parse_qs(urlsplit(start.headers["location"]).query)
            self.assertEqual(query["code_challenge_method"], ["S256"])
            self.assertEqual(query["redirect_uri"], [CALLBACK])
            self.nonce = query["nonce"][0]
            # The callback lands on another application instance. The pending
            # login and session are shared through PostgreSQL, cookies stay
            # browser-owned, and no Keycloak secret/token is returned to it.
            browser_b.cookies.update(browser_a.cookies)
            callback = browser_b.get(
                "/api/auth/callback",
                params={"code": "mock-code", "state": query["state"][0]},
            )
            self.assertEqual(callback.status_code, 303, callback.text)
            session = browser_b.get("/api/auth/session")
            self.assertEqual(session.status_code, 200, session.text)
            self.assertEqual(session.json()["roles"], ["household"])
            self.assertEqual(session.json()["subject"], "synthetic-household-1")
            self.assertNotIn("access_token", session.text)
            self.assertEqual(browser_b.get("/workspace/household").status_code, 200)
            self.assertEqual(len(calls), 1)
            replay = browser_a.get(
                "/api/auth/callback",
                params={"code": "mock-code", "state": query["state"][0]},
            )
            self.assertEqual(replay.status_code, 401)
            self.assertEqual(len(calls), 1)
            self.assertEqual(app_a.state.ronas_local_bff_session_backend, "postgresql")
            self.assertEqual(app_b.state.ronas_local_bff_session_backend, "postgresql")


if __name__ == "__main__":
    unittest.main()
