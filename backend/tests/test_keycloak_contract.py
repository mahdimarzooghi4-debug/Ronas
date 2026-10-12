"""Keycloak signed access-token admission: real RSA/JWKS, synthetic identities."""
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import InvalidToken
from ronas_api.keycloak import KeycloakConfig, KeycloakTokenVerifier

ISSUER = "https://login.example.test/realms/ronas"
API = "ronas-api"
BROWSER = "ronas-web"
HOUSE = "/api/v1/domestic/household-intake/example"
OPS = "/api/v1/admin/domestic/household-intake/example"
EXPORT = "/api/v1/admin/export/research/example"
FIN = "/api/v1/admin/finance/status"
GOV = "/api/v1/admin/governance/status"


def public_record(private, kid):
    data = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    data.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return data


class KeycloakRealmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_a = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.private_b = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk_a = public_record(cls.private_a, "realm-sign-a")
        cls.jwk_b = public_record(cls.private_b, "realm-sign-b")
        cls.document = json.dumps({"keys": [cls.jwk_a, cls.jwk_b]}).encode("utf-8")
        cls.config = KeycloakConfig(ISSUER, API, BROWSER, cls.document)
        cls.client = TestClient(create_app(cls.config))

    def token(self, roles=None, *, key=None, kid="realm-sign-a", **overrides):
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": ["account", API],
            "sub": "test-user-0001",
            "azp": BROWSER,
            "typ": "Bearer",
            "iat": now - 30,
            "nbf": now - 30,
            "exp": now + 600,
            "resource_access": {
                API: {"roles": roles if roles is not None else ["household"]},
                "account": {"roles": ["manage-account"]},
            },
        }
        claims.update(overrides)
        return jwt.encode(claims, key or self.private_a, algorithm="RS256",
                          headers={"kid": kid})

    def request(self, route, roles=None, **claims):
        token = self.token(roles, **claims)
        return self.client.get(route, headers={"Authorization": "Bearer " + token})

    def test_pinned_keycloak_multi_aud_access_token(self):
        r = self.request(HOUSE, ["household"])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["ref"], "DEMO-H01")
        self.assertFalse(r.json()["real_consent_verified"])
        self.assertEqual(self.request("/api/v1/me", ["household"]).json(),
                         {"subject": "test-user-0001", "roles": ["household"]})

    def test_four_admin_areas_strictly_independent(self):
        for role, allowed in (
            ("domestic_ops", OPS), ("export_ops", EXPORT),
            ("finance", FIN), ("governance", GOV),
        ):
            with self.subTest(role=role):
                self.assertEqual(self.request(allowed, [role]).status_code, 200)
                for path in (HOUSE, OPS, EXPORT, FIN, GOV):
                    if path != allowed:
                        self.assertEqual(self.request(path, [role]).status_code, 403, path)

    def test_client_grants_not_realm_roles_or_account_roles(self):
        signed_claims = {
            "resource_access": {"account": {"roles": ["domestic_ops", "export_ops"]}},
            "realm_access": {"roles": ["household", "governance"]},
        }
        r = self.request(OPS, ["domestic_ops"], **signed_claims)
        self.assertEqual(r.status_code, 401)
        r = self.request(GOV, ["household"], realm_access={"roles": ["governance"]})
        self.assertEqual(r.status_code, 403)
        r = self.request(OPS, ["household"],
                         resource_access={API: {"roles": ["household"]},
                                          "account": {"roles": ["domestic_ops"]}})
        self.assertEqual(r.status_code, 403)

    def test_authorized_party_exact_browser_and_api_audience(self):
        cases = (
            {"azp": "other-client"}, {"azp": None},
            {"aud": BROWSER}, {"aud": ["account", BROWSER]},
            {"aud": ["account", API, API]}, {"aud": ["account", None, API]},
            {"typ": "ID"}, {"typ": None},
            {"iss": "https://another.example.test/realms/ronas"},
        )
        for bad in cases:
            with self.subTest(bad=bad):
                self.assertEqual(self.request(HOUSE, ["household"], **bad).status_code, 401)

    def test_missing_auth_and_spoofed_header_denied(self):
        self.assertEqual(self.client.get(HOUSE).status_code, 401)
        h = {"X-Role": "domestic_ops", "X-User": "admin"}
        self.assertEqual(self.client.get(OPS, headers=h).status_code, 401)
        h["Authorization"] = "Bearer " + self.token(["household"])
        self.assertEqual(self.client.get(OPS, headers=h).status_code, 403)

    def test_invalid_roles_duplicate_and_unknown_rejected(self):
        for roles in ([], ["bad-admin"], ["household", "household"], "household",
                      [None], [0], ["household", "not-allowed"]):
            with self.subTest(roles=roles):
                self.assertEqual(self.request(HOUSE, roles).status_code, 401)
        no_roles = self.request(HOUSE, ["household"], resource_access={})
        self.assertEqual(no_roles.status_code, 401)

    def test_wrong_signature_unknown_kid_and_unsafe_jwt_headers(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        attacks = (
            self.token(["household"], key=other),
            self.token(["household"], kid="unknown-key"),
            self.token(["household"], kid="realm-sign-a", key=self.private_b),
        )
        for raw in attacks:
            self.assertEqual(
                self.client.get(HOUSE, headers={"Authorization": "Bearer " + raw}).status_code,
                401,
            )
        token = self.token(["household"])
        verifier = KeycloakTokenVerifier(self.config)
        self.assertEqual(verifier.verify(token).roles, frozenset({"household"}))

    def test_two_pinned_keys_support_explicit_operator_rotation(self):
        token = self.token(["export_ops"], key=self.private_b, kid="realm-sign-b")
        r = self.client.get(EXPORT, headers={"Authorization": "Bearer " + token})
        self.assertEqual(r.status_code, 200)
        old_config = KeycloakConfig(ISSUER, API, BROWSER,
                                   json.dumps({"keys": [self.jwk_a]}).encode())
        old_client = TestClient(create_app(old_config))
        self.assertEqual(
            old_client.get(EXPORT, headers={"Authorization": "Bearer " + token}).status_code,
            401,
        )

    def test_expiration_future_time_and_missing_required_claim(self):
        now = int(time.time())
        cases = (
            {"exp": now - 1}, {"iat": now + 120}, {"nbf": now + 120},
            {"exp": "1700000000"}, {"iat": "1700000000"}, {"nbf": "1700000000"},
            {"sub": ""}, {"sub": None},
        )
        for bad in cases:
            with self.subTest(bad=bad):
                self.assertEqual(self.request(HOUSE, ["household"], **bad).status_code, 401)
        with self.assertRaises(InvalidToken):
            KeycloakTokenVerifier(self.config).verify("nonsense")

    def test_no_write_routes_or_extra_role_panels(self):
        all_roles = ["household", "domestic_ops", "export_ops", "finance", "governance"]
        headers = {"Authorization": "Bearer " + self.token(all_roles)}
        for route in (HOUSE, OPS, EXPORT, FIN, GOV):
            self.assertEqual(self.client.post(route, headers=headers, json={}).status_code, 405)
        self.assertEqual(self.client.post("/api/v1/admin/support", headers=headers).status_code, 404)

    def test_jwks_refuses_private_keys_duplicate_ids_and_weak_keys(self):
        weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        entries = [
            {"keys": [self.jwk_a, self.jwk_a]},
            {"keys": []},
            {"keys": [{**self.jwk_a, "d": "secret"}]},
            {"keys": [{**self.jwk_a, "alg": "HS256"}]},
            {"keys": [{**self.jwk_a, "use": "enc"}]},
            {"keys": [public_record(weak, "weak")]},
            {"keys": [self.jwk_a] * 9},
            {"keys": [{"kid": "x", "kty": "oct", "k": "secret"}]},
            {"keys": [self.jwk_a], "private": "secret"},
        ]
        for bad in entries:
            with self.subTest(bad=str(bad)[:120]):
                with self.assertRaises(ValueError):
                    KeycloakConfig(ISSUER, API, BROWSER, json.dumps(bad).encode())

    def test_malformed_realm_client_config_rejected(self):
        for issuer in (
            "http://identity.example.test/realms/ronas",
            "https://identity.example.test/not-a-realm/ronas",
            "https://identity.example.test/realms/ronas/",
            "https://identity.example.test/realms/ronas?query=1",
            "https://name:password@identity.example.test/realms/ronas",
        ):
            with self.subTest(issuer=issuer):
                with self.assertRaises(ValueError):
                    KeycloakConfig(issuer, API, BROWSER, self.document)
        with self.assertRaises(ValueError):
            KeycloakConfig(ISSUER, API, API, self.document)
        with self.assertRaises(ValueError):
            KeycloakConfig(ISSUER, "", BROWSER, self.document)

    def test_default_environment_requires_only_approved_keycloak(self):
        with patch.dict(os.environ, {
            "RONAS_OIDC_ISSUER": ISSUER,
            "RONAS_OIDC_AUDIENCE": API,
            "RONAS_OIDC_KEY_ID": "realm-sign-a",
        }, clear=True):
            self.assertIsNone(KeycloakConfig.from_environment())
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "jwks.json")
            with open(path, "wb") as stream:
                stream.write(self.document)
            with patch.dict(os.environ, {
                "RONAS_KEYCLOAK_ISSUER": ISSUER,
                "RONAS_KEYCLOAK_API_CLIENT_ID": API,
                "RONAS_KEYCLOAK_BROWSER_CLIENT_ID": BROWSER,
                "RONAS_KEYCLOAK_JWKS_FILE": path,
            }, clear=True):
                config = KeycloakConfig.from_environment()
                self.assertIsNotNone(config)
                self.assertEqual(config.api_client_id, API)
            with patch.dict(os.environ, {
                "RONAS_KEYCLOAK_ISSUER": ISSUER,
                "RONAS_KEYCLOAK_API_CLIENT_ID": API,
                "RONAS_KEYCLOAK_BROWSER_CLIENT_ID": BROWSER,
                "RONAS_KEYCLOAK_JWKS_FILE": "relative.json",
            }, clear=True):
                self.assertIsNone(KeycloakConfig.from_environment())


if __name__ == "__main__":
    unittest.main()
