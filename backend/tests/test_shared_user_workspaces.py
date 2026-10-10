"""Signed, opt-in partner role workspace API and shared user BFF.

LOCAL/TEST only: verified synthetic Keycloak-shaped RS256 claims, no real
partnership, records, exchange, qualification or approval is represented.
"""
import json
from pathlib import Path
import secrets
import tempfile
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.grant_ledger_sqlite import SqliteSyntheticGrantLedger
from ronas_api.human_review_sqlite import SqliteSyntheticHumanReviewLedger
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant
from ronas_api.shared_workspaces import USER_ROLES, visible_user_workspaces

ISS = "https://identity.example.test/realms/ronas"
ORIGIN = "https://ronas.example.test"
API, WEB = "ronas-api", "ronas-web"
WORKSPACES = "/api/v1/me/user-workspaces"
COOKIE = "__Host-ronas_session"


def fixtures():
    return (ScopedDraft(
        "DEMO-D-001", "DOMESTIC", "synthetic-household-one", 1,
        (ScopedGrant("synthetic-domestic-operator", "domestic_ops"),),
    ),)


class LocalSessionStore:
    def __init__(self):
        self.sessions = {}

    def get_session(self, sid):
        return self.sessions.get(sid)

    def revoke_session(self, sid):
        self.sessions.pop(sid, None)


class UserPartnerWorkspacesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "roles-key", "use": "sig", "alg": "RS256"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = LocalSessionStore()

        async def reject_exchange(code, verifier):
            raise AssertionError("external IdP is not used in LOCAL/TEST")

        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.store, reject_exchange,
        )
        self.client = self.app_client()

    def app_client(self, kind=None):
        kwargs = {}
        if kind == "base":
            kwargs["scoped_registry"] = SqliteSyntheticGrantLedger(
                self.root / "base.db", fixtures(),
                trusted_revoke_authorizer=lambda a, e, r: False,
            )
        elif kind == "review":
            ledger = SqliteSyntheticHumanReviewLedger(
                self.root / "review.db", fixtures(),
                trusted_revoke_authorizer=lambda a, e, r: False,
                trusted_human_review_authorizer=lambda a, e, r: False,
            )
            kwargs.update(scoped_registry=ledger, technical_review_ledger=ledger)
        return TestClient(
            create_app(self.config, self.flow, **kwargs),
            base_url=ORIGIN, follow_redirects=False,
        )

    def signed(self, subject="synthetic-household-one",
               roles=("household",), *, expired=False):
        now = int(time.time())
        claim = {
            "iss": ISS, "aud": API, "azp": WEB,
            "sub": subject, "typ": "Bearer",
            "iat": now - (500 if expired else 5),
            "nbf": now - (500 if expired else 5),
            "exp": now - 60 if expired else now + 600,
            "resource_access": {API: {"roles": list(roles)}},
        }
        return jwt.encode(claim, self.key, algorithm="RS256",
                          headers={"kid": "roles-key"})

    def login(self, client=None, *, subject="synthetic-household-one",
              roles=("household",), expired=False):
        sid = secrets.token_urlsafe(36)
        self.store.sessions[sid] = BrowserSession(
            subject, frozenset(roles),
            self.signed(subject, roles, expired=expired),
            "synthetic-csrf", int(time.time()) + 240,
        )
        (client or self.client).cookies.set(COOKIE, sid)
        return sid

    def test_catalog_is_exact_five_canonical_user_roles(self):
        self.assertEqual(tuple(USER_ROLES), (
            "household", "local_buyer", "agronomy_expert",
            "equipment_seller", "export_supplier",
        ))
        self.assertNotIn("finance", USER_ROLES)
        self.assertNotIn("export_ops", USER_ROLES)

    def test_role_projection_never_grants_business_or_reveals_subject(self):
        p = Principal("synthetic-household-one", frozenset({
            "household", "equipment_seller", "finance",
        }))
        rows = visible_user_workspaces(p)
        self.assertEqual([x["role"] for x in rows],
                         ["household", "equipment_seller"])
        for row in rows:
            self.assertFalse(row["business_actions_enabled"])
            self.assertEqual(row["activity_state"], "NOT_OPERATIONAL")
            self.assertEqual(row["environment"], "SHARED_USER_PARTNER")
            self.assertEqual(row["local_test_reads"], [])
            self.assertNotIn("synthetic-household-one", str(row))

    def test_signed_bearer_shows_exact_assigned_roles_and_no_admin_workspace(self):
        res = self.client.get(WORKSPACES, headers={"Authorization": "Bearer " +
            self.signed(roles=("equipment_seller", "export_supplier", "governance"))})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual([x["role"] for x in res.json()["items"]],
                         ["equipment_seller", "export_supplier"])
        self.assertNotIn("governance", res.text)
        self.assertNotIn("finance", res.text)
        self.assertEqual(res.headers["cache-control"], "no-store")

    def test_all_five_shared_roles_can_have_distinct_readonly_workspace(self):
        signed = self.signed(roles=tuple(USER_ROLES))
        for role in USER_ROLES:
            with self.subTest(role=role):
                r = self.client.get(
                    WORKSPACES + "/" + role,
                    headers={"Authorization": "Bearer " + signed},
                )
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()["role"], role)
                self.assertFalse(r.json()["business_actions_enabled"])
                self.assertEqual(r.json()["local_test_reads"], [])

    def test_role_downgrade_and_unknown_roles_have_identical_404(self):
        headers = {"Authorization": "Bearer " + self.signed(roles=("local_buyer",))}
        for role in ("agronomy_expert", "export_supplier", "finance", "not-a-role"):
            r = self.client.get(WORKSPACES + "/" + role, headers=headers)
            self.assertEqual(r.status_code, 404)
            self.assertEqual(r.json(), {"detail": "WORKSPACE_NOT_FOUND"})

    def test_unassigned_roles_are_not_escalated_by_headers_or_query(self):
        headers = {
            "Authorization": "Bearer " + self.signed(roles=("local_buyer",)),
            "X-Role": "export_supplier", "X-Case-Grant": "ALL",
        }
        r = self.client.get(WORKSPACES, params={"role": "export_supplier"},
                            headers=headers)
        self.assertEqual([x["role"] for x in r.json()["items"]], ["local_buyer"])
        self.assertEqual(self.client.get(
            WORKSPACES + "/export_supplier", headers=headers
        ).status_code, 404)

    def test_missing_bad_or_expired_bearer_does_not_return_role_data(self):
        self.assertEqual(self.client.get(WORKSPACES).status_code, 401)
        for token in ("invalid", self.signed(expired=True)):
            r = self.client.get(WORKSPACES, headers={"Authorization": "Bearer " + token})
            self.assertEqual(r.status_code, 401)
            self.assertNotIn("local_buyer", r.text)

    def test_browser_session_reads_are_signed_and_logout_revokes_them(self):
        sid = self.login(roles=("local_buyer", "agronomy_expert"))
        r = self.client.get(WORKSPACES)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["role"] for x in r.json()["items"]],
                         ["local_buyer", "agronomy_expert"])
        self.assertEqual(self.client.get(WORKSPACES + "/local_buyer").status_code, 200)
        self.store.revoke_session(sid)
        self.assertEqual(self.client.get(WORKSPACES).status_code, 401)
        self.assertEqual(self.client.get("/workspace/local_buyer").status_code, 401)

    def test_invalid_explicit_bearer_never_uses_valid_browser_cookie(self):
        self.login(roles=("local_buyer",))
        r = self.client.get(WORKSPACES, headers={
            "Authorization": "Bearer invalid",
        })
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.client.get(WORKSPACES).status_code, 200)

    def test_existing_shared_shell_links_to_signed_roles_only(self):
        self.login(roles=("local_buyer", "equipment_seller"))
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("/workspace/local_buyer", r.text)
        self.assertIn("/workspace/equipment_seller", r.text)
        self.assertNotIn("/workspace/household", r.text)
        self.assertNotIn("/workspace/export_supplier", r.text)
        self.assertIn("dir=\"rtl\"", r.text)
        self.assertIn("frame-ancestors 'none'", r.headers["content-security-policy"])

    def test_partner_detail_is_readonly_and_no_fake_operational_claim(self):
        self.login(roles=("agronomy_expert",))
        r = self.client.get("/workspace/agronomy_expert")
        self.assertEqual(r.status_code, 200)
        self.assertIn("کارشناس کشاورزی", r.text)
        self.assertIn("غیرعملیاتی", r.text)
        self.assertNotIn("DEMO-D-001", r.text)
        self.assertNotIn("خرید انجام شد", r.text)
        self.assertNotIn("synthetic-household-one", r.text)
        self.assertNotIn("synthetic-csrf", r.text)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(self.client.post("/workspace/agronomy_expert").status_code, 405)
        self.assertEqual(self.client.post(WORKSPACES).status_code, 405)

    def test_partner_detail_cannot_be_opened_for_another_role(self):
        self.login(roles=("equipment_seller",))
        for path in ("/workspace/local_buyer", "/workspace/finance",
                     "/workspace/unassigned"):
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 404)
                self.assertEqual(r.json(), {"detail": "WORKSPACE_NOT_FOUND"})

    def test_owner_read_capabilities_exist_only_when_exact_ledger_injected(self):
        signed = self.signed()
        for kind, reads in (
            (None, []),
            ("base", ["OWNED_SYNTHETIC_DOMESTIC_DRAFTS"]),
            ("review", ["OWNED_SYNTHETIC_DOMESTIC_DRAFTS",
                        "OWNED_SYNTHETIC_TECHNICAL_PROGRESS"]),
        ):
            with self.subTest(kind=kind):
                client = self.app_client(kind)
                result = client.get(WORKSPACES + "/household", headers={
                    "Authorization": "Bearer " + signed,
                })
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["local_test_reads"], reads)
                self.assertFalse(result.json()["business_actions_enabled"])

    def test_browser_owner_role_detail_links_only_to_explicit_local_test_reads(self):
        for kind, expected in ((None, False), ("base", True), ("review", True)):
            with self.subTest(kind=kind):
                client = self.app_client(kind)
                self.login(client)
                r = client.get("/workspace/household")
                self.assertEqual(r.status_code, 200)
                self.assertEqual("مشاهده پرونده‌های ساختگی متعلق به من" in r.text,
                                 expected)
                self.assertIn("غیرعملیاتی", r.text)

    def test_default_non_browser_app_has_no_partner_role_workspace_api(self):
        client = TestClient(create_app(self.config), base_url=ORIGIN)
        headers = {"Authorization": "Bearer " + self.signed(roles=("local_buyer",))}
        self.assertEqual(client.get(WORKSPACES, headers=headers).status_code, 404)
        self.assertEqual(client.get(WORKSPACES + "/local_buyer",
                                    headers=headers).status_code, 404)
        self.assertEqual(client.get("/workspace/local_buyer").status_code, 404)

    def test_expired_browser_token_cannot_keep_role_workspace_alive(self):
        self.login(roles=("local_buyer",), expired=True)
        self.assertEqual(self.client.get("/workspace/local_buyer").status_code, 401)
        self.assertEqual(self.client.get(WORKSPACES).status_code, 401)


if __name__ == "__main__":
    unittest.main()
