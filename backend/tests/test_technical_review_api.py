"""Opt-in signed-Keycloak review GET contract. Synthetic records only."""
from pathlib import Path
import json
import sqlite3
import tempfile
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.human_review_sqlite import SqliteSyntheticHumanReviewLedger
from ronas_api.keycloak import KeycloakConfig
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant, ScopedSyntheticDraftRegistry


ISS = "https://id.example.test/realms/ronas"
API, WEB = "ronas-api", "ronas-web"
DOM = "/api/v1/admin/domestic/household-intake/drafts/DEMO-D-001/technical-review"
EXP = "/api/v1/admin/export/research/drafts/DEMO-E-001/technical-review"


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


def revoke_authority(actor, engine, ref):
    return actor == "synthetic-authority"


def human_authority(actor, engine, ref):
    return actor == "synthetic-domestic-002" and engine == "DOMESTIC" and ref == "DEMO-D-001"


class TechnicalReviewHTTPBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        public.update({"kid": "kid-test", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [public]}).encode())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "technical-review.db"
        self.ledger = SqliteSyntheticHumanReviewLedger(
            self.path, records(),
            trusted_revoke_authorizer=revoke_authority,
            trusted_human_review_authorizer=human_authority,
        )
        self.client = TestClient(create_app(
            self.config, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
        ))

    def token(self, subject="synthetic-domestic-001", roles=("domestic_ops",),
              **overrides):
        now = int(time.time())
        claims = {
            "iss": ISS, "aud": API, "azp": WEB, "sub": subject,
            "typ": "Bearer", "iat": now - 5, "nbf": now - 5, "exp": now + 300,
            "resource_access": {API: {"roles": list(roles)}},
        }
        claims.update(overrides)
        return jwt.encode(claims, self.key, algorithm="RS256",
                          headers={"kid": "kid-test"})

    def headers(self, subject="synthetic-domestic-001", roles=("domestic_ops",),
                **claims):
        return {"Authorization": "Bearer " + self.token(subject, roles, **claims)}

    def request_review(self):
        return self.ledger.request_evidence_review(
            engine="DOMESTIC", ref="DEMO-D-001",
            actor=Principal("synthetic-domestic-001", frozenset({"domestic_ops"})),
            expected_case_version=3, expected_review_revision=0,
            action_id="DEMO-ACTION-REQ", request_ref="DEMO-REQ",
            evidence_ref="DEMO-EVIDENCE",
        )

    def test_signed_assigned_operator_reads_only_synthetic_review_state(self):
        self.request_review()
        response = self.client.get(DOM, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["case_status"], "DRAFT_ONLY")
        self.assertEqual(data["technical_review_state"], "EVIDENCE_REVIEW_REQUESTED")
        self.assertEqual(data["review_revision"], 1)
        self.assertEqual(data["history"][0]["request_ref"], "DEMO-REQ")
        self.assertNotIn("actor_digest", data["history"][0])
        self.assertNotIn("command_digest", data["history"][0])
        self.assertEqual(response.headers["cache-control"], "no-store")
        event = self.ledger.audit_snapshot()[-1]
        self.assertEqual((event.kind, event.access_mode),
                         ("READ_ALLOWED", "TECHNICAL_REVIEW_HISTORY"))
        draft = self.client.get(
            "/api/v1/admin/domestic/household-intake/drafts/DEMO-D-001",
            headers=self.headers(),
        )
        self.assertEqual(draft.status_code, 200)
        self.assertEqual(draft.json()["status"], "DRAFT_ONLY")
        self.assertFalse(draft.json()["expert_approved"])
        self.assertFalse(draft.json()["plan_accepted"])

    def test_response_note_reference_is_never_a_business_approval(self):
        self.request_review()
        self.ledger.record_human_response(
            engine="DOMESTIC", ref="DEMO-D-001",
            actor=Principal("synthetic-domestic-002", frozenset({"domestic_ops"})),
            expected_case_version=3, expected_review_revision=1,
            action_id="DEMO-ACTION-RESPONSE", request_ref="DEMO-REQ",
            evidence_ref="DEMO-EVIDENCE-RESPONSE",
            decision_ref="DEMO-HUMAN-NOTE",
        )
        response = self.client.get(DOM, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["case_status"], "DRAFT_ONLY")
        self.assertEqual(data["technical_review_state"], "HUMAN_RESPONSE_RECORDED")
        self.assertEqual(data["history"][-1]["decision_ref"], "DEMO-HUMAN-NOTE")
        self.assertNotIn("accepted", data)
        self.assertNotIn("approved", data)
        self.assertEqual(self.client.post(DOM, headers=self.headers(), json={}).status_code, 405)

    def test_unsigned_invalid_and_claim_mismatch_tokens_fail_before_ledger(self):
        requests = [
            {},
            {"X-Role": "domestic_ops"},
            {"Authorization": "Bearer not-a-token"},
            self.headers(aud="different-client"),
            self.headers(azp="unauthorized-browser"),
            self.headers(resource_access={"other-client": {"roles": ["domestic_ops"]}}),
        ]
        for headers in requests:
            with self.subTest(headers=headers):
                result = self.client.get(DOM, headers=headers)
                self.assertEqual(result.status_code, 401)
        self.assertEqual(self.ledger.audit_snapshot(), ())

    def test_wrong_role_unassigned_actor_and_cross_engine_are_hidden(self):
        for path, headers in (
            (DOM, self.headers(roles=("finance",))),
            (DOM, self.headers(roles=("governance",))),
            (DOM, self.headers("synthetic-other-ops")),
            (EXP, self.headers(roles=("export_ops",))),
            (DOM, self.headers("synthetic-export-001", ("export_ops",))),
        ):
            with self.subTest(path=path, headers=headers):
                denied = self.client.get(path, headers=headers)
                self.assertEqual(denied.status_code, 404)
                self.assertEqual(denied.json(), {"detail": "DRAFT_NOT_FOUND"})
                event = self.ledger.audit_snapshot()[-1]
                self.assertEqual(event.kind, "READ_DENIED")
                self.assertEqual(event.access_mode, "TECHNICAL_REVIEW_HISTORY")
        unknown = self.client.get(
            DOM.replace("DEMO-D-001", "DEMO-NOT-FOUND"),
            headers=self.headers(),
        )
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(unknown.json(), {"detail": "DRAFT_NOT_FOUND"})

    def test_export_case_can_only_be_read_by_its_assigned_export_operator(self):
        res = self.client.get(
            EXP, headers=self.headers("synthetic-export-001", ("export_ops",))
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["engine"], "EXPORT")
        self.assertEqual(res.json()["case_status"], "DRAFT_ONLY")
        self.assertEqual(res.json()["technical_review_state"], "UNREQUESTED")
        self.assertEqual(res.json()["history"], [])
        draft = self.client.get(
            "/api/v1/admin/export/research/drafts/DEMO-E-001",
            headers=self.headers("synthetic-export-001", ("export_ops",)),
        )
        self.assertFalse(draft.json()["source_rights_verified"])
        self.assertFalse(draft.json()["review_approved"])

    def test_signed_old_token_is_denied_immediately_after_grant_revocation(self):
        previously_valid = self.headers()
        self.assertEqual(self.client.get(DOM, headers=previously_valid).status_code, 200)
        self.ledger.revoke_grant(
            engine="DOMESTIC", ref="DEMO-D-001",
            subject="synthetic-domestic-001", role="domestic_ops",
            actor="synthetic-authority", expected_grant_revision=0,
            action_id="DEMO-REVOKE-HTTP", reason_ref="DEMO-REASON-HTTP",
        )
        denied = self.client.get(DOM, headers=previously_valid)
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(self.ledger.audit_snapshot()[-1].kind, "READ_DENIED")
        self.assertEqual(self.ledger.review_state("DOMESTIC", "DEMO-D-001")[
            "case_status"], "DRAFT_ONLY")
        self.assertTrue(self.ledger.verify_integrity())

    def test_corrupt_review_history_fails_closed_without_leaking_references(self):
        self.request_review()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER review_no_update")
            db.execute("UPDATE technical_review_step SET request_ref='DEMO-TAMPERED'")
        response = self.client.get(DOM, headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "TECHNICAL_REVIEW_UNAVAILABLE"})
        self.assertNotIn("DEMO-TAMPERED", response.text)
        self.assertNotIn("DEMO-REQ", response.text)

    def test_failed_read_audit_fails_closed_and_rolls_back(self):
        self.request_review()
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER block_review_api_audit BEFORE INSERT ON audit_event
                WHEN NEW.payload LIKE '%TECHNICAL_REVIEW_HISTORY%'
                BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END;
            """)
        before = self.ledger.audit_snapshot()
        response = self.client.get(DOM, headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "TECHNICAL_REVIEW_UNAVAILABLE"})
        self.assertEqual(self.ledger.audit_snapshot(), before)
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER block_review_api_audit")
        self.assertEqual(self.client.get(DOM, headers=self.headers()).status_code, 200)
        self.assertTrue(self.ledger.verify_integrity())

    def test_default_runtime_never_mounts_technical_review_http_routes(self):
        self.assertEqual(TestClient(create_app(self.config)).get(
            DOM, headers=self.headers(),
        ).status_code, 404)
        scoped_only = TestClient(create_app(
            self.config, scoped_registry=self.ledger,
        ))
        self.assertEqual(scoped_only.get(DOM, headers=self.headers()).status_code, 404)
        self.assertEqual(scoped_only.get(
            "/api/v1/admin/domestic/household-intake/drafts/DEMO-D-001",
            headers=self.headers(),
        ).status_code, 200)
        for path in ("/api/v1/reviews", "/api/v1/admin/reviews/approve"):
            self.assertEqual(self.client.post(
                path, headers=self.headers(), json={},
            ).status_code, 404)

    def test_mismatched_or_missing_scope_store_cannot_mount_review_router(self):
        with self.assertRaises(ValueError):
            create_app(self.config, technical_review_ledger=self.ledger)
        unrelated = ScopedSyntheticDraftRegistry(records())
        with self.assertRaises(ValueError):
            create_app(self.config, scoped_registry=unrelated,
                       technical_review_ledger=self.ledger)
        with self.assertRaises(ValueError):
            create_app(None, scoped_registry=self.ledger,
                       technical_review_ledger=self.ledger)


if __name__ == "__main__":
    unittest.main()
