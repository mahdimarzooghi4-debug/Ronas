"""User-facing scoped Export research queue — all LOCAL/TEST DEMO only.

Only signed export role and a *current exact-case* grant may reveal an
immutable case. Filters are observed technical stages, never study findings.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
import unittest
from threading import Barrier

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.human_review_sqlite import SqliteSyntheticHumanReviewLedger
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant

ISS = "https://id.example.test/realms/ronas"
API, WEB, ORIGIN = "ronas-api", "ronas-web", "https://ronas.example.test"
API_ROUTE = "/api/v1/admin/export/research/cases"
UI_ROUTE = "/admin/export/research"


class Store:
    def __init__(self):
        self.sessions = {}

    def get_session(self, sid):
        return self.sessions.get(sid)

    def revoke_session(self, sid):
        self.sessions.pop(sid, None)


class ExportResearchQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "export-queue-key", "use": "sig", "alg": "RS256"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def fixtures(self):
        ops = ScopedGrant("synthetic-export-001", "export_ops")
        reviewer = ScopedGrant("synthetic-export-reviewer", "export_ops")
        other = ScopedGrant("synthetic-export-other", "export_ops")
        return (
            ScopedDraft("DEMO-E-001", "EXPORT", "synthetic-export-owner-1",
                        3, (ops,), source_ref="DEMO-SOURCE-001"),
            ScopedDraft("DEMO-E-002", "EXPORT", "synthetic-export-owner-2",
                        2, (ops,), source_ref="DEMO-SOURCE-002"),
            ScopedDraft("DEMO-E-003", "EXPORT", "synthetic-export-owner-3",
                        1, (ops, reviewer), source_ref="DEMO-SOURCE-003"),
            ScopedDraft("DEMO-E-004", "EXPORT", "synthetic-export-owner-4",
                        1, (other,), source_ref="DEMO-SOURCE-004"),
            ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-1",
                        1, (ScopedGrant("synthetic-domestic-ops", "domestic_ops"),)),
        )

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "research-queue.db"
        self.ledger = self.reopen()
        self.store = Store()
        async def no_exchange(_code, _verifier):
            raise AssertionError("external Keycloak not connected")
        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.store, no_exchange,
        )
        self.client = self.client_for(self.ledger)

    def reopen(self):
        return SqliteSyntheticHumanReviewLedger(
            self.path, self.fixtures(),
            previous_versions=(
                ScopedDraft("DEMO-E-001", "EXPORT", "synthetic-export-owner-1",
                            1, (ScopedGrant("synthetic-export-001", "export_ops"),),
                            source_ref="DEMO-SOURCE-001"),
                ScopedDraft("DEMO-E-001", "EXPORT", "synthetic-export-owner-1",
                            2, (ScopedGrant("synthetic-export-001", "export_ops"),),
                            source_ref="DEMO-SOURCE-001"),
            ),
            trusted_revoke_authorizer=lambda actor, engine, ref: (
                actor == "synthetic-controller" and engine == "EXPORT"
            ),
            trusted_human_review_authorizer=lambda actor, engine, ref: (
                actor == "synthetic-export-reviewer"
                and engine == "EXPORT" and ref == "DEMO-E-003"
            ),
        )

    def client_for(self, ledger):
        return TestClient(create_app(
            self.config, self.flow,
            scoped_registry=ledger, technical_review_ledger=ledger,
        ), base_url=ORIGIN)

    def token(self, subject="synthetic-export-001", roles=("export_ops",)):
        now = int(time.time())
        return jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "typ": "Bearer",
            "sub": subject, "iat": now-5, "nbf": now-5, "exp": now+400,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "export-queue-key"})

    def headers(self, subject="synthetic-export-001", roles=("export_ops",)):
        return {"Authorization": "Bearer " + self.token(subject, roles)}

    def get(self, *, state="ALL", after=None, limit=20, client=None,
            subject="synthetic-export-001", roles=("export_ops",)):
        params = {"technical_state": state, "limit": limit}
        if after is not None:
            params["after_ref"] = after
        return (client or self.client).get(
            API_ROUTE, params=params, headers=self.headers(subject, roles),
        )

    def login(self, subject="synthetic-export-001", roles=("export_ops",)):
        sid = secrets.token_urlsafe(36)
        self.store.sessions[sid] = BrowserSession(
            subject, frozenset(roles), self.token(subject, roles),
            secrets.token_urlsafe(32), int(time.time()) + 200,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        return sid

    def set_review_stages(self):
        maker = Principal("synthetic-export-001", frozenset({"export_ops"}))
        reviewer = Principal("synthetic-export-reviewer", frozenset({"export_ops"}))
        for ref, version in (("DEMO-E-002", 2), ("DEMO-E-003", 1)):
            self.ledger.request_evidence_review(
                engine="EXPORT", ref=ref, actor=maker,
                expected_case_version=version, expected_review_revision=0,
                action_id="DEMO-QUEUE-REQUEST-" + ref,
                request_ref="DEMO-QUEUE-PRIVATE-REQUEST-" + ref,
                evidence_ref="DEMO-QUEUE-PRIVATE-EVIDENCE-" + ref,
            )
        self.ledger.record_human_response(
            engine="EXPORT", ref="DEMO-E-003", actor=reviewer,
            expected_case_version=1, expected_review_revision=1,
            action_id="DEMO-QUEUE-RESPONSE-E003",
            request_ref="DEMO-QUEUE-PRIVATE-REQUEST-DEMO-E-003",
            evidence_ref="DEMO-QUEUE-PRIVATE-RESPONSE-E003",
            decision_ref="DEMO-QUEUE-PRIVATE-DECISION-E003",
        )

    def queue_audit(self):
        return [
            event for event in self.ledger.audit_snapshot()
            if event.access_mode == "EXPORT_RESEARCH_CASE_QUEUE"
        ]

    def test_default_queue_lists_only_three_granted_export_cases(self):
        result = self.get()
        self.assertEqual(result.status_code, 200, result.text)
        page = result.json()
        self.assertEqual(page["technical_state_filter"], "ALL")
        self.assertEqual([item["ref"] for item in page["items"]],
                         ["DEMO-E-001", "DEMO-E-002", "DEMO-E-003"])
        self.assertIsNone(page["next_cursor"])
        self.assertNotIn("DEMO-E-004", result.text)
        self.assertNotIn("DEMO-D-001", result.text)
        self.assertEqual(result.headers["cache-control"], "no-store")
        for item in page["items"]:
            self.assertFalse(item["research_question_defined"])
            self.assertFalse(item["source_rights_verified"])
            self.assertFalse(item["research_report_approved"])
            self.assertFalse(item["business_actions_enabled"])
            self.assertEqual(item["case_status"], "DRAFT_ONLY")

    def test_filters_match_only_persisted_technical_stages(self):
        self.set_review_stages()
        for state, expected in (
            ("ALL", ["DEMO-E-001", "DEMO-E-002", "DEMO-E-003"]),
            ("UNREQUESTED", ["DEMO-E-001"]),
            ("EVIDENCE_REVIEW_REQUESTED", ["DEMO-E-002"]),
            ("HUMAN_RESPONSE_RECORDED", ["DEMO-E-003"]),
        ):
            with self.subTest(state=state):
                data = self.get(state=state).json()
                self.assertEqual([item["ref"] for item in data["items"]], expected)
                self.assertEqual(data["technical_state_filter"], state)
                self.assertFalse(data["items"][0]["research_report_approved"])

    def test_keyset_pagination_operates_after_authorized_filtering(self):
        first = self.get(limit=1).json()
        self.assertEqual([x["ref"] for x in first["items"]], ["DEMO-E-001"])
        self.assertEqual(first["next_cursor"], "DEMO-E-001")
        second = self.get(limit=1, after=first["next_cursor"]).json()
        self.assertEqual([x["ref"] for x in second["items"]], ["DEMO-E-002"])
        self.assertEqual(second["next_cursor"], "DEMO-E-002")
        third = self.get(limit=1, after=second["next_cursor"]).json()
        self.assertEqual([x["ref"] for x in third["items"]], ["DEMO-E-003"])
        self.assertIsNone(third["next_cursor"])
        self.assertEqual(self.get(limit=1, after="DEMO-E-004").json()["items"], [])
        self.assertNotIn("DEMO-E-004", str(first))

    def test_filter_cursor_skips_unassigned_and_off_stage_cases(self):
        self.set_review_stages()
        first = self.get(state="EVIDENCE_REVIEW_REQUESTED", limit=1).json()
        self.assertEqual(first["items"][0]["ref"], "DEMO-E-002")
        self.assertIsNone(first["next_cursor"])
        self.assertEqual(self.get(state="UNREQUESTED",
                                  after="DEMO-E-001").json()["items"], [])

    def test_queue_audits_only_disclosed_rows_in_atomic_transaction(self):
        self.set_review_stages()
        self.assertEqual(self.queue_audit(), [])
        r = self.get(state="HUMAN_RESPONSE_RECORDED")
        self.assertEqual(r.status_code, 200)
        entries = self.queue_audit()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].ref, "DEMO-E-003")
        self.assertEqual(entries[0].kind, "READ_ALLOWED")
        self.assertEqual(entries[0].engine, "EXPORT")
        self.assertTrue(self.reopen().verify_integrity())

    def test_revoke_removes_from_queue_even_with_old_signed_token(self):
        self.assertEqual(len(self.get().json()["items"]), 3)
        self.ledger.revoke_grant(
            engine="EXPORT", ref="DEMO-E-002",
            subject="synthetic-export-001", role="export_ops",
            actor="synthetic-controller", expected_grant_revision=0,
            action_id="DEMO-QUEUE-REVOKE-002", reason_ref="DEMO-QUEUE-REASON-002",
        )
        new_page = self.get().json()
        self.assertEqual([x["ref"] for x in new_page["items"]],
                         ["DEMO-E-001", "DEMO-E-003"])
        self.assertNotIn("DEMO-E-002", str(new_page))
        self.assertTrue(self.ledger.verify_integrity())

    def test_role_and_grant_not_interchangeable_and_no_cross_engine(self):
        for subject, roles in (
            ("synthetic-export-001", ("domestic_ops",)),
            ("synthetic-domestic-ops", ("domestic_ops",)),
            ("synthetic-household-1", ("household",)),
            ("synthetic-export-owner-1", ("export_ops",)),
        ):
            with self.subTest(subject=subject, roles=roles):
                r = self.get(subject=subject, roles=roles)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()["items"], [])
                self.assertIsNone(r.json()["next_cursor"])
        assigned_other = self.get(subject="synthetic-export-other")
        self.assertEqual([x["ref"] for x in assigned_other.json()["items"]],
                         ["DEMO-E-004"])

    def test_bad_filter_cursor_or_limit_yields_422_without_case_disclosure(self):
        for params in (
            {"technical_state": "APPROVED"},
            {"technical_state": "HUMAN_RESPONSE_RECORDED-BUSINESS"},
            {"after_ref": "not-demo"},
            {"limit": 0}, {"limit": 51},
        ):
            with self.subTest(params=params):
                r = self.client.get(API_ROUTE, params=params,
                                    headers=self.headers())
                self.assertEqual(r.status_code, 422)
                self.assertNotIn("DEMO-E-001", r.text)
        self.assertEqual(self.queue_audit(), [])

    def test_research_queue_has_no_private_source_review_or_owner_refs(self):
        self.set_review_stages()
        r = self.get(state="HUMAN_RESPONSE_RECORDED")
        self.assertEqual(r.status_code, 200)
        for fragment in (
            "DEMO-SOURCE-003", "DEMO-QUEUE-PRIVATE", "synthetic-export-owner",
            "synthetic-export-reviewer", "actor_digest", "decision_ref",
        ):
            self.assertNotIn(fragment, r.text)

    def test_missing_and_forged_bearer_are_denied_without_audit(self):
        self.assertEqual(self.client.get(API_ROUTE).status_code, 401)
        self.assertEqual(self.client.get(
            API_ROUTE, headers={"Authorization": "Bearer forged"},
        ).status_code, 401)
        self.assertEqual(self.queue_audit(), [])

    def test_forced_audit_insert_failure_returns_503_not_partial_page(self):
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER fail_research_queue BEFORE INSERT ON audit_event
                WHEN NEW.payload LIKE '%EXPORT_RESEARCH_CASE_QUEUE%'
                BEGIN SELECT RAISE(ABORT, 'queue audit failure'); END;
            """)
        r = self.get()
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"detail": "TECHNICAL_REVIEW_UNAVAILABLE"})
        self.assertNotIn("DEMO-E-001", r.text)
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER fail_research_queue")
        self.assertEqual(self.queue_audit(), [])
        self.assertEqual(self.get().status_code, 200)

    def test_modified_review_history_returns_sanitized_503(self):
        self.set_review_stages()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER review_no_update")
            db.execute("""UPDATE technical_review_step
                       SET request_ref='DEMO-FORGED'
                       WHERE engine='EXPORT' AND ref='DEMO-E-002'""")
        r = self.get()
        self.assertEqual(r.status_code, 503)
        self.assertNotIn("DEMO-E-002", r.text)

    def test_admin_ui_filters_link_to_authorized_case_detail(self):
        self.login()
        admin = self.client.get("/admin")
        self.assertEqual(admin.status_code, 200)
        self.assertIn("/admin/export/research", admin.text)
        page = self.client.get(UI_ROUTE)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('aria-label="فیلتر وضعیت فنی پژوهش"', page.text)
        self.assertIn("DEMO-E-001", page.text)
        self.assertNotIn("DEMO-E-004", page.text)
        self.assertIn("/admin/export/research/drafts/DEMO-E-001", page.text)
        self.assertIn("frame-ancestors 'none'",
                      page.headers["content-security-policy"])
        self.assertEqual(page.headers["cache-control"], "no-store")
        detail = self.client.get("/admin/export/research/drafts/DEMO-E-001")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("/admin/export/research", detail.text)

    def test_ui_filters_zero_state_and_invalid_filter_fail(self):
        self.login()
        self.set_review_stages()
        response = self.client.get(UI_ROUTE, params={
            "technical_state": "HUMAN_RESPONSE_RECORDED",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("DEMO-E-003", response.text)
        self.assertNotIn("DEMO-E-001", response.text)
        self.assertNotIn("DEMO-E-002", response.text)
        self.assertIn("حقوق منبع هنوز احراز نشده‌اند", response.text)
        bad = self.client.get(UI_ROUTE, params={"technical_state": "APPROVED"})
        self.assertEqual(bad.status_code, 422)
        self.assertNotIn("DEMO-E-003", bad.text)

    def test_ui_wrong_role_no_case_disclosure_and_logout(self):
        sid = self.login(subject="synthetic-domestic-ops", roles=("domestic_ops",))
        denied = self.client.get(UI_ROUTE)
        self.assertEqual(denied.status_code, 404)
        self.assertNotIn("DEMO-E-001", denied.text)
        self.store.revoke_session(sid)
        self.assertEqual(self.client.get(UI_ROUTE).status_code, 401)
        self.client.cookies.clear()
        sid = self.login()
        self.assertEqual(self.client.get(UI_ROUTE).status_code, 200)
        self.store.revoke_session(sid)
        self.assertEqual(self.client.get(UI_ROUTE).status_code, 401)

    def test_default_runtime_exposes_no_queue_and_no_public_writes(self):
        plain = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(plain.get(API_ROUTE, headers=self.headers()).status_code, 404)
        self.assertEqual(self.client.post(
            API_ROUTE, headers=self.headers(), json={"approved": True},
        ).status_code, 405)
        self.login()
        self.assertEqual(self.client.post(
            UI_ROUTE, json={"publish": True}
        ).status_code, 405)

    def test_concurrent_query_and_grant_revocation_obey_serial_order(self):
        barrier = Barrier(2)
        def read():
            ledger = self.reopen()
            client = self.client_for(ledger)
            barrier.wait(timeout=12)
            return self.get(client=client)
        def revoke():
            ledger = self.reopen()
            barrier.wait(timeout=12)
            return ledger.revoke_grant(
                engine="EXPORT", ref="DEMO-E-002",
                subject="synthetic-export-001", role="export_ops",
                actor="synthetic-controller", expected_grant_revision=0,
                action_id="DEMO-QUEUE-CONCURRENT-REVOKE",
                reason_ref="DEMO-QUEUE-CONCURRENT-REASON",
            )
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(read), pool.submit(revoke)
            response, event = first.result(), second.result()
        self.assertEqual(response.status_code, 200)
        self.assertIn(len(response.json()["items"]), (2, 3))
        self.assertEqual(event.kind, "GRANT_REVOKED")
        self.assertEqual([x["ref"] for x in self.get().json()["items"]],
                         ["DEMO-E-001", "DEMO-E-003"])
        self.assertTrue(self.reopen().verify_integrity())


    def version_api(self, ref="DEMO-E-001", *,
                    subject="synthetic-export-001", roles=("export_ops",),
                    client=None):
        return (client or self.client).get(
            "/api/v1/admin/export/research/drafts/" + ref + "/versions",
            headers=self.headers(subject, roles),
        )

    def versions_audit(self):
        return [
            event for event in self.ledger.audit_snapshot()
            if event.access_mode == "EXPORT_RESEARCH_VERSION_HISTORY"
        ]

    def test_exact_preseeded_version_history_is_scoped_not_inferred(self):
        response = self.version_api()
        self.assertEqual(response.status_code, 200, response.text)
        d = response.json()
        self.assertEqual(d["ref"], "DEMO-E-001")
        self.assertEqual(d["version_numbers"], [1, 2, 3])
        self.assertEqual(d["history_source"], "PRESEEDED_IMMUTABLE_FIXTURES")
        self.assertEqual(d["case_version"], 3)
        self.assertEqual(d["versions"], [
            {"version": 1, "is_current": False, "case_status": "DRAFT_ONLY"},
            {"version": 2, "is_current": False, "case_status": "DRAFT_ONLY"},
            {"version": 3, "is_current": True, "case_status": "DRAFT_ONLY"},
        ])
        for field in ("source_rights_verified", "research_report_approved",
                      "buyer_verified", "contracted", "real_data",
                      "business_actions_enabled"):
            self.assertIs(d[field], False)
        for secret in ("synthetic-export-owner", "synthetic-export-001",
                       "DEMO-SOURCE", "decision_ref", "evidence_ref",
                       "request_ref", "audit_sequence", "timestamp", "content"):
            self.assertNotIn(secret, response.text)
        self.assertEqual(len(self.versions_audit()), 1)
        self.assertEqual(self.versions_audit()[0].kind, "READ_ALLOWED")
        self.assertTrue(self.reopen().verify_integrity())

    def test_export_versions_independent_role_and_current_case_grant(self):
        for subject, roles, ref in (
            ("synthetic-export-001", ("household",), "DEMO-E-001"),
            ("synthetic-export-owner-1", ("export_ops",), "DEMO-E-001"),
            ("synthetic-domestic-ops", ("domestic_ops",), "DEMO-E-001"),
            ("synthetic-export-001", ("export_ops",), "DEMO-E-004"),
            ("synthetic-export-001", ("export_ops",), "DEMO-D-001"),
            ("synthetic-export-001", ("export_ops",), "DEMO-NOT-FOUND"),
            ("synthetic-export-001", ("export_ops",), "not-demo"),
        ):
            with self.subTest(subject=subject, ref=ref):
                response = self.version_api(ref, subject=subject, roles=roles)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("version_numbers", response.text)
                self.assertNotIn("DEMO-SOURCE", response.text)
        other = self.version_api("DEMO-E-004", subject="synthetic-export-other")
        self.assertEqual(other.status_code, 200)
        self.assertEqual(other.json()["version_numbers"], [1])

    def test_version_history_grant_revocation_is_immediate_with_signed_old_token(self):
        self.assertEqual(self.version_api().status_code, 200)
        self.ledger.revoke_grant(
            engine="EXPORT", ref="DEMO-E-001",
            subject="synthetic-export-001", role="export_ops",
            actor="synthetic-controller", expected_grant_revision=0,
            action_id="DEMO-VERSION-REVOKE", reason_ref="DEMO-VERSION-REASON",
        )
        denied = self.version_api()
        self.assertEqual(denied.status_code, 404)
        self.assertNotIn("version_numbers", denied.text)
        self.assertEqual([e.kind for e in self.versions_audit()],
                         ["READ_ALLOWED", "READ_DENIED"])
        self.assertEqual(self.version_api("DEMO-E-002").status_code, 200)
        self.assertTrue(self.reopen().verify_integrity())

    def test_version_history_fails_closed_when_audit_cannot_append(self):
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER fail_export_versions BEFORE INSERT ON audit_event
                WHEN NEW.payload LIKE '%EXPORT_RESEARCH_VERSION_HISTORY%'
                BEGIN SELECT RAISE(ABORT, 'version audit failure'); END;
            """)
        denied = self.version_api()
        self.assertEqual(denied.status_code, 503)
        self.assertEqual(denied.json(),
                         {"detail": "TECHNICAL_REVIEW_UNAVAILABLE"})
        self.assertNotIn("DEMO-E-001", denied.text)
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER fail_export_versions")
        self.assertEqual(self.versions_audit(), [])
        self.assertEqual(self.version_api().status_code, 200)

    def test_tampered_version_history_is_not_disclosed_in_api_or_html(self):
        self.login()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER case_history_no_delete")
            db.execute("""
                DELETE FROM case_history
                WHERE engine='EXPORT' AND ref='DEMO-E-001' AND version=2
            """)
        api = self.version_api()
        self.assertEqual(api.status_code, 503)
        self.assertNotIn("version_numbers", api.text)
        page = self.client.get(
            "/admin/export/research/drafts/DEMO-E-001/versions"
        )
        self.assertEqual(page.status_code, 503)
        self.assertNotIn("نسخه پیشین DEMO", page.text)

    def test_versions_http_requires_verified_session_and_get_only(self):
        url = "/api/v1/admin/export/research/drafts/DEMO-E-001/versions"
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(
            url, headers={"Authorization": "Bearer forged"}
        ).status_code, 401)
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual(getattr(self.client, method)(
                url, headers=self.headers(),
            ).status_code, 405)
        unmounted = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(unmounted.get(url, headers=self.headers()).status_code,
                         404)
        self.assertEqual(self.versions_audit(), [])

    def test_filtered_research_queue_preserves_navigation_context_in_detail(self):
        self.login()
        self.set_review_stages()
        query = {
            "technical_state": "EVIDENCE_REVIEW_REQUESTED",
            "after_ref": "DEMO-E-001",
        }
        page = self.client.get(UI_ROUTE, params=query)
        self.assertEqual(page.status_code, 200, page.text)
        link = ("/admin/export/research/drafts/DEMO-E-002?"
                "technical_state=EVIDENCE_REVIEW_REQUESTED&after_ref=DEMO-E-001")
        self.assertIn(link.replace("&", "&amp;") if "&amp;" in page.text else link,
                      page.text)
        detail = self.client.get(link)
        self.assertEqual(detail.status_code, 200)
        self.assertIn("درخواست بررسی فنی ثبت‌شده", detail.text)
        self.assertIn(
            "/admin/export/research/drafts/DEMO-E-002/versions?"
            "technical_state=EVIDENCE_REVIEW_REQUESTED&after_ref=DEMO-E-001",
            detail.text,
        )
        self.assertIn(
            "/admin/export/research?technical_state=EVIDENCE_REVIEW_REQUESTED"
            "&after_ref=DEMO-E-001", detail.text,
        )
        self.assertNotIn("DEMO-QUEUE-PRIVATE", detail.text)
        history = self.client.get(
            "/admin/export/research/drafts/DEMO-E-002/versions", params=query
        )
        self.assertEqual(history.status_code, 200)
        self.assertIn("نسخه 2", history.text)
        self.assertIn("بازگشت به جزئیات پرونده", history.text)
        self.assertIn("بازگشت به فهرست فیلترشده", history.text)
        self.assertEqual(history.headers["cache-control"], "no-store")

    def test_version_page_uses_only_preseeded_versions_not_source_or_review_data(self):
        self.login()
        self.set_review_stages()
        page = self.client.get(
            "/admin/export/research/drafts/DEMO-E-001/versions"
        )
        self.assertEqual(page.status_code, 200, page.text)
        for label in ("نسخه 1", "نسخه 2", "نسخه 3", "نسخه پیشین DEMO",
                      "نسخه فعلی DEMO", "DRAFT_ONLY", "مجوز استفاده از منبع"):
            self.assertIn(label, page.text)
        for secret in ("DEMO-SOURCE", "synthetic-export",
                       "DEMO-QUEUE-PRIVATE", "decision_ref", "timestamp"):
            self.assertNotIn(secret, page.text)
        self.assertIn("frame-ancestors 'none'",
                      page.headers["content-security-policy"])
        self.assertTrue(self.reopen().verify_integrity())

    def test_version_page_rechecks_session_and_revoked_case(self):
        sid = self.login()
        self.assertEqual(self.client.get(
            "/admin/export/research/drafts/DEMO-E-001/versions"
        ).status_code, 200)
        self.ledger.revoke_grant(
            engine="EXPORT", ref="DEMO-E-001",
            subject="synthetic-export-001", role="export_ops",
            actor="synthetic-controller", expected_grant_revision=0,
            action_id="DEMO-HISTORY-REVOCATION", reason_ref="DEMO-HISTORY-REASON",
        )
        self.assertEqual(self.client.get(
            "/admin/export/research/drafts/DEMO-E-001/versions"
        ).status_code, 404)
        self.store.revoke_session(sid)
        self.assertEqual(self.client.get(
            "/admin/export/research/drafts/DEMO-E-001/versions"
        ).status_code, 401)

    def test_invalid_navigation_query_does_not_bypass_export_case_grants(self):
        self.login()
        for params in (
            {"technical_state": "APPROVED"},
            {"technical_state": "HUMAN_RESPONSE_RECORDED-BUSINESS"},
            {"after_ref": "not-demo"},
        ):
            with self.subTest(params=params):
                response = self.client.get(
                    "/admin/export/research/drafts/DEMO-E-001",
                    params=params,
                )
                self.assertEqual(response.status_code, 422)
                self.assertNotIn("DEMO-SOURCE-001", response.text)
        wrong = self.client.get(
            "/admin/export/research/drafts/DEMO-E-004/versions"
        )
        self.assertEqual(wrong.status_code, 404)
        self.assertNotIn("version_numbers", wrong.text)

    def test_version_history_and_grant_revocation_audits_are_serial(self):
        barrier = Barrier(2)
        def reader():
            ledger = self.reopen()
            client = self.client_for(ledger)
            barrier.wait(timeout=12)
            return self.version_api(client=client)
        def revoke():
            ledger = self.reopen()
            barrier.wait(timeout=12)
            return ledger.revoke_grant(
                engine="EXPORT", ref="DEMO-E-001",
                subject="synthetic-export-001", role="export_ops",
                actor="synthetic-controller", expected_grant_revision=0,
                action_id="DEMO-HISTORY-CONCURRENT-REVOKE",
                reason_ref="DEMO-HISTORY-CONCURRENT-REASON",
            )
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(reader), pool.submit(revoke)
            response, event = a.result(), b.result()
        self.assertIn(response.status_code, (200, 404))
        self.assertEqual(event.kind, "GRANT_REVOKED")
        self.assertEqual(self.version_api().status_code, 404)
        self.assertTrue(self.reopen().verify_integrity())


if __name__ == "__main__":
    unittest.main()
