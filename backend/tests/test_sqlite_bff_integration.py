"""Complete offline Keycloak callback through encrypted SQLite BFF storage."""
import json
from pathlib import Path
import secrets
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig
from ronas_api.session_sqlite import SqliteBrowserSessionStore

ISS = "https://keycloak.example.test/realms/ronas"
ORIGIN = "https://ronas.example.test"
API, WEB = "ronas-api", "ronas-web"


class LocalIntegratedBFFTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.private.public_key()))
        jwk.update({"kid": "local-001", "use": "sig", "alg": "RS256"})
        cls.cfg = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "sessions.db"
        self.key = secrets.token_bytes(32)
        self.store1 = SqliteBrowserSessionStore(self.path, self.key)
        self.store2 = SqliteBrowserSessionStore(self.path, self.key)
        self.nonce = None

        async def exchange(code, verifier):
            now = int(time.time())
            access = {
                "iss": ISS, "aud": [API], "azp": WEB, "typ": "Bearer",
                "iat": now - 5, "nbf": now - 5, "exp": now + 600,
                "sub": "synthetic-subject",
                "resource_access": {API: {"roles": ["domestic_ops"]}},
            }
            identity = {
                "iss": ISS, "aud": WEB, "typ": "ID", "nonce": self.nonce,
                "iat": now - 5, "exp": now + 600, "sub": "synthetic-subject",
            }
            return {
                "token_type": "Bearer",
                "access_token": jwt.encode(access, self.private, algorithm="RS256",
                                           headers={"kid": "local-001"}),
                "id_token": jwt.encode(identity, self.private, algorithm="RS256",
                                       headers={"kid": "local-001"}),
            }

        opts = BrowserOIDCConfig(self.cfg, ORIGIN + "/api/auth/callback", "/admin")
        self.flow1 = BrowserOIDC(opts, self.store1, exchange)
        self.flow2 = BrowserOIDC(opts, self.store2, exchange)
        self.client1 = TestClient(create_app(self.cfg, self.flow1),
                                  base_url=ORIGIN, follow_redirects=False)
        self.client2 = TestClient(create_app(self.cfg, self.flow2),
                                  base_url=ORIGIN, follow_redirects=False)

    def login(self):
        start = self.client1.get("/api/auth/start")
        self.assertEqual(start.status_code, 303)
        params = parse_qs(urlsplit(start.headers["location"]).query)
        self.nonce = params["nonce"][0]
        result = self.client1.get("/api/auth/callback",
                                  params={"code": "synthetic", "state": params["state"][0]})
        self.assertEqual(result.status_code, 303, result.text)
        return self.client1.cookies.get("__Host-ronas_session")

    def test_login_session_reopen_role_gated_views_and_cross_connection_logout(self):
        sid = self.login()
        self.assertTrue(sid)
        self.assertEqual(self.client1.get("/admin").status_code, 200)
        self.assertIn("DEMO-H01", self.client1.get("/admin").text)
        self.assertNotIn("DEMO-SOURCE-01", self.client1.get("/admin").text)
        self.assertEqual(self.client1.get("/").status_code, 200)
        self.assertNotIn("DEMO-H01", self.client1.get("/").text)
        self.client2.cookies.set("__Host-ronas_session", sid)
        self.assertEqual(self.client2.get("/admin").status_code, 200)
        self.assertEqual(self.client2.get(
            "/api/v1/admin/domestic/household-intake/example").status_code, 200)
        details = self.client2.get("/api/auth/session").json()
        rejected = self.client2.post("/api/auth/logout", headers={
            "Origin": ORIGIN, "X-CSRF-Token": "incorrect"
        })
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(self.client2.get("/admin").status_code, 200)
        approved = self.client2.post("/api/auth/logout", headers={
            "Origin": ORIGIN, "X-CSRF-Token": details["csrf"]
        })
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(self.client1.get("/admin").status_code, 401)
        self.assertEqual(self.client1.get(
            "/api/v1/admin/domestic/household-intake/example").status_code, 401)
        self.assertIsNone(self.store1.get_session(sid))

    def test_replay_after_consumption_does_not_reopen_login(self):
        start = self.client1.get("/api/auth/start")
        params = parse_qs(urlsplit(start.headers["location"]).query)
        self.nonce = params["nonce"][0]
        first = self.client1.get("/api/auth/callback",
                                 params={"code": "synthetic", "state": params["state"][0]})
        second = self.client1.get("/api/auth/callback",
                                  params={"code": "synthetic", "state": params["state"][0]})
        self.assertEqual(first.status_code, 303)
        self.assertEqual(second.status_code, 401)

    def test_wrong_encryption_key_cannot_resume_session(self):
        sid = self.login()
        other = SqliteBrowserSessionStore(self.path, secrets.token_bytes(32))
        self.assertIsNone(other.get_session(sid))


if __name__ == "__main__":
    unittest.main()
