"""Record-level authorization: explicitly assigned synthetic case only, no mutation.

Signed Keycloak roles are necessary but not sufficient for internal/export
personnel. A server-trusted case grant must also match the exact subject and
engine. No fake consent/real customer data can enter these tests.
"""
import json
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.scoped_drafts import (
    ScopedGrant, ScopedDraft, ScopedSyntheticDraftRegistry,
)

ISSUER = "https://keycloak.example.test/realms/ronas"
API = "ronas-api"
WEB = "ronas-web"
ORIGIN = "https://ronas.example.test"

OWN = "/api/v1/domestic/household-intake/drafts/"
DOPS = "/api/v1/admin/domestic/household-intake/drafts/"
EOPS = "/api/v1/admin/export/research/drafts/"


def catalogue():
    return ScopedSyntheticDraftRegistry((
        ScopedDraft(
            "DEMO-D-001", "DOMESTIC", "synthetic-household-001", 1,
            (ScopedGrant("synthetic-domestic-ops-001", "domestic_ops"),),
        ),
        ScopedDraft(
            "DEMO-D-002", "DOMESTIC", "synthetic-household-002", 2,
            (ScopedGrant("synthetic-domestic-ops-002", "domestic_ops"),),
        ),
        ScopedDraft(
            "DEMO-E-001", "EXPORT", "synthetic-research-owner-001", 1,
            (ScopedGrant("synthetic-export-ops-001", "export_ops"),),
            source_ref="DEMO-SOURCE-01",
        ),
        ScopedDraft(
            "DEMO-E-002", "EXPORT", "synthetic-research-owner-002", 4,
            (ScopedGrant("synthetic-export-ops-002", "export_ops"),),
            source_ref="DEMO-SOURCE-02",
        ),
    ))


class ScopedReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.private.public_key()))
        jwk.update({"kid": "trusted-key-01", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(
            ISSUER, API, WEB, json.dumps({"keys": [jwk]}).encode("utf-8"),
        )

    def setUp(self):
        self.data = catalogue()
        self.app = TestClient(create_app(self.config, scoped_registry=self.data))
        self.plain = TestClient(create_app(self.config))

    def token(self, subject, roles, *, overrides=None):
        now = int(time.time())
        claims = {
            "iss": ISSUER, "aud": [API, "account"], "azp": WEB,
            "typ": "Bearer", "sub": subject,
            "iat": now - 5, "nbf": now - 5, "exp": now + 500,
            "resource_access": {API: {"roles": roles}},
        }
        if overrides:
            claims.update(overrides)
        return jwt.encode(claims, self.private, algorithm="RS256",
                          headers={"kid": "trusted-key-01"})

    def get(self, route, subject, roles, *, client=None, extra=None):
        headers = {"Authorization": "Bearer " + self.token(subject, roles)}
        if extra:
            headers.update(extra)
        return (client or self.app).get(route, headers=headers)

    def test_household_owns_its_case_but_not_another_household_case(self):
        mine = self.get(OWN + "DEMO-D-001", "synthetic-household-001", ["household"])
        self.assertEqual(mine.status_code, 200)
        self.assertEqual(mine.json()["ref"], "DEMO-D-001")
        self.assertEqual(mine.json()["engine"], "DOMESTIC")
        self.assertEqual(mine.json()["version"], 1)
        self.assertEqual(mine.json()["status"], "DRAFT_ONLY")
        self.assertFalse(mine.json()["purpose_consent_verified"])
        self.assertFalse(mine.json()["expert_approved"])
        self.assertFalse(mine.json()["plan_accepted"])
        self.assertFalse(mine.json()["real_data"])
        self.assertEqual(
            self.get(OWN + "DEMO-D-002", "synthetic-household-001", ["household"]).status_code,
            404,
        )

    def test_domestic_operator_needs_case_assignment_in_addition_to_role(self):
        allowed = self.get(DOPS + "DEMO-D-001", "synthetic-domestic-ops-001", ["domestic_ops"])
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["ref"], "DEMO-D-001")
        self.assertEqual(
            self.get(DOPS + "DEMO-D-002", "synthetic-domestic-ops-001", ["domestic_ops"]).status_code,
            404,
        )

    def test_export_operator_must_match_explicit_export_case_grant(self):
        permitted = self.get(EOPS + "DEMO-E-001", "synthetic-export-ops-001", ["export_ops"])
        self.assertEqual(permitted.status_code, 200)
        self.assertEqual(permitted.json()["engine"], "EXPORT")
        self.assertEqual(permitted.json()["source_ref"], "DEMO-SOURCE-01")
        for key in ("source_rights_verified", "review_approved",
                    "buyer_verified", "contracted", "real_data"):
            self.assertFalse(permitted.json()[key], key)
        self.assertEqual(
            self.get(EOPS + "DEMO-E-002", "synthetic-export-ops-001", ["export_ops"]).status_code,
            404,
        )

    def test_multi_role_administrator_still_requires_per_record_grant(self):
        ops = "synthetic-domestic-ops-001"
        roles = ["domestic_ops", "export_ops", "governance", "finance", "household"]
        self.assertEqual(self.get(DOPS + "DEMO-D-001", ops, roles).status_code, 200)
        for path in (OWN + "DEMO-D-001", DOPS + "DEMO-D-002", EOPS + "DEMO-E-001"):
            self.assertEqual(self.get(path, ops, roles).status_code, 404, path)

    def test_governance_finance_expert_and_supplier_have_no_implicit_case_rights(self):
        for role in ("governance", "finance", "agronomy_expert",
                     "export_supplier", "equipment_seller", "local_buyer"):
            with self.subTest(role=role):
                subject = "synthetic-household-001"
                for route in (OWN + "DEMO-D-001", DOPS + "DEMO-D-001", EOPS + "DEMO-E-001"):
                    self.assertEqual(self.get(route, subject, [role]).status_code, 404)

    def test_role_claim_without_matching_subject_assignment_is_denied(self):
        for route, role in (
            (DOPS + "DEMO-D-001", "domestic_ops"),
            (EOPS + "DEMO-E-001", "export_ops"),
        ):
            self.assertEqual(
                self.get(route, "synthetic-unassigned-person", [role]).status_code,
                404,
            )

    def test_wrong_engine_and_missing_case_look_identical(self):
        h = "synthetic-export-ops-001"
        role = ["export_ops", "domestic_ops"]
        for route in (
            DOPS + "DEMO-E-001", EOPS + "DEMO-D-001",
            EOPS + "DEMO-NOT-EXIST", EOPS + "DEMO-D-002",
            EOPS + "UNKNOWN", EOPS + "%2E%2E%2FDEMO-E-001",
        ):
            self.assertEqual(self.get(route, h, role).status_code, 404)

    def test_headers_and_query_parameters_cannot_create_case_grants(self):
        forged = {
            "X-Ronas-Case-Grant": "DEMO-E-001",
            "X-Case-Owner": "synthetic-export-ops-001",
            "X-Role": "export_ops",
            "X-Actor": "synthetic-export-ops-001",
        }
        path = EOPS + "DEMO-E-001?subject=synthetic-export-ops-001&grant=export_ops"
        r = self.get(path, "synthetic-unassigned-person", ["export_ops"], extra=forged)
        self.assertEqual(r.status_code, 404)

    def test_unauthenticated_or_invalid_signed_key_denied_before_lookup(self):
        self.assertEqual(self.app.get(DOPS + "DEMO-D-001").status_code, 401)
        self.assertEqual(self.app.get(EOPS + "DEMO-E-001").status_code, 401)
        self.assertEqual(self.app.get(OWN + "DEMO-D-001").status_code, 401)
        self.assertEqual(self.app.get(
            DOPS + "DEMO-D-001", headers={"Authorization": "Bearer invalid"}
        ).status_code, 401)

    def test_record_api_absent_unless_injected_and_no_live_mutations(self):
        p = "synthetic-domestic-ops-001"
        self.assertEqual(self.get(DOPS + "DEMO-D-001", p, ["domestic_ops"],
                                  client=self.plain).status_code, 404)
        headers = {"Authorization": "Bearer " + self.token(p, ["domestic_ops"])}
        self.assertEqual(self.app.post(DOPS + "DEMO-D-001", headers=headers,
                                       json={"status": "ACCEPTED"}).status_code, 405)
        self.assertEqual(self.app.post("/api/v1/record-grants", headers=headers,
                                       json={"role": "domestic_ops"}).status_code, 404)

    def test_no_metadata_disclosure_in_record_payload(self):
        for path, subject, roles in (
            (OWN + "DEMO-D-001", "synthetic-household-001", ["household"]),
            (DOPS + "DEMO-D-001", "synthetic-domestic-ops-001", ["domestic_ops"]),
            (EOPS + "DEMO-E-001", "synthetic-export-ops-001", ["export_ops"]),
        ):
            with self.subTest(path=path):
                response = self.get(path, subject, roles)
                self.assertEqual(response.status_code, 200)
                data = response.json()
                for field in ("owner_subject", "grants", "roles",
                              "consent_ref", "real_name", "email", "address", "price"):
                    self.assertNotIn(field, data)
                self.assertEqual(response.headers["cache-control"], "no-store")

    def test_catalogue_rejects_untrusted_state_and_mismatched_grants(self):
        with self.assertRaises(ValueError):
            ScopedGrant("unverified-real-customer", "domestic_ops")
        with self.assertRaises(ValueError):
            ScopedGrant("synthetic-household-001", "governance")
        with self.assertRaises(ValueError):
            ScopedDraft("REAL-H1", "DOMESTIC", "synthetic-household-001", 1, ())
        with self.assertRaises(ValueError):
            ScopedDraft("DEMO-X", "DOMESTIC", "synthetic-household-001", 1,
                        (ScopedGrant("synthetic-user-001", "export_ops"),))
        with self.assertRaises(ValueError):
            ScopedDraft("DEMO-X", "EXPORT", "synthetic-household-001", 1, (),
                        source_ref=None)
        with self.assertRaises(ValueError):
            ScopedDraft("DEMO-X", "DOMESTIC", "synthetic-household-001", 0, ())
        with self.assertRaises(ValueError):
            ScopedSyntheticDraftRegistry((catalogue(),))
        draft = ScopedDraft("DEMO-X", "DOMESTIC", "synthetic-household-001", 1, ())
        with self.assertRaises(ValueError):
            ScopedSyntheticDraftRegistry((draft, draft))
        with self.assertRaises(ValueError):
            create_app(None, scoped_registry=ScopedSyntheticDraftRegistry((draft,)))

    def test_frozen_catalogue_does_not_mutate_when_result_changes(self):
        p = Principal("synthetic-household-001", frozenset({"household"}))
        initial = self.data.read("DOMESTIC", "DEMO-D-001", p, as_owner=True)
        self.assertIsNotNone(initial)
        initial["ref"] = "TAMPERED"
        self.assertEqual(self.data.read("DOMESTIC", "DEMO-D-001", p, as_owner=True)["ref"],
                         "DEMO-D-001")

    def test_case_version_is_immutable_not_a_client_override(self):
        path = DOPS + "DEMO-D-002"
        p = "synthetic-domestic-ops-002"
        response = self.get(path + "?version=999", p, ["domestic_ops"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], 2)
        self.assertEqual(response.json()["status"], "DRAFT_ONLY")

    def test_signed_browser_session_can_read_only_assigned_case(self):
        class FakeStore:
            def __init__(self): self.sessions = {}
            def get_session(self, sid): return self.sessions.get(sid)
        store = FakeStore()
        async def offline_exchange(code, verifier):
            raise RuntimeError("no Keycloak connection")
        flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            store, offline_exchange,
        )
        now = int(time.time())
        signed = self.token("synthetic-domestic-ops-001", ["domestic_ops"])
        store.sessions["fake-session-id"] = BrowserSession(
            "synthetic-domestic-ops-001", frozenset({"domestic_ops"}),
            signed, "fake-csrf", now + 300,
        )
        client = TestClient(
            create_app(self.config, flow, scoped_registry=self.data),
            base_url=ORIGIN,
        )
        client.cookies.set("__Host-ronas_session", "fake-session-id")
        self.assertEqual(client.get(DOPS + "DEMO-D-001").status_code, 200)
        self.assertEqual(client.get(DOPS + "DEMO-D-002").status_code, 404)
        self.assertEqual(client.get(EOPS + "DEMO-E-001").status_code, 404)
        self.assertEqual(client.get(OWN + "DEMO-D-001").status_code, 404)


if __name__ == "__main__":
    unittest.main()
