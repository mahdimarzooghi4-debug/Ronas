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
        from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig

        class EmptySessions:
            def get_session(self, sid):
                return None

            def revoke_session(self, sid):
                return None

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

    def test_default_app_does_not_expose_question_writer(self):
        other = TestClient(create_app(self.config), base_url="https://ronas.example.test")
        self.assertEqual(other.post(ROOT, json=self.command()).status_code, 404)
        self.assertEqual(other.get(ROOT).status_code, 404)


if __name__ == "__main__":
    unittest.main()
