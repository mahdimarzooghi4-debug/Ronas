"""Owner-facing synthetic technical progress (no reviewer or evidence disclosure)."""
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
from ronas_api.human_review_sqlite import SqliteSyntheticHumanReviewLedger
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant

ISS = "https://id.example.test/realms/ronas"
API, WEB = "ronas-api", "ronas-web"
ORIGIN = "https://ronas.example.test"
OWN = "/api/v1/domestic/household-intake/my-drafts"
STATUS = OWN + "/DEMO-D-001/technical-status"
PROGRESS = OWN + "/technical-progress"
DETAIL = "/my-drafts/DEMO-D-001"


def records():
    return (
        ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-one", 3, (
            ScopedGrant("synthetic-domestic-requester", "domestic_ops"),
            ScopedGrant("synthetic-domestic-reviewer", "domestic_ops"),
        )),
        ScopedDraft("DEMO-D-002", "DOMESTIC", "synthetic-household-two", 2, (
            ScopedGrant("synthetic-domestic-requester", "domestic_ops"),
        )),
        ScopedDraft("DEMO-D-003", "DOMESTIC", "synthetic-household-one", 1, (
            ScopedGrant("synthetic-domestic-requester", "domestic_ops"),
        )),
        ScopedDraft("DEMO-E-001", "EXPORT", "synthetic-household-one", 1, (
            ScopedGrant("synthetic-export-requester", "export_ops"),
        ), source_ref="DEMO-SOURCE"),
    )


class HouseholdProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "status-key", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "review.db"
        self.ledger = self.reopen()
        self.client = TestClient(create_app(
            self.config, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
        ), base_url=ORIGIN)

    def reopen(self):
        return SqliteSyntheticHumanReviewLedger(
            self.path, records(),
            trusted_revoke_authorizer=lambda actor, engine, ref: actor == "synthetic-controller",
            trusted_human_review_authorizer=lambda actor, engine, ref: (
                actor == "synthetic-domestic-reviewer"
                and engine == "DOMESTIC" and ref == "DEMO-D-001"
            ),
        )

    def headers(self, subject="synthetic-household-one", roles=("household",)):
        now = int(time.time())
        signed = jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "sub": subject,
            "typ": "Bearer", "iat": now - 5, "nbf": now - 5, "exp": now + 500,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "status-key"})
        return {"Authorization": "Bearer " + signed}

    def browser(self, *, subject="synthetic-household-one", roles=("household",),
                review_enabled=True, ledger=None):
        ledger = ledger or self.ledger
        class Store:
            def __init__(self):
                self.items = {}
            def get_session(self, sid):
                return self.items.get(sid)
            def revoke_session(self, sid):
                self.items.pop(sid, None)

        store = Store()
        async def no_exchange(_code, _verifier):
            raise AssertionError("external identity provider not permitted")
        flow = BrowserOIDC(BrowserOIDCConfig(
            self.config, ORIGIN + "/api/auth/callback",
        ), store, no_exchange)
        sid = secrets.token_urlsafe(36)
        signed = self.headers(subject, roles)["Authorization"][7:]
        store.items[sid] = BrowserSession(
            subject, frozenset(roles), signed, secrets.token_urlsafe(32),
            int(time.time()) + 200,
        )
        kwargs = {
            "scoped_registry": ledger,
        }
        if review_enabled:
            kwargs["technical_review_ledger"] = ledger
        client = TestClient(create_app(
            self.config, flow, **kwargs,
        ), base_url=ORIGIN)
        client.cookies.set("__Host-ronas_session", sid)
        return client, store, sid

    def request(self, ledger=None):
        return (ledger or self.ledger).request_evidence_review(
            engine="DOMESTIC", ref="DEMO-D-001",
            actor=Principal("synthetic-domestic-requester",
                            frozenset({"domestic_ops"})),
            expected_case_version=3, expected_review_revision=0,
            action_id="DEMO-ACTION-REQUEST",
            request_ref="DEMO-PRIVATE-REQUEST",
            evidence_ref="DEMO-PRIVATE-EVIDENCE",
        )

    def respond(self, ledger=None):
        return (ledger or self.ledger).record_human_response(
            engine="DOMESTIC", ref="DEMO-D-001",
            actor=Principal("synthetic-domestic-reviewer",
                            frozenset({"domestic_ops"})),
            expected_case_version=3, expected_review_revision=1,
            action_id="DEMO-ACTION-RESPONSE",
            request_ref="DEMO-PRIVATE-REQUEST",
            evidence_ref="DEMO-PRIVATE-RESPONSE-EVIDENCE",
            decision_ref="DEMO-PRIVATE-HUMAN-NOTE",
        )

    def test_three_technical_states_visible_without_private_review_lineage(self):
        for expected_state, transition in (
            ("UNREQUESTED", None),
            ("EVIDENCE_REVIEW_REQUESTED", self.request),
            ("HUMAN_RESPONSE_RECORDED", self.respond),
        ):
            if transition:
                transition()
            response = self.client.get(STATUS, headers=self.headers())
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(data["technical_review_state"], expected_state)
            self.assertEqual(data["status"], "DRAFT_ONLY")
            self.assertFalse(data["purpose_consent_verified"])
            self.assertFalse(data["expert_approved"])
            self.assertFalse(data["plan_accepted"])
            self.assertFalse(data["real_data"])
            self.assertEqual(data["ref"], "DEMO-D-001")
            self.assertEqual(data["version"], 3)
            for secret in ("DEMO-PRIVATE-REQUEST", "DEMO-PRIVATE-EVIDENCE",
                           "DEMO-PRIVATE-RESPONSE-EVIDENCE", "DEMO-PRIVATE-HUMAN-NOTE",
                           "synthetic-domestic-reviewer"):
                self.assertNotIn(secret, response.text)
            for forbidden in ("history", "actor_digest", "decision_ref",
                              "evidence_ref", "request_ref", "audit_sequence"):
                self.assertNotIn(forbidden, data)
        reads = [e for e in self.ledger.audit_snapshot()
                 if e.access_mode == "HOUSEHOLD_TECHNICAL_STATUS"]
        self.assertEqual(len(reads), 3)
        self.assertEqual([e.kind for e in reads], ["READ_ALLOWED"] * 3)
        self.assertTrue(self.reopen().verify_integrity())

    def test_no_token_bad_token_or_header_spoof_denied_before_audit(self):
        for headers in ({}, {"Authorization": "Bearer bad"}, {"X-Role": "household"},
                        self.headers("synthetic-household-one", ("finance",))):
            with self.subTest(headers=headers):
                response = self.client.get(STATUS, headers=headers)
                if "Authorization" not in headers:
                    self.assertEqual(response.status_code, 401)
                elif headers["Authorization"] == "Bearer bad":
                    self.assertEqual(response.status_code, 401)
                else:
                    self.assertEqual(response.status_code, 404)
        self.assertFalse(any(e.access_mode == "HOUSEHOLD_TECHNICAL_STATUS"
                             and e.kind == "READ_ALLOWED"
                             for e in self.ledger.audit_snapshot()))

    def test_other_owner_unassigned_staff_and_export_are_indistinguishable(self):
        requests = [
            (STATUS, "synthetic-household-two", ("household",)),
            (STATUS, "synthetic-domestic-requester", ("domestic_ops",)),
            (OWN + "/DEMO-D-002/technical-status", "synthetic-household-one", ("household",)),
            (OWN + "/DEMO-E-001/technical-status", "synthetic-household-one", ("household",)),
            (OWN + "/DEMO-UNKNOWN/technical-status", "synthetic-household-one", ("household",)),
        ]
        for path, subject, roles in requests:
            with self.subTest(path=path, subject=subject):
                response = self.client.get(path, headers=self.headers(subject, roles))
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "DRAFT_NOT_FOUND"})
                self.assertNotIn("DEMO-PRIVATE", response.text)
        allowed = self.client.get(
            OWN + "/DEMO-D-002/technical-status",
            headers=self.headers("synthetic-household-two"),
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["ref"], "DEMO-D-002")

    def test_staff_grant_revoked_does_not_revoke_household_self_status(self):
        self.request()
        self.ledger.revoke_grant(
            engine="DOMESTIC", ref="DEMO-D-001",
            subject="synthetic-domestic-requester", role="domestic_ops",
            actor="synthetic-controller", expected_grant_revision=0,
            action_id="DEMO-REVOKE-STAFF", reason_ref="DEMO-REASON",
        )
        response = self.client.get(STATUS, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["technical_review_state"],
                         "EVIDENCE_REVIEW_REQUESTED")
        self.assertEqual(response.json()["status"], "DRAFT_ONLY")
        self.assertTrue(self.reopen().verify_integrity())

    def test_review_history_corruption_blocks_api_without_evidence_leak(self):
        self.request()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER review_no_update")
            db.execute("UPDATE technical_review_step SET request_ref='DEMO-FORGED'")
        response = self.client.get(STATUS, headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "SYNTHETIC_LEDGER_UNAVAILABLE"})
        self.assertNotIn("DEMO-FORGED", response.text)

    def test_failed_audit_append_rolls_back_owner_status_read(self):
        self.request()
        before = self.ledger.audit_snapshot()
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER deny_owner_status BEFORE INSERT ON audit_event
                WHEN NEW.payload LIKE '%HOUSEHOLD_TECHNICAL_STATUS%'
                BEGIN SELECT RAISE(ABORT, 'audit failure'); END;
            """)
        response = self.client.get(STATUS, headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("DEMO-PRIVATE", response.text)
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER deny_owner_status")
        self.assertEqual(self.reopen().audit_snapshot(), before)
        self.assertEqual(self.client.get(STATUS, headers=self.headers()).status_code, 200)

    def test_default_plain_and_base_grant_ledgers_do_not_mount_status(self):
        plain = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(plain.get(STATUS, headers=self.headers()).status_code, 404)
        from ronas_api.grant_ledger_sqlite import SqliteSyntheticGrantLedger
        base_path = self.path.parent / "base.db"
        base_ledger = SqliteSyntheticGrantLedger(
            base_path, records(),
            trusted_revoke_authorizer=lambda a, e, r: False,
        )
        base = TestClient(create_app(
            self.config, scoped_registry=base_ledger,
        ), base_url=ORIGIN)
        self.assertEqual(base.get(STATUS, headers=self.headers()).status_code, 404)
        self.assertEqual(base.get(OWN, headers=self.headers()).status_code, 200)
        scoped_only = TestClient(create_app(
            self.config, scoped_registry=self.ledger,
        ), base_url=ORIGIN)
        # Review-aware ledger itself explicitly supplies the internal facade;
        # no untrusted caller can construct a Principal via this HTTP route.
        self.assertEqual(scoped_only.get(STATUS, headers=self.headers()).status_code, 200)
        self.assertEqual(self.client.post(
            STATUS, headers=self.headers(), json={"approve": True},
        ).status_code, 405)

    def test_browser_detail_and_link_are_in_existing_shared_user_shell(self):
        client, _, _ = self.browser()
        listing = client.get("/")
        self.assertEqual(listing.status_code, 200)
        self.assertIn("/my-drafts/DEMO-D-001", listing.text)
        self.assertNotIn("/api/v1/domestic/household-intake/drafts/DEMO-D-001\">",
                         listing.text)
        detail = client.get(DETAIL)
        self.assertEqual(detail.status_code, 200)
        self.assertIn("DEMO-D-001", detail.text)
        self.assertIn("DRAFT_ONLY", detail.text)
        self.assertIn("درخواستی برای بررسی فنی ثبت نشده", detail.text)
        self.assertIn("رضایت واقعی احراز نشده", detail.text)
        self.assertIn("frame-ancestors 'none'", detail.headers["content-security-policy"])
        self.assertEqual(detail.headers["cache-control"], "no-store")
        self.assertNotIn("id_token", detail.text)
        self.assertTrue(self.reopen().verify_integrity())

    def test_browser_detail_updates_after_review_without_exposing_response(self):
        client, _, _ = self.browser()
        self.request()
        requested = client.get(DETAIL)
        self.assertEqual(requested.status_code, 200)
        self.assertIn("درخواست بررسی شواهد ثبت شده", requested.text)
        self.respond()
        completed = client.get(DETAIL)
        self.assertEqual(completed.status_code, 200)
        self.assertIn("مرجع پاسخ انسانی ثبت شده", completed.text)
        self.assertIn("تأیید پرونده نیست", completed.text)
        self.assertIn("DRAFT_ONLY", completed.text)
        self.assertNotIn("DEMO-PRIVATE-HUMAN-NOTE", completed.text)
        self.assertNotIn("DEMO-PRIVATE-EVIDENCE", completed.text)
        self.assertNotIn("synthetic-domestic-reviewer", completed.text)

    def test_cross_household_staff_and_export_detail_are_denied(self):
        for subject, roles, path in (
            ("synthetic-household-two", ("household",), DETAIL),
            ("synthetic-domestic-requester", ("domestic_ops",), DETAIL),
            ("synthetic-household-one", ("household",), "/my-drafts/DEMO-E-001"),
            ("synthetic-household-one", ("household",), "/my-drafts/DEMO-UNKNOWN"),
        ):
            with self.subTest(subject=subject, path=path):
                client, _, _ = self.browser(subject=subject, roles=roles)
                r = client.get(path)
                self.assertEqual(r.status_code, 404)
                self.assertNotIn("DEMO-PRIVATE", r.text)

    def test_logout_invalidates_detail_without_review_audit_side_effect(self):
        client, store, sid = self.browser()
        self.assertEqual(client.get(DETAIL).status_code, 200)
        before = len(self.ledger.audit_snapshot())
        store.revoke_session(sid)
        response = client.get(DETAIL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(self.ledger.audit_snapshot()), before)

    def test_html_detail_is_unmounted_for_base_ledger_or_missing_review_wiring(self):
        client, _, _ = self.browser(review_enabled=False)
        self.assertEqual(client.get(DETAIL).status_code, 404)
        html = client.get("/").text
        # A simple owner ledger may expose its own version history,
        # but may not claim to mount the review-only detail page.
        self.assertNotIn('href="/my-drafts/DEMO-D-001"', html)
        self.assertIn('href="/my-drafts/DEMO-D-001/versions"', html)

    def test_concurrent_status_read_and_human_response_preserves_linearized_progress(self):
        self.request()
        barrier = Barrier(2)

        def read():
            ledger = self.reopen()
            client = TestClient(create_app(
                self.config, scoped_registry=ledger,
                technical_review_ledger=ledger,
            ), base_url=ORIGIN)
            barrier.wait(timeout=12)
            return client.get(STATUS, headers=self.headers())

        def respond():
            ledger = self.reopen()
            barrier.wait(timeout=12)
            return self.respond(ledger)

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(read)
            b = pool.submit(respond)
            result, event = a.result(), b.result()
        self.assertEqual(result.status_code, 200)
        self.assertIn(result.json()["technical_review_state"],
                      ("EVIDENCE_REVIEW_REQUESTED", "HUMAN_RESPONSE_RECORDED"))
        events = self.reopen().audit_snapshot()
        owner_read = next(e for e in events if e.access_mode == "HOUSEHOLD_TECHNICAL_STATUS")
        if result.json()["technical_review_state"] == "HUMAN_RESPONSE_RECORDED":
            self.assertGreater(owner_read.sequence, event.audit_sequence)
        else:
            self.assertLess(owner_read.sequence, event.audit_sequence)
        self.assertEqual(self.client.get(STATUS, headers=self.headers()).json()[
            "technical_review_state"], "HUMAN_RESPONSE_RECORDED")
        self.assertTrue(self.reopen().verify_integrity())


    def test_progress_filters_only_own_observed_technical_states(self):
        def read(state, *, subject="synthetic-household-one",
                 roles=("household",)):
            return self.client.get(
                PROGRESS, params={"technical_state": state},
                headers=self.headers(subject, roles),
            )
        initial = read("UNREQUESTED")
        self.assertEqual(initial.status_code, 200)
        self.assertEqual([r["ref"] for r in initial.json()["items"]],
                         ["DEMO-D-001", "DEMO-D-003"])
        self.assertEqual(initial.json()["technical_state_filter"], "UNREQUESTED")
        self.assertNotIn("DEMO-D-002", initial.text)
        self.assertNotIn("DEMO-E-001", initial.text)
        self.assertNotIn("owner_subject", initial.text)
        self.assertEqual(read("EVIDENCE_REVIEW_REQUESTED").json()["items"], [])
        self.request()
        self.assertEqual(
            [r["ref"] for r in read("UNREQUESTED").json()["items"]],
            ["DEMO-D-003"],
        )
        self.assertEqual(
            [r["ref"] for r in read("EVIDENCE_REVIEW_REQUESTED").json()["items"]],
            ["DEMO-D-001"],
        )
        self.respond()
        self.assertEqual(read("EVIDENCE_REVIEW_REQUESTED").json()["items"], [])
        done = read("HUMAN_RESPONSE_RECORDED")
        self.assertEqual([r["ref"] for r in done.json()["items"]],
                         ["DEMO-D-001"])
        self.assertEqual(done.json()["items"][0]["technical_review_state"],
                         "HUMAN_RESPONSE_RECORDED")
        self.assertFalse(done.json()["items"][0]["plan_accepted"])
        self.assertFalse(done.json()["items"][0]["expert_approved"])
        self.assertNotIn("DEMO-PRIVATE", done.text)
        self.assertEqual(
            [r["ref"] for r in read("ALL").json()["items"]],
            ["DEMO-D-001", "DEMO-D-003"],
        )
        self.assertEqual(
            [r["ref"] for r in read("ALL", subject="synthetic-household-two").json()["items"]],
            ["DEMO-D-002"],
        )
        self.assertTrue(self.reopen().verify_integrity())

    def test_filtered_owner_keyset_cursor_excludes_other_household(self):
        first = self.client.get(
            PROGRESS, params={"technical_state": "UNREQUESTED", "limit": 1},
            headers=self.headers(),
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual([item["ref"] for item in first.json()["items"]],
                         ["DEMO-D-001"])
        self.assertEqual(first.json()["next_cursor"], "DEMO-D-001")
        self.assertNotIn("total", first.json())
        other = self.client.get(
            PROGRESS, params={
                "technical_state": "UNREQUESTED", "after_ref": "DEMO-D-001",
                "limit": 1,
            }, headers=self.headers(),
        )
        self.assertEqual([item["ref"] for item in other.json()["items"]],
                         ["DEMO-D-003"])
        self.assertIsNone(other.json()["next_cursor"])
        audited = [e.ref for e in self.ledger.audit_snapshot()
                   if e.access_mode == "HOUSEHOLD_PROGRESS_WORKLIST"]
        self.assertEqual(audited, ["DEMO-D-001", "DEMO-D-003"])
        self.request()
        after = self.client.get(
            PROGRESS, params={"technical_state": "UNREQUESTED", "limit": 1},
            headers=self.headers(),
        )
        self.assertEqual([item["ref"] for item in after.json()["items"]],
                         ["DEMO-D-003"])
        self.assertIsNone(after.json()["next_cursor"])

    def test_progress_pages_keep_first_page_review_state_watermark(self):
        first = self.client.get(
            PROGRESS, params={"technical_state": "UNREQUESTED", "limit": 1},
            headers=self.headers(),
        )
        self.assertEqual(first.status_code, 200, first.text)
        snapshot = first.json()["snapshot_sequence"]
        self.assertIsInstance(snapshot, int)
        self.assertEqual(first.json()["next_cursor"], "DEMO-D-001")

        self.ledger.request_evidence_review(
            engine="DOMESTIC", ref="DEMO-D-003",
            actor=Principal("synthetic-domestic-requester",
                            frozenset({"domestic_ops"})),
            expected_case_version=1, expected_review_revision=0,
            action_id="DEMO-D003-REQUEST-AFTER-SNAPSHOT",
            request_ref="DEMO-PRIVATE-D003-REQUEST",
            evidence_ref="DEMO-PRIVATE-D003-EVIDENCE",
        )
        stable_page = self.client.get(
            PROGRESS, params={
                "technical_state": "UNREQUESTED", "after_ref": "DEMO-D-001",
                "limit": 1, "snapshot_sequence": snapshot,
            }, headers=self.headers(),
        )
        self.assertEqual(stable_page.status_code, 200, stable_page.text)
        self.assertEqual([item["ref"] for item in stable_page.json()["items"]],
                         ["DEMO-D-003"])
        self.assertEqual(stable_page.json()["snapshot_sequence"], snapshot)
        fresh_page = self.client.get(
            PROGRESS, params={
                "technical_state": "UNREQUESTED", "after_ref": "DEMO-D-001",
                "limit": 1,
            }, headers=self.headers(),
        )
        self.assertEqual(fresh_page.status_code, 200, fresh_page.text)
        self.assertEqual(fresh_page.json()["items"], [])
        self.assertTrue(self.reopen().verify_integrity())

    def test_future_snapshot_is_rejected_without_partial_page_audit(self):
        before = len(self.ledger.audit_snapshot())
        events = self.ledger.audit_snapshot()
        latest = events[-1].sequence if events else 0
        response = self.client.get(
            PROGRESS, params={"snapshot_sequence": latest + 1},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(len(self.ledger.audit_snapshot()), before)

    def test_household_browser_next_page_link_carries_snapshot_watermark(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        more = tuple(
            ScopedDraft(f"DEMO-D-{number:03}", "DOMESTIC",
                        "synthetic-household-one", 1, ())
            for number in range(4, 26)
        )
        ledger = SqliteSyntheticHumanReviewLedger(
            Path(temp.name) / "many.db", (*records(), *more),
            trusted_revoke_authorizer=lambda *_: False,
            trusted_human_review_authorizer=lambda *_: False,
        )
        client, _, _ = self.browser(ledger=ledger)
        home = client.get("/")
        self.assertEqual(home.status_code, 200, home.text)
        self.assertRegex(
            home.text,
            r'href="/\?household_technical_state=ALL&household_after_ref='
            r'DEMO-D-021&household_snapshot_sequence=[0-9]+">پرونده‌های بعدی</a>',
        )

    def test_invalid_owner_filter_and_cursor_do_not_read_audit(self):
        original = len(self.ledger.audit_snapshot())
        for params in ({"technical_state": "APPROVED"},
                       {"technical_state": "human_response_recorded"},
                       {"technical_state": ""},
                       {"after_ref": "D-001"},
                       {"limit": 0},
                       {"limit": 51}):
            with self.subTest(params=params):
                r = self.client.get(
                    PROGRESS, params=params, headers=self.headers(),
                )
                self.assertEqual(r.status_code, 422)
                self.assertNotIn("DEMO-D-001", r.text)
        self.assertEqual(len(self.ledger.audit_snapshot()), original)

    def test_owner_filter_role_is_independent_of_domestic_staff(self):
        for subject, roles in (
            ("synthetic-domestic-requester", ("domestic_ops",)),
            ("synthetic-household-one", ("finance",)),
            ("synthetic-no-household", ("household",)),
            ("synthetic-export-requester", ("export_ops",)),
        ):
            r = self.client.get(
                PROGRESS, params={"technical_state": "ALL"},
                headers=self.headers(subject, roles),
            )
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["items"], [])
            self.assertIsNone(r.json()["next_cursor"])
        self.assertEqual(
            self.client.get(PROGRESS).status_code, 401,
        )
        self.assertEqual(
            self.client.get(
                PROGRESS, headers={"Authorization": "Bearer forged"},
            ).status_code, 401,
        )
        reads = [x for x in self.ledger.audit_snapshot()
                 if x.access_mode == "HOUSEHOLD_PROGRESS_WORKLIST"]
        self.assertEqual(reads, [])

    def test_filtered_progress_failed_audit_returns_503_without_partial_page(self):
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER fail_filtered_owner BEFORE INSERT ON audit_event
                WHEN NEW.payload LIKE '%HOUSEHOLD_PROGRESS_WORKLIST%'
                BEGIN SELECT RAISE(ABORT, 'no filtered owner audit'); END;
            """)
        failed = self.client.get(
            PROGRESS, params={"technical_state": "UNREQUESTED"},
            headers=self.headers(),
        )
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn("DEMO-D-001", failed.text)
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER fail_filtered_owner")
        self.assertEqual(self.ledger.audit_snapshot(), ())
        self.assertEqual(self.client.get(
            PROGRESS, headers=self.headers(),
        ).status_code, 200)

    def test_filtered_progress_corrupted_review_history_is_503(self):
        self.request()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER review_no_update")
            db.execute("""
                UPDATE technical_review_step SET request_ref='DEMO-FORGED'
                WHERE engine='DOMESTIC' AND ref='DEMO-D-001'
            """)
        filtered = self.client.get(
            PROGRESS, params={"technical_state": "EVIDENCE_REVIEW_REQUESTED"},
            headers=self.headers(),
        )
        self.assertEqual(filtered.status_code, 503)
        self.assertNotIn("DEMO-FORGED", filtered.text)

    def test_household_rtl_filter_is_visible_only_in_review_aware_shell(self):
        client, _, _ = self.browser()
        home = client.get("/?household_technical_state=UNREQUESTED")
        self.assertEqual(home.status_code, 200)
        self.assertIn('aria-label="فیلتر پیگیری پرونده‌های خانوار"', home.text)
        self.assertIn("DEMO-D-001", home.text)
        self.assertIn("DEMO-D-003", home.text)
        self.assertNotIn("DEMO-D-002", home.text)
        self.assertIn("پاسخ انسانی به معنی تأیید طرح کشت نیست", home.text)
        self.request()
        requested = client.get(
            "/?household_technical_state=EVIDENCE_REVIEW_REQUESTED"
        )
        self.assertEqual(requested.status_code, 200)
        self.assertIn("/my-drafts/DEMO-D-001", requested.text)
        self.assertNotIn("/my-drafts/DEMO-D-003", requested.text)
        self.assertNotIn("DEMO-PRIVATE", requested.text)
        empty = client.get("/?household_technical_state=HUMAN_RESPONSE_RECORDED")
        self.assertEqual(empty.status_code, 200)
        self.assertIn("در این فیلتر", empty.text)
        self.assertEqual(client.get(
            "/?household_technical_state=APPROVED",
        ).status_code, 422)
        simple, _, _ = self.browser(review_enabled=False)
        self.assertEqual(simple.get(
            "/?household_technical_state=UNREQUESTED",
        ).status_code, 422)
        self.assertNotIn(
            'aria-label="فیلتر پیگیری پرونده‌های خانوار"',
            simple.get("/").text,
        )

    def test_household_status_detail_preserves_no_scientific_approval_after_filter(self):
        self.request()
        client, _, _ = self.browser()
        listing = client.get("/?household_technical_state=EVIDENCE_REVIEW_REQUESTED")
        self.assertEqual(listing.status_code, 200)
        self.assertIn('/my-drafts/DEMO-D-001', listing.text)
        self.assertIn('/my-drafts/DEMO-D-001/versions', listing.text)
        detail = client.get(DETAIL)
        self.assertIn("سابقه پیگیری فنی", detail.text)
        self.assertIn("تأیید علمی", detail.text)
        self.assertIn("هیچ تصمیم تجاری", detail.text)
        self.assertEqual(detail.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
