"""Signed LOCAL/TEST synthetic household manifest revisions — no real consent."""
from concurrent.futures import ThreadPoolExecutor
import json
import re
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
from ronas_api.agronomy_workspace import (
    SyntheticAgronomyAssignment, SyntheticAgronomyWorkspace,
)
from ronas_api.internal_cultivation_plan_contract import (
    InternalCultivationProposal, ProposedCultivationStage,
)
from ronas_api.auth import Principal
from ronas_api.grant_ledger_sqlite import LedgerIntegrityError
from ronas_api.household_input_ledger_sqlite import (
    SqliteSyntheticHouseholdInputLedger, InputRevisionConflict, EVENT_KIND, MODE,
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
        events = self.ledger.audit_snapshot()
        mutations = [
            event for event in events
            if event.kind == "SYNTHETIC_INPUT_MANIFEST_REVISION_RECORDED"
        ]
        self.assertEqual(len(mutations), 2)
        self.assertEqual([event.action_id for event in mutations],
                         ["DEMO-INPUT-A", "DEMO-INPUT-B"])
        self.assertNotIn(
            "READ_ALLOWED", [event.kind for event in mutations],
        )
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
        forbidden = (
            (ROOT, "synthetic-household-other", ("household",)),
            (ROOT, OWNER, ("domestic_ops",)),
            (ROOT, "synthetic-domestic-ops", ("domestic_ops",)),
            (ROOT, OWNER, ("export_ops",)),
            ("/api/v1/domestic/household-intake/my-drafts/DEMO-D-2/input-revisions",
             OWNER, ("household",)),
            ("/api/v1/domestic/household-intake/my-drafts/DEMO-E-1/input-revisions",
             OWNER, ("household",)),
        )
        for path, subject, roles in forbidden:
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


    def specialist(self, *, revision=1, digest=DIGEST1, input_snapshot=None):
        proposal = InternalCultivationProposal(
            household_case_ref="DEMO-D-1",
            household_case_version=3,
            household_input_revision=revision,
            household_input_snapshot_digest=digest,
            scientific_basis_manifest_digest="3" * 64,
            internal_model_artifact_digest="4" * 64,
            internal_run_ref="DEMO-RUN-ONE",
            proposal_content_digest="5" * 64,
            proposed_stages=(ProposedCultivationStage(
                "DEMO-STEP-ONE", "6" * 64, "7" * 64,
            ),),
        )
        workspace = SyntheticAgronomyWorkspace(
            self.ledger,
            (SyntheticAgronomyAssignment(
                "DEMO-D-1", "synthetic-agronomist-one", 3,
            ),),
            trusted_assignment_active=lambda actor, ref, version: (
                actor == "synthetic-agronomist-one"
                and ref == "DEMO-D-1" and version == 3
            ),
            proposal_fixtures=(proposal,),
            trusted_input_snapshot=input_snapshot,
        )
        return TestClient(create_app(
            self.config, self.flow, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
            agronomy_workspace=workspace,
        ), base_url=ORIGIN)

    def test_orphan_mutation_audit_kind_fails_closed_even_without_mode_prefix(self):
        with self.ledger._transaction() as db:
            self.ledger._verify(db)
            self.ledger._append(
                db, kind=EVENT_KIND, engine="DOMESTIC", ref="DEMO-D-1",
                actor=OWNER, action_id="DEMO-ORPHAN-INPUT",
                mode="SPOOFED_UNRELATED_MODE",
            )
        response = self.client.get(ROOT, headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("DEMO-D-1", response.text)
        with self.assertRaises(LedgerIntegrityError):
            self.reopen()

    def test_forged_input_mode_on_unpaired_read_event_fails_closed(self):
        with self.ledger._transaction() as db:
            self.ledger._verify(db)
            self.ledger._append(
                db, kind="READ_ALLOWED", engine="DOMESTIC",
                ref="DEMO-D-1", actor=OWNER,
                mode=MODE + "0" * 64,
            )
        response = self.client.get(ROOT, headers=self.headers())
        self.assertEqual(response.status_code, 503)
        with self.assertRaises(LedgerIntegrityError):
            self.reopen()

    def test_same_ledger_forbids_override_of_household_current_revision(self):
        self.assertEqual(self.client.post(
            ROOT, json=self.command(), headers=self.headers(),
        ).status_code, 201)
        with self.assertRaises(ValueError) as err:
            self.specialist(input_snapshot=lambda *_: (1, DIGEST1))
        self.assertIn("conflicting household input authorities", str(err.exception))
        self.assertEqual(self.client.post(
            ROOT, json=self.command(1, DIGEST2, "DEMO-INPUT-B"),
            headers=self.headers(),
        ).status_code, 201)
        with self.assertRaises(ValueError):
            self.specialist(input_snapshot=lambda *_: (1, DIGEST1))
        self.assertTrue(self.ledger.verify_integrity())

    def test_persisted_owner_revision_drives_expert_proposal_staleness(self):
        specialist = self.specialist()
        url = "/api/v1/agronomy/assigned-drafts/DEMO-D-1/internal-plan-proposal"
        expert = self.headers("synthetic-agronomist-one", ("agronomy_expert",))
        missing = specialist.get(url, headers=expert)
        self.assertEqual(missing.status_code, 503)
        self.assertNotIn("DEMO-STEP-ONE", missing.text)
        self.assertEqual(self.client.post(
            ROOT, json=self.command(), headers=self.headers(),
        ).status_code, 201)
        ready = specialist.get(url, headers=expert)
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assertEqual(ready.json()["proposal_status"],
                         "STRUCTURE_ONLY_UNREVIEWED")
        self.assertEqual(ready.json()["input_revision"], 1)
        self.assertEqual(ready.json()["proposed_stage_refs"], ["DEMO-STEP-ONE"])
        self.assertIs(ready.json()["plan_accepted"], False)
        self.assertIs(ready.json()["advice_enabled"], False)
        self.assertNotIn(DIGEST1, ready.text)
        self.assertEqual(self.client.post(
            ROOT, json=self.command(1, DIGEST2, "DEMO-INPUT-B"),
            headers=self.headers(),
        ).status_code, 201)
        stale = specialist.get(url, headers=expert)
        self.assertEqual(stale.status_code, 503)
        self.assertEqual(stale.json(), {
            "detail": "SYNTHETIC_AGRONOMY_UNAVAILABLE",
        })
        self.assertNotIn("DEMO-STEP-ONE", stale.text)
        new_specialist = self.specialist(revision=2, digest=DIGEST2)
        revised = new_specialist.get(url, headers=expert)
        self.assertEqual(revised.status_code, 200)
        self.assertEqual(revised.json()["input_revision"], 2)
        self.assertIs(revised.json()["plan_accepted"], False)
        self.assertTrue(self.ledger.verify_integrity())

    def test_new_household_revision_stales_all_three_review_tracks(self):
        specialist = self.specialist()
        route = "/api/v1/agronomy/assigned-drafts/DEMO-D-1/expert-review-preparation"
        token = self.headers("synthetic-agronomist-one", ("agronomy_expert",))
        self.assertEqual(specialist.get(route, headers=token).status_code, 503)
        self.assertEqual(self.client.post(
            ROOT, json=self.command(), headers=self.headers(),
        ).status_code, 201)
        available = specialist.get(route, headers=token)
        self.assertEqual(available.status_code, 200, available.text)
        self.assertEqual(available.json()["tracks"][0]["observed_structure"],
                         "SYNTHETIC_INPUT_REVISION_BOUND_NOT_VALIDATED")
        self.assertTrue(all(
            t["review_outcome"] == "NOT_REVIEWED"
            for t in available.json()["tracks"]
        ))
        self.assertEqual(self.client.post(
            ROOT, json=self.command(1, DIGEST2, "DEMO-INPUT-B"),
            headers=self.headers(),
        ).status_code, 201)
        old = specialist.get(route, headers=token)
        self.assertEqual(old.status_code, 503)
        self.assertNotIn("HOUSEHOLD_INPUT_ADEQUACY", old.text)
        new_specialist = self.specialist(revision=2, digest=DIGEST2)
        new = new_specialist.get(route, headers=token)
        self.assertEqual(new.status_code, 200, new.text)
        self.assertEqual(new.json()["combined_review_status"],
                         "NOT_AUTHORIZED_FOR_DECISION")
        self.assertFalse(new.json()["plan_accepted"])
        self.assertFalse(new.json()["qualified_reviewer_identity_verified"])
        self.assertTrue(self.ledger.verify_integrity())

    def test_persisted_household_revision_cannot_grant_expert_role_or_approval(self):
        self.client.post(ROOT, json=self.command(), headers=self.headers())
        specialist = self.specialist()
        url = "/api/v1/agronomy/assigned-drafts/DEMO-D-1/internal-plan-proposal"
        for subject, roles in (
            (OWNER, ("household",)),
            ("synthetic-agronomist-one", ("household",)),
            ("synthetic-household-other", ("agronomy_expert",)),
            ("synthetic-domestic-ops", ("domestic_ops",)),
        ):
            with self.subTest(subject=subject, roles=roles):
                denied = specialist.get(
                    url, headers=self.headers(subject, roles),
                )
                self.assertEqual(denied.status_code, 404)
                self.assertNotIn("DEMO-STEP-ONE", denied.text)
        ordinary = self.client.get(
            "/api/v1/domestic/household-intake/my-drafts/DEMO-D-1/technical-status",
            headers=self.headers(),
        )
        self.assertEqual(ordinary.status_code, 200)
        self.assertEqual(ordinary.json()["status"], "DRAFT_ONLY")
        self.assertFalse(ordinary.json()["plan_accepted"])
        self.assertFalse(ordinary.json()["purpose_consent_verified"])


    def demo_browser_form(self, *, rev=0, choice="DEMO-MANIFEST-ALPHA",
                          case_version=3, csrf=None,
                          action_id="DEMO-UI-D-TEST"):
        sid_cookie = self.client.cookies.get("__Host-ronas_session")
        session = self.sessions.get_session(sid_cookie)
        return {
            "csrf": session.csrf if csrf is None else csrf,
            "action_id": action_id,
            "case_version": str(case_version),
            "input_revision": str(rev),
            "scenario": choice,
        }

    def test_browser_local_demo_correction_roundtrip_and_stale(self):
        self.browser()
        before = self.client.get(HTML)
        self.assertEqual(before.status_code, 200, before.text)
        self.assertIn('form-action \'self\'', before.headers["content-security-policy"])
        self.assertIn("ثبت نسخه DEMO", before.text)
        rendered_action = re.search(
            r'name="action_id" value="(DEMO-UI-D-[A-Z0-9]+)"', before.text,
        )
        self.assertIsNotNone(rendered_action)
        form = self.demo_browser_form()
        form["action_id"] = rendered_action.group(1)
        route = HTML + "/demo-correction"
        first = self.client.post(route, data=form,
                                 headers={"Origin": ORIGIN},
                                 follow_redirects=False)
        self.assertEqual(first.status_code, 303, first.text)
        self.assertEqual(first.headers["location"], HTML)
        replay = self.client.post(route, data=form, headers={"Origin": ORIGIN},
                                  follow_redirects=False)
        self.assertEqual(replay.status_code, 303, replay.text)
        changed_replay = self.client.post(
            route, data={**form, "scenario": "DEMO-MANIFEST-BETA"},
            headers={"Origin": ORIGIN},
        )
        self.assertEqual(changed_replay.status_code, 409)
        self.assertEqual(self.client.get(ROOT, headers=self.headers()).json()[
            "input_revisions"], [1])
        stale = self.client.post(
            route, data={**form, "action_id": "DEMO-UI-D-STALE"},
            headers={"Origin": ORIGIN},
        )
        self.assertEqual(stale.status_code, 409)
        current = self.client.get(HTML)
        self.assertIn("بازنگری آزمایشی 1", current.text)
        self.assertNotIn("رضایت آگاهانه احراز شده", current.text)
        second = self.client.post(
            route, data=self.demo_browser_form(
                rev=1, choice="DEMO-MANIFEST-BETA",
                action_id="DEMO-UI-D-TEST-2",
            ), headers={"Origin": ORIGIN}, follow_redirects=False,
        )
        self.assertEqual(second.status_code, 303, second.text)
        self.assertEqual(self.reopen().read_owned_input_revisions(
            "DEMO-D-1", Principal(OWNER, frozenset({"household"}))
        )["input_revisions"], [1, 2])

    def test_browser_local_demo_correction_csrf_origin_and_scope(self):
        self.browser()
        route = HTML + "/demo-correction"
        form = self.demo_browser_form()
        for hdr, payload, status in (
            ({}, form, 403),
            ({"Origin": "https://evil.test"}, form, 403),
            ({"Origin": ORIGIN}, {**form, "csrf": "wrong"}, 403),
            ({"Origin": ORIGIN}, {**form, "scenario": "wheat"}, 422),
            ({"Origin": ORIGIN}, {**form, "case_version": "03"}, 422),
            ({"Origin": ORIGIN}, {**form, "new_field": "PII"}, 422),
        ):
            with self.subTest(payload=payload, hdr=hdr):
                got = self.client.post(route, data=payload, headers=hdr)
                self.assertEqual(got.status_code, status, got.text)
        self.assertEqual(self.client.post(
            "/my-drafts/DEMO-D-2/input-revisions/demo-correction",
            data=form, headers={"Origin": ORIGIN},
        ).status_code, 404)
        self.assertEqual(self.client.post(
            "/my-drafts/DEMO-E-1/input-revisions/demo-correction",
            data=form, headers={"Origin": ORIGIN},
        ).status_code, 404)
        self.assertEqual(self.client.get(ROOT, headers=self.headers()).json()[
            "input_revisions"], [])
        self.assertTrue(self.reopen().verify_integrity())

    def test_browser_local_demo_correction_no_session_or_expired(self):
        self.assertEqual(self.client.post(
            HTML + "/demo-correction", data={
                "csrf": "invalid", "case_version": "3",
                "input_revision": "0",
                "scenario": "DEMO-MANIFEST-ALPHA",
            }, headers={"Origin": ORIGIN},
        ).status_code, 401)
        self.browser(subject="synthetic-household-other")
        self.assertEqual(self.client.get(HTML).status_code, 404)
        self.assertEqual(self.client.post(
            HTML + "/demo-correction", data=self.demo_browser_form(),
            headers={"Origin": ORIGIN},
        ).status_code, 404)

    def test_owned_case_guides_to_current_input_without_real_consent(self):
        self.browser()
        case = "/my-drafts/DEMO-D-1"
        first = self.client.get(case)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertIn("اقدام بعدی در پرونده", first.text)
        self.assertIn("/input-revisions#domestic-demo-correction", first.text)
        self.assertNotIn("طرح کشت تأیید شده", first.text)
        # The exact currently authorized ledger, not browser storage,
        # supplies the revision. The next link remains safe and demo-only.
        self.ledger.append_owned_input_manifest(
            "DEMO-D-1", Principal(OWNER, frozenset({"household"})),
            action_id="DEMO-NEXT-INPUT", expected_case_version=3,
            expected_input_revision=0, synthetic_manifest_digest=DIGEST1,
        )
        again = self.client.get(case)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertIn("اقدام بعدی در پرونده", again.text)

    def test_owned_case_next_step_does_not_expose_other_owner(self):
        self.browser(subject="synthetic-household-other")
        resp = self.client.get("/my-drafts/DEMO-D-1")
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn("اقدام بعدی", resp.text)


    def progress_command(self, revision=0, input_revision=0, corrects_revision=0,
                         action="DEMO-PROGRESS-A",
                         note="DEMO: observed leaves", reported_at="2026-10-12T10:30:00+03:30"):
        return {
            "action_id": action, "expected_case_version": 3,
            "expected_revision": revision,
            "expected_input_revision": input_revision,
            "corrects_revision": corrects_revision,
            "reported_at": reported_at,
            "note": note,
        }

    def test_progress_note_api_is_owner_only_append_only_and_replay_safe(self):
        root = "/api/v1/domestic/household-intake/my-drafts/DEMO-D-1/progress-notes"
        initial = self.client.get(root, headers=self.headers())
        self.assertEqual(initial.status_code, 200, initial.text)
        self.assertEqual(initial.json()["notes"], [])
        for key in ("real_data", "scientific_review", "expert_inspection", "plan_accepted"):
            self.assertIs(initial.json()[key], False)
        first = self.client.post(root, json=self.progress_command(), headers=self.headers())
        self.assertEqual(first.status_code, 201, first.text)
        self.assertFalse(first.json()["idempotent_replay"])
        replay = self.client.post(root, json=self.progress_command(), headers=self.headers())
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertTrue(replay.json()["idempotent_replay"])
        history = self.client.get(root, headers=self.headers()).json()
        self.assertEqual(history["current_input_revision"], 0)
        self.assertEqual(history["notes"], [{
            "case_version": 3, "input_revision": 0, "revision": 1,
            "reported_at": "2026-10-12T10:30:00+03:30",
            "note": "DEMO: observed leaves", "current_case_version": True,
            "current_input_context": True,
            "corrects_revision": None, "superseded_by_revision": None,
            "is_superseded": False,
        }])
        self.assertTrue(self.ledger.verify_integrity())
        self.ledger = self.reopen()
        self.assertEqual(self.ledger.read_owned_progress_notes(
            "DEMO-D-1", Principal(OWNER, frozenset({"household"}))
        )["current_revision"], 1)

    def test_progress_notes_become_historical_after_input_revision_changes(self):
        root = "/api/v1/domestic/household-intake/my-drafts/DEMO-D-1/progress-notes"
        first = self.client.post(root, json=self.progress_command(), headers=self.headers())
        self.assertEqual(first.status_code, 201, first.text)
        updated_input = self.client.post(
            ROOT, json=self.command(
                revision=0, digest=DIGEST1, action="DEMO-INPUT-AFTER-PROGRESS",
            ), headers=self.headers(),
        )
        self.assertEqual(updated_input.status_code, 201, updated_input.text)

        history = self.client.get(root, headers=self.headers()).json()
        self.assertEqual(history["current_input_revision"], 1)
        self.assertFalse(history["notes"][0]["current_input_context"])
        stale = self.client.post(
            root,
            json=self.progress_command(
                revision=1, input_revision=0, action="DEMO-PROGRESS-STALE-INPUT",
                note="DEMO: based on old input",
            ),
            headers=self.headers(),
        )
        self.assertEqual(stale.status_code, 409, stale.text)

        second = self.client.post(
            root,
            json=self.progress_command(
                revision=1, input_revision=1, action="DEMO-PROGRESS-NEW-INPUT",
                note="DEMO: reviewed new input",
            ),
            headers=self.headers(),
        )
        self.assertEqual(second.status_code, 201, second.text)
        history = self.client.get(root, headers=self.headers()).json()
        self.assertEqual([item["current_input_context"] for item in history["notes"]],
                         [False, True])
        self.assertEqual([item["input_revision"] for item in history["notes"]], [0, 1])

    def test_progress_note_correction_is_append_only_replay_safe_and_single_target(self):
        root = "/api/v1/domestic/household-intake/my-drafts/DEMO-D-1/progress-notes"
        first = self.client.post(root, json=self.progress_command(), headers=self.headers())
        self.assertEqual(first.status_code, 201, first.text)
        correction_command = self.progress_command(
            revision=1, corrects_revision=1, action="DEMO-PROGRESS-CORRECT-1",
            note="DEMO: corrected observation",
        )
        corrected = self.client.post(root, json=correction_command, headers=self.headers())
        self.assertEqual(corrected.status_code, 201, corrected.text)
        self.assertEqual(corrected.json()["corrects_revision"], 1)
        replay = self.client.post(root, json=correction_command, headers=self.headers())
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertTrue(replay.json()["idempotent_replay"])
        conflict = self.client.post(
            root,
            json=self.progress_command(
                revision=2, corrects_revision=1, action="DEMO-PROGRESS-CORRECT-2",
                note="DEMO: competing correction",
            ),
            headers=self.headers(),
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        history = self.client.get(root, headers=self.headers()).json()
        self.assertEqual(history["contract_version"],
                         "ronas.domestic.synthetic-household-progress-notes.v2")
        self.assertEqual(history["notes"][0]["superseded_by_revision"], 2)
        self.assertTrue(history["notes"][0]["is_superseded"])
        self.assertFalse(history["notes"][1]["is_superseded"])
        self.assertEqual(history["notes"][1]["corrects_revision"], 1)
        self.assertTrue(self.ledger.verify_integrity())
        self.ledger = self.reopen()
        self.assertTrue(self.ledger.verify_integrity())

    def test_progress_note_schema_migrates_existing_unbound_local_history(self):
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER progress_note_no_update")
            db.execute("DROP TRIGGER progress_note_no_delete")
            db.execute("DROP TABLE household_progress_note")
            db.executescript("""
                CREATE TABLE household_progress_note (
                    action_id TEXT PRIMARY KEY, ref TEXT NOT NULL,
                    case_version INTEGER NOT NULL, revision INTEGER NOT NULL,
                    owner_digest TEXT NOT NULL, reported_at TEXT NOT NULL,
                    note TEXT NOT NULL, previous_receipt_digest TEXT NOT NULL,
                    receipt_digest TEXT NOT NULL UNIQUE,
                    audit_sequence INTEGER NOT NULL UNIQUE,
                    UNIQUE(ref, revision),
                    FOREIGN KEY(audit_sequence) REFERENCES audit_event(sequence)
                );
                CREATE TRIGGER progress_note_no_update
                BEFORE UPDATE ON household_progress_note
                BEGIN SELECT RAISE(ABORT, 'synthetic progress history immutable'); END;
                CREATE TRIGGER progress_note_no_delete
                BEFORE DELETE ON household_progress_note
                BEGIN SELECT RAISE(ABORT, 'synthetic progress history immutable'); END;
            """)
        self.ledger = self.reopen()
        with sqlite3.connect(self.path) as db:
            columns = {row[1] for row in db.execute(
                "PRAGMA table_info(household_progress_note)"
            )}
        self.assertIn("input_revision", columns)
        self.assertIn("corrects_revision", columns)
        self.client = self.client_for()
        self.assertEqual(self.client.post(
            "/api/v1/domestic/household-intake/my-drafts/DEMO-D-1/progress-notes",
            json=self.progress_command(), headers=self.headers(),
        ).status_code, 201)
        self.assertTrue(self.ledger.verify_integrity())

    def test_progress_note_api_rejects_stale_owner_role_and_real_claims(self):
        root = "/api/v1/domestic/household-intake/my-drafts/DEMO-D-1/progress-notes"
        for subject, roles in (
            ("synthetic-household-other", ("household",)),
            (OWNER, ("domestic_ops",)),
        ):
            self.assertEqual(self.client.get(root, headers=self.headers(subject, roles)).status_code, 404)
            self.assertEqual(self.client.post(root, json=self.progress_command(),
                                              headers=self.headers(subject, roles)).status_code, 404)
        self.assertEqual(self.client.post(root, json=self.progress_command(reported_at="2026-10-12T10:30:00"),
                                          headers=self.headers()).status_code, 422)
        self.assertEqual(self.client.post(root, json=self.progress_command(note="real crop data"),
                                          headers=self.headers()).status_code, 422)
        self.assertEqual(self.client.post(root, json=self.progress_command(),
                                          headers={"Authorization": "Bearer invalid"}).status_code, 401)
        self.client.post(root, json=self.progress_command(), headers=self.headers())
        stale = self.client.post(root, json=self.progress_command(revision=0, action="DEMO-PROGRESS-B"),
                                 headers=self.headers())
        self.assertEqual(stale.status_code, 409)

    def test_progress_note_audit_tampering_fails_closed(self):
        root = "/api/v1/domestic/household-intake/my-drafts/DEMO-D-1/progress-notes"
        self.assertEqual(self.client.post(root, json=self.progress_command(),
                                          headers=self.headers()).status_code, 201)
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER progress_note_no_update")
            db.execute("UPDATE household_progress_note SET note='DEMO: forged' WHERE revision=1")
        denied = self.client.get(root, headers=self.headers())
        self.assertEqual(denied.status_code, 503)
        with self.assertRaises(LedgerIntegrityError):
            self.reopen().verify_integrity()

    def test_progress_note_browser_form_csrf_origin_escape_and_owner(self):
        self.browser()
        route = "/my-drafts/DEMO-D-1/progress-notes"
        before = self.client.get(route)
        self.assertEqual(before.status_code, 200, before.text)
        self.assertIn("یادداشت‌های پیشرفت", before.text)
        action = re.search(
            r'name="action_id" value="(DEMO-PROGRESS-[A-Z0-9]+)"',
            before.text,
        )
        self.assertIsNotNone(action)
        form = {
            "csrf": self.sessions.get_session(self.client.cookies.get("__Host-ronas_session")).csrf,
            "action_id": action.group(1),
            "case_version": "3", "input_revision": "0", "revision": "0",
            "corrects_revision": "0",
            "reported_at": "2026-10-12T10:30:00+03:30",
            "note": 'DEMO: <script>alert("x")</script>',
        }
        good = dict(form)
        self.assertEqual(self.client.post(
            route, data=good, headers={"Origin": "https://evil.test"},
        ).status_code, 403)
        self.assertEqual(self.client.post(
            route, data={**good, "csrf": "wrong"}, headers={"Origin": ORIGIN},
        ).status_code, 403)
        saved = self.client.post(
            route, data=good, headers={"Origin": ORIGIN}, follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 303, saved.text)
        replay = self.client.post(
            route, data=good, headers={"Origin": ORIGIN}, follow_redirects=False,
        )
        self.assertEqual(replay.status_code, 303, replay.text)
        changed_replay = self.client.post(
            route, data={**good, "note": "DEMO: changed"},
            headers={"Origin": ORIGIN}, follow_redirects=False,
        )
        self.assertEqual(changed_replay.status_code, 409, changed_replay.text)
        view = self.client.get(route)
        self.assertIn("&lt;script&gt;", view.text)
        self.assertNotIn("<script>", view.text)
        self.assertIn("زمینه جاری پرونده و ورودی", view.text)
        self.assertEqual(view.text.count("<li><time>"), 1)
        self.assertEqual(self.ledger.read_owned_progress_notes(
            "DEMO-D-1", Principal(OWNER, frozenset({"household"})),
        )["current_revision"], 1)
        self.assertEqual(self.client.get("/my-drafts/DEMO-D-1").status_code, 200)
        self.assertIn("/my-drafts/DEMO-D-1/progress-notes",
                      self.client.get("/my-drafts/DEMO-D-1").text)

    def test_progress_note_history_browser_uses_stable_pages(self):
        self.browser()
        route = "/my-drafts/DEMO-D-1/progress-notes"
        csrf = self.sessions.get_session(
            self.client.cookies.get("__Host-ronas_session")
        ).csrf
        for revision, note in enumerate(("DEMO: first page", "DEMO: second page")):
            response = self.client.post(
                route,
                data={
                    "csrf": csrf, "action_id": f"DEMO-PROGRESS-PAGE-{revision}",
                    "case_version": "3", "input_revision": "0",
                    "revision": str(revision), "corrects_revision": "0",
                    "reported_at": "2026-10-12T10:30:00+03:30", "note": note,
                },
                headers={"Origin": ORIGIN}, follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303, response.text)
        first = self.client.get(route + "?limit=1")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertIn("DEMO: first page", first.text)
        self.assertNotIn("DEMO: second page", first.text)
        self.assertIn("after_revision=1", first.text)
        second = self.client.get(
            route + "?limit=1&after_revision=1&snapshot_revision=2",
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertIn("DEMO: second page", second.text)
        self.assertNotIn("DEMO: first page", second.text)

    def test_progress_note_browser_marks_input_context_stale_and_rejects_old_form(self):
        self.browser()
        route = "/my-drafts/DEMO-D-1/progress-notes"
        before = self.client.get(route)
        csrf = self.sessions.get_session(
            self.client.cookies.get("__Host-ronas_session")
        ).csrf
        action = re.search(r'name="action_id" value="(DEMO-PROGRESS-[A-Z0-9]+)"', before.text)
        self.assertIsNotNone(action)
        old_form = {
            "csrf": csrf, "action_id": action.group(1),
            "case_version": "3", "input_revision": "0", "revision": "0",
            "corrects_revision": "0",
            "reported_at": "2026-10-12T10:30:00+03:30",
            "note": "DEMO: initial context note",
        }
        saved = self.client.post(route, data=old_form, headers={"Origin": ORIGIN},
                                 follow_redirects=False)
        self.assertEqual(saved.status_code, 303, saved.text)
        changed = self.client.post(
            ROOT, json=self.command(
                revision=0, digest=DIGEST1, action="DEMO-INPUT-AFTER-BROWSER-NOTE",
            ), headers=self.headers(),
        )
        self.assertEqual(changed.status_code, 201, changed.text)

        current = self.client.get(route)
        self.assertIn("نسخه تاریخی ورودی 0", current.text)
        self.assertIn('name="input_revision" value="1"', current.text)
        stale_form = {**old_form, "action_id": "DEMO-PROGRESS-STALE-BROWSER",
                      "revision": "1", "note": "DEMO: stale browser context"}
        stale = self.client.post(route, data=stale_form,
                                 headers={"Origin": ORIGIN}, follow_redirects=False)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertIn('role="alert"', stale.text)
        self.assertIn("هیچ تغییری ثبت نشد", stale.text)
        self.assertIn('href="/my-drafts/DEMO-D-1/progress-notes"', stale.text)
        self.assertNotIn("stale browser context", stale.text)
        self.assertEqual(self.ledger.read_owned_progress_notes(
            "DEMO-D-1", Principal(OWNER, frozenset({"household"})),
        )["current_revision"], 1)

    def test_progress_note_browser_correction_uses_owner_append_only_flow(self):
        self.browser()
        route = "/my-drafts/DEMO-D-1/progress-notes"
        csrf = self.sessions.get_session(
            self.client.cookies.get("__Host-ronas_session")
        ).csrf
        initial = self.client.post(
            route,
            data={
                "csrf": csrf, "action_id": "DEMO-PROGRESS-BROWSER-ORIGINAL",
                "case_version": "3", "input_revision": "0", "revision": "0",
                "corrects_revision": "0",
                "reported_at": "2026-10-12T10:30:00+03:30",
                "note": "DEMO: original browser note",
            },
            headers={"Origin": ORIGIN}, follow_redirects=False,
        )
        self.assertEqual(initial.status_code, 303, initial.text)
        correction_page = self.client.get(route + "?corrects_revision=1")
        self.assertEqual(correction_page.status_code, 200, correction_page.text)
        self.assertIn("ثبت اصلاح برای یادداشت شماره 1", correction_page.text)
        self.assertIn('name="corrects_revision" value="1"', correction_page.text)
        correction = self.client.post(
            route,
            data={
                "csrf": csrf, "action_id": "DEMO-PROGRESS-BROWSER-CORRECTION",
                "case_version": "3", "input_revision": "0", "revision": "1",
                "corrects_revision": "1",
                "reported_at": "2026-10-12T11:30:00+03:30",
                "note": "DEMO: corrected browser note",
            },
            headers={"Origin": ORIGIN}, follow_redirects=False,
        )
        self.assertEqual(correction.status_code, 303, correction.text)
        history = self.client.get(route)
        self.assertIn("اصلاح شماره 2", history.text)
        original_entry = history.text[
            history.text.index("DEMO: original browser note"):
        ].split("</li>", 1)[0]
        self.assertNotIn("اصلاح این یادداشت</a>", original_entry)
        self.assertIn("اصلاح این یادداشت</a>",
                      history.text[history.text.index("DEMO: corrected browser note"):])

    def test_progress_note_form_is_disabled_for_wrong_owner_and_export(self):
        self.browser(subject="synthetic-household-other")
        self.assertEqual(self.client.get("/my-drafts/DEMO-D-1/progress-notes").status_code, 404)
        self.assertEqual(self.client.get("/my-drafts/DEMO-E-1/progress-notes").status_code, 404)

if __name__ == "__main__":
    unittest.main()
