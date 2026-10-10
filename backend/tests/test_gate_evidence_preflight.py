"""LOCAL/TEST technical blocker preflight, not real source attestation.

Uses synthetic Keycloak-shaped identities and DEMO byte fixtures only.
Neither digest matching nor human-note history creates evidence acceptance.
"""
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.gate_evidence_preflight import (
    BLOCKERS, BYTE_CHECK_MATCH, BYTE_CHECK_MISMATCH,
    preflight_for_status,
)
from ronas_api.gate_evidence_handoff_sqlite import (
    HandoffConflict, HandoffIntegrityError, HandoffNotAuthorized,
    SqliteSyntheticGateEvidenceHandoff,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession

ORIGIN = "https://ronas.example.test"
ISS = "https://id.example.test/realms/ronas"
API, WEB = "ronas-api", "ronas-web"
BASE = "/api/v1/admin/gate-evidence"
PREFLIGHT = BASE + "/DOMESTIC/admission-preflight"
DETAIL = "/admin/gate-evidence/DOMESTIC"
DEMO_BYTES = b"DEMO-EVIDENCE-BYTES-CONTROLLED-OFFLINE\n"


class TestSessionStore:
    def __init__(self):
        self.items = {}
    def get_session(self, sid):
        return self.items.get(sid)
    def revoke_session(self, sid):
        self.items.pop(sid, None)


class EvidenceAdmissionPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "preflight-key", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "preflight.db"
        self.reviewer_allowed = True
        self.ledger = self.reopen()
        self.maker = Principal("synthetic-evidence-maker", frozenset({"domestic_ops"}))
        self.reviewer = Principal("synthetic-independent-reviewer", frozenset({"domestic_ops"}))
        self.financier = Principal("synthetic-finance", frozenset({"finance"}))
        self.store = TestSessionStore()
        async def reject_exchange(_code, _verifier):
            raise AssertionError("no real external Keycloak")
        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.store, reject_exchange,
        )
        self.client = TestClient(
            create_app(self.config, self.flow, gate_handoff_ledger=self.ledger),
            base_url=ORIGIN,
        )

    def reopen(self):
        return SqliteSyntheticGateEvidenceHandoff(
            self.path, trusted_review_authorizer=lambda actor, domain, evidence: (
                self.reviewer_allowed
                and actor == "synthetic-independent-reviewer"
                and domain == "DOMESTIC" and evidence == "D1-B-01"
            ),
        )

    def headers(self, roles=("domestic_ops",)):
        now = int(time.time())
        token = jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB,
            "sub": "synthetic-evidence-maker", "typ": "Bearer",
            "iat": now - 5, "nbf": now - 5, "exp": now + 500,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "preflight-key"})
        return {"Authorization": "Bearer " + token}

    def session(self):
        sid = secrets.token_urlsafe(40)
        token = self.headers()["Authorization"][7:]
        self.store.items[sid] = BrowserSession(
            "synthetic-evidence-maker", frozenset({"domestic_ops"}),
            token, secrets.token_urlsafe(32), int(time.time()) + 240,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        return sid

    def record(self):
        return self.ledger.record_reference(
            principal=self.maker, domain="DOMESTIC", evidence_id="D1-B-01",
            action_id="DEMO-REFERENCE-PREFLIGHT-01",
            reference_ref="DEMO-REFERENCE-PREFLIGHT",
            claimed_sha256=hashlib.sha256(DEMO_BYTES).hexdigest(),
            expected_revision=0,
        )

    def respond(self):
        return self.ledger.record_human_note(
            principal=self.reviewer, domain="DOMESTIC", evidence_id="D1-B-01",
            action_id="DEMO-NOTE-PREFLIGHT-01",
            reference_ref="DEMO-REFERENCE-PREFLIGHT",
            claimed_sha256=hashlib.sha256(DEMO_BYTES).hexdigest(),
            note_ref="DEMO-NOTE-UNVERIFIED",
            expected_revision=1,
        )

    def inspect(self, payload=DEMO_BYTES, *, actor=None, ref="DEMO-REFERENCE-PREFLIGHT",
                domain="DOMESTIC"):
        return self.ledger.inspect_demo_reference_bytes(
            principal=actor or self.maker, domain=domain, evidence_id="D1-B-01",
            reference_ref=ref, demo_bytes=payload,
        )

    def test_all_nineteen_source_requirements_are_blocked_by_default(self):
        for domain, actor, size in (
            ("DOMESTIC", self.maker, 6),
            ("EXPORT", Principal("synthetic-export", frozenset({"export_ops"})), 6),
            ("FINANCE", self.financier, 7),
        ):
            with self.subTest(domain=domain):
                result = self.ledger.preflight_worklist(actor, domain)
                self.assertEqual(result["preflight_state"], "BLOCKED_EXTERNAL_VERIFICATION")
                self.assertEqual(len(result["items"]), size)
                for item in result["items"]:
                    self.assertEqual(item["technical_state"], "NO_REFERENCE")
                    self.assertEqual(item["bytes_check"], "NOT_CHECKED")
                    self.assertEqual(item["origin_state"], "NOT_AUTHENTICATED")
                    self.assertEqual(item["rights_state"], "NOT_VERIFIED")
                    self.assertEqual(item["reviewer_qualification_state"], "NOT_VERIFIED")
                    self.assertFalse(item["evidence_verified"])
                    self.assertFalse(item["admission_allowed"])
                    self.assertFalse(item["business_gate_passed"])
                    self.assertIn("EVIDENCE_BYTES_NOT_ATTESTED", item["blockers"])
                    for blocker in BLOCKERS:
                        self.assertIn(blocker, item["blockers"])

    def test_recorded_reference_and_human_note_do_not_clear_blockers(self):
        self.record()
        first = self.ledger.preflight_worklist(self.maker, "DOMESTIC")["items"][0]
        self.assertEqual(first["technical_state"], "REFERENCE_RECORDED")
        self.assertEqual(first["review_revision"], 1)
        self.assertFalse(first["admission_allowed"])
        self.respond()
        second = self.reopen().preflight_worklist(self.maker, "DOMESTIC")["items"][0]
        self.assertEqual(second["technical_state"], "HUMAN_NOTE_RECORDED")
        self.assertEqual(second["review_revision"], 2)
        self.assertFalse(second["evidence_verified"])
        self.assertFalse(second["business_gate_passed"])
        self.assertEqual(second["rights_state"], "NOT_VERIFIED")
        self.assertIn("REVIEWER_QUALIFICATION_NOT_VERIFIED", second["blockers"])
        self.assertTrue(self.reopen().verify_integrity())

    def test_actual_demo_byte_match_is_not_provenance_or_rights(self):
        self.record()
        match = self.inspect()
        self.assertEqual(match["bytes_check"], BYTE_CHECK_MATCH)
        self.assertNotIn("EVIDENCE_BYTES_NOT_ATTESTED", match["blockers"])
        self.assertEqual(set(match["blockers"]), set(BLOCKERS))
        self.assertFalse(match["evidence_verified"])
        self.assertFalse(match["business_gate_passed"])
        self.assertFalse(match["admission_allowed"])
        self.assertNotIn("claimed_sha256", match)
        self.assertNotIn("DEMO-REFERENCE", str(match))
        # The transient positive result is NOT persisted or promoted to GET.
        via_api = self.client.get(PREFLIGHT, headers=self.headers())
        self.assertEqual(via_api.status_code, 200)
        self.assertEqual(via_api.json()["items"][0]["bytes_check"], "NOT_CHECKED")
        self.assertFalse(via_api.json()["items"][0]["admission_allowed"])

    def test_mismatching_demo_byte_claim_is_explicitly_not_verified(self):
        self.record()
        mismatch = self.inspect(b"DEMO-OTHER-OFFLINE-EVIDENCE\n")
        self.assertEqual(mismatch["bytes_check"], BYTE_CHECK_MISMATCH)
        self.assertFalse(mismatch["admission_allowed"])
        self.assertIn("EVIDENCE_BYTES_NOT_ATTESTED", mismatch["blockers"])
        self.assertTrue(self.reopen().verify_integrity())

    def test_demo_byte_check_after_human_note_still_cannot_approve(self):
        self.record()
        self.respond()
        result = self.reopen().inspect_demo_reference_bytes(
            principal=self.maker, domain="DOMESTIC",
            evidence_id="D1-B-01", reference_ref="DEMO-REFERENCE-PREFLIGHT",
            demo_bytes=DEMO_BYTES,
        )
        self.assertEqual(result["technical_state"], "HUMAN_NOTE_RECORDED")
        self.assertEqual(result["bytes_check"], BYTE_CHECK_MATCH)
        self.assertFalse(result["business_gate_passed"])
        self.assertFalse(result["admission_allowed"])
        self.assertEqual(result["reviewer_qualification_state"], "NOT_VERIFIED")

    def test_wrong_reference_and_no_previous_claim_fail_closed(self):
        with self.assertRaises(HandoffConflict):
            self.inspect()
        self.record()
        with self.assertRaises(HandoffConflict):
            self.inspect(ref="DEMO-OTHER-REFERENCE")

    def test_unsupported_payload_types_and_non_demo_data_are_rejected(self):
        self.record()
        for payload in (
            b"", b"ACTUAL-PERSONAL-DATA", b"DEMO-" + b"x" * 1_048_576,
            "DEMO-TEXT", bytearray(DEMO_BYTES), None,
        ):
            with self.subTest(payload_type=type(payload).__name__):
                with self.assertRaises(ValueError):
                    self.inspect(payload)

    def test_domain_and_role_mismatch_cannot_inspect_claimed_digest(self):
        self.record()
        with self.assertRaises(HandoffNotAuthorized):
            self.inspect(actor=self.financier)
        with self.assertRaises(HandoffNotAuthorized):
            self.inspect(domain="EXPORT")
        with self.assertRaises(ValueError):
            self.ledger.inspect_demo_reference_bytes(
                principal=self.maker, domain="DOMESTIC", evidence_id="FIN-001",
                reference_ref="DEMO-REFERENCE-PREFLIGHT", demo_bytes=DEMO_BYTES,
            )

    def test_unauthorized_user_cannot_see_preflight_dossier(self):
        with self.assertRaises(HandoffNotAuthorized):
            self.ledger.preflight_worklist(self.financier, "DOMESTIC")
        self.assertEqual(
            self.client.get(PREFLIGHT, headers=self.headers(("household",))).status_code,
            404,
        )
        self.assertEqual(self.client.get(
            BASE + "/EXPORT/admission-preflight", headers=self.headers(),
        ).status_code, 404)
        self.assertEqual(self.client.get(
            BASE + "/UNKNOWN/admission-preflight", headers=self.headers(),
        ).status_code, 404)

    def test_signed_get_exposes_no_evidence_metadata_or_mutation(self):
        self.record()
        self.respond()
        result = self.client.get(PREFLIGHT, headers=self.headers())
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertEqual(result.json()["items"][0]["technical_state"],
                         "HUMAN_NOTE_RECORDED")
        self.assertEqual(result.json()["preflight_state"],
                         "BLOCKED_EXTERNAL_VERIFICATION")
        for secret in ("DEMO-REFERENCE-PREFLIGHT", "DEMO-NOTE-UNVERIFIED",
                       hashlib.sha256(DEMO_BYTES).hexdigest(),
                       "synthetic-independent-reviewer", "claimed_sha256"):
            self.assertNotIn(secret, result.text)
        self.assertEqual(self.client.post(
            PREFLIGHT, headers=self.headers(),
            json={"rights_verified": True, "qualification": "VERIFIED"}
        ).status_code, 405)

    def test_api_authentication_and_default_off_are_preserved(self):
        self.assertEqual(self.client.get(PREFLIGHT).status_code, 401)
        self.assertEqual(self.client.get(
            PREFLIGHT, headers={"Authorization": "Bearer forged"}
        ).status_code, 401)
        baseline = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(baseline.get(
            PREFLIGHT, headers=self.headers()
        ).status_code, 404)

    def test_session_logout_and_html_warning(self):
        sid = self.session()
        r = self.client.get(DETAIL)
        self.assertEqual(r.status_code, 200)
        self.assertIn("اصالت منشأ", r.text)
        self.assertIn("صلاحیت بازبین تأیید نشده", r.text)
        self.assertNotIn("DEMO-REFERENCE-PREFLIGHT", r.text)
        self.assertIn("frame-ancestors 'none'", r.headers["content-security-policy"])
        self.store.revoke_session(sid)
        self.assertEqual(self.client.get(DETAIL).status_code, 401)

    def test_corrupted_handoff_history_fails_api_and_transient_byte_check(self):
        self.record()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER handoff_no_update")
            db.execute(
                "UPDATE handoff_event SET payload='{}' WHERE sequence=1"
            )
        result = self.client.get(PREFLIGHT, headers=self.headers())
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json(), {"detail": "TECHNICAL_HANDOFF_UNAVAILABLE"})
        with self.assertRaises(HandoffIntegrityError):
            self.inspect()

    def test_invalid_stage_revision_cannot_make_preflight_ready(self):
        base = dict(domain="DOMESTIC", evidence_id="D1-B-01",
                    technical_state="HUMAN_NOTE_RECORDED", review_revision=2)
        with self.assertRaises(ValueError):
            preflight_for_status({**base, "review_revision": True})
        with self.assertRaises(ValueError):
            preflight_for_status({**base, "technical_state": "VERIFIED"})
        with self.assertRaises(ValueError):
            preflight_for_status({**base, "review_revision": 1})
        with self.assertRaises(ValueError):
            preflight_for_status(base, bytes_check="VALIDATED_FOR_PRODUCTION")
        ok = preflight_for_status(base, bytes_check=BYTE_CHECK_MATCH)
        self.assertFalse(ok["admission_allowed"])
        self.assertFalse(ok["business_gate_passed"])


if __name__ == "__main__":
    unittest.main()
