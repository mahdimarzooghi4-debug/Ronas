"""LOCAL/TEST signed specialist questions: append-only audit, no decisions."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.agronomy_workspace import (
    SyntheticAgronomyAssignment, SyntheticAgronomyWorkspace,
)
from ronas_api.expert_review_questions_sqlite import (
    SqliteSyntheticExpertQuestionLedger, TRACKS, EVENT,
)
from ronas_api.grant_ledger_sqlite import LedgerIntegrityError
from ronas_api.internal_cultivation_plan_contract import (
    InternalCultivationProposal, ProposedCultivationStage,
)
from ronas_api.internal_scientific_basis_contract import (
    ScientificBasisCandidate, ScientificSourceCandidate,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.scoped_drafts import ScopedDraft

ISS = "https://id.example.test/realms/ronas"
API, WEB = "ronas-api", "ronas-web"
ROOT = "/api/v1/agronomy/assigned-drafts/DEMO-D-1/review-questions"
INPUT_URL = "/api/v1/domestic/household-intake/my-drafts/DEMO-D-1/input-revisions"
OWNER, EXPERT = "synthetic-household-one", "synthetic-agronomy-one"


class LocalExpertQuestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        key.update({"kid": "question-test", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [key]}).encode())

    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.path = Path(root.name) / "question.db"
        self.active = True
        self.ledger = self.reopen()
        self.science_current = []
        self.workspace = self.specialist()
        self.sessions = {}
        self.client = self.make_client()
        self.owner = Principal(OWNER, frozenset({"household"}))
        self.expert = Principal(EXPERT, frozenset({"agronomy_expert"}))

    def records(self):
        return (
            ScopedDraft("DEMO-D-1", "DOMESTIC", OWNER, 3, ()),
            ScopedDraft("DEMO-D-2", "DOMESTIC", "synthetic-other-household", 1, ()),
            ScopedDraft("DEMO-E-1", "EXPORT", "synthetic-export-owner", 1, (),
                        source_ref="DEMO-SRC-1"),
        )

    def reopen(self):
        return SqliteSyntheticExpertQuestionLedger(
            self.path, self.records(),
            trusted_revoke_authorizer=lambda *_: False,
            trusted_human_review_authorizer=lambda *_: False,
        )

    def proposal(self, revision=1, digest="1" * 64, science="2" * 64):
        return InternalCultivationProposal(
            household_case_ref="DEMO-D-1", household_case_version=3,
            household_input_revision=revision,
            household_input_snapshot_digest=digest,
            scientific_basis_manifest_digest=science,
            internal_model_artifact_digest="3" * 64,
            internal_run_ref="DEMO-RUN-1",
            proposal_content_digest="4" * 64,
            proposed_stages=(ProposedCultivationStage(
                "DEMO-STAGE-A", "5" * 64, "6" * 64,
            ),),
        )

    def specialist(self, proposal=None, science_basis=None):
        if proposal is None:
            proposal = self.proposal()
        return SyntheticAgronomyWorkspace(
            self.ledger,
            (SyntheticAgronomyAssignment("DEMO-D-1", EXPERT, 3),),
            trusted_assignment_active=lambda actor, ref, version: (
                self.active is True and actor == EXPERT
                and ref == "DEMO-D-1" and version == 3
            ),
            proposal_fixtures=(proposal,),
            scientific_basis_fixtures=((science_basis,) if science_basis else ()),
            trusted_scientific_source_snapshot=(
                (lambda: tuple(self.science_current))
                if science_basis else None
            ),
        )

    def make_client(self):
        # Existing Keycloak app requires an explicit browser session flow to
        # mount specialist API, even when this test only invokes Bearer routes.
        from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
        session_records = self.sessions

        class EmptySessions:
            def get_session(self, sid):
                return session_records.get(sid)

            def revoke_session(self, sid):
                session_records.pop(sid, None)

        async def no_external_identity(*_args):
            raise AssertionError("external auth call forbidden")

        flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, "https://ronas.example.test/api/auth/callback"),
            EmptySessions(), no_external_identity,
        )
        return TestClient(create_app(
            self.config, flow, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
            agronomy_workspace=self.workspace,
        ), base_url="https://ronas.example.test")

    def headers(self, subject=EXPERT, roles=("agronomy_expert",),
                *, expired=False):
        now = int(time.time())
        token = jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "typ": "Bearer",
            "sub": subject, "iat": now - 5, "nbf": now - 5,
            "exp": now - 10 if expired else now + 500,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "question-test"})
        return {"Authorization": "Bearer " + token}

    def seed_input(self, *, revision=0, digest="1" * 64, action="DEMO-INPUT-A"):
        return self.ledger.append_owned_input_manifest(
            "DEMO-D-1", self.owner,
            action_id=action, expected_case_version=3,
            expected_input_revision=revision,
            synthetic_manifest_digest=digest,
        )

    def command(self, *, track=TRACKS[0], revision=0, action="DEMO-Q-A",
                input_revision=1, **changes):
        payload = {
            "action_id": action, "track": track,
            "expected_case_version": 3,
            "expected_input_revision": input_revision,
            "expected_question_revision": revision,
            "reason_ref": "DEMO-REASON-A",
            "evidence_ref": "DEMO-EVIDENCE-A",
        }
        payload.update(changes)
        return payload

    def post(self, **kwargs):
        return self.client.post(
            ROOT, headers=self.headers(), json=self.command(**kwargs),
        )

    def test_empty_history_has_no_approval_and_note_api_is_opt_in(self):
        empty = self.client.get(ROOT, headers=self.headers())
        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertEqual(empty.json()["questions"], [])
        self.assertFalse(empty.json()["qualification_verified"])
        self.assertFalse(empty.json()["questions_are_review_decisions"])
        self.assertFalse(empty.json()["plan_accepted"])
        self.assertTrue(self.ledger.verify_integrity())

    def test_single_persisted_question_and_idempotent_replay(self):
        self.seed_input()
        created = self.post()
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["record_state"],
                         "SYNTHETIC_QUESTION_ONLY_NOT_REVIEWED")
        self.assertIs(created.json()["data_adequacy_approved"], False)
        again = self.post()
        self.assertEqual(again.status_code, 201, again.text)
        self.assertIs(again.json()["idempotent_replay"], True)
        history = self.client.get(ROOT, headers=self.headers())
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.json()["questions"]), 1)
        self.assertEqual(history.json()["questions"][0]["draft_reason_ref"],
                         "DEMO-REASON-A")
        self.assertEqual(history.json()["questions"][0]["record_state"],
                         "HISTORICAL_QUESTION_ONLY_NOT_REVIEWED")
        self.assertNotIn("1" * 64, history.text)
        self.assertEqual(
            [x.kind for x in self.ledger.audit_snapshot()
             if x.kind == EVENT], [EVENT],
        )
        self.ledger = self.reopen()
        self.assertTrue(self.ledger.verify_integrity())

    def test_all_three_tracks_remain_independent_and_never_approved(self):
        self.seed_input()
        for ix, track in enumerate(TRACKS):
            response = self.post(track=track, action=f"DEMO-Q-{ix}")
            self.assertEqual(response.status_code, 201, response.text)
            self.assertFalse(response.json()["plan_approved"])
            self.assertFalse(response.json()["science_rights_approved"])
        data = self.client.get(ROOT, headers=self.headers()).json()
        self.assertEqual([x["track"] for x in data["questions"]], list(TRACKS))
        self.assertEqual([x["question_revision"] for x in data["questions"]],
                         [1, 1, 1])
        self.assertFalse(data["questions_are_review_decisions"])
        self.assertTrue(self.ledger.verify_integrity())

    def test_same_track_cas_and_conflicting_replay(self):
        self.seed_input()
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post(action="DEMO-Q-B").status_code, 409)
        self.assertEqual(self.post(evidence_ref="DEMO-CHANGED").status_code, 409)
        self.assertEqual(self.post(track=TRACKS[1]).status_code, 409)
        self.assertEqual(self.post(action="DEMO-Q-B", revision=1).status_code, 201)
        self.assertEqual(len(self.client.get(
            ROOT, headers=self.headers()).json()["questions"]), 2)

    def test_invalid_inputs_and_no_real_notes_or_approval_claims(self):
        self.seed_input()
        for changes in (
            {"track": "APPROVE_PROGRAM"},
            {"action_id": "REAL-ACTION"},
            {"reason_ref": "actual household confidential data"},
            {"evidence_ref": "https://external.example"},
            {"expected_question_revision": True},
            {"expected_input_revision": "1"},
            {"expected_case_version": 5},
            {"approval": True},
            {"decision": "APPROVED"},
        ):
            with self.subTest(changes=changes):
                result = self.post(**changes)
                self.assertIn(result.status_code, (409, 422))
        self.assertEqual(self.client.get(
            ROOT, headers=self.headers()).json()["questions"], [])

    def test_revoked_assignment_and_signed_role_isolation(self):
        self.seed_input()
        for actor, roles in (
            (OWNER, ("household",)),
            (EXPERT, ("domestic_ops",)),
            ("synthetic-other-expert", ("agronomy_expert",)),
        ):
            with self.subTest(actor=actor, roles=roles):
                forbidden = self.client.post(
                    ROOT, headers=self.headers(actor, roles),
                    json=self.command(),
                )
                self.assertEqual(forbidden.status_code, 404)
                self.assertEqual(self.client.get(
                    ROOT, headers=self.headers(actor, roles),
                ).status_code, 404)
        self.active = False
        self.assertEqual(self.post().status_code, 404)
        self.assertEqual(self.client.get(ROOT, headers=self.headers()).status_code, 404)
        self.assertFalse(self.ledger.verify_integrity() is False)

    def test_missing_or_invalid_bearer_never_records_question(self):
        self.seed_input()
        self.assertEqual(self.client.post(ROOT, json=self.command()).status_code, 401)
        self.assertEqual(self.client.post(
            ROOT, headers={"Authorization": "Bearer fake"},
            json=self.command(),
        ).status_code, 401)
        self.assertEqual(self.client.post(
            ROOT, headers=self.headers(expired=True),
            json=self.command(),
        ).status_code, 401)
        self.assertEqual(self.client.get(
            ROOT, headers={"Authorization": "Bearer fake"},
        ).status_code, 401)

    def test_owner_input_revision_correction_stales_new_writes_but_history_survives(self):
        self.seed_input()
        self.assertEqual(self.post().status_code, 201)
        self.seed_input(revision=1, digest="7" * 64, action="DEMO-INPUT-B")
        self.assertEqual(self.post(
            track=TRACKS[1], action="DEMO-Q-B",
        ).status_code, 409)
        old = self.client.get(ROOT, headers=self.headers())
        self.assertEqual(old.status_code, 200)
        self.assertEqual(old.json()["questions"][0]["bound_input_revision"], 1)
        self.workspace = self.specialist(
            proposal=self.proposal(revision=2, digest="7" * 64),
        )
        self.client = self.make_client()
        newer = self.post(
            track=TRACKS[1], action="DEMO-Q-B", input_revision=2,
        )
        self.assertEqual(newer.status_code, 201, newer.text)
        history = self.client.get(ROOT, headers=self.headers()).json()["questions"]
        self.assertEqual([row["bound_input_revision"] for row in history], [1, 2])
        self.assertTrue(self.ledger.verify_integrity())

    def test_revised_scientific_rights_block_new_questions_without_deleting_old(self):
        src = ScientificSourceCandidate(
            ref="DEMO-SCI-01", version=1, content_sha256="a" * 64,
            rights_document_ref="DEMO-RIGHTS-01",
            rights_document_sha256="b" * 64,
            science_review_request_ref="DEMO-SCI-REVIEW",
            science_review_material_sha256="c" * 64,
        )
        basis = ScientificBasisCandidate(
            ref="DEMO-BASIS-01", version=1, sources=(src,),
        )
        self.science_current[:] = [src]
        self.workspace = self.specialist(
            proposal=self.proposal(science=basis.manifest_digest),
            science_basis=basis,
        )
        self.client = self.make_client()
        self.seed_input()
        self.assertEqual(self.post().status_code, 201)
        self.science_current[0] = replace(
            src, rights_document_sha256="d" * 64,
        )
        self.assertEqual(self.post(
            track=TRACKS[1], action="DEMO-Q-B",
        ).status_code, 409)
        old = self.client.get(ROOT, headers=self.headers())
        self.assertEqual(old.status_code, 200)
        self.assertEqual(len(old.json()["questions"]), 1)
        self.assertFalse(old.json()["plan_accepted"])

    def test_concurrent_same_track_revision_has_only_one_winner(self):
        self.seed_input()

        def submit(action):
            return self.post(action=action).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(submit, ("DEMO-ONE", "DEMO-TWO")))
        self.assertEqual(sorted(statuses), [201, 409])
        self.assertEqual(len(self.client.get(
            ROOT, headers=self.headers()).json()["questions"]), 1)
        self.assertTrue(self.ledger.verify_integrity())

    def test_modified_question_row_fails_closed(self):
        self.seed_input()
        self.assertEqual(self.post().status_code, 201)
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER expert_question_no_update")
            db.execute(
                "UPDATE expert_review_question SET reason_ref='DEMO-TAMPER'",
            )
        self.assertEqual(self.client.get(ROOT, headers=self.headers()).status_code, 503)
        with self.assertRaises(LedgerIntegrityError):
            self.reopen()

    def test_orphan_question_mutation_event_fails_closed(self):
        with self.ledger._transaction() as db:
            self.ledger._verify(db)
            self.ledger._append(
                db, kind=EVENT, engine="DOMESTIC", ref="DEMO-D-1",
                actor=EXPERT, action_id="DEMO-ORPHAN", mode="OTHER_MODE",
            )
        self.assertEqual(self.client.get(ROOT, headers=self.headers()).status_code, 503)
        with self.assertRaises(LedgerIntegrityError):
            self.reopen()

    def test_audit_write_failure_rolls_back_question_and_receipt(self):
        self.seed_input()
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER block_question_audit BEFORE INSERT ON audit_event
                WHEN NEW.payload LIKE '%SYNTHETIC_EXPERT_REVIEW_QUESTION_RECORDED%'
                BEGIN SELECT RAISE(ABORT, 'question audit blocked'); END;
            """)
        result = self.post()
        self.assertEqual(result.status_code, 503)
        with sqlite3.connect(self.path) as db:
            count = db.execute("SELECT COUNT(*) FROM expert_review_question").fetchone()[0]
        self.assertEqual(count, 0)

    def test_history_page_is_owner_scoped_persian_read_only_with_logout(self):
        from ronas_api.oidc_browser import BrowserSession
        import secrets
        self.seed_input()
        self.assertEqual(self.post().status_code, 201)
        sid = secrets.token_urlsafe(32)
        self.sessions[sid] = BrowserSession(
            EXPERT, frozenset({"agronomy_expert"}),
            self.headers()["Authorization"][7:],
            secrets.token_urlsafe(32), int(time.time()) + 200,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        path = "/agronomy/assigned-drafts/DEMO-D-1/review-questions"
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("تاریخچه پرسش‌های بررسی متخصص", page.text)
        self.assertIn("کفایت داده خانوار", page.text)
        self.assertIn("DEMO-REASON-A", page.text)
        self.assertIn("صرفاً سابقه", page.text)
        self.assertNotIn("1" * 64, page.text)
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.assertIn("frame-ancestors 'none'",
                      page.headers["content-security-policy"])
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual(
                getattr(self.client, method)(path).status_code, 405,
            )
        self.active = False
        self.assertEqual(self.client.get(path).status_code, 404)
        self.active = True
        self.sessions.pop(sid)
        self.assertEqual(self.client.get(path).status_code, 401)

    def test_history_page_cookie_cannot_submit_bearer_only_question(self):
        from ronas_api.oidc_browser import BrowserSession
        import secrets
        self.seed_input()
        sid = secrets.token_urlsafe(32)
        self.sessions[sid] = BrowserSession(
            EXPERT, frozenset({"agronomy_expert"}),
            self.headers()["Authorization"][7:],
            secrets.token_urlsafe(32), int(time.time()) + 200,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        self.assertEqual(
            self.client.post(ROOT, json=self.command()).status_code, 401,
        )
        self.assertEqual(
            self.client.get(ROOT, headers=self.headers()).json()["questions"], [],
        )

    def owner_reply_url(self):
        return "/api/v1/domestic/household-intake/my-drafts/DEMO-D-1/question-responses"

    def owner_reply_command(self, *, question_revision=1, action="DEMO-REPLY-A",
                            input_revision=1, track=TRACKS[0], **changes):
        payload = {
            "action_id": action, "track": track,
            "expected_question_revision": question_revision,
            "expected_case_version": 3,
            "expected_input_revision": input_revision,
            "answer_ref": "DEMO-ANSWER-A", "evidence_ref": "DEMO-OWNER-EVIDENCE",
        }
        payload.update(changes)
        return payload

    def owner_reply(self, **changes):
        return self.client.post(
            self.owner_reply_url(),
            headers=self.headers(OWNER, ("household",)),
            json=self.owner_reply_command(**changes),
        )

    def test_owner_response_requires_exact_existing_input_question(self):
        self.seed_input()
        self.assertEqual(self.owner_reply().status_code, 409)
        self.assertEqual(self.post().status_code, 201)
        created = self.owner_reply()
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["record_state"],
                         "SYNTHETIC_RESPONSE_RECEIVED_NOT_REVIEWED")
        for k in ("purpose_consent_verified", "household_input_adequacy_verified",
                  "science_rights_verified", "qualified_expert_decision_recorded",
                  "plan_accepted", "real_data"):
            self.assertIs(created.json()[k], False)
        self.assertTrue(self.ledger.verify_integrity())

    def test_idempotent_household_answer_and_owner_history(self):
        self.seed_input()
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.owner_reply().status_code, 201)
        replay = self.owner_reply()
        self.assertEqual(replay.status_code, 201)
        self.assertIs(replay.json()["idempotent_replay"], True)
        history = self.client.get(
            self.owner_reply_url(), headers=self.headers(OWNER, ("household",)),
        )
        self.assertEqual(history.status_code, 200, history.text)
        questions = history.json()["questions"]
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["response_state"],
                         "HISTORICAL_RESPONSE_ONLY_NOT_REVIEWED")
        self.assertEqual(questions[0]["response_ref"], "DEMO-ANSWER-A")
        self.assertTrue(questions[0]["is_current_input_version"])
        self.assertNotIn("DEMO-REASON-A", history.text)
        self.assertNotIn("1" * 64, history.text)
        self.assertFalse(history.json()["expert_review_recorded"])
        self.assertFalse(history.json()["plan_accepted"])
        self.ledger = self.reopen()
        self.assertTrue(self.ledger.verify_integrity())

    def test_assigned_specialist_sees_only_response_presence_not_owner_refs(self):
        self.seed_input()
        self.post()
        before = self.client.get(ROOT, headers=self.headers()).json()
        self.assertFalse(before["questions"][0]["synthetic_household_response_received"])
        self.owner_reply()
        after = self.client.get(ROOT, headers=self.headers())
        self.assertEqual(after.status_code, 200)
        self.assertTrue(after.json()["questions"][0]["synthetic_household_response_received"])
        self.assertIs(after.json()["questions"][0]["response_is_expert_approval"], False)
        self.assertNotIn("DEMO-ANSWER-A", after.text)
        self.assertNotIn("DEMO-OWNER-EVIDENCE", after.text)
        self.assertIs(after.json()["plan_accepted"], False)

    def test_specialist_persian_history_shows_only_unreviewed_receipt_marker(self):
        from ronas_api.oidc_browser import BrowserSession
        import secrets
        self.seed_input()
        self.post()
        self.owner_reply()
        sid = secrets.token_urlsafe(32)
        self.sessions[sid] = BrowserSession(
            EXPERT, frozenset({"agronomy_expert"}),
            self.headers()["Authorization"][7:],
            secrets.token_urlsafe(32), int(time.time()) + 200,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        page = self.client.get("/agronomy/assigned-drafts/DEMO-D-1/review-questions")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("پاسخ ساختاری خانوار دریافت شده (بررسی نشده)", page.text)
        self.assertIn("بدون تأیید", page.text)
        self.assertNotIn("DEMO-ANSWER-A", page.text)
        self.assertNotIn("DEMO-OWNER-EVIDENCE", page.text)
        self.assertNotIn("1" * 64, page.text)
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.assertTrue(self.ledger.verify_integrity())

    def test_training_science_and_plan_questions_cannot_take_household_reply(self):
        self.seed_input()
        for ix, track in enumerate(TRACKS):
            self.assertEqual(self.post(
                track=track, action=f"DEMO-Q-{ix}",
            ).status_code, 201)
        for track in TRACKS[1:]:
            with self.subTest(track=track):
                result = self.owner_reply(track=track)
                self.assertEqual(result.status_code, 422)
        self.assertEqual(
            self.client.get(self.owner_reply_url(),
                            headers=self.headers(OWNER, ("household",))).json()
            ["questions"][0]["response_state"], "MISSING_RESPONSE",
        )

    def test_changed_answer_payload_and_second_response_denied(self):
        self.seed_input()
        self.post()
        self.assertEqual(self.owner_reply().status_code, 201)
        for payload in (
            {"answer_ref": "DEMO-ANSWER-CHANGED"},
            {"evidence_ref": "DEMO-EVIDENCE-CHANGED"},
            {"action_id": "DEMO-SECOND"},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.owner_reply(**payload).status_code, 409)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM household_question_response",
            ).fetchone()[0], 1)

    def test_owner_input_revision_change_keeps_answer_history_but_blocks_reuse(self):
        self.seed_input()
        self.post()
        self.assertEqual(self.owner_reply().status_code, 201)
        self.seed_input(revision=1, digest="7" * 64, action="DEMO-INPUT-B")
        stale = self.owner_reply()
        self.assertEqual(stale.status_code, 409)
        old = self.client.get(
            self.owner_reply_url(), headers=self.headers(OWNER, ("household",)),
        )
        self.assertEqual(old.status_code, 200, old.text)
        self.assertFalse(old.json()["questions"][0]["is_current_input_version"])
        self.assertEqual(old.json()["questions"][0]["response_state"],
                         "HISTORICAL_RESPONSE_ONLY_NOT_REVIEWED")
        self.assertFalse(old.json()["new_advice_enabled"])
        self.assertTrue(self.ledger.verify_integrity())

    def test_next_question_supersedes_old_answer_and_needs_fresh_reference(self):
        self.seed_input()
        self.post()
        self.owner_reply()
        self.assertEqual(self.post(
            revision=1, action="DEMO-Q-B",
        ).status_code, 201)
        self.assertEqual(self.owner_reply().status_code, 409)
        newer = self.owner_reply(question_revision=2, action="DEMO-REPLY-B")
        self.assertEqual(newer.status_code, 201, newer.text)
        history = self.client.get(
            self.owner_reply_url(), headers=self.headers(OWNER, ("household",)),
        ).json()["questions"]
        self.assertEqual([x["question_revision"] for x in history], [1, 2])
        self.assertTrue(all(
            x["response_state"] == "HISTORICAL_RESPONSE_ONLY_NOT_REVIEWED"
            for x in history
        ))

    def test_only_exact_signed_household_owner_may_reply_or_read(self):
        self.seed_input()
        self.post()
        for subject, roles in (
            (EXPERT, ("agronomy_expert",)),
            (OWNER, ("domestic_ops",)),
            ("synthetic-other-household", ("household",)),
            ("synthetic-export-owner", ("household",)),
        ):
            with self.subTest(subject=subject, roles=roles):
                self.assertEqual(self.client.post(
                    self.owner_reply_url(),
                    headers=self.headers(subject, roles),
                    json=self.owner_reply_command(),
                ).status_code, 404)
                self.assertEqual(self.client.get(
                    self.owner_reply_url(),
                    headers=self.headers(subject, roles),
                ).status_code, 404)
        self.assertEqual(self.client.post(
            self.owner_reply_url().replace("DEMO-D-1", "DEMO-E-1"),
            headers=self.headers(OWNER, ("household",)),
            json=self.owner_reply_command(),
        ).status_code, 404)
        self.assertTrue(self.ledger.verify_integrity())

    def test_unsigned_cookie_or_invalid_jwt_cannot_write_answer(self):
        self.seed_input()
        self.post()
        self.assertEqual(self.client.post(
            self.owner_reply_url(), json=self.owner_reply_command(),
        ).status_code, 401)
        for headers in (
            {"Authorization": "Bearer fake"},
            self.headers(OWNER, ("household",), expired=True),
        ):
            self.assertEqual(self.client.post(
                self.owner_reply_url(), headers=headers,
                json=self.owner_reply_command(),
            ).status_code, 401)
        self.assertEqual(self.client.get(
            self.owner_reply_url(),
            headers=self.headers(OWNER, ("household",)),
        ).json()["questions"][0]["response_state"], "MISSING_RESPONSE")

    def test_reject_extra_real_personal_fields_or_forged_consent(self):
        self.seed_input()
        self.post()
        for changed in (
            {"consent_verified": True}, {"approve_program": True},
            {"real_crop_data": "fiction"}, {"answer_ref": "a raw answer"},
            {"evidence_ref": "https://private.example"},
            {"action_id": "REAL-REPLY"},
            {"expected_question_revision": True},
            {"expected_input_revision": "1"},
            {"expected_case_version": 4},
        ):
            with self.subTest(changed=changed):
                result = self.owner_reply(**changed)
                self.assertIn(result.status_code, (409, 422))
        self.assertEqual(self.client.get(
            self.owner_reply_url(),
            headers=self.headers(OWNER, ("household",)),
        ).json()["questions"][0]["response_state"], "MISSING_RESPONSE")

    def test_modified_response_row_fails_closed_and_restart_rejects(self):
        self.seed_input()
        self.post()
        self.assertEqual(self.owner_reply().status_code, 201)
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER household_response_no_update")
            db.execute(
                "UPDATE household_question_response "
                "SET answer_ref='DEMO-FORGED'",
            )
        bad = self.client.get(
            self.owner_reply_url(), headers=self.headers(OWNER, ("household",)),
        )
        self.assertEqual(bad.status_code, 503)
        with self.assertRaises(LedgerIntegrityError):
            self.reopen()

    def test_orphan_household_response_event_fails_closed(self):
        from ronas_api.expert_review_questions_sqlite import ANSWER_EVENT
        with self.ledger._transaction() as db:
            self.ledger._verify(db)
            self.ledger._append(
                db, kind=ANSWER_EVENT, engine="DOMESTIC", ref="DEMO-D-1",
                actor=OWNER, action_id="DEMO-ORPHAN",
                mode="UNEXPECTED_MODE",
            )
        self.assertEqual(self.client.get(
            self.owner_reply_url(), headers=self.headers(OWNER, ("household",)),
        ).status_code, 503)
        with self.assertRaises(LedgerIntegrityError):
            self.reopen()

    def test_audit_insertion_failure_rolls_back_response_record(self):
        self.seed_input()
        self.post()
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER block_answer_audit BEFORE INSERT ON audit_event
                WHEN NEW.payload LIKE '%SYNTHETIC_HOUSEHOLD_QUESTION_RESPONSE_RECORDED%'
                BEGIN SELECT RAISE(ABORT, 'response audit blocked'); END;
            """)
        self.assertEqual(self.owner_reply().status_code, 503)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM household_question_response",
            ).fetchone()[0], 0)

    def test_concurrent_two_household_response_actions_one_wins(self):
        self.seed_input()
        self.post()
        def send(action):
            return self.owner_reply(action=action).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, ("DEMO-R-A", "DEMO-R-B")))
        self.assertEqual(sorted(results), [201, 409])
        self.assertTrue(self.ledger.verify_integrity())

    def test_owner_persian_question_response_history_and_logout(self):
        from ronas_api.oidc_browser import BrowserSession
        import secrets
        self.seed_input()
        self.post()
        self.owner_reply()
        sid = secrets.token_urlsafe(32)
        self.sessions[sid] = BrowserSession(
            OWNER, frozenset({"household"}),
            self.headers(OWNER, ("household",))["Authorization"][7:],
            secrets.token_urlsafe(32), int(time.time()) + 200,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        path = "/my-drafts/DEMO-D-1/question-responses"
        self.assertIn(path, self.client.get(
            "/my-drafts/DEMO-D-1/input-revisions",
        ).text)
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("تاریخچه پاسخ‌های ساختاری خانوار", page.text)
        self.assertIn("DEMO-ANSWER-A", page.text)
        self.assertIn("تأیید/رد وجود ندارد", page.text)
        self.assertNotIn("1" * 64, page.text)
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.assertIn("frame-ancestors 'none'",
                      page.headers["content-security-policy"])
        for method in ("post", "patch", "put", "delete"):
            self.assertEqual(
                getattr(self.client, method)(path).status_code, 405,
            )
        self.sessions.pop(sid)
        self.assertEqual(self.client.get(path).status_code, 401)
        sid2 = secrets.token_urlsafe(32)
        self.sessions[sid2] = BrowserSession(
            "synthetic-other-household", frozenset({"household"}),
            self.headers("synthetic-other-household", ("household",))["Authorization"][7:],
            secrets.token_urlsafe(32), int(time.time()) + 200,
        )
        self.client.cookies.set("__Host-ronas_session", sid2)
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_default_app_cannot_accept_or_read_household_question_responses(self):
        other = TestClient(create_app(self.config), base_url="https://ronas.example.test")
        self.assertEqual(other.post(
            self.owner_reply_url(), json=self.owner_reply_command(),
        ).status_code, 404)
        self.assertEqual(other.get(self.owner_reply_url()).status_code, 404)

    def inspect_url(self):
        return ("/api/v1/agronomy/assigned-drafts/DEMO-D-1/"
                "response-receipt-inspections")

    def inspect_command(self, *, action="DEMO-INSPECT-A",
                        question_revision=1, input_revision=1, **overrides):
        values = {
            "action_id": action, "expected_case_version": 3,
            "expected_input_revision": input_revision,
            "expected_question_revision": question_revision,
        }
        values.update(overrides)
        return values

    def inspect(self, **values):
        return self.client.post(
            self.inspect_url(), json=self.inspect_command(**values),
            headers=self.headers(),
        )

    def test_inspection_requires_a_genuine_prior_owner_response(self):
        self.seed_input()
        self.assertEqual(self.inspect().status_code, 409)
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.inspect().status_code, 409)
        self.assertEqual(self.owner_reply().status_code, 201)
        result = self.inspect()
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()["state"],
                         "SYNTHETIC_RECEIPT_SEEN_NOT_REVIEWED")
        for key in (
            "household_input_adequacy_verified", "source_rights_verified",
            "scientific_validity_verified", "professional_qualification_verified",
            "expert_decision_recorded", "plan_accepted", "new_advice_enabled",
            "real_data",
        ):
            self.assertIs(result.json()[key], False)
        self.assertTrue(self.ledger.verify_integrity())

    def test_inspection_exact_replay_is_idempotent_and_history_is_private(self):
        self.seed_input()
        self.post()
        self.owner_reply()
        self.assertEqual(self.inspect().status_code, 201)
        again = self.inspect()
        self.assertEqual(again.status_code, 201)
        self.assertIs(again.json()["idempotent_replay"], True)
        history = self.client.get(ROOT, headers=self.headers())
        self.assertTrue(history.json()["questions"][0]
                        ["synthetic_receipt_inspected_not_reviewed"])
        self.assertIs(history.json()["questions"][0]
                      ["inspection_is_expert_decision"], False)
        self.assertNotIn("DEMO-ANSWER-A", history.text)
        self.assertNotIn("DEMO-OWNER-EVIDENCE", history.text)
        self.assertEqual(self.ledger.audit_snapshot()[-2].kind,
                         "SYNTHETIC_EXPERT_RESPONSE_RECEIPT_INSPECTED")
        self.ledger = self.reopen()
        self.assertTrue(self.ledger.verify_integrity())

    def test_inspection_wrong_role_assignee_or_cross_engine_is_denied(self):
        self.seed_input()
        self.post()
        self.owner_reply()
        for actor, roles in (
            (OWNER, ("household",)),
            (EXPERT, ("domestic_ops",)),
            ("synthetic-other-expert", ("agronomy_expert",)),
        ):
            bad = self.client.post(
                self.inspect_url(), json=self.inspect_command(),
                headers=self.headers(actor, roles),
            )
            self.assertEqual(bad.status_code, 404)
        self.active = False
        self.assertEqual(self.inspect().status_code, 404)
        self.active = True
        self.assertEqual(self.client.post(
            self.inspect_url().replace("DEMO-D-1", "DEMO-E-1"),
            json=self.inspect_command(), headers=self.headers(),
        ).status_code, 404)

    def test_inspection_token_and_strict_no_approval_payload(self):
        self.seed_input()
        self.post()
        self.owner_reply()
        self.assertEqual(self.client.post(
            self.inspect_url(), json=self.inspect_command(),
        ).status_code, 401)
        for headers in (
            {"Authorization": "Bearer fake"},
            self.headers(expired=True),
        ):
            self.assertEqual(self.client.post(
                self.inspect_url(), json=self.inspect_command(),
                headers=headers,
            ).status_code, 401)
        for bad in (
            {"approve": True}, {"review_outcome": "APPROVED"},
            {"answer_ref": "DEMO-OWNER-EVIDENCE"},
            {"actual_expert_certificate": "real"},
            {"expected_case_version": 2},
            {"expected_input_revision": True},
            {"expected_question_revision": "1"},
            {"action_id": "REAL-INSPECTION"},
        ):
            with self.subTest(bad=bad):
                self.assertIn(self.inspect(**bad).status_code, (409, 422))
        self.assertEqual(self.inspect().status_code, 201)

    def test_inspection_reuse_and_same_question_conflicts(self):
        self.seed_input()
        self.post()
        self.owner_reply()
        self.assertEqual(self.inspect().status_code, 201)
        for changed in (
            {"action": "DEMO-INSPECT-B"},
            {"question_revision": 2},
        ):
            with self.subTest(changed=changed):
                self.assertEqual(self.inspect(**changed).status_code, 409)
        self.assertTrue(self.ledger.verify_integrity())

    def test_new_question_or_owner_revision_stales_uninspected_answer(self):
        self.seed_input()
        self.post()
        self.owner_reply()
        self.assertEqual(
            self.post(action="DEMO-Q-B", revision=1).status_code, 201,
        )
        self.assertEqual(self.inspect().status_code, 409)
        self.owner_reply(question_revision=2, action="DEMO-REPLY-B")
        self.assertEqual(self.inspect(
            question_revision=2, action="DEMO-INSPECT-B",
        ).status_code, 201)
        self.seed_input(revision=1, digest="7" * 64, action="DEMO-INPUT-B")
        self.assertEqual(self.inspect(
            question_revision=2, action="DEMO-INSPECT-B",
        ).status_code, 409)
        self.assertTrue(self.ledger.verify_integrity())

    def test_changed_science_rights_blocks_inspection_of_old_receipt(self):
        src = ScientificSourceCandidate(
            ref="DEMO-SCI-01", version=1, content_sha256="a" * 64,
            rights_document_ref="DEMO-RIGHTS-01",
            rights_document_sha256="b" * 64,
            science_review_request_ref="DEMO-SCI-REVIEW",
            science_review_material_sha256="c" * 64,
        )
        basis = ScientificBasisCandidate(
            ref="DEMO-BASIS-01", version=1, sources=(src,),
        )
        self.science_current[:] = [src]
        self.workspace = self.specialist(
            proposal=self.proposal(science=basis.manifest_digest),
            science_basis=basis,
        )
        self.client = self.make_client()
        self.seed_input()
        self.post()
        self.owner_reply()
        self.science_current[0] = replace(
            src, rights_document_sha256="d" * 64,
        )
        self.assertEqual(self.inspect().status_code, 409)
        self.assertEqual(self.client.get(
            ROOT, headers=self.headers()).status_code, 200)
        self.assertEqual(self.client.get(
            self.owner_reply_url(),
            headers=self.headers(OWNER, ("household",)),
        ).status_code, 200)

    def test_concurrent_inspections_have_exactly_one_winner(self):
        self.seed_input()
        self.post()
        self.owner_reply()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda action: self.inspect(action=action).status_code,
                ("DEMO-I-ONE", "DEMO-I-TWO"),
            ))
        self.assertEqual(sorted(results), [201, 409])
        self.assertTrue(self.ledger.verify_integrity())

    def test_modified_inspection_row_fails_closed_on_read_and_reopen(self):
        self.seed_input()
        self.post()
        self.owner_reply()
        self.inspect()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER response_inspection_no_update")
            db.execute(
                "UPDATE expert_response_receipt_inspection "
                "SET actor_digest=?", ("f" * 64,),
            )
        self.assertEqual(self.client.get(
            ROOT, headers=self.headers()).status_code, 503)
        with self.assertRaises(LedgerIntegrityError):
            self.reopen()

    def test_orphan_inspection_event_and_failed_audit_are_detected(self):
        from ronas_api.expert_review_questions_sqlite import INSPECTION_EVENT
        with self.ledger._transaction() as db:
            self.ledger._verify(db)
            self.ledger._append(
                db, kind=INSPECTION_EVENT, engine="DOMESTIC", ref="DEMO-D-1",
                actor=EXPERT, action_id="DEMO-FAKE-EVENT", mode="WRONG_MODE",
            )
        self.assertEqual(self.client.get(
            ROOT, headers=self.headers()).status_code, 503)
        with self.assertRaises(LedgerIntegrityError):
            self.reopen()

    def test_inspection_audit_failure_does_not_commit_record(self):
        self.seed_input()
        self.post()
        self.owner_reply()
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER deny_inspection_audit BEFORE INSERT ON audit_event
                WHEN NEW.payload LIKE '%SYNTHETIC_EXPERT_RESPONSE_RECEIPT_INSPECTED%'
                BEGIN SELECT RAISE(ABORT, 'inspection audit blocked'); END;
            """)
        self.assertEqual(self.inspect().status_code, 503)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM expert_response_receipt_inspection",
            ).fetchone()[0], 0)

    def test_persian_history_shows_inspection_but_no_owner_response_data(self):
        from ronas_api.oidc_browser import BrowserSession
        import secrets
        self.seed_input()
        self.post()
        self.owner_reply()
        self.assertEqual(self.inspect().status_code, 201)
        sid = secrets.token_urlsafe(32)
        self.sessions[sid] = BrowserSession(
            EXPERT, frozenset({"agronomy_expert"}),
            self.headers()["Authorization"][7:],
            secrets.token_urlsafe(32), int(time.time()) + 200,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        page = self.client.get(
            "/agronomy/assigned-drafts/DEMO-D-1/review-questions",
        )
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("رسید پاسخ مشاهده شد (بدون داوری تخصصی)", page.text)
        self.assertIn("بدون تأیید", page.text)
        self.assertNotIn("DEMO-ANSWER-A", page.text)
        self.assertNotIn("DEMO-OWNER-EVIDENCE", page.text)
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.active = False
        self.assertEqual(self.client.get(
            "/agronomy/assigned-drafts/DEMO-D-1/review-questions",
        ).status_code, 404)
        self.active = True
        self.sessions.pop(sid)
        self.assertEqual(self.client.get(
            "/agronomy/assigned-drafts/DEMO-D-1/review-questions",
        ).status_code, 401)

    def test_default_app_does_not_mount_inspection_command(self):
        other = TestClient(create_app(self.config),
                           base_url="https://ronas.example.test")
        self.assertEqual(other.post(
            self.inspect_url(), json=self.inspect_command(),
        ).status_code, 404)

    def test_default_app_does_not_expose_question_writer(self):
        other = TestClient(create_app(self.config), base_url="https://ronas.example.test")
        self.assertEqual(other.post(ROOT, json=self.command()).status_code, 404)
        self.assertEqual(other.get(ROOT).status_code, 404)


if __name__ == "__main__":
    unittest.main()
