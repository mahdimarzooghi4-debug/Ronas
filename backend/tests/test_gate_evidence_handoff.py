"""Synthetic Business-gate evidence reference handoff; no source approval.

No real file is uploaded or consumed. An external claimed digest is metadata,
never proof of rights or authenticity. Human notes are NOT gate decisions.
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
from ronas_api.business_gate_evidence import BUSINESS_SOURCE_SHA
from ronas_api.gate_evidence_handoff_sqlite import (
    HandoffIntegrityError, HandoffConflict, HandoffNotAuthorized,
    SqliteSyntheticGateEvidenceHandoff,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession

ISS, API, WEB = "https://id.example.test/realms/ronas", "ronas-api", "ronas-web"
ORIGIN = "https://ronas.example.test"
ROOT = "/api/v1/admin/gate-evidence"
NOTE = ROOT + "/DOMESTIC/technical-handoff"
BODY = "/admin/gate-evidence/DOMESTIC"


class Sessions:
    def __init__(self):
        self.entries = {}

    def get_session(self, sid):
        return self.entries.get(sid)

    def revoke_session(self, sid):
        self.entries.pop(sid, None)


class SyntheticGateHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "handoff-key", "use": "sig", "alg": "RS256"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "handoff.db"
        self.reviewer_authorized = True
        self.ledger = self.reopen()
        self.maker = Principal("synthetic-evidence-maker", frozenset({"domestic_ops"}))
        self.checker = Principal("synthetic-evidence-checker", frozenset({"domestic_ops"}))
        self.finance = Principal("synthetic-finance-actor", frozenset({"finance"}))
        self.sessions = Sessions()

        async def no_exchange(_code, _verifier):
            raise AssertionError("no external identity provider")

        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.sessions, no_exchange,
        )
        self.client = self.client_for(self.ledger)

    def reopen(self):
        return SqliteSyntheticGateEvidenceHandoff(
            self.path,
            trusted_review_authorizer=lambda actor, domain, ref: (
                self.reviewer_authorized and actor == "synthetic-evidence-checker"
                and domain == "DOMESTIC" and ref == "D1-B-01"
            ),
        )

    def client_for(self, ledger=None, *, browser=True):
        return TestClient(create_app(
            self.config, self.flow if browser else None,
            gate_handoff_ledger=ledger,
        ), base_url=ORIGIN)

    def signed(self, roles=("domestic_ops",), *, expired=False):
        now = int(time.time())
        return jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "sub": "synthetic-evidence-maker",
            "typ": "Bearer", "iat": now - 5, "nbf": now - 5,
            "exp": now - 50 if expired else now + 500,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "handoff-key"})

    def headers(self, roles=("domestic_ops",), *, expired=False):
        return {"Authorization": "Bearer " + self.signed(roles, expired=expired)}

    def login(self, roles=("domestic_ops",)):
        sid = secrets.token_urlsafe(40)
        self.sessions.entries[sid] = BrowserSession(
            "synthetic-evidence-maker", frozenset(roles), self.signed(roles),
            secrets.token_urlsafe(32), int(time.time()) + 240,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        return sid

    def record(self, ledger=None, **changes):
        args = {
            "principal": self.maker, "domain": "DOMESTIC",
            "evidence_id": "D1-B-01", "action_id": "DEMO-REGISTER-01",
            "reference_ref": "DEMO-RECEIPT-01",
            "claimed_sha256": "a" * 64, "expected_revision": 0,
        }
        args.update(changes)
        return (ledger or self.ledger).record_reference(**args)

    def respond(self, ledger=None, **changes):
        args = {
            "principal": self.checker, "domain": "DOMESTIC",
            "evidence_id": "D1-B-01", "action_id": "DEMO-REVIEW-01",
            "reference_ref": "DEMO-RECEIPT-01", "claimed_sha256": "a" * 64,
            "note_ref": "DEMO-HUMAN-NOTE-01", "expected_revision": 1,
        }
        args.update(changes)
        return (ledger or self.ledger).record_human_note(**args)

    def test_initial_worklist_is_unverified_without_records(self):
        listing = self.ledger.worklist(self.maker, "DOMESTIC")
        self.assertEqual(len(listing["items"]), 6)
        self.assertTrue(all(x["technical_state"] == "NO_REFERENCE"
                            for x in listing["items"]))
        self.assertTrue(all(x["business_approval"] is False
                            and x["rights_verified"] is False
                            and x["evidence_verified"] is False
                            for x in listing["items"]))
        self.assertEqual(listing["business_source_sha"], BUSINESS_SOURCE_SHA)
        self.assertTrue(self.ledger.verify_integrity())

    def test_reference_and_independent_note_persist_without_gate_pass(self):
        ref = self.record()
        self.assertEqual(ref.stage, "REFERENCE_RECORDED")
        self.assertEqual(ref.revision, 1)
        note = self.respond()
        self.assertEqual(note.stage, "HUMAN_NOTE_RECORDED")
        self.assertEqual(note.revision, 2)
        self.assertNotEqual(ref.actor_digest, note.actor_digest)
        rebuilt = self.reopen().worklist(self.maker, "DOMESTIC")
        first = rebuilt["items"][0]
        self.assertEqual(first["technical_state"], "HUMAN_NOTE_RECORDED")
        self.assertEqual(first["review_revision"], 2)
        self.assertFalse(first["evidence_verified"])
        self.assertFalse(first["rights_verified"])
        self.assertFalse(first["business_approval"])
        self.assertNotIn("DEMO-HUMAN-NOTE-01", str(rebuilt))
        self.assertNotIn("DEMO-RECEIPT-01", str(rebuilt))
        self.assertNotIn("a" * 64, str(rebuilt))
        self.assertTrue(self.reopen().verify_integrity())

    def test_same_action_idempotent_only_for_exact_payload_and_current_authority(self):
        ref = self.record()
        self.assertEqual(self.record(), ref)
        with self.assertRaises(HandoffConflict):
            self.record(reference_ref="DEMO-OTHER-REF")
        note = self.respond()
        self.assertEqual(self.respond(), note)
        self.reviewer_authorized = False
        with self.assertRaises(HandoffNotAuthorized):
            self.respond()
        self.assertTrue(self.reopen().verify_integrity())

    def test_wrong_role_or_unassigned_authority_cannot_record_a_human_note(self):
        self.record()
        with self.assertRaises(HandoffNotAuthorized):
            self.respond(principal=self.maker)
        with self.assertRaises(HandoffNotAuthorized):
            self.respond(principal=Principal("synthetic-stranger",
                                             frozenset({"domestic_ops"})))
        with self.assertRaises(HandoffNotAuthorized):
            self.respond(principal=Principal("synthetic-finance-actor",
                                             frozenset({"finance"})))
        self.assertEqual(self.ledger.worklist(self.maker, "DOMESTIC")[
            "items"][0]["review_revision"], 1)

    def test_response_cannot_precede_request_or_be_same_maker(self):
        with self.assertRaises(HandoffConflict):
            self.respond()
        self.record()
        with self.assertRaises(HandoffConflict):
            self.respond(principal=self.maker)
        self.assertTrue(self.reopen().verify_integrity())

    def test_invalid_revision_reference_and_provenance_input_rejected(self):
        for updates in (
            {"evidence_id": "NO-ID"}, {"reference_ref": "https://example.com/foo"},
            {"claimed_sha256": "not-a-digest"}, {"action_id": "NOT-DEMO"},
            {"expected_revision": True}, {"expected_revision": 8},
        ):
            with self.subTest(updates=updates):
                with self.assertRaises((ValueError, HandoffConflict)):
                    self.record(**updates)
        self.assertTrue(self.ledger.verify_integrity())

    def test_cross_engine_criteria_and_finance_roles_remain_separate(self):
        with self.assertRaises(HandoffNotAuthorized):
            self.record(principal=self.finance)
        finance = self.ledger.record_reference(
            principal=self.finance, domain="FINANCE", evidence_id="FIN-001",
            action_id="DEMO-FIN-REGISTER", reference_ref="DEMO-FIN-REF",
            claimed_sha256="f" * 64,
        )
        self.assertEqual(finance.domain, "FINANCE")
        self.assertEqual(self.ledger.worklist(self.finance, "FINANCE")[
            "items"][0]["technical_state"], "REFERENCE_RECORDED")
        with self.assertRaises(HandoffNotAuthorized):
            self.ledger.worklist(self.maker, "FINANCE")
        self.assertEqual(self.ledger.worklist(self.maker, "DOMESTIC")[
            "items"][0]["technical_state"], "NO_REFERENCE")

    def test_append_only_trigger_and_tampered_payload_fail_closed(self):
        self.record()
        with sqlite3.connect(self.path) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE handoff_event SET payload='{}' WHERE sequence=1")
            db.execute("DROP TRIGGER handoff_no_update")
            db.execute("UPDATE handoff_event SET payload='{}' WHERE sequence=1")
        self.assertFalse(self.ledger.verify_integrity())
        with self.assertRaises(HandoffIntegrityError):
            self.reopen()

    def test_changed_event_hash_or_metadata_head_detected_on_reopen(self):
        for column, val in (("head", "0" * 64),):
            with self.subTest(column=column):
                self.record()
                with sqlite3.connect(self.path) as db:
                    db.execute(
                        "UPDATE handoff_meta SET value=? WHERE key='head'", (val,),
                    )
                with self.assertRaises(HandoffIntegrityError):
                    self.reopen()
                return

    def test_audit_insert_failure_rolls_back_entire_reference_command(self):
        baseline = self.ledger.worklist(self.maker, "DOMESTIC")
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER block_handoff BEFORE INSERT ON handoff_event
                BEGIN SELECT RAISE(ABORT, 'evidence write failed'); END;
            """)
        with self.assertRaises(sqlite3.IntegrityError):
            self.record()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER block_handoff")
        self.assertEqual(self.ledger.worklist(self.maker, "DOMESTIC"), baseline)
        self.assertTrue(self.reopen().verify_integrity())

    def test_parallel_duplicate_reference_is_single_durable_event(self):
        barrier = Barrier(2)
        def runner():
            ledger = self.reopen()
            barrier.wait(timeout=12)
            return self.record(ledger)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(runner)
            b = pool.submit(runner)
            self.assertEqual(a.result(), b.result())
        self.assertEqual(self.ledger.worklist(self.maker, "DOMESTIC")[
            "items"][0]["review_revision"], 1)
        self.assertTrue(self.reopen().verify_integrity())

    def test_signed_api_is_optional_and_readonly(self):
        r = self.client.get(NOTE, headers=self.headers())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["items"]), 6)
        self.assertNotIn("claimed_sha256", r.text)
        self.assertEqual(r.headers["cache-control"], "no-store")
        for path in (NOTE,):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(
                    path, headers=self.headers(),
                    json={"approval": "PASS", "evidence_ref": "DEMO-FAKE"}
                ).status_code, 405)

    def test_api_rejects_unassigned_unknown_and_forged_identity(self):
        self.assertEqual(self.client.get(NOTE).status_code, 401)
        self.assertEqual(self.client.get(
            NOTE, headers={"Authorization": "Bearer fake"}
        ).status_code, 401)
        self.assertEqual(self.client.get(
            NOTE, headers=self.headers(("household",))
        ).status_code, 404)
        self.assertEqual(self.client.get(
            ROOT + "/UNKNOWN/technical-handoff",
            headers=self.headers(),
        ).status_code, 404)
        self.assertEqual(self.client.get(
            ROOT + "/FINANCE/technical-handoff",
            headers=self.headers(),
        ).status_code, 404)

    def test_admin_html_shows_only_reference_stage_no_pii_or_decision(self):
        self.record()
        self.respond()
        sid = self.login()
        r = self.client.get(BODY)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("HUMAN_NOTE_RECORDED", r.text)
        self.assertIn("D1-B-01", r.text)
        self.assertIn("OPEN", r.text)
        self.assertNotIn("DEMO-HUMAN-NOTE-01", r.text)
        self.assertNotIn("DEMO-RECEIPT-01", r.text)
        self.assertIn("frame-ancestors 'none'", r.headers["content-security-policy"])
        self.sessions.revoke_session(sid)
        self.assertEqual(self.client.get(BODY).status_code, 401)

    def test_source_state_corruption_hides_all_handoff_metadata(self):
        from unittest.mock import patch
        from ronas_api.business_gate_evidence import PINNED_BUSINESS_SOURCE_BLOBS
        with patch.dict(PINNED_BUSINESS_SOURCE_BLOBS, {
            next(iter(PINNED_BUSINESS_SOURCE_BLOBS)): "f" * 40
        }):
            self.assertEqual(self.client.get(NOTE, headers=self.headers()).status_code,
                             503)
        self.assertTrue(self.ledger.verify_integrity())

    def test_default_app_does_not_mount_handoff_and_requires_browser(self):
        default = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(default.get(NOTE, headers=self.headers()).status_code, 404)
        with self.assertRaises(ValueError):
            create_app(self.config, gate_handoff_ledger=self.ledger)

    def test_no_cross_context_mutation_of_business_gate_registry(self):
        self.record()
        self.respond()
        snapshot = self.client.get(
            ROOT + "/DOMESTIC", headers=self.headers()
        ).json()
        self.assertEqual(snapshot["gate_status_at_source"], "OPEN")
        self.assertTrue(all(e["verified_here"] is False
                            for e in snapshot["evidence_items"]))
        self.assertFalse(snapshot["actions_enabled"])
        self.assertEqual(snapshot["snapshot_state"],
                         "PINNED_DRAFT_SNAPSHOT_NOT_LIVE")


if __name__ == "__main__":
    unittest.main()
