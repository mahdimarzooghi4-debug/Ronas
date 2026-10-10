"""End-to-end local PKCE/browser BFF contract with a fake exchange, no IdP/network."""
import base64
import hashlib
import json
import time
import unittest
from urllib.parse import parse_qs, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig

ISS = "https://keycloak.example.test/realms/ronas"
API = "ronas-api"
BROWSER = "ronas-web"
ORIGIN = "https://ronas.example.test"
CALLBACK = ORIGIN + "/api/auth/callback"
HOUSE = "/api/v1/domestic/household-intake/example"
DOMESTIC_OPS = "/api/v1/admin/domestic/household-intake/example"
EXPORT = "/api/v1/admin/export/research/example"


class FakeAtomicStore:
    """ONLY a test double. Not eligible for real sessions or multi-replica use."""

    def __init__(self):
        self.pending = {}
        self.sessions = {}
        self.latest_pending = None

    def save_pending(self, item):
        self.pending[item.state] = item
        self.latest_pending = item

    def take_pending(self, state):
        return self.pending.pop(state, None)

    def save_session(self, sid, session):
        self.sessions[sid] = session

    def get_session(self, sid):
        return self.sessions.get(sid)

    def revoke_session(self, sid):
        self.sessions.pop(sid, None)


class BrowserLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.private.public_key()))
        jwk.update({"kid": "realm-sign-001", "use": "sig", "alg": "RS256"})
        cls.config = KeycloakConfig(ISS, API, BROWSER, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        self.store = FakeAtomicStore()
        self.exchange_calls = []
        self.fixed_time = [time.time()]
        self.id_changes = {}
        self.access_changes = {}
        self.exchange_error = None

        async def fake_exchange(code, verifier):
            self.exchange_calls.append((code, verifier))
            if self.exchange_error is not None:
                raise self.exchange_error
            now = int(time.time())
            access = {
                "iss": ISS, "aud": [API, "account"], "azp": BROWSER,
                "typ": "Bearer", "sub": "synthetic-test-user", "iat": now - 30,
                "nbf": now - 30, "exp": now + 700,
                "resource_access": {API: {"roles": ["domestic_ops"]}},
            }
            access.update(self.access_changes)
            identity = {
                "iss": ISS, "aud": BROWSER, "sub": "synthetic-test-user",
                "nonce": self.store.latest_pending.nonce,
                "iat": now - 30, "exp": now + 700,
                "typ": "ID",
            }
            identity.update(self.id_changes)
            return {
                "token_type": "Bearer",
                "access_token": jwt.encode(access, self.private, algorithm="RS256",
                                           headers={"kid": "realm-sign-001"}),
                "id_token": jwt.encode(identity, self.private, algorithm="RS256",
                                       headers={"kid": "realm-sign-001"}),
            }

        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, CALLBACK, "/admin"),
            self.store, fake_exchange, now=lambda: self.fixed_time[0],
        )
        self.client = TestClient(create_app(self.config, self.flow),
                                 base_url=ORIGIN, follow_redirects=False)

    def start(self):
        response = self.client.get("/api/auth/start")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("__Host-ronas_login=", response.headers["set-cookie"])
        self.assertIn("httponly", response.headers["set-cookie"].lower())
        self.assertIn("secure", response.headers["set-cookie"].lower())
        self.assertIn("samesite=lax", response.headers["set-cookie"].lower())
        url = urlsplit(response.headers["location"])
        args = parse_qs(url.query)
        return url, args

    def complete(self, params, code="synthetic-code"):
        return self.client.get(
            "/api/auth/callback",
            params={"state": params["state"][0], "code": code},
        )

    def test_code_flow_pkce_s256_and_correct_origin(self):
        url, qs = self.start()
        self.assertEqual(url.scheme, "https")
        self.assertEqual(url.netloc, "keycloak.example.test")
        self.assertEqual(url.path, "/realms/ronas/protocol/openid-connect/auth")
        self.assertEqual(qs["client_id"], [BROWSER])
        self.assertEqual(qs["redirect_uri"], [CALLBACK])
        self.assertEqual(qs["response_type"], ["code"])
        self.assertEqual(qs["scope"], ["openid"])
        self.assertEqual(qs["code_challenge_method"], ["S256"])
        self.assertEqual(qs["nonce"], [self.store.latest_pending.nonce])
        self.assertEqual(qs["state"], [self.store.latest_pending.state])
        verifier = self.store.latest_pending.verifier
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        self.assertEqual(qs["code_challenge"], [expected])
        self.assertNotIn(verifier, url.query)
        self.assertNotIn("access_token", url.query)
        self.assertNotIn("client_secret", url.query)

    def test_callback_issues_http_only_cookie_and_scoped_session(self):
        _, params = self.start()
        r = self.complete(params)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers["location"], "/admin")
        self.assertIn("__Host-ronas_session=", r.headers["set-cookie"])
        self.assertIn("httponly", r.headers["set-cookie"].lower())
        self.assertIn("secure", r.headers["set-cookie"].lower())
        self.assertIn("samesite=lax", r.headers["set-cookie"].lower())
        self.assertEqual(len(self.exchange_calls), 1)
        self.assertEqual(self.exchange_calls[0][1], self.store.latest_pending.verifier)
        session = self.client.get("/api/auth/session")
        self.assertEqual(session.status_code, 200, session.text)
        self.assertEqual(session.json()["subject"], "synthetic-test-user")
        self.assertEqual(session.json()["roles"], ["domestic_ops"])
        self.assertIn("csrf", session.json())
        self.assertEqual(session.headers["cache-control"], "no-store")
        self.assertEqual(self.client.get(DOMESTIC_OPS).status_code, 200)
        self.assertEqual(self.client.get(EXPORT).status_code, 403)
        self.assertEqual(self.client.get(HOUSE).status_code, 403)
        self.assertNotIn("access_token", r.headers["set-cookie"])
        self.assertNotIn("id_token", r.headers["set-cookie"])
        self.assertNotIn("synthetic-test-user", r.headers["set-cookie"])

    def test_state_cookie_required_and_wrong_state_prevents_exchange(self):
        _, params = self.start()
        state = params["state"][0]
        self.client.cookies.clear()
        r = self.complete(params)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.exchange_calls, [])
        self.assertIn(state, self.store.pending)
        _, args = self.start()
        r = self.client.get("/api/auth/callback",
                            params={"state": "wrong-state", "code": "code"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.exchange_calls, [])
        self.assertIn(args["state"][0], self.store.pending)

    def test_login_state_is_one_time_even_on_callback_replay(self):
        _, params = self.start()
        self.assertEqual(self.complete(params).status_code, 303)
        before = len(self.exchange_calls)
        second = self.complete(params)
        self.assertEqual(second.status_code, 401)
        self.assertEqual(len(self.exchange_calls), before)

    def test_state_expiration_denies_callback(self):
        _, params = self.start()
        self.fixed_time[0] += 301
        self.assertEqual(self.complete(params).status_code, 401)
        self.assertEqual(self.exchange_calls, [])

    def test_missing_code_rejected_before_exchange(self):
        _, params = self.start()
        self.assertEqual(self.complete(params, code="").status_code, 401)
        self.assertEqual(self.exchange_calls, [])

    def test_nonce_id_token_or_access_subject_mismatch_rejected(self):
        for changes in (
            {"nonce": "wrong"}, {"aud": API}, {"sub": "another-subject"},
            {"typ": "Bearer"}, {"exp": int(time.time()) - 1},
        ):
            with self.subTest(changes=changes):
                self.setUp()
                _, params = self.start()
                self.id_changes = changes
                self.assertEqual(self.complete(params).status_code, 401)
                self.assertEqual(len(self.store.sessions), 0)
        self.setUp()
        _, params = self.start()
        self.access_changes = {"sub": "different-user"}
        self.assertEqual(self.complete(params).status_code, 401)

    def test_token_exchange_unexpected_result_never_creates_session(self):
        self.exchange_error = ValueError("synthetic exchange failed")
        _, params = self.start()
        self.assertEqual(self.complete(params).status_code, 401)
        self.assertEqual(self.store.sessions, {})

    def test_expired_access_session_rejected_despite_cookie(self):
        _, params = self.start()
        self.assertEqual(self.complete(params).status_code, 303)
        self.fixed_time[0] += 901
        self.assertEqual(self.client.get("/api/auth/session").status_code, 401)
        self.assertEqual(self.client.get(DOMESTIC_OPS).status_code, 401)

    def test_logout_requires_origin_and_csrf_and_is_immediate(self):
        _, params = self.start()
        self.assertEqual(self.complete(params).status_code, 303)
        details = self.client.get("/api/auth/session").json()
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 403)
        self.assertEqual(self.client.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/logout", headers={
            "Origin": "https://evil.example.test",
            "X-CSRF-Token": details["csrf"],
        }).status_code, 403)
        self.assertEqual(self.client.get(DOMESTIC_OPS).status_code, 200)
        ok = self.client.post("/api/auth/logout", headers={
            "Origin": ORIGIN, "X-CSRF-Token": details["csrf"],
        })
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json(), {"session": "closed"})
        self.assertEqual(self.store.sessions, {})
        self.assertEqual(self.client.get("/api/auth/session").status_code, 401)
        self.assertEqual(self.client.get(DOMESTIC_OPS).status_code, 401)

    def test_bearer_header_has_no_cookie_fallback(self):
        _, params = self.start()
        self.complete(params)
        self.assertEqual(self.client.get(DOMESTIC_OPS, headers={
            "Authorization": "Bearer invalid",
        }).status_code, 401)

    def test_default_app_does_not_expose_login_or_session(self):
        app = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(app.get("/api/auth/start").status_code, 404)
        self.assertEqual(app.get("/api/auth/session").status_code, 404)
        self.assertEqual(app.post("/api/auth/logout").status_code, 404)
        self.assertEqual(app.get(DOMESTIC_OPS).status_code, 401)

    def test_invalid_callback_config_is_rejected(self):
        for uri in (
            "http://ronas.example.test/api/auth/callback",
            "https://ronas.example.test/another",
            "https://evil@ronas.example.test/api/auth/callback",
            "https://ronas.example.test/api/auth/callback?evil=x",
        ):
            with self.subTest(uri=uri):
                with self.assertRaises(ValueError):
                    BrowserOIDCConfig(self.config, uri)
        with self.assertRaises(ValueError):
            BrowserOIDCConfig(self.config, CALLBACK, "https://evil.example.test")
        other = KeycloakConfig(ISS, API, "different-web", self.config.jwks_json)
        with self.assertRaises(ValueError):
            create_app(other, self.flow)


if __name__ == "__main__":
    unittest.main()
