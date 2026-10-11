"""Signed LOCAL/TEST synthetic household manifest revisions — no real consent."""
from concurrent.futures import ThreadPoolExecutor
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
from ronas_api.grant_ledger_sqlite import LedgerIntegrityError
from ronas_api.household_input_ledger_sqlite import (
    SqliteSyntheticHouseholdInputLedger, InputRevisionConflict,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant

ISS = "https://id.example.test/realms/ronas"
API, WEB, ORIGIN = "ronas-api", "ronas-web", "https://ronas.example.test"
ROOT = "/api/v1/domestic/household-intake/my-drafts/DEMO-D-1/input-revisions"
HTML = "/my-drafts/DEMO-D-1/input-revisions"
OWNER = "synthetic-household-one"
DIGEST1 = "1" * 64
DIGEST2 = "2" * 64


def records():
    return (
        ScopedDraft("DEMO-D-1", "DOMESTIC", OWNER, 3, (
            ScopedGrant("synthetic-domestic-ops", "domestic_ops"),
        )),
        ScopedDraft("DEMO-D-2", "DOMESTIC", "synthetic-household-other", 1, ()),
        ScopedDraft("DEMO-E-1", "EXPORT", OWNER, 1, (
            ScopedGrant("synthetic-export-ops", "export_ops"),
        ), source_ref="DEMO-SRC-1"),
    )


class Sessions:
    def __init__(self):
        self.sessions = {}

    def get_session(self, sid):
        return self.sessions.get(sid)

    def revoke_session(self, sid):
        self.sessions.pop(sid, None)


class SyntheticHouseholdInputLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        public.update({"kid": "household-input", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [public]}).encode())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "household.db"
        self.ledger = self.reopen()
        self.sessions = Sessions()

        async def no_exchange(code, verifier):
            raise AssertionError("no external identity calls in local test")

        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.sessions, no_exchange,
        )
        self.client = self.client_for()

    def reopen(self):
        return SqliteSyntheticHouseholdInputLedger(
            self.path, records(),
            trusted_revoke_authorizer=lambda *_: False,
            trusted_human_review_authorizer=lambda *_: False,
        )

    def client_for(self, ledger=None, browser=True):
        ledger = self.ledger if ledger is None else ledger
        return TestClient(create_app(
            self.config, self.flow if browser else None,
            scoped_registry=ledger, technical_review_ledger=ledger,
        ), base_url=ORIGIN)

    def signed(self, subject=OWNER, roles=("household",), expired=False):
        now = int(time.time())
        return jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "typ": "Bearer",
            "sub": subject, "iat": now - 5, "nbf": now - 5,
            "exp": now - 5 if expired else now + 500,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "household-input"})

    def headers(self, subject=OWNER, roles=("household",)):
        return {"Authorization": "Bearer " + self.signed(subject, roles)}

    def command(self, revision=0, digest=DIGEST1, action="DEMO-INPUT-A"):
        return {
            "action_id": action, "expected_case_version": 3,
            "expected_input_revision": revision,
            "synthetic_manifest_digest": digest,
        }

    def browser(self, subject=OWNER, roles=("household",)):
        sid = secrets.token_urlsafe(40)
        self.sessions.sessions[sid] = BrowserSession(
            subject, frozenset(roles), self.signed(subject, roles),
            secrets.token_urlsafe(32), int(time.time()) + 200,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        return sid

    def test_initial_owner_history_is_empty_and_no_fake_consent(self):
        res = self.client.get(ROOT, headers=self.headers())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["input_revisions"], [])
        self.assertIsNone(res.json()["current_input_revision"])
        self.assertEqual(res.json()["input_state"], "NOT_RECORDED_IN_DEMO")
        for key in ("purpose_consent_verified", "science_validated",
                    "ai_training_authorized", "plan_accepted", "real_data"):
            self.assertIs(res.json()[key], False)
        self.assertNotIn(DIGEST1, res.text)

    def test_append_two_digest_only_revisions_and_reopen(self):
        one = self.client.post(ROOT, json=self.command(), headers=self.headers())
        self.assertEqual(one.status_code, 201, one.text)
        self.assertEqual(one.json()["input_revision"], 1)
        self.assertIs(one.json()["purpose_consent_verified"], False)
        two = self.client.post(
            ROOT, json=self.command(1, DIGEST2, "DEMO-INPUT-B"),
            headers=self.headers(),
        )
        self.assertEqual(two.status_code, 201, two.text)
        self.assertEqual(two.json()["input_revision"], 2)
        current = self.client.get(ROOT, headers=self.headers()).json()
        self.assertEqual(current["input_revisions"], [1, 2])
        self.assertEqual(current["current_input_revision"], 2)
        self.assertNotIn(DIGEST1, str(current))
        self.assertNotIn(DIGEST2, str(current))
        self.assertEqual(self.ledger.internal_input_snapshot("DEMO-D-1", 3),
                         (2, DIGEST2))
        self.assertTrue(self.ledger.verify_integrity())
        self.ledger = self.reopen()
        self.client = self.client_for()
        self.assertEqual(
            self.client.get(ROOT, headers=self.headers()).json()["input_revisions"],
            [1, 2],
        )

    def test_same_action_replays_idempotently_not_new_revision(self):
        self.assertEqual(self.client.post(
            ROOT, json=self.command(), headers=self.headers()
        ).status_code, 201)
        replay = self.client.post(ROOT, json=self.command(), headers=self.headers())
        self.assertEqual(replay.status_code, 201)
        self.assertIs(replay.json()["idempotent_replay"], True)
        self.assertEqual(self.client.get(
            ROOT, headers=self.headers()
        ).json()["input_revisions"], [1])

    def test_stale_or_changed_action_or_repeat_digest_returns_409(self):
        self.client.post(ROOT, json=self.command(), headers=self.headers())
        attempts = (
            self.command(0, DIGEST2, "DEMO-INPUT-B"),
            self.command(0, DIGEST2, "DEMO-INPUT-A"),
            self.command(1, DIGEST1, "DEMO-INPUT-B"),
            {**self.command(1, DIGEST2, "DEMO-INPUT-B"), "expected_case_version": 4},
        )
        for command in attempts:
            with self.subTest(command=command):
                res = self.client.post(ROOT, json=command, headers=self.headers())
                self.assertEqual(res.status_code, 409)
                self.assertEqual(res.json(), {
                    "detail": "SYNTHETIC_INPUT_VERSION_CONFLICT",
                })
        self.assertEqual(self.client.get(
            ROOT, headers=self.headers()
        ).json()["input_revisions"], [1])

    def test_only_exact_household_owner_can_read_or_append(self):
        for path in (
            ROOT,
            "/api/v1/domestic/household-intake/my-drafts/DEMO-D-2/input-revisions",
            "/api/v1/domestic/household-intake/my-drafts/DEMO-E-1/input-revisions",
        ):
            for subject, roles in (
                ("synthetic-household-other", ("household",)),
                (OWNER, ("domestic_ops",)),
                ("synthetic-domestic-ops", ("domestic_ops",)),
                (OWNER, ("export_ops",)),
            ):
                with self.subTest(path=path, subject=subject, roles=roles):
                    self.assertEqual(self.client.get(
                        path, headers=self.headers(subject, roles)
                    ).status_code, 404)
                    self.assertEqual(self.client.post(
                        path, json=self.command(),
                        headers=self.headers(subject, roles),
                    ).status_code, 404)
        self.assertTrue(self.ledger.verify_integrity())

    def test_no_real_fields_or_unknown_schema_can_enter(self):
        for payload in (
            {**self.command(), "crop": "fake crop"},
            {**self.command(), "consent_accepted": True},
            {**self.command(), "real_data": True},
            {**self.command(), "synthetic_manifest_digest": "A" * 64},
            {**self.command(), "synthetic_manifest_digest": "z" * 64},
            {**self.command(), "expected_input_revision": True},
            {**self.command(), "action_id": "ACTUAL-123"},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(
                    ROOT, json=payload, headers=self.headers(),
                )
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get(
            ROOT, headers=self.headers()
        ).json()["input_revisions"], [])

    def test_no_bearer_mutation_and_invalid_signed_authentication(self):
        self.browser()
        self.assertEqual(self.client.post(
            ROOT, json=self.command(),
        ).status_code, 401)
        for token in ("forged", self.signed(expired=True)):
            r = self.client.post(ROOT, json=self.command(), headers={
                "Authorization": "Bearer " + token,
            })
            self.assertEqual(r.status_code, 401)
        self.assertEqual(self.client.get(ROOT, headers={
            "Authorization": "Bearer forged",
        }).status_code, 401)

    def test_browser_rtl_owner_history_and_logout_isolated(self):
        sid = self.browser()
        detail = self.client.get("/my-drafts/DEMO-D-1")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(HTML, detail.text)
        before = self.client.get(HTML)
        self.assertEqual(before.status_code, 200)
        self.assertIn("هنوز اثرانگشت نسخه‌ای", before.text)
        self.client.post(ROOT, json=self.command(), headers=self.headers())
        after = self.client.get(HTML)
        self.assertEqual(after.status_code, 200)
        self.assertIn("بازنگری آزمایشی 1", after.text)
        self.assertIn("رضایت آگاهانه", after.text)
        self.assertNotIn(DIGEST1, after.text)
        self.assertEqual(after.headers["cache-control"], "no-store")
        self.assertIn("frame-ancestors 'none'",
                      after.headers["content-security-policy"])
        self.sessions.revoke_session(sid)
        self.assertEqual(self.client.get(HTML).status_code, 401)

    def test_wrong_owner_browser_no_records_or_count(self):
        self.browser(subject="synthetic-household-other")
        res = self.client.get(HTML)
        self.assertEqual(res.status_code, 404)
        self.assertNotIn("DEMO-D-1", res.text)

    def test_tampered_manifest_and_removed_row_fail_closed(self):
        self.client.post(ROOT, json=self.command(), headers=self.headers())
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER input_no_update")
            db.execute(
                "UPDATE household_input_revision SET manifest_digest=?",
                (DIGEST2,),
            )
        res = self.client.get(ROOT, headers=self.headers())
        self.assertEqual(res.status_code, 503)
        self.assertNotIn(DIGEST2, res.text)
        with self.assertRaises(LedgerIntegrityError):
            self.reopen()

    def test_broken_audit_insertion_rolls_back_entire_command(self):
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER input_fail_audit BEFORE INSERT ON audit_event
                BEGIN SELECT RAISE(ABORT,'private audit failure'); END;
            """)
        r = self.client.post(ROOT, json=self.command(), headers=self.headers())
        self.assertEqual(r.status_code, 503)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM household_input_revision"
            ).fetchone()[0], 0)

    def test_concurrent_revision_compare_and_swap_one_wins(self):
        def submit(action):
            return self.client.post(
                ROOT, json=self.command(0, DIGEST1, action),
                headers=self.headers(),
            ).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, ("DEMO-CONC-A", "DEMO-CONC-B")))
        self.assertEqual(sorted(responses), [201, 409])
        self.assertTrue(self.ledger.verify_integrity())
        self.assertEqual(self.ledger.read_owned_input_revisions(
            "DEMO-D-1", Principal(OWNER, frozenset({"household"}))
        )["input_revisions"], [1])

    def test_default_app_without_explicit_input_ledger_has_no_routes(self):
        basic = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(basic.get(ROOT).status_code, 404)
        self.assertEqual(basic.post(ROOT, json=self.command()).status_code, 404)
        # The paired identity browser must be explicit for the write route.
        missing_browser = self.client_for(browser=False)
        self.assertEqual(missing_browser.get(
            ROOT, headers=self.headers(),
        ).status_code, 404)


if __name__ == "__main__":
    unittest.main()
