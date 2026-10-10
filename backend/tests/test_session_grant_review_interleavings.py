"""Offline cross-boundary consistency: Keycloak session, case grant and review.

These are synthetic LOCAL/TEST fixtures. Revocation within the review ledger
is transactional; the separate browser-session DB is NOT a distributed
transaction. A read already in flight may finish before a revoke commits.
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
from ronas_api.grant_ledger_sqlite import LedgerIntegrityError, _hash
from ronas_api.human_review_sqlite import (
    SqliteSyntheticHumanReviewLedger, REQUESTED, RECORDED,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.scoped_audit import GrantNotAuthorized
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant
from ronas_api.session_sqlite import SqliteBrowserSessionStore


ISS, API, WEB = "https://id.example.test/realms/ronas", "ronas-api", "ronas-web"
ORIGIN = "https://ronas.example.test"
DOM = "/api/v1/admin/domestic/household-intake/drafts/DEMO-D-001/technical-review"
EXP = "/api/v1/admin/export/research/drafts/DEMO-E-001/technical-review"
COOKIE = "__Host-ronas_session"


def records():
    return (
        ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-001", 3, (
            ScopedGrant("synthetic-domestic-001", "domestic_ops"),
            ScopedGrant("synthetic-domestic-002", "domestic_ops"),
        )),
        ScopedDraft("DEMO-E-001", "EXPORT", "synthetic-export-owner", 2, (
            ScopedGrant("synthetic-export-001", "export_ops"),
        ), source_ref="DEMO-SOURCE-01"),
    )


def revoke_authorizer(actor, engine, ref):
    return actor == "synthetic-controller" and engine == "DOMESTIC" and ref == "DEMO-D-001"


def review_authorizer(actor, engine, ref):
    return actor == "synthetic-domestic-002" and engine == "DOMESTIC" and ref == "DEMO-D-001"


class SessionGrantReviewInterleavingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        public.update({"kid": "interleaving-key", "use": "sig", "alg": "RS256"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [public]}).encode())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.ledger_path = root / "reviews.db"
        self.session_path = root / "sessions.db"
        self.session_key = secrets.token_bytes(32)
        self.store1 = SqliteBrowserSessionStore(self.session_path, self.session_key)
        self.store2 = SqliteBrowserSessionStore(self.session_path, self.session_key)
        self.ledger = self.reopen_ledger()
        self.requester = Principal("synthetic-domestic-001", frozenset({"domestic_ops"}))
        self.reviewer = Principal("synthetic-domestic-002", frozenset({"domestic_ops"}))
        opts = BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback")
        async def exchange(_code, _verifier):
            raise AssertionError("No IdP/authorization code exchange in these tests")
        self.flow1 = BrowserOIDC(opts, self.store1, exchange)
        self.flow2 = BrowserOIDC(opts, self.store2, exchange)
        self.client1 = TestClient(create_app(
            self.config, self.flow1, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
        ), base_url=ORIGIN)
        self.client2 = TestClient(create_app(
            self.config, self.flow2, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
        ), base_url=ORIGIN)
        self.sid = secrets.token_urlsafe(40)
        now = int(time.time())
        self.signed_token = jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "typ": "Bearer",
            "sub": self.requester.subject, "iat": now - 5,
            "nbf": now - 5, "exp": now + 500,
            "resource_access": {API: {"roles": ["domestic_ops"]}},
        }, self.key, algorithm="RS256", headers={"kid": "interleaving-key"})
        self.store1.save_session(self.sid, BrowserSession(
            self.requester.subject, self.requester.roles,
            self.signed_token, secrets.token_urlsafe(32), now + 300,
        ))
        for client in (self.client1, self.client2):
            client.cookies.set(COOKIE, self.sid)

    def reopen_ledger(self):
        return SqliteSyntheticHumanReviewLedger(
            self.ledger_path, records(),
            trusted_revoke_authorizer=revoke_authorizer,
            trusted_human_review_authorizer=review_authorizer,
        )

    def request(self, ledger=None, *, action="DEMO-REQUEST-ACTION"):
        return (ledger or self.ledger).request_evidence_review(
            engine="DOMESTIC", ref="DEMO-D-001", actor=self.requester,
            expected_case_version=3, expected_review_revision=0,
            action_id=action, request_ref="DEMO-REQUEST",
            evidence_ref="DEMO-EVIDENCE",
        )

    def respond(self, ledger=None):
        return (ledger or self.ledger).record_human_response(
            engine="DOMESTIC", ref="DEMO-D-001", actor=self.reviewer,
            expected_case_version=3, expected_review_revision=1,
            action_id="DEMO-RESPONSE-ACTION", request_ref="DEMO-REQUEST",
            evidence_ref="DEMO-RESPONSE-EVIDENCE",
            decision_ref="DEMO-HUMAN-REFERENCE",
        )

    def revoke(self, subject, *, action):
        return self.reopen_ledger().revoke_grant(
            engine="DOMESTIC", ref="DEMO-D-001", subject=subject,
            role="domestic_ops", actor="synthetic-controller",
            expected_grant_revision=0, action_id=action,
            reason_ref="DEMO-REVOCATION-REASON",
        )

    def test_independent_session_logout_blocks_reads_without_new_review_audit(self):
        self.request()
        self.assertEqual(self.client1.get(DOM).status_code, 200)
        audit_before = len(self.ledger.audit_snapshot())
        details = self.client2.get("/api/auth/session").json()
        self.assertEqual(self.client2.post("/api/auth/logout", headers={
            "Origin": ORIGIN, "X-CSRF-Token": details["csrf"],
        }).status_code, 200)
        self.assertEqual(self.client1.get(DOM).status_code, 401)
        self.assertEqual(self.client2.get(DOM).status_code, 401)
        self.assertEqual(len(self.ledger.audit_snapshot()), audit_before)
        self.assertEqual(self.reopen_ledger().review_state("DOMESTIC", "DEMO-D-001")[
            "case_status"], "DRAFT_ONLY")

    def test_active_session_after_case_revoke_cannot_view_review_or_other_engine(self):
        self.request()
        self.assertEqual(self.client1.get(DOM).status_code, 200)
        self.revoke(self.requester.subject, action="DEMO-REVOKE-REQUESTER")
        self.assertEqual(self.client1.get("/api/auth/session").status_code, 200)
        self.assertEqual(self.client1.get(DOM).status_code, 404)
        self.assertEqual(self.client2.get(DOM).status_code, 404)
        self.assertEqual(self.client2.get(EXP).status_code, 404)
        self.assertEqual(self.reopen_ledger().audit_snapshot()[-1].kind, "READ_DENIED")
        self.assertTrue(self.reopen_ledger().verify_integrity())

    def test_request_racing_with_grant_revoke_respects_audit_order(self):
        barrier = Barrier(2)

        def attempt_request():
            conn = self.reopen_ledger()
            barrier.wait(timeout=12)
            try:
                return self.request(conn).stage
            except GrantNotAuthorized:
                return "DENIED"

        def attempt_revoke():
            barrier.wait(timeout=12)
            return self.revoke(self.requester.subject, action="DEMO-REVOKE-RACING-REQUEST")

        with ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(attempt_request)
            b = executor.submit(attempt_revoke)
            outcome, revoked = a.result(), b.result()
        events = self.reopen_ledger().audit_snapshot()
        self.assertEqual(revoked.kind, "GRANT_REVOKED")
        accepted = [e for e in events if e.kind == REQUESTED]
        if outcome == REQUESTED:
            self.assertEqual(len(accepted), 1)
            self.assertLess(accepted[0].sequence, revoked.sequence)
        else:
            self.assertEqual(outcome, "DENIED")
            self.assertEqual(accepted, [])
        with self.assertRaises(GrantNotAuthorized):
            self.request(self.reopen_ledger())
        self.assertEqual(self.reopen_ledger().review_state(
            "DOMESTIC", "DEMO-D-001")["review_revision"], len(accepted))
        self.assertTrue(self.reopen_ledger().verify_integrity())

    def test_reviewer_response_racing_with_revoke_is_serialized(self):
        self.request()
        barrier = Barrier(2)

        def attempt_response():
            connection = self.reopen_ledger()
            barrier.wait(timeout=12)
            try:
                return self.respond(connection).stage
            except GrantNotAuthorized:
                return "DENIED"

        def attempt_revoke():
            barrier.wait(timeout=12)
            return self.revoke(self.reviewer.subject, action="DEMO-REVOKE-REVIEWER")

        with ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(attempt_response)
            b = executor.submit(attempt_revoke)
            outcome, revoked = a.result(), b.result()
        events = self.reopen_ledger().audit_snapshot()
        responses = [e for e in events if e.kind == RECORDED]
        if outcome == RECORDED:
            self.assertEqual(len(responses), 1)
            self.assertLess(responses[0].sequence, revoked.sequence)
        else:
            self.assertEqual(outcome, "DENIED")
            self.assertEqual(responses, [])
        state = self.reopen_ledger().review_state("DOMESTIC", "DEMO-D-001")
        self.assertEqual(state["review_revision"], 1 + len(responses))
        self.assertEqual(state["case_status"], "DRAFT_ONLY")
        self.assertTrue(self.reopen_ledger().verify_integrity())

    def test_same_action_replay_after_grant_revocation_cannot_change_history(self):
        original = self.request()
        self.revoke(self.requester.subject, action="DEMO-REVOKE-BEFORE-REPLAY")
        before = self.reopen_ledger().audit_snapshot()
        with self.assertRaises(GrantNotAuthorized):
            self.request(self.reopen_ledger())
        self.assertEqual(self.reopen_ledger().audit_snapshot(), before)
        self.assertEqual(self.reopen_ledger().review_history(
            "DOMESTIC", "DEMO-D-001")[0].audit_sequence, original.audit_sequence)
        self.assertEqual(self.reopen_ledger().review_state(
            "DOMESTIC", "DEMO-D-001")["case_status"], "DRAFT_ONLY")

    def test_corrupt_review_evidence_fails_closed_for_session_and_signed_bearer(self):
        self.request()
        with sqlite3.connect(self.ledger_path) as db:
            db.execute("DROP TRIGGER review_no_update")
            db.execute(
                "UPDATE technical_review_step SET evidence_ref='DEMO-CORRUPTED'"
            )
        for headers in ({}, {"Authorization": "Bearer " + self.signed_token}):
            with self.subTest(headers=bool(headers)):
                response = self.client1.get(DOM, headers=headers)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {
                    "detail": "TECHNICAL_REVIEW_UNAVAILABLE",
                })
                self.assertNotIn("DEMO-CORRUPTED", response.text)

    def test_revoke_and_logout_both_persist_after_restart_without_regrant(self):
        self.request()
        self.revoke(self.requester.subject, action="DEMO-REVOKE-PERSISTENT")
        details = self.client1.get("/api/auth/session").json()
        self.assertEqual(self.client1.post("/api/auth/logout", headers={
            "Origin": ORIGIN, "X-CSRF-Token": details["csrf"],
        }).status_code, 200)
        self.assertIsNone(self.store2.get_session(self.sid))
        reopened = self.reopen_ledger()
        self.assertTrue(reopened.verify_integrity())
        self.assertEqual(reopened.grant_revision("DOMESTIC", "DEMO-D-001"), 1)
        fresh_sid = secrets.token_urlsafe(40)
        now = int(time.time())
        self.store1.save_session(fresh_sid, BrowserSession(
            self.requester.subject, self.requester.roles, self.signed_token,
            secrets.token_urlsafe(32), now + 250,
        ))
        self.client2.cookies.set(COOKIE, fresh_sid)
        self.assertEqual(self.client2.get(DOM).status_code, 404)
        self.assertEqual(self.client2.get(EXP).status_code, 404)
        self.assertEqual(reopened.review_state("DOMESTIC", "DEMO-D-001")[
            "case_status"], "DRAFT_ONLY")
        self.assertTrue(reopened.verify_integrity())


if __name__ == "__main__":
    unittest.main()
