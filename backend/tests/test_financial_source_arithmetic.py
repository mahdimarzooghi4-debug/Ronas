"""Source-grounded Finance discrepancy, never a finance approval."""
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
import secrets

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.business_gate_evidence import BusinessSourceSnapshotError
from ronas_api.financial_source_arithmetic import (
    SOURCE_BLOB_SHA, SOURCE_PATH, source_arithmetic,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession

ISS = "https://identity.example.test/realms/ronas"
API, WEB, ORIGIN = "ronas-api", "ronas-web", "https://ronas.example.test"
JSON_ROUTE = "/api/v1/admin/finance/source-arithmetic"
HTML_ROUTE = "/admin/finance/source-arithmetic"


class Sessions:
    def __init__(self):
        self.live = {}

    def get_session(self, sid):
        return self.live.get(sid)

    def revoke_session(self, sid):
        self.live.pop(sid, None)


class FinanceSourceArithmeticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        public.update({"kid": "finance-arithmetic", "use": "sig", "alg": "RS256"})
        cls.config = KeycloakConfig(
            ISS, API, WEB, json.dumps({"keys": [public]}).encode(),
        )

    def setUp(self):
        self.sessions = Sessions()
        async def no_exchange(*_):
            raise AssertionError("no live IdP in this test")
        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.sessions, no_exchange,
        )
        self.client = TestClient(
            create_app(self.config, self.flow), base_url=ORIGIN,
        )

    def token(self, roles=("finance",)):
        now = int(time.time())
        return jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "typ": "Bearer",
            "sub": "synthetic-finance", "iat": now - 5, "nbf": now - 5,
            "exp": now + 500,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "finance-arithmetic"})

    def headers(self, roles=("finance",)):
        return {"Authorization": "Bearer " + self.token(roles)}

    def login(self, roles=("finance",)):
        sid = secrets.token_urlsafe(36)
        self.sessions.live[sid] = BrowserSession(
            "synthetic-finance", frozenset(roles), self.token(roles),
            secrets.token_urlsafe(24), int(time.time()) + 300,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        return sid

    def test_pinned_source_arithmetic_is_factual_not_approved_model(self):
        data = source_arithmetic()
        self.assertEqual(data["source_blob_sha"], SOURCE_BLOB_SHA)
        self.assertEqual(data["unit"], "million_toman")
        self.assertEqual(data["reported_equipment"], 6760)
        self.assertEqual(data["reported_pre_operating"], 750)
        self.assertEqual(data["arithmetic_component_sum"], 7510)
        self.assertEqual(data["arithmetic_unexplained_difference"], 11405)
        self.assertEqual(data["reported_initial_capital"], 18915)
        self.assertEqual(data["reported_year_one_operating_cost"], 11405)
        for k in ("classification_resolved", "corrected_budget_approved",
                  "operating_cashflow_verified", "finance_gate_passed",
                  "payments_enabled"):
            self.assertIs(data[k], False)
        self.assertNotIn("interest_rate", data)
        self.assertNotIn("approved_initial_capital", data)

    def test_modified_or_missing_source_fails_closed(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            f = base / SOURCE_PATH
            f.parent.mkdir(parents=True)
            shutil.copyfile(repo / SOURCE_PATH, f)
            self.assertEqual(source_arithmetic(root=base)["source_blob_sha"],
                             SOURCE_BLOB_SHA)
            f.write_text(f.read_text(encoding="utf-8").replace(
                "۱۸٬۹۱۵", "۱۸٬۹۱۶",
            ), encoding="utf-8")
            with self.assertRaises(BusinessSourceSnapshotError):
                source_arithmetic(root=base)
            f.unlink()
            with self.assertRaises(BusinessSourceSnapshotError):
                source_arithmetic(root=base)

    def test_finance_only_signed_api_is_default_off(self):
        result = self.client.get(JSON_ROUTE, headers=self.headers())
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["finance_gate_at_source"], "OPEN")
        self.assertEqual(result.headers["cache-control"], "no-store")
        for roles in (("governance",), ("export_ops",), ("domestic_ops",),
                      ("household",)):
            with self.subTest(roles=roles):
                self.assertEqual(self.client.get(
                    JSON_ROUTE, headers=self.headers(roles),
                ).status_code, 404)
        self.assertEqual(self.client.get(JSON_ROUTE).status_code, 401)
        other = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(other.get(
            JSON_ROUTE, headers=self.headers(),
        ).status_code, 404)

    def test_finance_browser_page_and_existing_admin_link(self):
        self.login()
        admin = self.client.get("/admin")
        self.assertEqual(admin.status_code, 200, admin.text)
        self.assertIn(HTML_ROUTE, admin.text)
        result = self.client.get(HTML_ROUTE)
        self.assertEqual(result.status_code, 200, result.text)
        for amount in ("18915", "6760", "750", "7510", "11405"):
            self.assertIn(amount, result.text)
        self.assertIn("نوع سرمایه/هزینه", result.text)
        self.assertNotIn("تسویه‌شده", result.text)
        self.assertIn("form-action 'none'",
                      result.headers["content-security-policy"])
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.sessions.live.clear()
        self.assertEqual(self.client.get(HTML_ROUTE).status_code, 401)

    def test_unrelated_admin_cannot_read_finance_html_or_api(self):
        self.login(("governance",))
        self.assertEqual(self.client.get(HTML_ROUTE).status_code, 404)
        self.assertEqual(self.client.get(JSON_ROUTE).status_code, 404)
        self.assertNotIn(HTML_ROUTE, self.client.get("/admin").text)
        self.assertEqual(self.client.post(
            JSON_ROUTE, json={"finance_gate_passed": True},
            headers=self.headers(),
        ).status_code, 405)

    def test_source_integrity_failure_returns_503_no_arithmetic(self):
        with patch(
            "ronas_api.business_gate_evidence.verify_pinned_business_sources",
            side_effect=BusinessSourceSnapshotError("source tampered"),
        ):
            result = self.client.get(JSON_ROUTE, headers=self.headers())
            self.assertEqual(result.status_code, 503)
            self.assertNotIn("18915", result.text)
        with patch(
            "ronas_api.ui_bff.source_arithmetic",
            side_effect=BusinessSourceSnapshotError("source tampered"),
        ):
            self.login()
            result = self.client.get(HTML_ROUTE)
            self.assertEqual(result.status_code, 503)
            self.assertNotIn("18915", result.text)


if __name__ == "__main__":
    unittest.main()
