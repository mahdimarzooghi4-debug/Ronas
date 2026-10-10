"""Authenticated two-shell BFF HTML integration, all signed users synthetic."""
import json
import secrets
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession

ISS = "https://identity.example.test/realms/ronas"
ORIGIN = "https://ronas.example.test"
API, BROWSER = "ronas-api", "ronas-web"


class TestSessionStore:
    def __init__(self):
        self.sessions = {}
        self.pending = {}
    def save_pending(self, pending):
        self.pending[pending.state] = pending
    def take_pending(self, state):
        return self.pending.pop(state, None)
    def save_session(self, sid, session):
        self.sessions[sid] = session
    def get_session(self, sid):
        return self.sessions.get(sid)
    def revoke_session(self, sid):
        self.sessions.pop(sid, None)


class TwoShellBFFTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "one", "use": "sig", "alg": "RS256"})
        cls.config = KeycloakConfig(ISS, API, BROWSER, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        self.store = TestSessionStore()
        async def no_exchange(code, verifier):
            raise AssertionError("no live identity exchange")
        self.flow = BrowserOIDC(BrowserOIDCConfig(
            self.config, ORIGIN + "/api/auth/callback"), self.store, no_exchange)
        self.client = TestClient(create_app(self.config, self.flow),
                                 base_url=ORIGIN, follow_redirects=False)

    def sign_in(self, roles):
        now = int(time.time())
        claims = {
            "iss": ISS, "aud": [API], "sub": "fake-subject",
            "azp": BROWSER, "typ": "Bearer",
            "iat": now - 5, "nbf": now - 5, "exp": now + 700,
            "resource_access": {API: {"roles": roles}},
        }
        signed = jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "one"})
        sid = secrets.token_urlsafe(36)
        self.store.save_session(sid, BrowserSession(
            "fake-subject", frozenset(roles), signed, "fixed-test-csrf", now + 650
        ))
        self.client.cookies.set("__Host-ronas_session", sid)
        return sid

    def test_guest_user_shell_has_only_login_and_no_case(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("ورود با Keycloak", r.text)
        self.assertNotIn("DEMO-H01", r.text)
        self.assertNotIn("DEMO-SOURCE-01", r.text)
        self.assertIn("frame-ancestors 'none'", r.headers["content-security-policy"])
        self.assertEqual(self.client.get("/admin").status_code, 401)
        self.assertNotIn("عملیات داخلی", self.client.get("/admin").text)

    def test_household_only_sees_own_synthetic_view(self):
        self.sign_in(["household"])
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("خانوار / تولیدکننده خانگی", r.text)
        self.assertIn("DEMO-H01", r.text)
        self.assertNotIn("DEMO-SOURCE-01", r.text)
        self.assertNotIn("خریدار محلی", r.text)
        denied = self.client.get("/admin")
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn("DEMO-H01", denied.text)
        self.assertNotIn("DEMO-SOURCE-01", denied.text)

    def test_each_admin_role_only_sees_matching_area(self):
        areas = {
            "domestic_ops": ("عملیات داخلی", "DEMO-H01", "DEMO-SOURCE-01"),
            "export_ops": ("عملیات صادرات", "DEMO-SOURCE-01", "DEMO-H01"),
            "finance": ("مالی", "پرداخت، تسویه", "DEMO-H01"),
            "governance": ("راهبری", "دسترسی", "DEMO-SOURCE-01"),
        }
        for role, (label, content, forbidden) in areas.items():
            with self.subTest(role=role):
                self.setUp()
                self.sign_in([role])
                page = self.client.get("/admin")
                self.assertEqual(page.status_code, 200)
                self.assertIn(label, page.text)
                self.assertIn(content, page.text)
                self.assertNotIn(forbidden, page.text)

    def test_explicit_multi_role_areas_visible_and_other_roles_hidden(self):
        self.sign_in(["finance", "export_ops"])
        r = self.client.get("/admin")
        self.assertIn("عملیات صادرات", r.text)
        self.assertIn("مالی", r.text)
        self.assertNotIn("DEMO-H01", r.text)
        self.assertNotIn("راهبری به معنی", r.text)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertNotIn("DEMO-H01", self.client.get("/").text)

    def test_invalid_session_never_falls_back_to_client_header(self):
        self.sign_in(["domestic_ops"])
        self.store.sessions.clear()
        r = self.client.get("/admin", headers={"X-Role": "governance"})
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("DEMO-H01", r.text)

    def test_logout_and_revocation_invalidate_html_and_api(self):
        sid = self.sign_in(["domestic_ops"])
        self.assertEqual(self.client.get("/admin").status_code, 200)
        logout = self.client.post("/api/auth/logout", headers={
            "Origin": ORIGIN, "X-CSRF-Token": "fixed-test-csrf"
        })
        self.assertEqual(logout.status_code, 200)
        self.assertNotIn(sid, self.store.sessions)
        self.assertEqual(self.client.get("/admin").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/admin/domestic/household-intake/example").status_code, 401)

    def test_exact_self_hosted_static_assets_and_no_access_tokens_in_html(self):
        self.sign_in(["household"])
        html = self.client.get("/").text
        self.assertNotIn("access_token", html)
        self.assertNotIn("id_token", html)
        self.assertNotIn("fixed-test-csrf", html)
        css = self.client.get("/assets/ronas.css")
        self.assertEqual(css.status_code, 200)
        self.assertIn("text/css", css.headers["content-type"])
        javascript = self.client.get("/assets/ronas-auth.js")
        self.assertEqual(javascript.status_code, 200)
        self.assertIn("same-origin", javascript.text)
        self.assertIn("X-CSRF-Token", javascript.text)
        self.assertNotIn("fixed-test-csrf", javascript.text)

    def test_opt_in_only_default_app_exposes_no_user_shell_or_assets(self):
        app = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(app.get("/").status_code, 404)
        self.assertEqual(app.get("/admin").status_code, 404)
        self.assertEqual(app.get("/assets/ronas-auth.js").status_code, 404)
        self.assertEqual(app.get("/api/auth/start").status_code, 404)


if __name__ == "__main__":
    unittest.main()
