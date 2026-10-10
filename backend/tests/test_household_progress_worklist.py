"""Integrated owner-only snapshot of synthetic Domestic technical progress.

Tests use an ephemeral local key, fake identity claims, and only DEMO cases.
There is no real enrollment, Business approval, consent or Production runtime.
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
from ronas_api.grant_ledger_sqlite import SqliteSyntheticGrantLedger
from ronas_api.human_review_sqlite import SqliteSyntheticHumanReviewLedger
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant, ScopedSyntheticDraftRegistry

ISS = "https://id.example.test/realms/ronas"
API, WEB = "ronas-api", "ronas-web"
ORIGIN = "https://ronas.example.test"
PROGRESS = "/api/v1/domestic/household-intake/my-drafts/technical-progress"


def cases():
    return (
        ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-one", 3, (
            ScopedGrant("synthetic-domestic-requester", "domestic_ops"),
            ScopedGrant("synthetic-domestic-reviewer", "domestic_ops"),
        )),
        ScopedDraft("DEMO-D-002", "DOMESTIC", "synthetic-household-one", 1, (
            ScopedGrant("synthetic-domestic-requester", "domestic_ops"),
        )),
        ScopedDraft("DEMO-D-003", "DOMESTIC", "synthetic-household-two", 2, (
            ScopedGrant("synthetic-domestic-requester", "domestic_ops"),
        )),
        ScopedDraft("DEMO-D-004", "DOMESTIC", "synthetic-household-one", 4, (
            ScopedGrant("synthetic-domestic-requester", "domestic_ops"),
        )),
        ScopedDraft("DEMO-E-001", "EXPORT", "synthetic-household-one", 2, (
            ScopedGrant("synthetic-export-operator", "export_ops"),
        ), source_ref="DEMO-SOURCE-001"),
    )


class UnifiedHouseholdProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "progress-key", "use": "sig", "alg": "RS256"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "progress.db"
        self.ledger = self.reopen()
        self.client = self.client_for(self.ledger)

    def reopen(self):
        return SqliteSyntheticHumanReviewLedger(
            self.path, cases(),
            trusted_revoke_authorizer=lambda a, e, r: a == "synthetic-controller",
            trusted_human_review_authorizer=lambda a, e, r: (
                a == "synthetic-domestic-reviewer"
                and e == "DOMESTIC" and r == "DEMO-D-001"
            ),
        )

    def client_for(self, ledger):
        return TestClient(create_app(
            self.config, scoped_registry=ledger, technical_review_ledger=ledger,
        ), base_url=ORIGIN)

    def headers(self, subject="synthetic-household-one", roles=("household",)):
        now = int(time.time())
        value = jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "sub": subject,
            "typ": "Bearer", "iat": now - 5, "nbf": now - 5, "exp": now + 500,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "progress-key"})
        return {"Authorization": "Bearer " + value}

    def get(self, params=None, *, subject="synthetic-household-one",
            roles=("household",), client=None):
        return (client or self.client).get(
            PROGRESS, params=params, headers=self.headers(subject, roles)
        )

    def owner_events(self, ledger=None):
        return [e for e in (ledger or self.ledger).audit_snapshot()
                if e.access_mode == "HOUSEHOLD_PROGRESS_WORKLIST"]

    def request(self, ledger=None):
        return (ledger or self.ledger).request_evidence_review(
            engine="DOMESTIC", ref="DEMO-D-001",
            actor=Principal("synthetic-domestic-requester", frozenset({"domestic_ops"})),
            expected_case_version=3, expected_review_revision=0,
            action_id="DEMO-PROGRESS-REQUEST", request_ref="DEMO-PRIVATE-REQUEST",
            evidence_ref="DEMO-PRIVATE-EVIDENCE",
        )

    def respond(self, ledger=None):
        return (ledger or self.ledger).record_human_response(
            engine="DOMESTIC", ref="DEMO-D-001",
            actor=Principal("synthetic-domestic-reviewer", frozenset({"domestic_ops"})),
            expected_case_version=3, expected_review_revision=1,
            action_id="DEMO-PROGRESS-RESPONSE",
            request_ref="DEMO-PRIVATE-REQUEST",
            evidence_ref="DEMO-PRIVATE-RESPONSE-EVIDENCE",
            decision_ref="DEMO-PRIVATE-NOTE",
        )

    def browser(self, subject="synthetic-household-one", roles=("household",),
                *, review_enabled=True):
        class Store:
            def __init__(self):
                self.data = {}
            def get_session(self, sid):
                return self.data.get(sid)
            def revoke_session(self, sid):
                self.data.pop(sid, None)

        store = Store()
        async def no_exchange(_code, _verifier):
            raise AssertionError("no external identity provider")
        flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            store, no_exchange,
        )
        now = int(time.time())
        sid = secrets.token_urlsafe(40)
        store.data[sid] = BrowserSession(
            subject, frozenset(roles), self.headers(subject, roles)["Authorization"][7:],
            secrets.token_urlsafe(32), now + 250,
        )
        kwargs = {"scoped_registry": self.ledger}
        if review_enabled:
            kwargs["technical_review_ledger"] = self.ledger
        client = TestClient(create_app(self.config, flow, **kwargs), base_url=ORIGIN)
        client.cookies.set("__Host-ronas_session", sid)
        return client, store, sid

    def test_single_snapshot_keyset_pages_hide_unowned_records_and_counts(self):
        one = self.get({"limit": 2})
        self.assertEqual(one.status_code, 200, one.text)
        self.assertEqual([i["ref"] for i in one.json()["items"]],
                         ["DEMO-D-001", "DEMO-D-002"])
        self.assertEqual(one.json()["next_cursor"], "DEMO-D-002")
        self.assertEqual(one.json()["engine"], "DOMESTIC")
        self.assertNotIn("DEMO-D-003", one.text)
        self.assertNotIn("DEMO-E-001", one.text)
        self.assertNotIn("total", one.json())
        for i in one.json()["items"]:
            self.assertEqual(i["status"], "DRAFT_ONLY")
            self.assertEqual(i["technical_review_state"], "UNREQUESTED")
            self.assertEqual(i["review_revision"], 0)
            self.assertFalse(i["purpose_consent_verified"])
        second = self.get({"after_ref": one.json()["next_cursor"], "limit": 2})
        self.assertEqual([i["ref"] for i in second.json()["items"]], ["DEMO-D-004"])
        self.assertIsNone(second.json()["next_cursor"])
        self.assertEqual([e.ref for e in self.owner_events()],
                         ["DEMO-D-001", "DEMO-D-002", "DEMO-D-004"])
        self.assertTrue(self.reopen().verify_integrity())

    def test_technical_progress_refreshes_without_private_evidence_disclosure(self):
        self.request()
        requested = self.get()
        item = requested.json()["items"][0]
        self.assertEqual(item["review_revision"], 1)
        self.assertEqual(item["technical_review_state"], "EVIDENCE_REVIEW_REQUESTED")
        self.respond()
        next_read = self.get(client=self.client_for(self.reopen()))
        item = next_read.json()["items"][0]
        self.assertEqual(item["review_revision"], 2)
        self.assertEqual(item["technical_review_state"], "HUMAN_RESPONSE_RECORDED")
        self.assertEqual(item["status"], "DRAFT_ONLY")
        for private in ("DEMO-PRIVATE-REQUEST", "DEMO-PRIVATE-EVIDENCE",
                        "DEMO-PRIVATE-RESPONSE-EVIDENCE", "DEMO-PRIVATE-NOTE",
                        "synthetic-domestic-reviewer", "actor_digest",
                        "decision_ref", "audit_sequence", "owner_subject"):
            self.assertNotIn(private, next_read.text)
        self.assertTrue(self.reopen().verify_integrity())

    def test_other_household_can_only_see_its_own_unrelated_domestic_case(self):
        r = self.get(subject="synthetic-household-two")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([i["ref"] for i in r.json()["items"]], ["DEMO-D-003"])
        self.assertNotIn("DEMO-D-001", r.text)
        self.assertEqual([e.ref for e in self.owner_events()], ["DEMO-D-003"])

    def test_staff_role_and_unassigned_household_cannot_list_owned_cases(self):
        for subject, roles in (
            ("synthetic-domestic-requester", ("domestic_ops",)),
            ("synthetic-household-one", ("domestic_ops",)),
            ("synthetic-unassigned", ("household",)),
            ("synthetic-export-operator", ("export_ops",)),
        ):
            with self.subTest(subject=subject, roles=roles):
                page = self.get(subject=subject, roles=roles)
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.json()["items"], [])
                self.assertIsNone(page.json()["next_cursor"])
        self.assertEqual(self.owner_events(), [])

    def test_invalid_or_missing_signed_identity_never_generates_owner_audit(self):
        self.assertEqual(self.client.get(PROGRESS).status_code, 401)
        self.assertEqual(self.client.get(
            PROGRESS, headers={"Authorization": "Bearer invalid"}
        ).status_code, 401)
        self.assertEqual(self.client.get(
            PROGRESS, headers={"X-Role": "household"}
        ).status_code, 401)
        self.assertEqual(self.owner_events(), [])

    def test_cursor_validation_and_keyset_end_do_not_enumerate_others(self):
        for params in ({"limit": 0}, {"limit": 51}, {"limit": "NaN"},
                       {"after_ref": "not-a-demo-ref"}):
            with self.subTest(params=params):
                r = self.get(params)
                self.assertEqual(r.status_code, 422)
                self.assertNotIn("DEMO-D-003", r.text)
        self.assertEqual(self.owner_events(), [])
        empty = self.get({"after_ref": "DEMO-D-004"})
        self.assertEqual(empty.json()["items"], [])
        self.assertIsNone(empty.json()["next_cursor"])

    def test_rejects_tampered_review_lineage_with_sanitized_503(self):
        self.request()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER review_no_update")
            db.execute(
                "UPDATE technical_review_step SET evidence_ref='DEMO-PRIVATE-TAMPER'"
            )
        response = self.get()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "SYNTHETIC_LEDGER_UNAVAILABLE"})
        self.assertNotIn("DEMO-PRIVATE-TAMPER", response.text)

    def test_rejected_audit_append_rolls_back_full_progress_page(self):
        self.request()
        baseline = self.ledger.audit_snapshot()
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER stop_progress BEFORE INSERT ON audit_event
                WHEN NEW.payload LIKE '%HOUSEHOLD_PROGRESS_WORKLIST%'
                BEGIN SELECT RAISE(ABORT, 'synthetic audit failure'); END;
            """)
        response = self.get({"limit": 2})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("DEMO-D-001", response.text)
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER stop_progress")
        self.assertEqual(self.reopen().audit_snapshot(), baseline)
        self.assertEqual([i["ref"] for i in self.get().json()["items"]],
                         ["DEMO-D-001", "DEMO-D-002", "DEMO-D-004"])

    def test_default_and_base_grant_store_do_not_mount_technical_progress(self):
        plain = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(plain.get(PROGRESS, headers=self.headers()).status_code, 404)
        basic = SqliteSyntheticGrantLedger(
            self.path.parent / "basic.db", cases(),
            trusted_revoke_authorizer=lambda a, e, r: False,
        )
        base = TestClient(create_app(self.config, scoped_registry=basic), base_url=ORIGIN)
        self.assertEqual(base.get(PROGRESS, headers=self.headers()).status_code, 404)
        self.assertEqual(base.get(
            "/api/v1/domestic/household-intake/my-drafts",
            headers=self.headers(),
        ).status_code, 200)
        self.assertEqual(self.client.post(
            PROGRESS, headers=self.headers(), json={"approved": True},
        ).status_code, 405)

    def test_shared_user_shell_shows_owner_progress_in_same_page(self):
        client, _, _ = self.browser()
        self.request()
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("DEMO-D-001", page.text)
        self.assertIn("درخواست بررسی شواهد ثبت شده", page.text)
        self.assertIn("بررسی فنی درخواست نشده", page.text)
        self.assertIn("DRAFT_ONLY", page.text)
        self.assertIn("/my-drafts/DEMO-D-001", page.text)
        self.assertNotIn("DEMO-D-003", page.text)
        self.assertNotIn("DEMO-E-001", page.text)
        self.assertNotIn("DEMO-PRIVATE-REQUEST", page.text)
        self.assertNotIn("DEMO-PRIVATE-EVIDENCE", page.text)
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.assertIn("frame-ancestors 'none'", page.headers["content-security-policy"])
        self.assertEqual(len(self.owner_events()), 3)

    def test_shared_user_shell_refreshes_after_human_response_without_approval(self):
        client, _, _ = self.browser()
        self.request()
        self.respond()
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("مرجع پاسخ انسانی ثبت شده؛ به معنی تأیید نیست", page.text)
        self.assertNotIn("DEMO-PRIVATE-NOTE", page.text)
        self.assertNotIn("DEMO-PRIVATE-RESPONSE-EVIDENCE", page.text)
        self.assertIn("DRAFT_ONLY", page.text)

    def test_revoked_browser_sid_and_staff_grant_boundaries_remain_independent(self):
        client, store, sid = self.browser()
        self.assertEqual(client.get("/").status_code, 200)
        last_count = len(self.owner_events())
        store.revoke_session(sid)
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("DEMO-D-001", page.text)
        self.assertEqual(len(self.owner_events()), last_count)
        self.ledger.revoke_grant(
            engine="DOMESTIC", ref="DEMO-D-001",
            subject="synthetic-domestic-requester", role="domestic_ops",
            actor="synthetic-controller", expected_grant_revision=0,
            action_id="DEMO-OP-REVOKE", reason_ref="DEMO-REASON",
        )
        self.assertIn("DEMO-D-001", self.get().text)
        self.assertTrue(self.reopen().verify_integrity())

    def test_concurrent_human_response_and_page_has_one_ordered_snapshot(self):
        self.request()
        barrier = Barrier(2)

        def read():
            client = self.client_for(self.reopen())
            barrier.wait(timeout=12)
            return client.get(PROGRESS, headers=self.headers())

        def respond():
            ledger = self.reopen()
            barrier.wait(timeout=12)
            return self.respond(ledger)

        with ThreadPoolExecutor(max_workers=2) as workers:
            a = workers.submit(read)
            b = workers.submit(respond)
            page, step = a.result(), b.result()
        self.assertEqual(page.status_code, 200, page.text)
        item = next(i for i in page.json()["items"] if i["ref"] == "DEMO-D-001")
        self.assertIn(item["technical_review_state"], (
            "EVIDENCE_REVIEW_REQUESTED", "HUMAN_RESPONSE_RECORDED",
        ))
        events = self.reopen().audit_snapshot()
        owner_event = next(e for e in events
                           if e.access_mode == "HOUSEHOLD_PROGRESS_WORKLIST"
                           and e.ref == "DEMO-D-001")
        page_audit = [e for e in events if e.access_mode == "HOUSEHOLD_PROGRESS_WORKLIST"]
        self.assertEqual(len(page_audit), 3)
        self.assertEqual([e.ref for e in page_audit],
                         ["DEMO-D-001", "DEMO-D-002", "DEMO-D-004"])
        if item["technical_review_state"] == "HUMAN_RESPONSE_RECORDED":
            self.assertGreater(owner_event.sequence, step.audit_sequence)
        else:
            self.assertLess(owner_event.sequence, step.audit_sequence)
        self.assertEqual(self.get().json()["items"][0]["technical_review_state"],
                         "HUMAN_RESPONSE_RECORDED")
        self.assertTrue(self.reopen().verify_integrity())

    def test_html_integrity_failure_does_not_return_partial_owner_cards(self):
        client, _, _ = self.browser()
        self.request()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER review_no_update")
            db.execute(
                "UPDATE technical_review_step SET request_ref='DEMO-PRIVATE-CORRUPT'"
            )
        r = client.get("/")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"detail": "SYNTHETIC_LEDGER_UNAVAILABLE"})
        self.assertNotIn("DEMO-D-001", r.text)
        self.assertNotIn("DEMO-PRIVATE-CORRUPT", r.text)


if __name__ == "__main__":
    unittest.main()
