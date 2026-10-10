"""One-transaction Business evidence technical readiness matrix (LOCAL/TEST).

No live authorities, rights, evidence, reviewer certificates or Gate PASS.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
from threading import Barrier
import time
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.business_gate_evidence import PINNED_BUSINESS_SOURCE_BLOBS
from ronas_api.gate_evidence_handoff_sqlite import (
    HandoffIntegrityError, SqliteSyntheticGateEvidenceHandoff,
)
from ronas_api.gate_evidence_authority_enquiry_sqlite import (
    CHECKS, SqliteSyntheticAuthorityEnquiryLedger,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession

ISS = "https://identity.example.test/realms/ronas"
API, WEB, ORIGIN = "ronas-api", "ronas-web", "https://ronas.example.test"
JSON_ROUTE = "/api/v1/admin/gate-evidence/DOMESTIC/readiness-matrix"
HTML_ROUTE = "/admin/gate-evidence/DOMESTIC/readiness"


class Sessions:
    def __init__(self):
        self.sessions = {}
    def get_session(self, sid):
        return self.sessions.get(sid)
    def revoke_session(self, sid):
        self.sessions.pop(sid, None)


class VerifiedSingleSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "matrix-key", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "matrix.db"
        self.maker = Principal("synthetic-matrix-maker", frozenset({"domestic_ops"}))
        self.human = Principal("synthetic-matrix-human", frozenset({"domestic_ops"}))
        self.checker = Principal("synthetic-matrix-checker", frozenset({"domestic_ops"}))
        self.finance = Principal("synthetic-matrix-finance", frozenset({"finance"}))
        self.handoff, self.authority = self.reopen()
        self.sessions = Sessions()
        async def reject_exchange(_code, _verifier):
            raise AssertionError("No external identity provider is configured")
        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.sessions, reject_exchange,
        )
        self.client = self.for_instance(self.handoff, self.authority)

    def reopen(self):
        handoff = SqliteSyntheticGateEvidenceHandoff(
            self.path, trusted_review_authorizer=lambda actor, domain, ref: (
                actor == "synthetic-matrix-human"
                and domain == "DOMESTIC" and ref == "D1-B-01"
            ),
        )
        authority = SqliteSyntheticAuthorityEnquiryLedger(
            handoff, trusted_response_authorizer=lambda actor, domain, ref, kind: (
                actor == "synthetic-matrix-checker"
                and domain == "DOMESTIC" and ref == "D1-B-01" and kind in CHECKS
            ),
        )
        return handoff, authority

    def for_instance(self, handoff, authority):
        return TestClient(create_app(
            self.config, self.flow, gate_handoff_ledger=handoff,
            authority_enquiry_ledger=authority,
        ), base_url=ORIGIN)

    def token(self, roles=("domestic_ops",), *, expired=False):
        now = int(time.time())
        return jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB,
            "sub": "synthetic-matrix-maker", "typ": "Bearer",
            "iat": now-5, "nbf": now-5, "exp": now-5 if expired else now+600,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "matrix-key"})

    def headers(self, roles=("domestic_ops",), *, expired=False):
        return {"Authorization": "Bearer " + self.token(roles, expired=expired)}

    def login(self, roles=("domestic_ops",)):
        sid = secrets.token_urlsafe(40)
        self.sessions.sessions[sid] = BrowserSession(
            "synthetic-matrix-maker", frozenset(roles),
            self.token(roles), secrets.token_urlsafe(32),
            int(time.time()) + 300,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        return sid

    def register(self):
        return self.handoff.record_reference(
            principal=self.maker, domain="DOMESTIC", evidence_id="D1-B-01",
            action_id="DEMO-MATRIX-REF-01", reference_ref="DEMO-MATRIX-SOURCE",
            claimed_sha256="a" * 64, expected_revision=0,
        )

    def human_note(self):
        return self.handoff.record_human_note(
            principal=self.human, domain="DOMESTIC", evidence_id="D1-B-01",
            action_id="DEMO-MATRIX-HUMAN-NOTE",
            reference_ref="DEMO-MATRIX-SOURCE",
            claimed_sha256="a" * 64, note_ref="DEMO-MATRIX-NOTE", expected_revision=1,
        )

    def request(self, kind="ORIGIN", authority=None):
        return (authority or self.authority).request_check(
            principal=self.maker, domain="DOMESTIC", evidence_id="D1-B-01",
            check_kind=kind, source_action_id="DEMO-MATRIX-REF-01",
            action_id="DEMO-MATRIX-REQUEST-" + kind.replace("_", "-"),
            request_ref="DEMO-MATRIX-CHECK-" + kind.replace("_", "-"),
            expected_revision=0,
        )

    def respond(self, kind="ORIGIN"):
        return self.authority.record_response_reference(
            principal=self.checker, domain="DOMESTIC", evidence_id="D1-B-01",
            check_kind=kind, source_action_id="DEMO-MATRIX-REF-01",
            action_id="DEMO-MATRIX-RESPONSE-" + kind.replace("_", "-"),
            request_ref="DEMO-MATRIX-CHECK-" + kind.replace("_", "-"),
            response_ref="DEMO-MATRIX-RESULT-" + kind.replace("_", "-"),
            expected_revision=1,
        )

    def first(self):
        return self.authority.read_readiness_matrix(
            self.maker, "DOMESTIC"
        )["items"][0]

    def test_empty_matrix_preserves_all_local_business_requirement_slots(self):
        for domain, actor, size in (
            ("DOMESTIC", self.maker, 6),
            ("EXPORT", Principal("synthetic-export", frozenset({"export_ops"})), 6),
            ("FINANCE", self.finance, 7),
        ):
            with self.subTest(domain=domain):
                result = self.authority.read_readiness_matrix(actor, domain)
                self.assertEqual(result["snapshot_contract"],
                                 "SAME_LOCAL_SQLITE_TRANSACTION")
                self.assertEqual(result["matrix_state"], "BLOCKED_EXTERNAL_VERIFICATION")
                self.assertEqual(len(result["items"]), size)
                for row in result["items"]:
                    self.assertEqual(row["technical_handoff"]["technical_state"],
                                     "NO_REFERENCE")
                    self.assertEqual(len(row["authority_checks"]), 3)
                    self.assertEqual([c["check_kind"] for c in row["authority_checks"]],
                                     list(CHECKS))
                    self.assertTrue(all(c["technical_state"] == "NO_REQUEST"
                                        for c in row["authority_checks"]))
                    self.assertFalse(row["technical_handoff"]["admission_allowed"])
                    self.assertFalse(row["business_approval"])
                self.assertFalse(result["business_gate_passed"])

    def test_reference_note_and_three_enquiries_are_atomic_read_projection(self):
        self.register()
        self.human_note()
        for kind in CHECKS:
            self.request(kind)
        self.respond("SOURCE_RIGHTS")
        reopened_handoff, reopened = self.reopen()
        page = reopened.read_readiness_matrix(self.maker, "DOMESTIC")
        row = page["items"][0]
        self.assertEqual(row["technical_handoff"]["technical_state"],
                         "HUMAN_NOTE_RECORDED")
        self.assertEqual(row["technical_handoff"]["review_revision"], 2)
        expected = {
            "ORIGIN": "CHECK_REFERENCE_REQUESTED",
            "SOURCE_RIGHTS": "TECHNICAL_RESPONSE_REF_RECORDED",
            "REVIEWER_QUALIFICATION": "CHECK_REFERENCE_REQUESTED",
        }
        self.assertEqual({c["check_kind"]: c["technical_state"]
                          for c in row["authority_checks"]}, expected)
        self.assertTrue(all(not c["authority_verified"]
                            for c in row["authority_checks"]))
        self.assertFalse(row["technical_handoff"]["evidence_verified"])
        self.assertFalse(row["technical_handoff"]["admission_allowed"])
        self.assertFalse(page["business_gate_passed"])
        self.assertTrue(reopened.verify_integrity())
        self.assertTrue(reopened_handoff.verify_integrity())

    def test_private_event_references_and_actor_metadata_do_not_leave_api(self):
        self.register()
        self.request()
        self.respond()
        result = self.client.get(JSON_ROUTE, headers=self.headers())
        self.assertEqual(result.status_code, 200, result.text)
        for secret in ("DEMO-MATRIX-SOURCE", "DEMO-MATRIX-CHECK",
                       "DEMO-MATRIX-RESULT", "DEMO-MATRIX-REF-01",
                       "synthetic-matrix-maker", "synthetic-matrix-checker",
                       "claimed_sha256", "event_digest", "actor_digest",
                       "source_action_id", "request_ref", "response_ref"):
            self.assertNotIn(secret, result.text)
        self.assertEqual(result.headers["cache-control"], "no-store")

    def test_authenticated_domain_scope_and_unknown_domain_parity(self):
        self.assertEqual(self.client.get(JSON_ROUTE).status_code, 401)
        self.assertEqual(self.client.get(
            JSON_ROUTE, headers={"Authorization": "Bearer forged"}
        ).status_code, 401)
        for roles in (("household",), ("governance",), ("finance",)):
            self.assertEqual(self.client.get(
                JSON_ROUTE, headers=self.headers(roles)
            ).status_code, 404)
        self.assertEqual(self.client.get(
            "/api/v1/admin/gate-evidence/UNKNOWN/readiness-matrix",
            headers=self.headers()
        ).status_code, 404)
        self.assertEqual(self.client.get(
            "/api/v1/admin/gate-evidence/EXPORT/readiness-matrix",
            headers=self.headers()
        ).status_code, 404)

    def test_multi_role_signed_domain_not_inferred_from_governance_alone(self):
        r = self.client.get(
            JSON_ROUTE, headers=self.headers(("domestic_ops", "governance"))
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["domain"], "DOMESTIC")
        self.assertEqual(r.json()["items"][0]["technical_handoff"]["technical_state"],
                         "NO_REFERENCE")

    def test_governance_can_still_read_public_gate_without_private_matrix(self):
        self.login(("governance",))
        public = self.client.get("/admin/gate-evidence/DOMESTIC")
        self.assertEqual(public.status_code, 200)
        self.assertIn("D1-B-01", public.text)
        self.assertNotIn("/readiness", public.text)
        self.assertNotIn("پیگیری استعلام فنی", public.text)
        self.assertEqual(self.client.get(HTML_ROUTE).status_code, 404)

    def test_role_scoped_admin_link_and_html_snapshot_are_read_only(self):
        self.register()
        self.request("ORIGIN")
        self.login()
        public = self.client.get("/admin/gate-evidence/DOMESTIC")
        self.assertEqual(public.status_code, 200)
        self.assertIn("/admin/gate-evidence/DOMESTIC/readiness", public.text)
        page = self.client.get(HTML_ROUTE)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("D1-B-01", page.text)
        self.assertIn("CHECK_REFERENCE_REQUESTED", page.text)
        self.assertIn("پذیرش: مسدود", page.text)
        self.assertNotIn("DEMO-MATRIX-CHECK", page.text)
        self.assertIn("frame-ancestors 'none'", page.headers["content-security-policy"])
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.assertEqual(self.client.post(HTML_ROUTE).status_code, 405)
        self.assertEqual(self.client.post(
            JSON_ROUTE, headers=self.headers(), json={"pass": True}
        ).status_code, 405)

    def test_logout_prevents_matrix_html_and_cookie_api_access(self):
        sid = self.login()
        self.assertEqual(self.client.get(HTML_ROUTE).status_code, 200)
        self.assertEqual(self.client.get(JSON_ROUTE).status_code, 200)
        self.sessions.revoke_session(sid)
        self.assertEqual(self.client.get(HTML_ROUTE).status_code, 401)
        self.assertEqual(self.client.get(JSON_ROUTE).status_code, 401)

    def test_bad_explicit_bearer_cannot_fallback_to_valid_browser_cookie(self):
        self.login()
        self.assertEqual(self.client.get(
            JSON_ROUTE, headers={"Authorization": "Bearer invalid"}
        ).status_code, 401)
        self.assertEqual(self.client.get(JSON_ROUTE).status_code, 200)

    def test_corrupted_enquiry_hides_entire_matrix_without_partial_rows(self):
        self.register()
        self.request()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER authority_enquiry_no_update")
            db.execute("UPDATE authority_enquiry_event SET payload='{}'")
        result = self.client.get(JSON_ROUTE, headers=self.headers())
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json(),
                         {"detail": "TECHNICAL_HANDOFF_UNAVAILABLE"})
        self.assertNotIn("D1-B-01", result.text)
        self.assertFalse(self.authority.verify_integrity())

    def test_corrupt_original_handoff_blocks_same_matrix(self):
        self.register()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER handoff_no_update")
            db.execute("UPDATE handoff_event SET payload='{}'")
        result = self.client.get(JSON_ROUTE, headers=self.headers())
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("D1-B-01", result.text)

    def test_pinned_business_source_drift_blocks_matrix(self):
        key = next(iter(PINNED_BUSINESS_SOURCE_BLOBS))
        with patch.dict(PINNED_BUSINESS_SOURCE_BLOBS, {key: "f" * 40}):
            result = self.client.get(JSON_ROUTE, headers=self.headers())
            self.assertEqual(result.status_code, 503)
            self.assertEqual(result.json(),
                             {"detail": "PINNED_BUSINESS_SOURCE_UNAVAILABLE"})

    def test_initial_domain_without_enquiries_is_different_from_approved_evidence(self):
        self.register()
        matrix = self.authority.read_readiness_matrix(self.maker, "DOMESTIC")
        row = matrix["items"][0]
        self.assertEqual(row["technical_handoff"]["technical_state"],
                         "REFERENCE_RECORDED")
        self.assertEqual(row["technical_handoff"]["origin_state"],
                         "NOT_AUTHENTICATED")
        self.assertFalse(row["technical_handoff"]["business_gate_passed"])
        self.assertTrue(all(c["technical_state"] == "NO_REQUEST"
                            for c in row["authority_checks"]))
        self.assertFalse(matrix["admission_allowed"])

    def test_concurrent_response_and_matrix_read_share_ordered_sqlite_snapshot(self):
        self.register()
        self.request()
        barrier = Barrier(2)
        def reader():
            handoff, authority = self.reopen()
            barrier.wait(timeout=12)
            data = authority.read_readiness_matrix(self.maker, "DOMESTIC")
            return data["items"][0]
        def writer():
            handoff, authority = self.reopen()
            barrier.wait(timeout=12)
            return authority.record_response_reference(
                principal=self.checker, domain="DOMESTIC", evidence_id="D1-B-01",
                check_kind="ORIGIN", source_action_id="DEMO-MATRIX-REF-01",
                action_id="DEMO-MATRIX-RESPONSE-ORIGIN",
                request_ref="DEMO-MATRIX-CHECK-ORIGIN",
                response_ref="DEMO-MATRIX-RESULT-ORIGIN", expected_revision=1,
            )
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(reader), pool.submit(writer)
            read, _ = a.result(), b.result()
        check = read["authority_checks"][0]
        self.assertIn(check["technical_state"],
                      ("CHECK_REFERENCE_REQUESTED",
                       "TECHNICAL_RESPONSE_REF_RECORDED"))
        self.assertEqual(check["revision"],
                         1 if check["technical_state"] == "CHECK_REFERENCE_REQUESTED"
                         else 2)
        self.assertEqual(self.first()["authority_checks"][0]["revision"], 2)
        self.assertTrue(self.authority.verify_integrity())

    def test_no_default_or_mismatched_provider_routes(self):
        plain = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(plain.get(
            JSON_ROUTE, headers=self.headers()
        ).status_code, 404)
        handoff, other = self.reopen()
        with self.assertRaises(ValueError):
            create_app(self.config, self.flow,
                       gate_handoff_ledger=self.handoff,
                       authority_enquiry_ledger=other)


if __name__ == "__main__":
    unittest.main()
