"""Never-admitted real-authority connector boundary tests (LOCAL/TEST).

All identity, source bytes, issuer data and roles are deliberately DEMO.
No network port or provider is invoked even with forged compatible objects.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.business_gate_evidence import PINNED_BUSINESS_SOURCE_BLOBS
from ronas_api.gate_authority_connector_boundary import (
    CONNECTOR_STATE, CONTRACT_VERSION, UNRESOLVED_ADMISSION,
    AuthorityConnectorNotAdmitted, AuthorityRequestIdentity,
    accept_unadmitted_response, dispatch_unadmitted,
)
from ronas_api.gate_evidence_authority_enquiry_sqlite import (
    CHECKS, SqliteSyntheticAuthorityEnquiryLedger,
)
from ronas_api.gate_evidence_handoff_sqlite import (
    HandoffIntegrityError, HandoffNotAuthorized, SqliteSyntheticGateEvidenceHandoff,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession

ISS, API, WEB = "https://id.example.test/realms/ronas", "ronas-api", "ronas-web"
ORIGIN = "https://ronas.example.test"
ROUTE = "/api/v1/admin/gate-evidence/DOMESTIC/authority-connectors"


class LocalSessions:
    def __init__(self):
        self.items = {}
    def get_session(self, sid):
        return self.items.get(sid)
    def revoke_session(self, sid):
        self.items.pop(sid, None)


class AuthorityConnectorBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "connector-key", "use": "sig", "alg": "RS256"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "connector.db"
        self.maker = Principal("synthetic-connector-maker", frozenset({"domestic_ops"}))
        self.checker = Principal("synthetic-connector-checker", frozenset({"domestic_ops"}))
        self.finance = Principal("synthetic-finance-maker", frozenset({"finance"}))
        self.handoff, self.authority = self.reopen()
        self.sessions = LocalSessions()

        async def no_provider(*_):
            raise AssertionError("no real identity provider")

        self.browser = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.sessions, no_provider,
        )
        self.client = TestClient(create_app(
            self.config, self.browser, gate_handoff_ledger=self.handoff,
            authority_enquiry_ledger=self.authority,
        ), base_url=ORIGIN)

    def reopen(self):
        source = SqliteSyntheticGateEvidenceHandoff(
            self.path, trusted_review_authorizer=lambda *_: False,
        )
        authority = SqliteSyntheticAuthorityEnquiryLedger(
            source,
            trusted_response_authorizer=lambda actor, domain, ref, kind: (
                actor == "synthetic-connector-checker" and domain == "DOMESTIC"
                and ref == "D1-B-01" and kind in CHECKS
            ),
        )
        return source, authority

    def headers(self, roles=("domestic_ops",), *, expired=False):
        now = int(time.time())
        token = jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB,
            "sub": "synthetic-connector-maker", "typ": "Bearer",
            "iat": now - 5, "nbf": now - 5,
            "exp": now - 10 if expired else now + 600,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "connector-key"})
        return {"Authorization": "Bearer " + token}

    def login(self):
        sid = secrets.token_urlsafe(40)
        self.sessions.items[sid] = BrowserSession(
            "synthetic-connector-maker", frozenset({"domestic_ops"}),
            self.headers()["Authorization"][7:], secrets.token_urlsafe(32),
            int(time.time()) + 200,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        return sid

    def register(self):
        return self.handoff.record_reference(
            principal=self.maker, domain="DOMESTIC", evidence_id="D1-B-01",
            action_id="DEMO-CNX-SOURCE", reference_ref="DEMO-CNX-REF",
            claimed_sha256="a" * 64, expected_revision=0,
        )

    def request(self, kind="ORIGIN"):
        return self.authority.request_check(
            principal=self.maker, domain="DOMESTIC", evidence_id="D1-B-01",
            check_kind=kind, source_action_id="DEMO-CNX-SOURCE",
            action_id="DEMO-CNX-REQUEST-" + kind.replace("_", "-"),
            request_ref="DEMO-CNX-REQ-" + kind.replace("_", "-"),
            expected_revision=0,
        )

    def respond(self, kind="ORIGIN"):
        return self.authority.record_response_reference(
            principal=self.checker, domain="DOMESTIC", evidence_id="D1-B-01",
            check_kind=kind, source_action_id="DEMO-CNX-SOURCE",
            action_id="DEMO-CNX-RESPONSE-" + kind.replace("_", "-"),
            request_ref="DEMO-CNX-REQ-" + kind.replace("_", "-"),
            response_ref="DEMO-CNX-NOTE-" + kind.replace("_", "-"),
            expected_revision=1,
        )

    def test_none_of_nineteen_dossier_slots_have_an_approved_connector(self):
        for domain, principal, expected in (
            ("DOMESTIC", self.maker, 18),
            ("EXPORT", Principal("synthetic-export", frozenset({"export_ops"})), 18),
            ("FINANCE", self.finance, 21),
        ):
            with self.subTest(domain=domain):
                data = self.authority.connector_readiness(principal, domain)
                self.assertEqual(data["connector_state"], CONNECTOR_STATE)
                self.assertEqual(data["contract_version"], CONTRACT_VERSION)
                self.assertEqual(len(data["items"]), expected)
                self.assertTrue(all(x["technical_state"] == "NO_REQUEST"
                                    for x in data["items"]))
                self.assertTrue(all(x["unresolved"] == list(UNRESOLVED_ADMISSION)
                                    for x in data["items"]))
                self.assertTrue(all(not x["dispatch_authorized"]
                                    and not x["provider_response_trusted"]
                                    and not x["business_gate_passed"]
                                    for x in data["items"]))
                self.assertEqual(
                    self.authority.pending_connector_request_identities(
                        principal, domain,
                    ), (),
                )

    def test_pending_fingerprint_is_pinned_to_original_action_and_request_event(self):
        source = self.register()
        request = self.request()
        pending = self.authority.pending_connector_request_identities(
            self.maker, "DOMESTIC",
        )
        self.assertEqual(len(pending), 1)
        identity = pending[0]
        self.assertIsInstance(identity, AuthorityRequestIdentity)
        self.assertEqual(identity.original_handoff_digest, source.event_digest)
        self.assertEqual(identity.enquiry_event_digest, request.event_digest)
        self.assertEqual(identity.original_handoff_action, source.action_id)
        self.assertEqual(identity.enquiry_action, request.action_id)
        self.assertEqual(identity.request_reference, request.request_ref)
        self.assertEqual(identity.contract_version, CONTRACT_VERSION)
        self.assertEqual(len(identity.fingerprint), 64)
        self.assertEqual(identity.fingerprint,
                         self.authority.pending_connector_request_identities(
                             self.maker, "DOMESTIC",
                         )[0].fingerprint)
        self.assertTrue(self.authority.verify_integrity())

    def test_three_independent_request_packets_bound_to_distinct_actions(self):
        self.register()
        for kind in CHECKS:
            self.request(kind)
        pending = self.authority.pending_connector_request_identities(
            self.maker, "DOMESTIC",
        )
        self.assertEqual([p.check_kind for p in pending], sorted(CHECKS))
        self.assertEqual(len({p.fingerprint for p in pending}), 3)
        self.assertTrue(all(p.business_source_sha == pending[0].business_source_sha
                            for p in pending))

    def test_response_removes_only_its_own_pending_dispatch_identity(self):
        self.register()
        for kind in CHECKS:
            self.request(kind)
        self.respond("SOURCE_RIGHTS")
        ids = self.authority.pending_connector_request_identities(
            self.maker, "DOMESTIC",
        )
        self.assertEqual({p.check_kind for p in ids},
                         {"ORIGIN", "REVIEWER_QUALIFICATION"})
        view = self.authority.connector_readiness(self.maker, "DOMESTIC")
        responded = next(x for x in view["items"]
                         if x["evidence_id"] == "D1-B-01"
                         and x["check_kind"] == "SOURCE_RIGHTS")
        self.assertEqual(responded["technical_state"],
                         "TECHNICAL_RESPONSE_REF_RECORDED")
        self.assertFalse(responded["provider_response_trusted"])

    def test_mock_port_must_never_be_invoked_even_when_request_is_valid(self):
        self.register()
        self.request()
        req = self.authority.pending_connector_request_identities(
            self.maker, "DOMESTIC",
        )[0]
        class ExplosivePort:
            calls = 0
            def exchange(self, request):
                self.calls += 1
                raise AssertionError("unapproved network/provider call")
        port = ExplosivePort()
        with self.assertRaises(AuthorityConnectorNotAdmitted):
            dispatch_unadmitted(req, port=port)
        self.assertEqual(port.calls, 0)
        self.assertEqual(self.authority.connector_readiness(
            self.maker, "DOMESTIC",
        )["connector_state"], "NO_AUTHORITY_APPROVED")

    def test_forged_provider_response_is_never_accepted(self):
        self.register()
        self.request()
        identity = self.authority.pending_connector_request_identities(
            self.maker, "DOMESTIC",
        )[0]
        for response in (
            {"signed": True, "qualified": True, "accepted": True},
            b"DEMO-PROVIDER-SAYS-APPROVED", None, True,
        ):
            with self.subTest(response=type(response).__name__):
                with self.assertRaises(AuthorityConnectorNotAdmitted):
                    accept_unadmitted_response(identity, response)
        self.assertTrue(self.authority.verify_integrity())

    def test_no_http_endpoint_exposes_internal_request_fingerprint_or_references(self):
        self.register()
        self.request()
        result = self.client.get(ROUTE, headers=self.headers())
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertEqual(result.json()["connector_state"], CONNECTOR_STATE)
        self.assertNotIn("DEMO-CNX-SOURCE", result.text)
        self.assertNotIn("DEMO-CNX-REQ", result.text)
        self.assertNotIn("event_digest", result.text)
        self.assertNotIn("fingerprint", result.text)
        self.assertNotIn("request_reference", result.text)
        self.assertFalse(result.json()["items"][0]["dispatch_authorized"])

    def test_no_public_dispatch_acceptance_upload_or_mutation_route(self):
        self.register()
        self.request()
        for path in (ROUTE,):
            for method in ("post", "put", "patch", "delete"):
                with self.subTest(method=method):
                    result = getattr(self.client, method)(
                        path, headers=self.headers(), json={"pass": True},
                    ) if method != "delete" else self.client.delete(
                        path, headers=self.headers(),
                    )
                    self.assertEqual(result.status_code, 405)

    def test_unassigned_domain_and_governance_do_not_inherit_technical_read(self):
        for roles in (("governance",), ("household",), ("finance",)):
            with self.subTest(roles=roles):
                self.assertEqual(
                    self.client.get(ROUTE, headers=self.headers(roles)).status_code,
                    404,
                )
        self.assertEqual(self.client.get(
            "/api/v1/admin/gate-evidence/EXPORT/authority-connectors",
            headers=self.headers(),
        ).status_code, 404)
        self.assertEqual(self.client.get(
            "/api/v1/admin/gate-evidence/UNKNOWN/authority-connectors",
            headers=self.headers(),
        ).status_code, 404)

    def test_missing_invalid_and_expired_jwt_are_rejected(self):
        self.assertEqual(self.client.get(ROUTE).status_code, 401)
        self.assertEqual(self.client.get(
            ROUTE, headers={"Authorization": "Bearer forged"},
        ).status_code, 401)
        self.assertEqual(self.client.get(
            ROUTE, headers=self.headers(expired=True),
        ).status_code, 401)

    def test_signed_browser_session_and_revocation_are_respected(self):
        sid = self.login()
        self.assertEqual(self.client.get(ROUTE).status_code, 200)
        self.assertEqual(self.client.get(
            ROUTE, headers={"Authorization": "Bearer forged"},
        ).status_code, 401)
        self.sessions.revoke_session(sid)
        self.assertEqual(self.client.get(ROUTE).status_code, 401)

    def test_corrupt_handoff_or_enquiry_history_prevents_packet_generation(self):
        self.register()
        self.request()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER authority_enquiry_no_update")
            db.execute(
                "UPDATE authority_enquiry_event SET payload='{}' WHERE sequence=1"
            )
        with self.assertRaises(HandoffIntegrityError):
            self.authority.pending_connector_request_identities(
                self.maker, "DOMESTIC",
            )
        result = self.client.get(ROUTE, headers=self.headers())
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("D1-B-01", result.text)

    def test_pinned_business_source_drift_prevents_internal_and_public_reads(self):
        self.register()
        self.request()
        source = next(iter(PINNED_BUSINESS_SOURCE_BLOBS))
        with patch.dict(PINNED_BUSINESS_SOURCE_BLOBS, {source: "f" * 40}):
            from ronas_api.business_gate_evidence import BusinessSourceSnapshotError
            with self.assertRaises(BusinessSourceSnapshotError):
                self.authority.pending_connector_request_identities(
                    self.maker, "DOMESTIC",
                )
            self.assertEqual(
                self.client.get(ROUTE, headers=self.headers()).status_code, 503,
            )

    def test_default_app_keeps_all_external_authority_connector_routes_off(self):
        plain = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(plain.get(
            ROUTE, headers=self.headers(),
        ).status_code, 404)

    def test_concurrent_enquiry_response_does_not_mix_pending_identity_snapshots(self):
        self.register()
        self.request()
        def read():
            _, enquiry = self.reopen()
            return enquiry.pending_connector_request_identities(
                self.maker, "DOMESTIC",
            )
        def respond():
            _, enquiry = self.reopen()
            return enquiry.record_response_reference(
                principal=self.checker, domain="DOMESTIC",
                evidence_id="D1-B-01", check_kind="ORIGIN",
                source_action_id="DEMO-CNX-SOURCE",
                action_id="DEMO-CNX-RESPONSE-ORIGIN",
                request_ref="DEMO-CNX-REQ-ORIGIN",
                response_ref="DEMO-CNX-NOTE-ORIGIN", expected_revision=1,
            )
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(read), pool.submit(respond)
            pending, _ = a.result(), b.result()
        self.assertIn(len(pending), (0, 1))
        self.assertEqual(self.authority.pending_connector_request_identities(
            self.maker, "DOMESTIC",
        ), ())
        self.assertTrue(self.authority.verify_integrity())


if __name__ == "__main__":
    unittest.main()
