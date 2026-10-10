"""LOCAL/TEST operator review worklist: authorized DEMO cases only."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
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
from ronas_api.human_review_sqlite import SqliteSyntheticHumanReviewLedger
from ronas_api.keycloak import KeycloakConfig
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant

ISS = "https://id.example.test/realms/ronas"
API, WEB = "ronas-api", "ronas-web"
DOM = "/api/v1/admin/domestic/household-intake/technical-review-worklist"
EXP = "/api/v1/admin/export/research/technical-review-worklist"


def cases():
    return (
        ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-001", 2, (
            ScopedGrant("synthetic-domestic-001", "domestic_ops"),
            ScopedGrant("synthetic-domestic-reviewer", "domestic_ops"),
        )),
        ScopedDraft("DEMO-D-002", "DOMESTIC", "synthetic-household-002", 1, (
            ScopedGrant("synthetic-domestic-001", "domestic_ops"),
        )),
        ScopedDraft("DEMO-D-003", "DOMESTIC", "synthetic-household-003", 1, (
            ScopedGrant("synthetic-domestic-other", "domestic_ops"),
        )),
        ScopedDraft("DEMO-D-004", "DOMESTIC", "synthetic-household-004", 4, (
            ScopedGrant("synthetic-domestic-001", "domestic_ops"),
        )),
        ScopedDraft("DEMO-E-001", "EXPORT", "synthetic-export-owner", 3, (
            ScopedGrant("synthetic-export-001", "export_ops"),
        ), source_ref="DEMO-SOURCE-001"),
    )


def revoke_authority(actor, engine, ref):
    return actor == "synthetic-controller"


def human_authority(actor, engine, ref):
    return (actor == "synthetic-domestic-reviewer"
            and engine == "DOMESTIC" and ref == "DEMO-D-001")


class TechnicalReviewWorklistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "worklist-key", "use": "sig", "alg": "RS256"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "worklist.db"
        self.ledger = self.reopen()
        self.client = self.new_client(self.ledger)
        self.operator = Principal("synthetic-domestic-001", frozenset({"domestic_ops"}))

    def reopen(self):
        return SqliteSyntheticHumanReviewLedger(
            self.path, cases(),
            trusted_revoke_authorizer=revoke_authority,
            trusted_human_review_authorizer=human_authority,
        )

    def new_client(self, ledger):
        return TestClient(create_app(
            self.config, scoped_registry=ledger,
            technical_review_ledger=ledger,
        ))

    def signed(self, subject="synthetic-domestic-001", roles=("domestic_ops",)):
        now = int(time.time())
        token = jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "sub": subject,
            "typ": "Bearer", "iat": now - 5, "nbf": now - 5, "exp": now + 600,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "worklist-key"})
        return {"Authorization": "Bearer " + token}

    def get(self, path=DOM, *, client=None, params=None, subject="synthetic-domestic-001",
            roles=("domestic_ops",)):
        return (client or self.client).get(
            path, params=params, headers=self.signed(subject, roles)
        )

    def audit_worklist(self):
        return [
            event for event in self.ledger.audit_snapshot()
            if event.access_mode == "TECHNICAL_REVIEW_WORKLIST"
        ]

    def request(self):
        return self.ledger.request_evidence_review(
            engine="DOMESTIC", ref="DEMO-D-001", actor=self.operator,
            expected_case_version=2, expected_review_revision=0,
            action_id="DEMO-REQUEST-WORKLIST", request_ref="DEMO-REQUEST-001",
            evidence_ref="DEMO-EVIDENCE-001",
        )

    def test_keyset_pagination_returns_only_assigned_cases_without_hidden_count(self):
        one = self.get(params={"limit": 2})
        self.assertEqual(one.status_code, 200, one.text)
        self.assertEqual(one.json()["engine"], "DOMESTIC")
        self.assertEqual([x["ref"] for x in one.json()["items"]],
                         ["DEMO-D-001", "DEMO-D-002"])
        self.assertEqual(one.json()["next_cursor"], "DEMO-D-002")
        for item in one.json()["items"]:
            self.assertEqual(item["case_status"], "DRAFT_ONLY")
            self.assertEqual(item["technical_review_state"], "UNREQUESTED")
            self.assertNotIn("owner_subject", item)
            self.assertNotIn("evidence_ref", item)
            self.assertNotIn("decision_ref", item)
        self.assertNotIn("total", one.json())
        self.assertNotIn("DEMO-D-003", one.text)
        self.assertEqual(one.headers["cache-control"], "no-store")
        two = self.get(params={"limit": 2, "after_ref": one.json()["next_cursor"]})
        self.assertEqual(two.status_code, 200)
        self.assertEqual([x["ref"] for x in two.json()["items"]], ["DEMO-D-004"])
        self.assertIsNone(two.json()["next_cursor"])
        self.assertEqual([e.ref for e in self.audit_worklist()],
                         ["DEMO-D-001", "DEMO-D-002", "DEMO-D-004"])
        self.assertTrue(self.reopen().verify_integrity())

    def test_cursor_filters_authorized_refs_only_and_end_page_is_empty(self):
        result = self.get(params={"limit": 1, "after_ref": "DEMO-D-003"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual([x["ref"] for x in result.json()["items"]], ["DEMO-D-004"])
        self.assertIsNone(result.json()["next_cursor"])
        done = self.get(params={"after_ref": "DEMO-D-004"})
        self.assertEqual(done.json()["items"], [])
        self.assertIsNone(done.json()["next_cursor"])
        self.assertEqual([x.ref for x in self.audit_worklist()], ["DEMO-D-004"])

    def test_revoked_assignment_disappears_with_previous_signed_token(self):
        headers = self.signed()
        self.assertIn("DEMO-D-002", self.client.get(DOM, headers=headers).text)
        self.ledger.revoke_grant(
            engine="DOMESTIC", ref="DEMO-D-002",
            subject="synthetic-domestic-001", role="domestic_ops",
            actor="synthetic-controller", expected_grant_revision=0,
            action_id="DEMO-REVOKE-D-002", reason_ref="DEMO-REASON-002",
        )
        after = self.client.get(DOM, headers=headers)
        self.assertEqual(after.status_code, 200)
        self.assertEqual([x["ref"] for x in after.json()["items"]],
                         ["DEMO-D-001", "DEMO-D-004"])
        self.assertNotIn("DEMO-D-002", after.text)
        self.assertTrue(self.reopen().verify_integrity())

    def test_wrong_role_unassigned_or_cross_engine_roles_never_list_other_cases(self):
        for path, subject, roles in (
            (DOM, "synthetic-domestic-001", ("finance",)),
            (DOM, "synthetic-unassigned", ("domestic_ops",)),
            (EXP, "synthetic-domestic-001", ("domestic_ops", "export_ops")),
            (DOM, "synthetic-export-001", ("export_ops", "domestic_ops")),
        ):
            with self.subTest(path=path, subject=subject, roles=roles):
                r = self.get(path, subject=subject, roles=roles)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()["items"], [])
                self.assertIsNone(r.json()["next_cursor"])
        self.assertEqual(self.audit_worklist(), [])
        permitted = self.get(EXP, subject="synthetic-export-001", roles=("export_ops",))
        self.assertEqual([x["ref"] for x in permitted.json()["items"]], ["DEMO-E-001"])
        self.assertEqual(permitted.json()["items"][0]["case_status"], "DRAFT_ONLY")
        self.assertNotIn("source_rights_verified", permitted.text)
        self.assertTrue(self.reopen().verify_integrity())

    def test_review_request_and_response_update_live_worklist_without_approval(self):
        self.request()
        one = self.get()
        selected = next(x for x in one.json()["items"] if x["ref"] == "DEMO-D-001")
        self.assertEqual(selected["technical_review_state"], "EVIDENCE_REVIEW_REQUESTED")
        self.assertEqual(selected["review_revision"], 1)
        reviewer = Principal("synthetic-domestic-reviewer", frozenset({"domestic_ops"}))
        self.ledger.record_human_response(
            engine="DOMESTIC", ref="DEMO-D-001", actor=reviewer,
            expected_case_version=2, expected_review_revision=1,
            action_id="DEMO-RESPONSE-WORKLIST", request_ref="DEMO-REQUEST-001",
            evidence_ref="DEMO-RESPONSE-EVIDENCE",
            decision_ref="DEMO-HUMAN-REFERENCE",
        )
        reopened = self.new_client(self.reopen())
        two = self.get(client=reopened)
        selected = next(x for x in two.json()["items"] if x["ref"] == "DEMO-D-001")
        self.assertEqual(selected["technical_review_state"], "HUMAN_RESPONSE_RECORDED")
        self.assertEqual(selected["review_revision"], 2)
        self.assertEqual(selected["case_status"], "DRAFT_ONLY")
        self.assertNotIn("DEMO-HUMAN-REFERENCE", two.text)
        self.assertNotIn("DEMO-RESPONSE-EVIDENCE", two.text)
        self.assertEqual(self.reopen().review_state("DOMESTIC", "DEMO-D-001")[
            "case_status"], "DRAFT_ONLY")

    def test_unsigned_and_invalid_token_rejected_before_worklist_audit(self):
        self.assertEqual(self.client.get(DOM).status_code, 401)
        self.assertEqual(self.client.get(
            DOM, headers={"Authorization": "Bearer invalid"}
        ).status_code, 401)
        self.assertEqual(self.audit_worklist(), [])

    def test_invalid_limit_and_cursor_never_infer_hidden_records(self):
        for params in (
            {"limit": 0}, {"limit": 51},
            {"limit": "oops"}, {"after_ref": "not-synthetic"},
        ):
            with self.subTest(params=params):
                r = self.get(params=params)
                self.assertEqual(r.status_code, 422)
                self.assertNotIn("DEMO-D-003", r.text)
        self.assertEqual(self.audit_worklist(), [])

    def test_corrupted_evidence_or_revocation_must_fail_503_not_422(self):
        self.request()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER review_no_update")
            db.execute("UPDATE technical_review_step SET evidence_ref='DEMO-TAMPERED'")
        r = self.get()
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"detail": "TECHNICAL_REVIEW_UNAVAILABLE"})
        self.assertNotIn("DEMO-TAMPERED", r.text)

    def test_failed_worklist_audit_is_atomic_and_does_not_return_partial_page(self):
        before = self.ledger.audit_snapshot()
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER stop_worklist_page BEFORE INSERT ON audit_event
                WHEN NEW.payload LIKE '%TECHNICAL_REVIEW_WORKLIST%'
                BEGIN SELECT RAISE(ABORT, 'audit insert rejected'); END;
            """)
        r = self.get(params={"limit": 2})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"detail": "TECHNICAL_REVIEW_UNAVAILABLE"})
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER stop_worklist_page")
        self.assertEqual(self.reopen().audit_snapshot(), before)
        self.assertEqual([x["ref"] for x in self.get(
            params={"limit": 2}
        ).json()["items"]], ["DEMO-D-001", "DEMO-D-002"])

    def test_default_runtime_and_scoped_only_app_exclude_worklists_and_writes(self):
        empty = TestClient(create_app(self.config))
        scoped = TestClient(create_app(self.config, scoped_registry=self.ledger))
        self.assertEqual(empty.get(DOM, headers=self.signed()).status_code, 404)
        self.assertEqual(scoped.get(DOM, headers=self.signed()).status_code, 404)
        self.assertEqual(self.client.post(
            DOM, headers=self.signed(), json={"action": "APPROVE"}
        ).status_code, 405)
        self.assertEqual(self.audit_worklist(), [])

    def test_concurrent_worklist_read_and_revoke_has_ordered_audit(self):
        barrier = Barrier(2)
        def read():
            client = self.new_client(self.reopen())
            barrier.wait(timeout=12)
            return client.get(DOM, headers=self.signed())
        def revoke():
            ledger = self.reopen()
            barrier.wait(timeout=12)
            return ledger.revoke_grant(
                engine="DOMESTIC", ref="DEMO-D-001",
                subject="synthetic-domestic-001", role="domestic_ops",
                actor="synthetic-controller", expected_grant_revision=0,
                action_id="DEMO-RACE-REVOKE", reason_ref="DEMO-RACE-REASON",
            )
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(read)
            b = pool.submit(revoke)
            response, revoked = a.result(), b.result()
        self.assertEqual(response.status_code, 200, response.text)
        revealed = [x["ref"] for x in response.json()["items"]]
        events = self.reopen().audit_snapshot()
        item_events = [
            e for e in events
            if e.access_mode == "TECHNICAL_REVIEW_WORKLIST" and e.ref == "DEMO-D-001"
        ]
        if "DEMO-D-001" in revealed:
            self.assertEqual(len(item_events), 1)
            self.assertLess(item_events[0].sequence, revoked.sequence)
        else:
            self.assertEqual(item_events, [])
        self.assertEqual([x["ref"] for x in self.get().json()["items"]],
                         ["DEMO-D-002", "DEMO-D-004"])
        self.assertTrue(self.reopen().verify_integrity())


if __name__ == "__main__":
    unittest.main()
