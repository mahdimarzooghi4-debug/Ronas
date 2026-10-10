"""Restart-safe synthetic human-evidence review, never business approval."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
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
from ronas_api.grant_ledger_sqlite import (
    SqliteSyntheticGrantLedger, LedgerIntegrityError,
)
from ronas_api.human_review_sqlite import (
    SqliteSyntheticHumanReviewLedger, REQUESTED, RECORDED,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.scoped_audit import GrantConflict, GrantNotAuthorized
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant

ISS = "https://id.example.test/realms/ronas"
API, WEB = "ronas-api", "ronas-web"
DOM_PATH = "/api/v1/admin/domestic/household-intake/drafts/DEMO-D-001"


def records():
    return (
        ScopedDraft(
            "DEMO-D-001", "DOMESTIC", "synthetic-household-001", 3, (
                ScopedGrant("synthetic-domestic-001", "domestic_ops"),
                ScopedGrant("synthetic-domestic-002", "domestic_ops"),
            )
        ),
        ScopedDraft(
            "DEMO-E-001", "EXPORT", "synthetic-export-owner", 2, (
                ScopedGrant("synthetic-export-001", "export_ops"),
                ScopedGrant("synthetic-export-002", "export_ops"),
            ), source_ref="DEMO-SOURCE-01"
        ),
    )


def history():
    return (
        ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-001", 1, ()),
        ScopedDraft("DEMO-E-001", "EXPORT", "synthetic-export-owner", 1, (),
                    source_ref="DEMO-SOURCE-01"),
    )


def revoke_authority(actor, engine, ref):
    return actor == "synthetic-authority"


def human_authority(actor, engine, ref):
    return (actor == "synthetic-domestic-002"
            and engine == "DOMESTIC" and ref == "DEMO-D-001") or (
            actor == "synthetic-export-002"
            and engine == "EXPORT" and ref == "DEMO-E-001")


class DurableHumanReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "review-ledger.db"
        self.ledger = self.open()
        self.requester = Principal("synthetic-domestic-001", frozenset({"domestic_ops"}))
        self.reviewer = Principal("synthetic-domestic-002", frozenset({"domestic_ops"}))
        self.exporter = Principal("synthetic-export-001", frozenset({"export_ops"}))
        self.export_reviewer = Principal("synthetic-export-002", frozenset({"export_ops"}))

    def open(self, *, review_authorizer=human_authority):
        return SqliteSyntheticHumanReviewLedger(
            self.path, records(), previous_versions=history(),
            trusted_revoke_authorizer=revoke_authority,
            trusted_human_review_authorizer=review_authorizer,
        )

    def request(self, ledger=None, **update):
        command = dict(
            engine="DOMESTIC", ref="DEMO-D-001", actor=self.requester,
            expected_case_version=3, expected_review_revision=0,
            action_id="DEMO-ACTION-REQUEST-001",
            request_ref="DEMO-REQUEST-001",
            evidence_ref="DEMO-EVIDENCE-001",
        )
        command.update(update)
        return (ledger or self.ledger).request_evidence_review(**command)

    def respond(self, ledger=None, **update):
        command = dict(
            engine="DOMESTIC", ref="DEMO-D-001", actor=self.reviewer,
            expected_case_version=3, expected_review_revision=1,
            action_id="DEMO-ACTION-RESPONSE-001",
            request_ref="DEMO-REQUEST-001",
            evidence_ref="DEMO-EVIDENCE-RESPONSE-001",
            decision_ref="DEMO-HUMAN-NOTE-001",
        )
        command.update(update)
        return (ledger or self.ledger).record_human_response(**command)

    def test_state_is_technical_only_and_case_never_approved(self):
        self.assertEqual(
            self.ledger.review_state("DOMESTIC", "DEMO-D-001"),
            dict(engine="DOMESTIC", ref="DEMO-D-001", case_version=3,
                 case_status="DRAFT_ONLY", review_revision=0,
                 technical_review_state="UNREQUESTED"),
        )
        requested = self.request()
        self.assertEqual(requested.stage, REQUESTED)
        self.assertEqual(requested.revision, 1)
        state = self.ledger.review_state("DOMESTIC", "DEMO-D-001")
        self.assertEqual(state["technical_review_state"], "EVIDENCE_REVIEW_REQUESTED")
        self.assertEqual(state["case_status"], "DRAFT_ONLY")
        response = self.respond()
        self.assertEqual(response.stage, RECORDED)
        self.assertEqual(response.revision, 2)
        state = self.ledger.review_state("DOMESTIC", "DEMO-D-001")
        self.assertEqual(state["technical_review_state"], "HUMAN_RESPONSE_RECORDED")
        self.assertEqual(state["case_status"], "DRAFT_ONLY")
        view = self.ledger.read("DOMESTIC", "DEMO-D-001", self.requester, as_owner=False)
        self.assertEqual(view["status"], "DRAFT_ONLY")
        for field in ("purpose_consent_verified", "expert_approved", "plan_accepted"):
            self.assertIs(view[field], False)
        self.assertEqual(self.ledger.case_versions("DOMESTIC", "DEMO-D-001"), (1, 3))

    def test_reopen_preserves_exact_human_request_and_response_lineage(self):
        self.request()
        self.respond()
        reopened = self.open()
        steps = reopened.review_history("DOMESTIC", "DEMO-D-001")
        self.assertEqual([s.stage for s in steps], [REQUESTED, RECORDED])
        self.assertEqual([s.revision for s in steps], [1, 2])
        self.assertEqual(steps[1].request_ref, steps[0].request_ref)
        self.assertNotEqual(steps[1].actor_digest, steps[0].actor_digest)
        self.assertEqual(steps[1].decision_ref, "DEMO-HUMAN-NOTE-001")
        self.assertEqual(steps[1].evidence_ref, "DEMO-EVIDENCE-RESPONSE-001")
        self.assertEqual(reopened.review_state("DOMESTIC", "DEMO-D-001")[
            "technical_review_state"], "HUMAN_RESPONSE_RECORDED")
        self.assertTrue(reopened.verify_integrity())

    def test_response_without_requested_review_is_rejected(self):
        with self.assertRaises(GrantConflict):
            self.respond()
        self.assertEqual(self.ledger.review_history("DOMESTIC", "DEMO-D-001"), ())
        self.assertEqual(self.ledger.audit_snapshot(), ())

    def test_human_reviewer_requires_independent_authorizer_and_assignment(self):
        self.request()
        with self.assertRaises(GrantNotAuthorized):
            self.respond(actor=self.requester)
        with self.assertRaises(GrantNotAuthorized):
            self.respond(actor=Principal("synthetic-governance-001",
                                        frozenset({"governance", "domestic_ops"})))
        with self.assertRaises(GrantNotAuthorized):
            self.respond(self.open(review_authorizer=lambda *args: False))
        self.assertEqual(self.ledger.review_state("DOMESTIC", "DEMO-D-001")[
            "review_revision"], 1)
        self.respond()
        self.assertEqual(self.ledger.review_state("DOMESTIC", "DEMO-D-001")[
            "review_revision"], 2)

    def test_same_requester_cannot_be_human_responder_even_if_authorized(self):
        special = self.open(review_authorizer=lambda actor, engine, ref: True)
        self.request(special)
        with self.assertRaises(GrantConflict):
            self.respond(special, actor=self.requester)
        self.assertEqual(special.review_state("DOMESTIC", "DEMO-D-001")[
            "review_revision"], 1)

    def test_stale_case_or_review_revision_fails_closed(self):
        with self.assertRaises(GrantNotAuthorized):
            self.request(expected_case_version=2)
        self.request()
        with self.assertRaises(GrantConflict):
            self.request(action_id="DEMO-ACTION-NEW-001")
        with self.assertRaises(GrantConflict):
            self.respond(request_ref="DEMO-REQUEST-WRONG")
        with self.assertRaises(GrantNotAuthorized):
            self.respond(expected_case_version=2)
        self.assertEqual(self.ledger.review_state("DOMESTIC", "DEMO-D-001")[
            "review_revision"], 1)

    def test_exact_idempotent_actions_survive_restarts_changed_payload_fails(self):
        request = self.request()
        self.assertEqual(self.request(self.open()), request)
        with self.assertRaises(GrantConflict):
            self.request(self.open(), evidence_ref="DEMO-EVIDENCE-CHANGED")
        response = self.respond()
        self.assertEqual(self.respond(self.open()), response)
        with self.assertRaises(GrantConflict):
            self.respond(self.open(), decision_ref="DEMO-HUMAN-NOTE-CHANGED")
        self.assertEqual(len(self.open().review_history("DOMESTIC", "DEMO-D-001")), 2)
        events = self.open().audit_snapshot()
        self.assertEqual(len(events), 2)
        self.assertEqual([e.kind for e in events], [REQUESTED, RECORDED])

    def test_current_active_grant_required_even_with_existing_signed_role(self):
        self.ledger.revoke_grant(
            engine="DOMESTIC", ref="DEMO-D-001",
            subject=self.requester.subject, role="domestic_ops",
            actor="synthetic-authority", expected_grant_revision=0,
            action_id="DEMO-REVOKE-REQUESTER", reason_ref="DEMO-REASON-001",
        )
        with self.assertRaises(GrantNotAuthorized):
            self.request()
        self.assertEqual(self.ledger.review_history("DOMESTIC", "DEMO-D-001"), ())

    def test_reviewer_revoked_after_request_cannot_record_response(self):
        self.request()
        self.ledger.revoke_grant(
            engine="DOMESTIC", ref="DEMO-D-001",
            subject=self.reviewer.subject, role="domestic_ops",
            actor="synthetic-authority", expected_grant_revision=0,
            action_id="DEMO-REVOKE-REVIEWER", reason_ref="DEMO-REASON-001",
        )
        with self.assertRaises(GrantNotAuthorized):
            self.respond()
        self.assertEqual(self.open().review_state("DOMESTIC", "DEMO-D-001")[
            "review_revision"], 1)

    def test_export_is_independent_and_never_changes_domestic(self):
        self.ledger.request_evidence_review(
            engine="EXPORT", ref="DEMO-E-001", actor=self.exporter,
            expected_case_version=2, expected_review_revision=0,
            action_id="DEMO-E-REQ-001", request_ref="DEMO-E-REVIEW-001",
            evidence_ref="DEMO-E-SOURCE-001",
        )
        self.ledger.record_human_response(
            engine="EXPORT", ref="DEMO-E-001", actor=self.export_reviewer,
            expected_case_version=2, expected_review_revision=1,
            action_id="DEMO-E-RESP-001", request_ref="DEMO-E-REVIEW-001",
            evidence_ref="DEMO-E-LIMITATION-001",
            decision_ref="DEMO-E-HUMAN-NOTE-001",
        )
        self.assertEqual(self.ledger.review_state("EXPORT", "DEMO-E-001")[
            "technical_review_state"], "HUMAN_RESPONSE_RECORDED")
        self.assertEqual(self.ledger.review_state("DOMESTIC", "DEMO-D-001")[
            "technical_review_state"], "UNREQUESTED")
        export_view = self.ledger.read("EXPORT", "DEMO-E-001", self.exporter, as_owner=False)
        for field in ("source_rights_verified", "review_approved",
                      "buyer_verified", "contracted"):
            self.assertIs(export_view[field], False)

    def test_unauthorized_cross_engine_or_wrong_role(self):
        with self.assertRaises(GrantNotAuthorized):
            self.request(engine="EXPORT", ref="DEMO-E-001",
                         expected_case_version=2, actor=self.requester)
        with self.assertRaises(GrantNotAuthorized):
            self.request(actor=Principal("synthetic-unknown-user",
                                         frozenset({"domestic_ops"})))
        with self.assertRaises(ValueError):
            self.request(action_id="REALLY-LIVE-001")
        self.assertEqual(self.ledger.audit_snapshot(), ())

    def test_audit_contains_no_real_identity_or_note_content(self):
        self.request()
        self.respond()
        events = self.ledger.audit_snapshot()
        self.assertEqual(events[1].previous_digest, events[0].digest)
        contents = json.dumps([e.__dict__ if hasattr(e, "__dict__") else str(e)
                               for e in events])
        self.assertNotIn("synthetic-domestic-001", contents)
        self.assertNotIn("synthetic-domestic-002", contents)
        self.assertNotIn("Bearer ", contents)
        self.assertTrue(all(len(x.actor_digest) == 64 for x in events))

    def test_db_triggers_refuse_review_history_mutation(self):
        self.request()
        with sqlite3.connect(self.path) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE technical_review_step SET revision=99")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM technical_review_step")
        self.assertTrue(self.open().verify_integrity())

    def test_corrupted_review_request_ref_fails_closed(self):
        self.request()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER review_no_update")
            db.execute("UPDATE technical_review_step SET request_ref='DEMO-ALTERED'")
        with self.assertRaises(LedgerIntegrityError):
            self.open()
        self.assertFalse(self.ledger.verify_integrity())
        with self.assertRaises(LedgerIntegrityError):
            self.ledger.review_state("DOMESTIC", "DEMO-D-001")

    def test_review_sensitive_columns_tampering_fails_closed_on_reopen(self):
        # Independent databases ensure each mutation is detected on its own.
        # This is corruption testing, not a claim of protection against a
        # privileged attacker rewriting the entire local SQLite audit chain.
        mutations = (
            ("action_id", "DEMO-ACTION-ALTERED"),
            ("stage", "TECH_HUMAN_RESPONSE_RECORDED"),
            ("actor_digest", "a" * 64),
            ("request_ref", "DEMO-REQUEST-ALTERED"),
            ("evidence_ref", "DEMO-EVIDENCE-ALTERED"),
            ("command_digest", "b" * 64),
            ("audit_sequence", 999),
        )
        for column, replacement in mutations:
            with self.subTest(column=column):
                path = Path(self.temp.name) / f"tamper-{column}.db"
                ledger = SqliteSyntheticHumanReviewLedger(
                    path, records(), previous_versions=history(),
                    trusted_revoke_authorizer=revoke_authority,
                    trusted_human_review_authorizer=human_authority,
                )
                self.request(ledger)
                with sqlite3.connect(path) as db:
                    db.execute("DROP TRIGGER review_no_update")
                    db.execute(
                        f"UPDATE technical_review_step SET {column}=?",
                        (replacement,),
                    )
                with self.assertRaises(LedgerIntegrityError):
                    SqliteSyntheticHumanReviewLedger(
                        path, records(), previous_versions=history(),
                        trusted_revoke_authorizer=revoke_authority,
                        trusted_human_review_authorizer=human_authority,
                    )
                self.assertFalse(ledger.verify_integrity())

    def test_response_note_reference_tampering_fails_closed(self):
        self.request()
        self.respond()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER review_no_update")
            db.execute(
                "UPDATE technical_review_step SET decision_ref=? "
                "WHERE stage=?",
                ("DEMO-HUMAN-NOTE-TAMPERED", RECORDED),
            )
        with self.assertRaises(LedgerIntegrityError):
            self.open()
        self.assertFalse(self.ledger.verify_integrity())

    def test_missing_review_row_with_existing_audit_fails_closed(self):
        self.request()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER review_no_delete")
            db.execute("DELETE FROM technical_review_step")
        with self.assertRaises(LedgerIntegrityError):
            self.open()

    def test_failed_review_insert_rolls_back_audit_and_state(self):
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TRIGGER reject_review BEFORE INSERT ON technical_review_step
                BEGIN SELECT RAISE(ABORT, 'test review write error'); END;""")
        with self.assertRaises(sqlite3.DatabaseError):
            self.request()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER reject_review")
        self.assertEqual(self.open().review_history("DOMESTIC", "DEMO-D-001"), ())
        self.assertEqual(self.open().audit_snapshot(), ())
        self.request()
        self.assertTrue(self.open().verify_integrity())

    def test_concurrent_duplicate_requests_exactly_once(self):
        barrier = Barrier(7)

        def task(_):
            instance = self.open()
            barrier.wait(timeout=12)
            return self.request(instance)

        with ThreadPoolExecutor(max_workers=7) as executor:
            results = list(executor.map(task, range(7)))
        self.assertTrue(all(e == results[0] for e in results))
        self.assertEqual(len(self.open().review_history("DOMESTIC", "DEMO-D-001")), 1)

    def test_conflicting_simultaneous_requests_one_accepted(self):
        barrier = Barrier(2)

        def task(n):
            instance = self.open()
            barrier.wait(timeout=12)
            try:
                self.request(instance, action_id=f"DEMO-D-REQUEST-ACTION-{n}")
                return "ok"
            except GrantConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(task, (1, 2)))
        self.assertCountEqual(results, ("ok", "conflict"))
        self.assertEqual(self.open().review_state("DOMESTIC", "DEMO-D-001")[
            "review_revision"], 1)

    def test_generic_base_ledger_does_not_silently_ignore_review_audit(self):
        self.request()
        with self.assertRaises(LedgerIntegrityError):
            SqliteSyntheticGrantLedger(
                self.path, records(), previous_versions=history(),
                trusted_revoke_authorizer=revoke_authority,
            )

    def test_no_review_http_endpoints_and_default_keycloak_app_still_off(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwk.update({"kid": "kid-1", "alg": "RS256", "use": "sig"})
        cfg = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())
        now = int(time.time())
        jwt_string = jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "sub": self.requester.subject,
            "typ": "Bearer", "iat": now - 5, "nbf": now - 5,
            "exp": now + 500,
            "resource_access": {API: {"roles": ["domestic_ops", "governance"]}},
        }, key, algorithm="RS256", headers={"kid": "kid-1"})
        h = {"Authorization": "Bearer " + jwt_string}
        client = TestClient(create_app(cfg, scoped_registry=self.ledger))
        self.assertEqual(client.get("/api/v1/admin/domestic/household-intake/drafts/DEMO-D-001", headers=h).status_code, 200)
        self.assertEqual(client.post("/api/v1/reviews", headers=h, json={}).status_code, 404)
        self.assertEqual(client.post("/api/v1/admin/reviews/approve", headers=h, json={}).status_code, 404)
        self.assertEqual(client.get("/api/v1/admin/human-review-history", headers=h).status_code, 404)
        default = TestClient(create_app(cfg))
        self.assertEqual(default.get(
            "/api/v1/admin/domestic/household-intake/drafts/DEMO-D-001", headers=h
        ).status_code, 404)


if __name__ == "__main__":
    unittest.main()
