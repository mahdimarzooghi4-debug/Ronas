"""Signed-token API tests; no real users or customer data."""
import os
import time
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import AuthConfig

ISSUER = "https://identity.ronas.test/realm/example"
AUD = "ronas-api"
KID = "test-rsa-key"
HOUSE = "/api/v1/domestic/household-intake/example"
OPS = "/api/v1/admin/domestic/household-intake/example"
EXPORT = "/api/v1/admin/export/research/example"
FINANCE = "/api/v1/admin/finance/status"
GOVERN = "/api/v1/admin/governance/status"
PROTECTED = ("/api/v1/me", HOUSE, OPS, EXPORT, FINANCE, GOVERN)


class APIAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_pem = cls.key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        cls.config = AuthConfig(ISSUER, AUD, KID, public_pem)
        cls.client = TestClient(create_app(cls.config))

    def token(self, roles, *, headers=None, **changes):
        now = int(time.time())
        claims = {
            "iss": ISSUER, "aud": AUD, "sub": "synthetic-subject",
            "iat": now - 30, "nbf": now - 30, "exp": now + 900,
            "ronas_roles": roles,
        }
        claims.update(changes)
        return jwt.encode(claims, self.key, algorithm="RS256",
                          headers=headers if headers is not None else {"kid": KID})

    def auth(self, roles, **changes):
        return {"Authorization": "Bearer " + self.token(roles, **changes)}

    def test_unconfigured_auth_fails_closed(self):
        client = TestClient(create_app(None))
        self.assertEqual(client.get("/healthz").json()["status"], "alive")
        self.assertEqual(client.get("/readyz").status_code, 503)
        for path in PROTECTED:
            self.assertEqual(client.get(path).status_code, 503, path)

    def test_readiness_cannot_claim_production(self):
        r = self.client.get("/readyz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["scope"], "READ_ONLY_SYNTHETIC")

    def test_unauthenticated_and_header_spoof_denied(self):
        for path in PROTECTED:
            self.assertEqual(self.client.get(path).status_code, 401, path)
        r = self.client.get(EXPORT, headers={"X-Role": "export_ops",
                                            "X-User": "admin"})
        self.assertEqual(r.status_code, 401)
        h = self.auth(["household"])
        h["X-Role"] = "export_ops"
        self.assertEqual(self.client.get(EXPORT, headers=h).status_code, 403)

    def test_household_can_see_only_fake_domestic_record(self):
        h = self.auth(["household"])
        r = self.client.get(HOUSE, headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["ref"], "DEMO-H01")
        self.assertFalse(r.json()["real_consent_verified"])
        self.assertFalse(r.json()["expert_approved"])
        self.assertFalse(r.json()["accepted"])
        for route in (OPS, EXPORT, FINANCE, GOVERN):
            self.assertEqual(self.client.get(route, headers=h).status_code, 403)

    def test_domestic_ops_is_not_export_or_household(self):
        h = self.auth(["domestic_ops"])
        self.assertEqual(self.client.get(OPS, headers=h).status_code, 200)
        for path in (HOUSE, EXPORT, FINANCE, GOVERN):
            self.assertEqual(self.client.get(path, headers=h).status_code, 403)

    def test_export_ops_lacks_other_permissions_and_verified_sources(self):
        h = self.auth(["export_ops"])
        r = self.client.get(EXPORT, headers=h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["source_ref"], "DEMO-SOURCE-01")
        self.assertFalse(data["source_rights_verified"])
        self.assertFalse(data["buyer_verified"])
        self.assertFalse(data["contracted"])
        self.assertIsNone(data["product"])
        self.assertIsNone(data["destination"])
        for path in (HOUSE, OPS, FINANCE, GOVERN):
            self.assertEqual(self.client.get(path, headers=h).status_code, 403)

    def test_finance_and_governance_are_not_implicit_superusers(self):
        for role, allowed, denied in (
            ("finance", FINANCE, (HOUSE, OPS, EXPORT, GOVERN)),
            ("governance", GOVERN, (HOUSE, OPS, EXPORT, FINANCE)),
        ):
            with self.subTest(role=role):
                h = self.auth([role])
                self.assertEqual(self.client.get(allowed, headers=h).status_code, 200)
                for path in denied:
                    self.assertEqual(self.client.get(path, headers=h).status_code, 403)

    def test_other_external_roles_do_not_inherit_data_access(self):
        for role in ("local_buyer", "agronomy_expert", "equipment_seller", "export_supplier"):
            with self.subTest(role=role):
                h = self.auth([role])
                self.assertEqual(self.client.get("/api/v1/me", headers=h).status_code, 200)
                for path in (HOUSE, OPS, EXPORT, FINANCE, GOVERN):
                    self.assertEqual(self.client.get(path, headers=h).status_code, 403)

    def test_multiple_explicit_roles_do_not_grant_a_third_role(self):
        h = self.auth(["finance", "domestic_ops"])
        self.assertEqual(self.client.get(FINANCE, headers=h).status_code, 200)
        self.assertEqual(self.client.get(OPS, headers=h).status_code, 200)
        for path in (HOUSE, EXPORT, GOVERN):
            self.assertEqual(self.client.get(path, headers=h).status_code, 403)

    def test_me_does_not_echo_full_token_or_profile(self):
        signed = self.token(["household", "domestic_ops"])
        r = self.client.get("/api/v1/me", headers={"Authorization": "Bearer " + signed})
        self.assertEqual(r.json(), {"subject": "synthetic-subject",
                                    "roles": ["domestic_ops", "household"]})
        self.assertNotIn(signed, r.text)
        self.assertNotIn("email", r.text)

    def test_invalid_signed_claims_are_all_rejected(self):
        now = int(time.time())
        cases = [
            {"iss": "https://attacker.test"}, {"aud": "wrong-client"},
            {"exp": now - 1}, {"nbf": now + 3600},
            {"iat": now + 3600}, {"sub": ""}, {"sub": None},
            {"ronas_roles": []}, {"ronas_roles": "export_ops"},
            {"ronas_roles": ["export_ops", "export_ops"]},
            {"ronas_roles": ["unknown_role"]},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                r = self.client.get(EXPORT, headers=self.auth(["export_ops"], **changes))
                self.assertEqual(r.status_code, 401, r.text)

    def test_missing_required_claims_rejected(self):
        now = int(time.time())
        claims = {
            "iss": ISSUER, "aud": AUD, "sub": "test",
            "iat": now - 10, "nbf": now - 10, "exp": now + 300,
            "ronas_roles": ["export_ops"],
        }
        for removed in ("iss", "aud", "sub", "iat", "nbf", "exp"):
            with self.subTest(removed=removed):
                c = dict(claims)
                c.pop(removed)
                tok = jwt.encode(c, self.key, algorithm="RS256", headers={"kid": KID})
                self.assertEqual(self.client.get(EXPORT, headers={"Authorization": "Bearer " + tok}).status_code, 401)

    def test_tampered_key_wrong_kid_and_hs_algorithm_denied(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": AUD, "sub": "bad",
                  "iat": now, "nbf": now, "exp": now + 300,
                  "ronas_roles": ["export_ops"]}
        attempts = [
            jwt.encode(claims, other, algorithm="RS256", headers={"kid": KID}),
            self.token(["export_ops"], headers={"kid": "untrusted-key"}),
            jwt.encode(claims, "secret", algorithm="HS256", headers={"kid": KID}),
        ]
        for tok in attempts:
            self.assertEqual(self.client.get(EXPORT, headers={"Authorization": "Bearer " + tok}).status_code, 401)

    def test_readonly_even_for_all_roles(self):
        h = self.auth(["household", "domestic_ops", "export_ops", "finance", "governance"])
        for path in (HOUSE, OPS, EXPORT, FINANCE, GOVERN):
            self.assertEqual(self.client.post(path, headers=h, json={"decision": "APPROVED"}).status_code, 405)
        self.assertEqual(self.client.post("/api/v1/consent", headers=h, json={}).status_code, 404)

    def test_secure_headers_no_cross_origin_access(self):
        for path in ("/healthz", HOUSE):
            r = self.client.get(path, headers={**self.auth(["household"]),
                                               "Origin": "https://attacker.test"})
            self.assertEqual(r.headers["Cache-Control"], "no-store")
            self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
            self.assertNotIn("access-control-allow-origin", r.headers)

    def test_no_magic_development_login_or_token(self):
        for s in ("Basic token", "bearer 1", "Bearer", "Bearer ", "Bearer x y"):
            self.assertEqual(self.client.get("/api/v1/me", headers={"Authorization": s}).status_code, 401)
        for path in ("/api/v1/auth/dev-login", "/api/v1/login", "/api/v1/auth/token"):
            self.assertEqual(self.client.post(path, json={}).status_code, 404)

    def test_missing_environment_config_and_bad_crypto_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(AuthConfig.from_environment())
        with patch.dict(os.environ, {
            "RONAS_OIDC_ISSUER": ISSUER, "RONAS_OIDC_AUDIENCE": AUD,
            "RONAS_OIDC_KEY_ID": KID, "RONAS_OIDC_PUBLIC_KEY_FILE": "relative.pem",
        }, clear=True):
            self.assertIsNone(AuthConfig.from_environment())
        with self.assertRaises(ValueError):
            AuthConfig("http://insecure.test", AUD, KID, self.config.public_key_pem)
        weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        pem = weak.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        with self.assertRaises(ValueError):
            AuthConfig(ISSUER, AUD, KID, pem)


if __name__ == "__main__":
    unittest.main()
