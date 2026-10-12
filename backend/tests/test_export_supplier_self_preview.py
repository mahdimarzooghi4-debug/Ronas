"""Strictly synthetic export supplier self-preview and shared-shell tests."""
import json
import secrets
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.export_supplier_workspace import (
    SyntheticSupplierPreviewSeed, SyntheticSupplierWorkspace,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession

ISS, API, WEB = "https://id.example.test/realms/ronas", "ronas-api", "ronas-web"
ORIGIN = "https://ronas.example.test"
ROUTE = "/api/v1/export-supplier/my-preview"
HTML = "/export-supplier/my-preview"
WORK = "/workspace/export_supplier"
CAPABILITY = "/api/v1/me/user-workspaces/export_supplier"


class Sessions:
    def __init__(self):
        self.items = {}

    def get_session(self, sid):
        return self.items.get(sid)

    def revoke_session(self, sid):
        self.items.pop(sid, None)


class ExportSupplierSelfPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "supplier-test", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        self.active = {"DEMO-SUP-001", "DEMO-SUP-002"}
        self.workspace = self.workspace_for()
        self.sessions = Sessions()

        async def no_exchange(_code, _verifier):
            raise AssertionError("no real IdP configured")

        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.sessions, no_exchange,
        )
        self.client = self.make_client()

    def workspace_for(self, *, seeds=None, checker=None):
        if seeds is None:
            seeds = (
                SyntheticSupplierPreviewSeed(
                    "DEMO-SUP-001", "synthetic-supplier-001", 2
                ),
                SyntheticSupplierPreviewSeed(
                    "DEMO-SUP-002", "synthetic-supplier-002", 1
                ),
            )
        return SyntheticSupplierWorkspace(
            seeds, trusted_self_access=checker or (
                lambda actor, ref, version: (
                    actor.startswith("synthetic-supplier-")
                    and ref in self.active and version in (1, 2)
                )
            ),
        )

    def make_client(self, *, workspace="present"):
        kwargs = (
            {"export_supplier_workspace": self.workspace}
            if workspace == "present" else {}
        )
        return TestClient(
            create_app(self.config, self.flow, **kwargs),
            base_url=ORIGIN,
        )

    def token(self, subject="synthetic-supplier-001",
              roles=("export_supplier",), *, expired=False):
        now = int(time.time())
        return jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB,
            "sub": subject, "typ": "Bearer",
            "iat": now-5, "nbf": now-5,
            "exp": now-10 if expired else now+600,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "supplier-test"})

    def headers(self, subject="synthetic-supplier-001",
                roles=("export_supplier",), **kwargs):
        return {"Authorization": "Bearer " + self.token(subject, roles, **kwargs)}

    def login(self, subject="synthetic-supplier-001",
              roles=("export_supplier",)):
        sid = secrets.token_urlsafe(40)
        self.sessions.items[sid] = BrowserSession(
            subject, frozenset(roles), self.token(subject, roles),
            secrets.token_urlsafe(32), int(time.time())+300,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        return sid

    def test_own_profile_read_has_only_null_capacity_and_no_commerce(self):
        r = self.client.get(ROUTE, headers=self.headers())
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["contract_version"],
                         "ronas.export-supplier.self-preview.v1")
        self.assertEqual(body["profile_ref"], "DEMO-SUP-001")
        self.assertEqual(body["profile_version"], 2)
        self.assertEqual(body["profile_state"], "NOT_SUBMITTED_DEMO")
        self.assertEqual(body["source"], "SYNTHETIC_ONLY")
        self.assertEqual(body["supplier_fields"], {
            "identity": None, "products": None, "capacity": None,
            "availability": None, "facility": None,
            "export_permissions": None,
        })
        for flag in ("identity_verified", "professional_status_verified",
                     "capacity_verified", "source_and_trade_rights_verified",
                     "export_gate_approved", "commercial_actions_enabled",
                     "data_submission_enabled", "buyer_or_contract_exists",
                     "real_data"):
            self.assertIs(body[flag], False)
        self.assertNotIn("synthetic-supplier-001", r.text)
        self.assertNotIn("synthetic-supplier-002", r.text)
        self.assertEqual(r.headers["cache-control"], "no-store")

    def test_two_suppliers_cannot_read_each_others_previews(self):
        first = self.client.get(ROUTE, headers=self.headers()).json()
        second = self.client.get(ROUTE, headers=self.headers(
            "synthetic-supplier-002"
        )).json()
        self.assertEqual(second["profile_ref"], "DEMO-SUP-002")
        self.assertNotEqual(first["profile_ref"], second["profile_ref"])
        self.assertNotIn("DEMO-SUP-001", str(second))
        self.assertNotIn("DEMO-SUP-002", str(first))
        self.assertEqual(self.client.get(
            ROUTE, params={"subject": "synthetic-supplier-002"},
            headers=self.headers(),
        ).json()["profile_ref"], "DEMO-SUP-001")

    def test_signed_supplier_role_alone_without_seed_is_not_enough(self):
        r = self.client.get(
            ROUTE, headers=self.headers("synthetic-supplier-no-seed")
        )
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {"detail": "PREVIEW_NOT_FOUND"})

    def test_operator_admin_household_or_governance_role_not_authorized(self):
        for roles in (("export_ops",), ("household",), ("finance",),
                      ("governance",), ("domestic_ops",)):
            with self.subTest(roles=roles):
                r = self.client.get(ROUTE, headers=self.headers(roles=roles))
                self.assertEqual(r.status_code, 404)
                self.assertNotIn("DEMO-SUP", r.text)
        self.assertEqual(self.client.get(
            "/api/v1/admin/export/research/cases",
            headers=self.headers(),
        ).status_code, 404)

    def test_live_revocation_with_old_signed_token_removes_access(self):
        self.assertEqual(self.client.get(
            ROUTE, headers=self.headers()
        ).status_code, 200)
        self.active.remove("DEMO-SUP-001")
        r = self.client.get(ROUTE, headers=self.headers())
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("DEMO-SUP", r.text)
        self.assertEqual(self.client.get(
            ROUTE, headers=self.headers("synthetic-supplier-002")
        ).status_code, 200)

    def test_checker_must_return_literal_true_and_provider_exception_503(self):
        for value in (1, "true", None, False):
            with self.subTest(value=value):
                self.workspace._current_access = lambda *_: value
                self.assertEqual(
                    self.client.get(ROUTE, headers=self.headers()).status_code,
                    404,
                )
        def unavailable(*_):
            raise RuntimeError("private synthetic authority exception")
        self.workspace._current_access = unavailable
        r = self.client.get(ROUTE, headers=self.headers())
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"detail": "SUPPLIER_PREVIEW_UNAVAILABLE"})
        self.assertNotIn("DEMO-SUP-001", r.text)

    def test_role_capability_present_only_when_injected(self):
        r = self.client.get(CAPABILITY, headers=self.headers())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["local_test_reads"],
                         ["OWN_SYNTHETIC_EXPORT_SUPPLIER_PREVIEW"])
        self.assertFalse(r.json()["business_actions_enabled"])
        off = self.make_client(workspace="none")
        r = off.get(CAPABILITY, headers=self.headers())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["local_test_reads"], [])

    def test_supplier_user_shell_links_to_personal_readonly_preview(self):
        self.login()
        root = self.client.get("/")
        self.assertEqual(root.status_code, 200)
        self.assertIn(WORK, root.text)
        role = self.client.get(WORK)
        self.assertEqual(role.status_code, 200)
        self.assertIn(HTML, role.text)
        page = self.client.get(HTML)
        self.assertEqual(page.status_code, 200, page.text)
        for term in ("تأمین‌کننده", "DEMO-SUP-001", "ظرفیت تأمین: ثبت نشده",
                     "مجوزهای صادراتی: ثبت نشده", "اطلاعاتی ارسال نشده است",
                     "خریدار، قیمت، سفارش، معامله"):
            self.assertIn(term, page.text)
        self.assertNotIn("synthetic-supplier-001", page.text)
        self.assertIn("frame-ancestors 'none'",
                      page.headers["content-security-policy"])
        self.assertEqual(page.headers["cache-control"], "no-store")

    def test_role_link_hides_when_current_supplier_access_revoked(self):
        self.login()
        self.assertIn(HTML, self.client.get(WORK).text)
        self.active.remove("DEMO-SUP-001")
        self.assertNotIn(HTML, self.client.get(WORK).text)
        self.assertEqual(self.client.get(HTML).status_code, 404)

    def test_other_signed_role_cannot_open_browser_preview(self):
        self.login(roles=("export_ops",))
        self.assertEqual(self.client.get(WORK).status_code, 404)
        self.assertEqual(self.client.get(HTML).status_code, 404)
        self.assertNotIn("DEMO-SUP-001", self.client.get(HTML).text)

    def test_session_logout_revokes_both_html_and_cookie_api_access(self):
        sid = self.login()
        self.assertEqual(self.client.get(HTML).status_code, 200)
        self.assertEqual(self.client.get(ROUTE).status_code, 200)
        self.sessions.revoke_session(sid)
        self.assertEqual(self.client.get(HTML).status_code, 401)
        self.assertEqual(self.client.get(ROUTE).status_code, 401)

    def test_expired_forged_and_wrong_bearer_rejected(self):
        self.assertEqual(self.client.get(ROUTE).status_code, 401)
        for token in ("forged", self.token(expired=True)):
            self.assertEqual(self.client.get(
                ROUTE, headers={"Authorization": "Bearer " + token},
            ).status_code, 401)
        self.login()
        self.assertEqual(self.client.get(
            ROUTE, headers={"Authorization": "Bearer forged"},
        ).status_code, 401)
        self.assertEqual(self.client.get(ROUTE).status_code, 200)

    def test_default_app_routes_off_and_mutation_not_admitted(self):
        plain = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(plain.get(
            ROUTE, headers=self.headers()
        ).status_code, 404)
        self.assertEqual(plain.get(HTML).status_code, 404)
        self.login()
        for path in (ROUTE, HTML):
            for method in ("post", "patch", "put", "delete"):
                with self.subTest(path=path, method=method):
                    r = getattr(self.client, method)(path)
                    self.assertEqual(r.status_code, 405)

    def test_invalid_duplicate_or_non_demo_seed_rejected(self):
        seed = SyntheticSupplierPreviewSeed(
            "DEMO-SUP-001", "synthetic-supplier-001", 2
        )
        for seeds in ((seed, seed), (
            seed, SyntheticSupplierPreviewSeed(
                "DEMO-SUP-001", "synthetic-supplier-002", 1
            ),
        )):
            with self.assertRaises(ValueError):
                self.workspace_for(seeds=seeds)
        for kwargs in (
            {"ref": "NOT-DEMO", "subject": "synthetic-supplier-001", "version": 1},
            {"ref": "DEMO-SUP-003", "subject": "real-person", "version": 1},
            {"ref": "DEMO-SUP-003", "subject": "synthetic-supplier-003",
             "version": True},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                SyntheticSupplierPreviewSeed(**kwargs)

    def test_no_selected_supplier_record_does_not_fabricate_profile(self):
        self.workspace = self.workspace_for(seeds=())
        client = self.make_client()
        r = client.get(ROUTE, headers=self.headers())
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {"detail": "PREVIEW_NOT_FOUND"})
        self.assertEqual(client.get(CAPABILITY, headers=self.headers()).status_code, 200)


if __name__ == "__main__":
    unittest.main()
