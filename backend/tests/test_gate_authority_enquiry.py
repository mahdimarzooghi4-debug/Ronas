"""Three-channel authority-enquiry technical metadata, never verification.

Every source, role, response and JWT in this suite is LOCAL/TEST synthetic.
A response *reference* proves neither a trusted provider nor legal rights.
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

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.gate_evidence_handoff_sqlite import (
    HandoffConflict, HandoffIntegrityError, HandoffNotAuthorized,
    SqliteSyntheticGateEvidenceHandoff,
)
from ronas_api.gate_evidence_authority_enquiry_sqlite import (
    CHECKS, REQUESTED, RESPONDED, SqliteSyntheticAuthorityEnquiryLedger,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession

ISS = "https://id.example.test/realms/ronas"
API, WEB, ORIGIN = "ronas-api", "ronas-web", "https://ronas.example.test"
API_PATH = "/api/v1/admin/gate-evidence/DOMESTIC/authority-enquiries"
HTML_PATH = "/admin/gate-evidence/DOMESTIC"


class Sessions:
    def __init__(self):
        self.items = {}
    def get_session(self, sid):
        return self.items.get(sid)
    def revoke_session(self, sid):
        self.items.pop(sid, None)


class AuthorityEnquiryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "authority-key", "use": "sig", "alg": "RS256"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "authority.db"
        self.allowed = True
        self.submitter = Principal("synthetic-authority-maker", frozenset({"domestic_ops"}))
        self.reviewer = Principal("synthetic-authority-reviewer", frozenset({"domestic_ops"}))
        self.financier = Principal("synthetic-finance", frozenset({"finance"}))
        self.handoff, self.enquiry = self.reopen()
        self.sessions = Sessions()
        async def no_exchange(_code, _verifier):
            raise AssertionError("external identity not connected")
        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.sessions, no_exchange,
        )
        self.client = self.build_client()

    def reopen(self):
        handoff = SqliteSyntheticGateEvidenceHandoff(
            self.path, trusted_review_authorizer=lambda *_: False,
        )
        enquiry = SqliteSyntheticAuthorityEnquiryLedger(
            handoff, trusted_response_authorizer=lambda actor, domain, evidence, kind: (
                self.allowed and actor == "synthetic-authority-reviewer"
                and domain == "DOMESTIC" and evidence == "D1-B-01"
                and kind in CHECKS
            ),
        )
        return handoff, enquiry

    def build_client(self, *, handoff=None, enquiry=None):
        return TestClient(create_app(
            self.config, self.flow,
            gate_handoff_ledger=handoff or self.handoff,
            authority_enquiry_ledger=enquiry or self.enquiry,
        ), base_url=ORIGIN)

    def token(self, roles=("domestic_ops",), *, expired=False):
        now = int(time.time())
        return jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "typ": "Bearer",
            "sub": "synthetic-authority-maker",
            "iat": now - 5, "nbf": now - 5,
            "exp": now - 10 if expired else now + 500,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "authority-key"})

    def headers(self, roles=("domestic_ops",), *, expired=False):
        return {"Authorization": "Bearer " + self.token(roles, expired=expired)}

    def session(self):
        sid = secrets.token_urlsafe(36)
        self.sessions.items[sid] = BrowserSession(
            "synthetic-authority-maker", frozenset({"domestic_ops"}),
            self.token(), secrets.token_urlsafe(32), int(time.time()) + 250,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        return sid

    def source(self):
        return self.handoff.record_reference(
            principal=self.submitter, domain="DOMESTIC",
            evidence_id="D1-B-01", action_id="DEMO-HANDOFF-AUTH-01",
            reference_ref="DEMO-HANDOFF-REF-01", claimed_sha256="a" * 64,
        )

    def request(self, kind="ORIGIN", ledger=None, **changes):
        payload = dict(
            principal=self.submitter, domain="DOMESTIC",
            evidence_id="D1-B-01", check_kind=kind,
            source_action_id="DEMO-HANDOFF-AUTH-01",
            action_id="DEMO-AUTH-REQUEST-" + kind.replace("_", "-"),
            request_ref="DEMO-AUTH-REQ-" + kind.replace("_", "-"),
            expected_revision=0,
        )
        payload.update(changes)
        return (ledger or self.enquiry).request_check(**payload)

    def respond(self, kind="ORIGIN", ledger=None, **changes):
        payload = dict(
            principal=self.reviewer, domain="DOMESTIC",
            evidence_id="D1-B-01", check_kind=kind,
            source_action_id="DEMO-HANDOFF-AUTH-01",
            action_id="DEMO-AUTH-RESPONSE-" + kind.replace("_", "-"),
            request_ref="DEMO-AUTH-REQ-" + kind.replace("_", "-"),
            response_ref="DEMO-AUTH-NOTE-" + kind.replace("_", "-"),
            expected_revision=1,
        )
        payload.update(changes)
        return (ledger or self.enquiry).record_response_reference(**payload)

    def test_all_nineteen_items_and_three_channels_initially_unconfigured(self):
        for domain, actor, count in (
            ("DOMESTIC", self.submitter, 18),
            ("EXPORT", Principal("synthetic-export", frozenset({"export_ops"})), 18),
            ("FINANCE", self.financier, 21),
        ):
            with self.subTest(domain=domain):
                data = self.enquiry.read_check_status(actor, domain)
                self.assertEqual(len(data["items"]), count)
                self.assertEqual(data["verification_state"], "NO_TRUSTED_EXTERNAL_AUTHORITY")
                self.assertTrue(all(x["technical_state"] == "NO_REQUEST"
                                    and x["revision"] == 0 for x in data["items"]))
                self.assertTrue(all(x["admission_allowed"] is False
                                    and x["business_gate_passed"] is False
                                    and x["authority_verified"] is False
                                    and x["reviewer_qualified"] is False
                                    for x in data["items"]))

    def test_three_independent_channels_remain_unverified_after_response(self):
        self.source()
        for kind in CHECKS:
            request = self.request(kind)
            response = self.respond(kind)
            self.assertEqual(request.stage, REQUESTED)
            self.assertEqual(response.stage, RESPONDED)
            self.assertNotEqual(request.actor_digest, response.actor_digest)
        _, reopened = self.reopen()
        statuses = reopened.read_check_status(self.submitter, "DOMESTIC")["items"]
        for kind in CHECKS:
            item = next(s for s in statuses if s["evidence_id"] == "D1-B-01"
                        and s["check_kind"] == kind)
            self.assertEqual(item["technical_state"], RESPONDED)
            self.assertEqual(item["revision"], 2)
            self.assertFalse(item["source_rights_verified"])
            self.assertFalse(item["reviewer_qualified"])
            self.assertFalse(item["admission_allowed"])
        self.assertNotIn("DEMO-AUTH-REQ", str(statuses))
        self.assertNotIn("DEMO-AUTH-NOTE", str(statuses))
        self.assertTrue(reopened.verify_integrity())

    def test_request_requires_existing_exact_original_handoff_reference(self):
        with self.assertRaises(HandoffConflict):
            self.request()
        self.source()
        with self.assertRaises(HandoffConflict):
            self.request(source_action_id="DEMO-OTHER-SOURCE")
        self.assertTrue(self.enquiry.verify_integrity())

    def test_unknown_check_and_invalid_action_input_fail_closed(self):
        self.source()
        for fields in (
            {"check_kind": "ALL"}, {"request_ref": "https://example.com"},
            {"action_id": "PUBLISH-REAL"}, {"expected_revision": True},
            {"expected_revision": 5}, {"evidence_id": "D1-B-99"},
        ):
            with self.subTest(fields=fields):
                with self.assertRaises((ValueError, HandoffConflict)):
                    self.request(**fields)
        self.assertTrue(self.enquiry.verify_integrity())

    def test_signed_domain_role_is_required_for_internal_commands_and_read(self):
        self.source()
        with self.assertRaises(HandoffNotAuthorized):
            self.request(principal=self.financier)
        with self.assertRaises(HandoffNotAuthorized):
            self.enquiry.read_check_status(self.financier, "DOMESTIC")
        with self.assertRaises(HandoffNotAuthorized):
            self.request(principal=Principal("real-identity", frozenset({"domestic_ops"})))

    def test_same_maker_cannot_record_technical_response_even_if_authorized(self):
        self.source()
        self.request()
        permissive = SqliteSyntheticAuthorityEnquiryLedger(
            self.handoff, trusted_response_authorizer=lambda *_: True,
        )
        with self.assertRaises(HandoffConflict):
            self.respond(ledger=permissive, principal=self.submitter)
        self.assertTrue(self.enquiry.verify_integrity())

    def test_response_without_request_or_wrong_lineage_rejected(self):
        self.source()
        with self.assertRaises(HandoffConflict):
            self.respond()
        self.request()
        with self.assertRaises(HandoffConflict):
            self.respond(request_ref="DEMO-OTHER-REQUEST")
        with self.assertRaises(HandoffConflict):
            self.respond(source_action_id="DEMO-OTHER-SOURCE")

    def test_idempotent_exact_replay_and_conflicting_action_fail_closed(self):
        self.source()
        request = self.request()
        self.assertEqual(self.request(), request)
        with self.assertRaises(HandoffConflict):
            self.request(request_ref="DEMO-MISMATCHED-REQUEST")
        response = self.respond()
        self.assertEqual(self.respond(), response)
        with self.assertRaises(HandoffConflict):
            self.respond(response_ref="DEMO-OTHER-NOTE")
        self.assertTrue(self.enquiry.verify_integrity())

    def test_revoked_current_reviewer_authority_blocks_response_replay(self):
        self.source()
        self.request()
        self.respond()
        self.allowed = False
        with self.assertRaises(HandoffNotAuthorized):
            self.respond()
        self.assertTrue(self.enquiry.verify_integrity())

    def test_concurrent_same_action_creates_one_event(self):
        self.source()
        barrier = Barrier(2)
        def submit():
            _, e = self.reopen()
            barrier.wait(timeout=12)
            return self.request(ledger=e)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(submit), pool.submit(submit)
            self.assertEqual(first.result(), second.result())
        status = self.enquiry.read_check_status(self.submitter, "DOMESTIC")
        self.assertEqual(status["items"][0]["revision"], 1)
        self.assertTrue(self.enquiry.verify_integrity())

    def test_tampered_response_payload_and_chain_head_fail_closed(self):
        self.source()
        self.request()
        self.respond()
        with sqlite3.connect(self.path) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE authority_enquiry_event SET payload='{}'")
            db.execute("DROP TRIGGER authority_enquiry_no_update")
            db.execute("UPDATE authority_enquiry_event SET payload='{}' WHERE sequence=2")
        self.assertFalse(self.enquiry.verify_integrity())
        with self.assertRaises(HandoffIntegrityError):
            self.enquiry.read_check_status(self.submitter, "DOMESTIC")
        with self.assertRaises(HandoffIntegrityError):
            self.reopen()

    def test_hash_head_mismatch_cannot_become_successful_response(self):
        self.source()
        self.request()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE authority_enquiry_meta SET value=? WHERE key='head'",
                       ("f" * 64,))
        self.assertFalse(self.enquiry.verify_integrity())
        with self.assertRaises(HandoffIntegrityError):
            self.respond()

    def test_transaction_failure_rolls_back_one_command(self):
        self.source()
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER deny_enquiry BEFORE INSERT ON authority_enquiry_event
                BEGIN SELECT RAISE(ABORT, 'technical test failure'); END;
            """)
        with self.assertRaises(sqlite3.IntegrityError):
            self.request()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER deny_enquiry")
        self.assertEqual(self.enquiry.read_check_status(
            self.submitter, "DOMESTIC"
        )["items"][0]["technical_state"], "NO_REQUEST")
        self.assertTrue(self.enquiry.verify_integrity())

    def test_readonly_signed_api_no_secret_reference_or_automatic_approval(self):
        self.source()
        self.request()
        self.respond()
        result = self.client.get(API_PATH, headers=self.headers())
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["items"][0]["technical_state"], RESPONDED)
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertNotIn("DEMO-AUTH-REQ", result.text)
        self.assertNotIn("DEMO-AUTH-NOTE", result.text)
        self.assertNotIn("DEMO-HANDOFF-REF", result.text)
        self.assertFalse(result.json()["items"][0]["authority_verified"])
        self.assertFalse(result.json()["items"][0]["business_gate_passed"])
        self.assertEqual(self.client.post(API_PATH, headers=self.headers(),
                                          json={"approve": True}).status_code, 405)

    def test_api_denies_unknown_unassigned_and_invalid_identity(self):
        self.assertEqual(self.client.get(API_PATH).status_code, 401)
        self.assertEqual(self.client.get(
            API_PATH, headers={"Authorization": "Bearer fake"},
        ).status_code, 401)
        self.assertEqual(self.client.get(
            API_PATH, headers=self.headers(("household",)),
        ).status_code, 404)
        self.assertEqual(self.client.get(
            "/api/v1/admin/gate-evidence/EXPORT/authority-enquiries",
            headers=self.headers(),
        ).status_code, 404)
        self.assertEqual(self.client.get(
            "/api/v1/admin/gate-evidence/UNKNOWN/authority-enquiries",
            headers=self.headers(),
        ).status_code, 404)

    def test_default_app_and_mismatched_handoff_are_not_allowed(self):
        plain = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(plain.get(API_PATH, headers=self.headers()).status_code, 404)
        other_handoff = SqliteSyntheticGateEvidenceHandoff(
            self.path.parent / "other.db",
            trusted_review_authorizer=lambda *_: False,
        )
        with self.assertRaises(ValueError):
            create_app(self.config, self.flow,
                       gate_handoff_ledger=other_handoff,
                       authority_enquiry_ledger=self.enquiry)
        with self.assertRaises(ValueError):
            create_app(self.config, gate_handoff_ledger=self.handoff,
                       authority_enquiry_ledger=self.enquiry)

    def test_admin_same_panel_shows_reference_status_not_private_response(self):
        self.source()
        self.request("SOURCE_RIGHTS")
        self.respond("SOURCE_RIGHTS")
        sid = self.session()
        page = self.client.get(HTML_PATH)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("پیگیری استعلام فنی", page.text)
        self.assertIn("TECHNICAL_RESPONSE_REF_RECORDED", page.text)
        self.assertIn("صلاحیت بازبین", page.text)
        self.assertNotIn("DEMO-AUTH-NOTE", page.text)
        self.assertNotIn("DEMO-HANDOFF-REF", page.text)
        self.assertIn("frame-ancestors 'none'", page.headers["content-security-policy"])
        self.sessions.revoke_session(sid)
        self.assertEqual(self.client.get(HTML_PATH).status_code, 401)

    def test_damaged_enquiry_returns_sanitized_503_not_partial_records(self):
        self.source()
        self.request()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER authority_enquiry_no_update")
            db.execute("UPDATE authority_enquiry_event SET payload='{}'")
        result = self.client.get(API_PATH, headers=self.headers())
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json(),
                         {"detail": "TECHNICAL_HANDOFF_UNAVAILABLE"})
        self.assertNotIn("DEMO-AUTH-REQ", result.text)


if __name__ == "__main__":
    unittest.main()
