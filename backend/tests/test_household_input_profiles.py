"""Schema-driven owner profile intake is versioned, private, and guarded."""
import hashlib
import json
import re
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.domestic_stage_observation import CurrentStageContext, StageRequirement
from ronas_api.household_input_profiles import (
    HouseholdInputField, HouseholdInputSchema,
    SqliteSyntheticHouseholdProfileLedger,
)
from ronas_api.stage_observation_artifacts import PrivateFilesystemStageArtifactStore
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant
from ronas_api.agronomy_workspace import (
    SyntheticAgronomyAssignment, SyntheticAgronomyWorkspace,
)
from ronas_api.expert_review_questions_sqlite import SqliteSyntheticExpertQuestionLedger
from ronas_api.domestic_surplus_publication import (
    OfferRevision, PublicationAttestation, PublicationAuthorities,
)
from ronas_api.domestic_surplus_drafts import SqliteSyntheticSurplusDraftLedger
from ronas_api.internal_cultivation_plan_contract import (
    InternalCultivationProposal, ProposedCultivationStage,
)
from ronas_api.internal_ai_proposal_runtime import (
    CandidateOutput, CandidateStage, ProfileBackedProposalContextAuthority,
    ProposalRuntimeBasis, ProposalRuntimeStale,
    candidate_structure_digest, run_current_synthetic_internal_proposal,
)

ISS = "https://identity.example.test/realms/ronas"
API, WEB, ORIGIN = "ronas-api", "ronas-web", "https://ronas.example.test"
OWNER = "synthetic-household-profile-owner"
REF = "DEMO-D-PROFILE"
ROOT = f"/api/v1/domestic/household-intake/my-drafts/{REF}/cultivation-inputs"
PAGE = f"/my-drafts/{REF}/cultivation-inputs"


class Sessions:
    def __init__(self):
        self.sessions = {}

    def get_session(self, sid):
        return self.sessions.get(sid)

    def revoke_session(self, sid):
        self.sessions.pop(sid, None)


class HouseholdProfileFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "profile-test", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(
            ISS, API, WEB, json.dumps({"keys": [jwk]}).encode(),
        )
        cls.schema = HouseholdInputSchema(
            "RONAS-DOMESTIC-INPUT", 1,
            (
                HouseholdInputField("field_alpha", "فیلد آزمایشی <الف>", "text",
                                    required=True, max_length=80),
                HouseholdInputField("field_choice", "گزینه", "choice",
                                    choices=("sample-a", "sample-b")),
            ),
        )

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "profiles.db"
        self.artifact_root = Path(temp.name) / "stage-artifacts"
        self.artifact_root.mkdir(mode=0o700)
        self.artifact_root.chmod(0o700)
        self.artifact_store = PrivateFilesystemStageArtifactStore(
            self.artifact_root, b"x" * 32,
        )
        self.records = (
            ScopedDraft(REF, "DOMESTIC", OWNER, 2, (
                ScopedGrant("synthetic-domestic-ops", "domestic_ops"),
            )),
            ScopedDraft("DEMO-D-OTHER", "DOMESTIC", "synthetic-other", 1, ()),
            ScopedDraft("DEMO-E-PROFILE", "EXPORT", OWNER, 1, (),
                        source_ref="DEMO-SOURCE"),
        )
        self.ledger = self.reopen()
        self.stage_plan_digest = "b" * 64
        self.stage_plan_available = True
        self.sessions = Sessions()

        async def no_exchange(_code, _verifier):
            raise AssertionError("identity exchange is not expected in this test")

        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.sessions, no_exchange,
        )
        self.app = self.make_app()
        self.client = TestClient(self.app, base_url=ORIGIN)

    def test_profile_and_assigned_specialist_share_one_case_ledger(self):
        self.assertIsInstance(self.ledger, SqliteSyntheticExpertQuestionLedger)
        specialist = "synthetic-agronomy-profile-reviewer"
        workspace = SyntheticAgronomyWorkspace(
            self.ledger,
            (SyntheticAgronomyAssignment(REF, specialist, 2),),
            trusted_assignment_active=lambda actor, ref, version: (
                actor == specialist and ref == REF and version == 2
            ),
        )
        app = create_app(
            self.config, self.flow,
            scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
            household_profile_schema=self.schema,
            household_profile_access_authority=self.allowed,
            household_stage_context_authority=self.stage_context,
            agronomy_workspace=workspace,
        )
        client = TestClient(app, base_url=ORIGIN)

        owner_write = client.post(
            ROOT, json=self.command(), headers=self.bearer(),
        )
        self.assertEqual(owner_write.status_code, 201, owner_write.text)

        assigned = client.get(
            "/api/v1/agronomy/assigned-drafts/" + REF,
            headers=self.bearer(
                subject=specialist, roles=("agronomy_expert",),
            ),
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertEqual(assigned.json()["ref"], REF)

        unassigned = client.get(
            "/api/v1/agronomy/assigned-drafts/" + REF,
            headers=self.bearer(
                subject="synthetic-agronomy-unassigned",
                roles=("agronomy_expert",),
            ),
        )
        self.assertEqual(unassigned.status_code, 404, unassigned.text)
        self.assertTrue(self.ledger.verify_integrity())

    def reopen(self):
        return SqliteSyntheticHouseholdProfileLedger(
            self.path, self.records, profile_schema=self.schema,
            trusted_revoke_authorizer=lambda *_: False,
            trusted_human_review_authorizer=lambda *_: False,
        )

    def allowed(self, principal, ref, schema_ref):
        return (schema_ref == self.schema.schema_ref
                and "household" in principal.roles)

    def stage_context(self, ref):
        if not self.stage_plan_available:
            return None
        lineage = self.ledger.internal_proposal_lineage(ref)
        if lineage is None:
            return None
        version, input_revision, digest = lineage
        return CurrentStageContext(
            ref, version, input_revision, digest, self.stage_plan_digest,
            (StageRequirement("DEMO-STAGE-01", "a" * 64),),
        )

    def make_app(self, *, schema=True, authority=True, stage_authority=True,
                 artifact_store=None, surplus_authority=None,
                 surplus_draft_ledger=None):
        return create_app(
            self.config, self.flow, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
            household_profile_schema=self.schema if schema else None,
            household_profile_access_authority=self.allowed if authority else None,
            household_stage_context_authority=(
                self.stage_context if stage_authority and schema else None
            ),
            household_stage_artifact_store=artifact_store,
            household_surplus_publication_authority=surplus_authority,
            household_surplus_draft_ledger=surplus_draft_ledger,
        )

    def stage_command(self, *, action="DEMO-STAGE-OBS-1", revision=0):
        version, input_revision, input_digest = self.ledger.internal_proposal_lineage(REF)
        return {
            "action_id": action,
            "expected_observation_revision": revision,
            "expected_case_version": version,
            "expected_input_revision": input_revision,
            "expected_input_snapshot_digest": input_digest,
            "expected_plan_digest": self.stage_plan_digest,
            "stage_ref": "DEMO-STAGE-01",
            "expected_observation_requirements_digest": "a" * 64,
            "observed_at": "2026-10-12T10:20:30+00:00",
            "observation_artifact_digest": "c" * 64,
        }

    def token(self, subject=OWNER, roles=("household",), expired=False):
        now = int(time.time())
        return jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "typ": "Bearer",
            "sub": subject, "iat": now - 5, "nbf": now - 5,
            "exp": now - 1 if expired else now + 500,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "profile-test"})

    def bearer(self, subject=OWNER, roles=("household",)):
        return {"Authorization": "Bearer " + self.token(subject, roles)}

    def browser_session(self, subject=OWNER, roles=("household",)):
        sid = secrets.token_urlsafe(40)
        self.sessions.sessions[sid] = BrowserSession(
            subject, frozenset(roles), self.token(subject, roles),
            secrets.token_urlsafe(32), int(time.time()) + 300,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        return self.sessions.sessions[sid]

    def command(self, *, revision=0, action="DEMO-PROFILE-1", values=None):
        return {
            "action_id": action, "expected_case_version": 2,
            "expected_revision": revision,
            "values": values or {"field_alpha": "sample value", "field_choice": "sample-a"},
        }

    def test_owner_can_create_correct_and_read_versioned_profile(self):
        first = self.client.post(ROOT, json=self.command(), headers=self.bearer())
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json()["profile_revision"], 1)
        second = self.client.post(
            ROOT, json=self.command(
                revision=1, action="DEMO-PROFILE-2",
                values={"field_alpha": "corrected sample", "field_choice": "sample-b"},
            ), headers=self.bearer(),
        )
        self.assertEqual(second.status_code, 201, second.text)
        current = self.client.get(ROOT, headers=self.bearer())
        self.assertEqual(current.status_code, 200, current.text)
        body = current.json()
        self.assertEqual(body["current_revision"], 2)
        self.assertEqual(body["current_values"], {
            "field_alpha": "corrected sample", "field_choice": "sample-b",
        })
        self.assertEqual([x["revision"] for x in body["revisions"]], [1, 2])
        self.assertFalse(body["purpose_consent_verified"])
        self.assertFalse(body["science_validated"])
        self.assertFalse(body["plan_accepted"])
        self.assertNotIn("content_digest", str(body))
        self.assertTrue(self.ledger.verify_integrity())
        self.ledger = self.reopen()
        self.assertEqual(
            self.ledger.read_owned_profile(
                REF, Principal(OWNER, frozenset({"household"})),
            )["current_revision"], 2,
        )

    def test_owner_can_read_exact_profile_history_revision_through_api(self):
        first = self.client.post(ROOT, json=self.command(), headers=self.bearer())
        self.assertEqual(first.status_code, 201)
        second = self.client.post(
            ROOT, json=self.command(
                revision=1, action="DEMO-PROFILE-HISTORY-2",
                values={"field_alpha": "corrected historical sample",
                        "field_choice": "sample-b"},
            ), headers=self.bearer(),
        )
        self.assertEqual(second.status_code, 201)
        historical = self.client.get(
            ROOT + "/revisions/1", headers=self.bearer(),
        )
        self.assertEqual(historical.status_code, 200, historical.text)
        self.assertEqual(historical.json()["revision"], 1)
        self.assertEqual(historical.json()["values"], {
            "field_alpha": "sample value", "field_choice": "sample-a",
        })
        self.assertNotIn("corrected historical sample", historical.text)
        denied = self.client.get(
            ROOT + "/revisions/1",
            headers=self.bearer("synthetic-other", ("household",)),
        )
        self.assertEqual(denied.status_code, 404)
        missing = self.client.get(
            ROOT + "/revisions/9", headers=self.bearer(),
        )
        self.assertEqual(missing.status_code, 404)

    def test_stage_observation_api_is_owner_bound_audited_and_lineage_current(self):
        self.assertEqual(self.client.post(
            ROOT, json=self.command(), headers=self.bearer(),
        ).status_code, 201)
        path = ROOT.replace("/cultivation-inputs", "/stage-observations")
        command = self.stage_command()
        before_receipt = self.client.get(path, headers=self.bearer())
        self.assertEqual(before_receipt.json()["stage_progress"], [{
            "stage_ref": "DEMO-STAGE-01", "state": "NOT_REPORTED",
            "observation_revision": None,
            "receipt_inspected": False,
        }])
        saved = self.client.post(path, json=command, headers=self.bearer())
        self.assertEqual(saved.status_code, 201, saved.text)
        self.assertEqual(saved.json()["revision"], 1)
        self.assertFalse(saved.json()["stage_completed"])
        replay = self.client.post(path, json=command, headers=self.bearer())
        self.assertTrue(replay.json()["idempotent_replay"])
        current = self.client.get(path, headers=self.bearer())
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json()["state"], "CURRENT_PLAN_AVAILABLE")
        self.assertTrue(current.json()["observations"][0]["current"])
        self.assertEqual(current.json()["observations"][0]["case_version"], 2)
        self.assertEqual(current.json()["observations"][0]["input_revision"], 1)
        self.assertEqual(current.json()["stage_progress"], [{
            "stage_ref": "DEMO-STAGE-01", "state": "CURRENT_RECEIPT",
            "observation_revision": 1,
            "receipt_inspected": False,
        }])
        self.assertTrue(self.ledger.verify_integrity())
        denied = self.client.get(
            path, headers=self.bearer("synthetic-other", ("household",)),
        )
        self.assertEqual(denied.status_code, 404)

        stale_command = self.stage_command(
            action="DEMO-STAGE-OBS-STALE", revision=1,
        )
        corrected = self.client.post(
            ROOT, json=self.command(
                revision=1, action="DEMO-PROFILE-AFTER-STAGE",
                values={"field_alpha": "corrected", "field_choice": "sample-b"},
            ), headers=self.bearer(),
        )
        self.assertEqual(corrected.status_code, 201)
        history = self.client.get(path, headers=self.bearer())
        self.assertFalse(history.json()["observations"][0]["current"])
        self.assertEqual(history.json()["stage_progress"], [{
            "stage_ref": "DEMO-STAGE-01", "state": "HISTORICAL_RECEIPT",
            "observation_revision": 1,
            "receipt_inspected": False,
        }])
        stale = self.client.post(
            path, json=stale_command, headers=self.bearer(),
        )
        self.assertEqual(stale.status_code, 409)
        self.assertTrue(self.ledger.verify_integrity())

    def test_stage_observation_correction_appends_and_supersedes_one_current_receipt(self):
        path = ROOT.replace("/cultivation-inputs", "/stage-observations")
        self.assertEqual(self.client.post(
            ROOT, json=self.command(), headers=self.bearer(),
        ).status_code, 201)
        original = self.stage_command(action="DEMO-STAGE-ORIGINAL")
        first = self.client.post(path, json=original, headers=self.bearer())
        self.assertEqual(first.status_code, 201, first.text)
        correction = self.stage_command(action="DEMO-STAGE-CORRECTION", revision=1)
        correction["corrects_revision"] = 1
        correction["observation_artifact_digest"] = "d" * 64
        saved = self.client.post(path, json=correction, headers=self.bearer())
        self.assertEqual(saved.status_code, 201, saved.text)
        self.assertEqual(saved.json()["revision"], 2)
        replay = self.client.post(path, json=correction, headers=self.bearer())
        self.assertTrue(replay.json()["idempotent_replay"])
        conflict = self.stage_command(action="DEMO-STAGE-CORRECTION-2", revision=2)
        conflict["corrects_revision"] = 1
        self.assertEqual(self.client.post(
            path, json=conflict, headers=self.bearer(),
        ).status_code, 409)
        history = self.client.get(path, headers=self.bearer()).json()["observations"]
        self.assertEqual([item["revision"] for item in history], [1, 2])
        self.assertTrue(history[0]["is_superseded"])
        self.assertEqual(history[0]["superseded_by_revision"], 2)
        self.assertEqual(history[1]["corrects_revision"], 1)
        self.assertEqual(history[1]["case_version"], 2)
        self.assertEqual(history[1]["input_revision"], 1)
        self.assertTrue(self.ledger.verify_integrity())
        self.ledger = self.reopen()
        self.assertTrue(self.ledger.verify_integrity())

    def test_stage_observation_ui_uses_current_context_and_marks_old_receipts(self):
        self.assertEqual(self.client.post(
            ROOT, json=self.command(), headers=self.bearer(),
        ).status_code, 201)
        session = self.browser_session()
        path = PAGE.replace("/cultivation-inputs", "/stage-observations")
        intake = self.client.get(PAGE)
        self.assertIn(path, intake.text)
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("ثبت رسید مشاهده", page.text)
        self.assertIn('name="action_id"', page.text)
        self.assertIn("هنوز رسیدی ثبت نشده", page.text)
        values = self.stage_command()
        form = {
            "csrf": session.csrf,
            "action_id": "DEMO-STAGE-OBS-BROWSER-RETRY",
            "case_version": str(values["expected_case_version"]),
            "input_revision": str(values["expected_input_revision"]),
            "input_snapshot_digest": values["expected_input_snapshot_digest"],
            "plan_digest": values["expected_plan_digest"],
            "stage_ref": values["stage_ref"],
            "requirements_digest":
                values["expected_observation_requirements_digest"],
            "observation_revision": "0",
            "corrects_revision": "0",
            "artifact_digest": values["observation_artifact_digest"],
        }
        saved = self.client.post(
            path, content=urlencode(form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 303, saved.text)
        replay = self.client.post(
            path, content=urlencode(form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(replay.status_code, 303, replay.text)
        conflicting_replay = dict(form)
        conflicting_replay["artifact_digest"] = "d" * 64
        conflict = self.client.post(
            path, content=urlencode(conflicting_replay),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(conflict.status_code, 409)
        api_history = self.client.get(
            ROOT.replace("/cultivation-inputs", "/stage-observations"),
            headers=self.bearer(),
        )
        self.assertEqual(len(api_history.json()["observations"]), 1)
        correction_page = self.client.get(path + "?corrects_revision=1")
        self.assertEqual(correction_page.status_code, 200, correction_page.text)
        self.assertIn("اصلاح رسید شماره 1", correction_page.text)
        correction_form = dict(form)
        correction_form.update({
            "action_id": "DEMO-STAGE-OBS-BROWSER-CORRECTION",
            "observation_revision": "1", "corrects_revision": "1",
            "artifact_digest": "d" * 64,
        })
        correction_post = self.client.post(
            path, content=urlencode(correction_form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(correction_post.status_code, 303, correction_post.text)
        corrected_history = self.client.get(path)
        self.assertIn('با <a href="#observation-DEMO-STAGE-01-2">رسید 2</a> اصلاح شد',
                      corrected_history.text)
        self.assertIn('اصلاح <a href="#observation-DEMO-STAGE-01-1">نسخه 1</a>',
                      corrected_history.text)
        original_entry = corrected_history.text[
            corrected_history.text.index("نسخه 1"):
        ].split("</li>", 1)[0]
        self.assertNotIn("اصلاح رسید</a>", original_entry)
        current_page = self.client.get(path)
        self.assertIn("رسید جاری", current_page.text)
        self.assertIn("رسید جاری ثبت شده", current_page.text)
        self.assertTrue(self.ledger.verify_integrity())

        self.client.post(
            ROOT, json=self.command(
                revision=1, action="DEMO-PROFILE-UI-STAGE-2",
                values={"field_alpha": "updated", "field_choice": "sample-b"},
            ), headers=self.bearer(),
        )
        history = self.client.get(path)
        self.assertIn("رسید قدیمی", history.text)
        self.assertIn("فقط رسید تاریخی موجود است", history.text)
        self.assertNotIn("· رسید جاری ·", history.text)

    def test_assigned_specialist_reads_receipt_and_private_artifact(self):
        image = b"\x89PNG\r\n\x1a\n" + b"synthetic-stage-image"
        artifact = self.artifact_store.put(
            OWNER, REF + ":DEMO-STAGE-01", "image/png", image,
        )
        self.ledger.append_owned_profile(
            REF, Principal(OWNER, frozenset({"household"})),
            action_id="DEMO-PROFILE-1", expected_case_version=2,
            expected_revision=0,
            values={"field_alpha": "sample value", "field_choice": "sample-a"},
        )
        case_version, input_revision, input_digest = (
            self.ledger.internal_proposal_lineage(REF)
        )
        proposal = InternalCultivationProposal(
            household_case_ref=REF, household_case_version=case_version,
            household_input_revision=input_revision,
            household_input_snapshot_digest=input_digest,
            scientific_basis_manifest_digest="2" * 64,
            internal_model_artifact_digest="3" * 64,
            internal_run_ref="DEMO-RUN-STAGE-QUESTION",
            proposal_content_digest="4" * 64,
            proposed_stages=(ProposedCultivationStage(
                "DEMO-STAGE-01", "5" * 64, "6" * 64,
            ),),
        )
        specialist = "synthetic-agronomy-stage-reviewer"
        active = {"assigned"}
        workspace = SyntheticAgronomyWorkspace(
            self.ledger,
            (SyntheticAgronomyAssignment(REF, specialist, 2),),
            trusted_assignment_active=lambda actor, ref, version: (
                actor == specialist and ref == REF and version == 2
                and bool(active)
            ),
            proposal_fixtures=(proposal,),
        )
        app = create_app(
            self.config, self.flow,
            scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
            household_profile_schema=self.schema,
            household_profile_access_authority=self.allowed,
            household_stage_context_authority=self.stage_context,
            household_stage_artifact_store=self.artifact_store,
            agronomy_workspace=workspace,
        )
        client = TestClient(app, base_url=ORIGIN)
        command = self.stage_command()
        command["observation_artifact_digest"] = artifact.digest
        stage_api_path = (
            "/api/v1/domestic/household-intake/my-drafts/" + REF
            + "/stage-observations"
        )
        submitted = client.post(
            stage_api_path, json=command, headers=self.bearer(),
        )
        self.assertEqual(submitted.status_code, 201, submitted.text)

        specialist_headers = self.bearer(
            subject=specialist, roles=("agronomy_expert",),
        )
        api_path = (
            "/api/v1/agronomy/assigned-drafts/" + REF
            + "/stage-observations"
        )
        observed = client.get(api_path, headers=specialist_headers)
        self.assertEqual(observed.status_code, 200, observed.text)
        self.assertEqual(observed.json()["observations"][0][
            "observation_artifact_digest"
        ], artifact.digest)
        self.assertTrue(observed.json()["observations"][0]["current"])
        receipt = observed.json()["observations"][0]
        self.assertFalse(receipt["receipt_inspected"])
        question_path = (
            "/api/v1/agronomy/assigned-drafts/" + REF + "/review-questions"
        )
        stale_question = {
            "action_id": "DEMO-STAGE-QUESTION-STALE",
            "track": "HOUSEHOLD_INPUT_ADEQUACY",
            "expected_case_version": 2,
            "expected_input_revision": 1,
            "expected_question_revision": 0,
            "reason_ref": "DEMO-MISSING-REF",
            "evidence_ref": "DEMO-PENDING-REF",
            "stage_ref": "DEMO-STAGE-01",
            "expected_stage_observation_revision": receipt["revision"],
            "expected_stage_observation_receipt_digest": "0" * 64,
        }
        rejected_question = client.post(
            question_path, json=stale_question, headers=specialist_headers,
        )
        self.assertEqual(rejected_question.status_code, 409, rejected_question.text)
        direct_question = workspace.record_assigned_synthetic_review_question(
            REF, Principal(specialist, frozenset({"agronomy_expert"})),
            action_id="DEMO-STAGE-QUESTION-DIRECT",
            track="HOUSEHOLD_INPUT_ADEQUACY",
            expected_case_version=2, expected_input_revision=1,
            expected_question_revision=0,
            reason_ref="DEMO-MISSING-REF", evidence_ref="DEMO-PENDING-REF",
            stage_context_authority=self.stage_context,
            stage_ref="DEMO-STAGE-01",
            expected_stage_observation_revision=receipt["revision"],
            expected_stage_observation_receipt_digest=receipt["receipt_digest"],
        )
        self.assertEqual(direct_question["question_revision"], 1)
        with self.ledger._transaction() as db:
            self.ledger._verify(db)
        linked_question = client.post(
            question_path,
            json={**stale_question,
                  "action_id": "DEMO-STAGE-QUESTION-1",
                  "expected_question_revision": 1,
                  "expected_stage_observation_receipt_digest": receipt["receipt_digest"]},
            headers=specialist_headers,
        )
        self.assertEqual(linked_question.status_code, 201, linked_question.text)
        specialist_history = client.get(question_path, headers=specialist_headers)
        self.assertEqual(specialist_history.status_code, 200)
        linked_history = specialist_history.json()["questions"][0]
        self.assertEqual(linked_history["stage_ref"], "DEMO-STAGE-01")
        self.assertEqual(linked_history["stage_observation_revision"], 1)
        owner_questions = self.ledger.read_owned_question_responses(
            REF, Principal(OWNER, frozenset({"household"})),
        )
        self.assertEqual(owner_questions["questions"][0]["stage_ref"], "DEMO-STAGE-01")
        self.assertEqual(
            owner_questions["questions"][0]["stage_observation_receipt_digest"],
            receipt["receipt_digest"],
        )
        owner_reply = self.ledger.append_owned_question_response(
            REF, Principal(OWNER, frozenset({"household"})),
            action_id="DEMO-STAGE-QUESTION-REPLY",
            track="HOUSEHOLD_INPUT_ADEQUACY",
            expected_question_revision=2, expected_case_version=2,
            expected_input_revision=1, answer_ref="DEMO-ANSWER-REF",
            evidence_ref="DEMO-ANSWER-EVIDENCE",
        )
        self.assertEqual(owner_reply["record_state"], "SYNTHETIC_RESPONSE_RECEIVED_NOT_REVIEWED")
        owner_questions = self.ledger.read_owned_question_responses(
            REF, Principal(OWNER, frozenset({"household"})),
        )
        self.assertEqual(
            owner_questions["questions"][1]["response_state"],
            "HISTORICAL_RESPONSE_ONLY_NOT_REVIEWED",
        )
        specialist_history = workspace.read_assigned_synthetic_review_questions(
            REF, Principal(specialist, frozenset({"agronomy_expert"})),
        )
        self.assertTrue(
            specialist_history["questions"][1]["synthetic_household_response_received"]
        )
        self.assertNotIn("DEMO-ANSWER-REF", repr(specialist_history))
        inspection_path = api_path + "/inspections"
        inspection = {
            "action_id": "DEMO-STAGE-INSPECT-1",
            "expected_case_version": 2,
            "stage_ref": "DEMO-STAGE-01",
            "expected_observation_revision": receipt["revision"],
            "expected_observation_receipt_digest": receipt["receipt_digest"],
        }
        self.assertEqual(client.post(
            inspection_path, json=inspection,
        ).status_code, 401)
        inspected = client.post(
            inspection_path, json=inspection, headers=specialist_headers,
        )
        self.assertEqual(inspected.status_code, 201, inspected.text)
        self.assertEqual(
            inspected.json()["record_state"],
            "SYNTHETIC_STAGE_RECEIPT_INSPECTED_NOT_REVIEWED",
        )
        self.assertFalse(inspected.json()["review_completed"])
        self.assertFalse(inspected.json()["stage_completed"])
        self.assertTrue(client.post(
            inspection_path, json=inspection, headers=specialist_headers,
        ).json()["idempotent_replay"])
        owner_history = client.get(
            "/api/v1/domestic/household-intake/my-drafts/" + REF
            + "/stage-observations",
            headers=self.bearer(),
        )
        self.assertTrue(owner_history.json()["observations"][0][
            "receipt_inspected"
        ])
        self.assertTrue(owner_history.json()["stage_progress"][0][
            "receipt_inspected"
        ])

        second_observation = self.stage_command(
            action="DEMO-STAGE-OBS-2", revision=1,
        )
        second_observation["observation_artifact_digest"] = artifact.digest
        self.assertEqual(client.post(
            stage_api_path, json=second_observation, headers=self.bearer(),
        ).status_code, 201)
        artifact_path = (
            api_path + "/artifacts/DEMO-STAGE-01/" + artifact.digest
        )
        downloaded = client.get(artifact_path, headers=specialist_headers)
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.content, image)
        self.assertEqual(
            downloaded.headers["content-disposition"],
            'attachment; filename="stage-observation"',
        )

        sid = secrets.token_urlsafe(40)
        csrf = secrets.token_urlsafe(32)
        self.sessions.sessions[sid] = BrowserSession(
            specialist, frozenset({"agronomy_expert"}),
            self.token(specialist, ("agronomy_expert",)),
            csrf, int(time.time()) + 300,
        )
        client.cookies.set("__Host-ronas_session", sid)
        question_page = client.get(
            "/agronomy/assigned-drafts/" + REF + "/review-questions",
        )
        self.assertEqual(question_page.status_code, 200, question_page.text)
        self.assertIn("پرسش درباره رسید جاری DEMO-STAGE-01", question_page.text)
        self.assertIn(
            "/agronomy/assigned-drafts/" + REF
            + "/stage-observations#observation-DEMO-STAGE-01-1",
            question_page.text,
        )
        page_path = "/agronomy/assigned-drafts/" + REF + "/stage-observations"
        page = client.get(page_path)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('id="observation-DEMO-STAGE-01-2"', page.text)
        self.assertIn("نسخه پرونده 2 · نسخه اطلاعات خانوار 1", page.text)
        self.assertIn("نسخه اطلاعات خانوار 1", page.text)
        self.assertIn("DEMO-STAGE-01", page.text)
        self.assertIn("دریافت فایل مشاهده", page.text)
        self.assertIn("ثبت مشاهده رسید (بدون بررسی)", page.text)
        form = {
            "csrf": csrf, "case_version": "2",
            "stage_ref": "DEMO-STAGE-01",
            "observation_revision": "2",
            "receipt_digest": client.get(api_path, headers=specialist_headers)
                .json()["observations"][1]["receipt_digest"],
        }
        browser_post = client.post(
            page_path + "/inspect", content=urlencode(form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(browser_post.status_code, 303, browser_post.text)
        inspected_page = client.get(page_path)
        self.assertIn("رسید مشاهده شد (بدون داوری تخصصی)", inspected_page.text)
        self.assertIn("رسید مشاهده شد (بدون داوری)", inspected_page.text)
        self.assertNotIn("ثبت مشاهده رسید (بدون بررسی)", inspected_page.text)
        refreshed = client.get(api_path, headers=specialist_headers).json()
        self.assertTrue(refreshed["stage_progress"][0]["receipt_inspected"])
        browser_download = client.get(
            page_path + "/artifacts/DEMO-STAGE-01/" + artifact.digest,
        )
        self.assertEqual(browser_download.status_code, 200, browser_download.text)
        self.assertEqual(browser_download.content, image)

        active.clear()
        self.assertEqual(client.post(
            inspection_path, json={**inspection,
                                   "action_id": "DEMO-STAGE-INSPECT-REVOKED",
                                   "expected_observation_revision": 2},
            headers=specialist_headers,
        ).status_code, 404)
        self.assertEqual(
            client.get(api_path, headers=specialist_headers).status_code, 404,
        )
        self.assertEqual(
            client.get(artifact_path, headers=specialist_headers).status_code, 404,
        )
        self.assertTrue(self.ledger.verify_integrity())

    def test_browser_upload_stores_real_file_then_records_and_downloads_receipt(self):
        self.assertEqual(self.client.post(
            ROOT, json=self.command(), headers=self.bearer(),
        ).status_code, 201)
        self.client = TestClient(
            self.make_app(artifact_store=self.artifact_store), base_url=ORIGIN,
        )
        session = self.browser_session()
        page_path = PAGE.replace("/cultivation-inputs", "/stage-observations")
        page = self.client.get(page_path)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('type="file"', page.text)
        self.assertIn("ronas-stage-observation-upload.js", page.text)
        self.assertNotIn('name="artifact_digest" type="text"', page.text)
        upload_script = self.client.get(
            "/assets/ronas-stage-observation-upload.js",
        )
        self.assertEqual(upload_script.status_code, 200)
        self.assertIn("application/pdf", upload_script.text)
        self.assertIn("اطلاعات پرونده یا طرح تغییر کرده", upload_script.text)
        self.assertIn("digest.value = ''", upload_script.text)
        upload_path = page_path + "/artifacts"
        image = b"\x89PNG\r\n\x1a\n" + b"synthetic-stage-image"
        upload_headers = {
            "Origin": ORIGIN, "X-CSRF-Token": session.csrf,
            "Content-Type": "image/png", "X-Ronas-Case-Version": "2",
            "X-Ronas-Input-Revision": "1",
            "X-Ronas-Plan-Digest": self.stage_plan_digest,
            "X-Ronas-Stage-Ref": "DEMO-STAGE-01",
            "X-Ronas-Requirements-Digest": "a" * 64,
        }
        denied_csrf = dict(upload_headers, **{"X-CSRF-Token": "invalid"})
        self.assertEqual(self.client.put(
            upload_path, content=image, headers=denied_csrf,
        ).status_code, 403)
        stale_context = dict(upload_headers, **{"X-Ronas-Plan-Digest": "f" * 64})
        self.assertEqual(self.client.put(
            upload_path, content=image, headers=stale_context,
        ).status_code, 409)
        uploaded = self.client.put(upload_path, content=image, headers=upload_headers)
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        digest = uploaded.json()["digest"]
        self.assertEqual(digest, hashlib.sha256(image).hexdigest())
        self.assertTrue(self.artifact_store.contains(
            OWNER, REF + ":DEMO-STAGE-01", digest,
        ))
        form = {
            "csrf": session.csrf, "action_id": "DEMO-STAGE-OBS-UPLOAD-RETRY",
            "case_version": "2", "input_revision": "1",
            "input_snapshot_digest": self.ledger.internal_proposal_lineage(REF)[2],
            "plan_digest": self.stage_plan_digest, "stage_ref": "DEMO-STAGE-01",
            "requirements_digest": "a" * 64, "observation_revision": "0",
            "corrects_revision": "0",
            "artifact_digest": digest,
        }
        missing = dict(form, artifact_digest="d" * 64)
        rejected = self.client.post(
            page_path, content=urlencode(missing),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(rejected.status_code, 422)
        saved = self.client.post(
            page_path, content=urlencode(form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 303, saved.text)
        history = self.client.get(page_path)
        self.assertIn("دریافت فایل", history.text)
        download_path = (
            "/my-drafts/" + REF
            + "/stage-observations/artifacts/DEMO-STAGE-01/" + digest
        )
        self.assertIn(download_path, history.text)
        downloaded = self.client.get(download_path)
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.content, image)
        self.assertEqual(downloaded.headers["cache-control"], "no-store")
        self.assertEqual(downloaded.headers["x-content-type-options"], "nosniff")
        unlinked = self.client.get(
            "/my-drafts/" + REF
            + "/stage-observations/artifacts/DEMO-STAGE-01/" + "d" * 64,
        )
        self.assertEqual(unlinked.status_code, 404)
        other = TestClient(
            self.make_app(artifact_store=self.artifact_store), base_url=ORIGIN,
        )
        self.assertEqual(other.get(download_path).status_code, 401)
        self.browser_session(subject="synthetic-other")
        self.assertEqual(self.client.get(download_path).status_code, 404)
        self.assertTrue(self.ledger.verify_integrity())

    def test_stage_observation_is_not_offered_without_current_plan(self):
        self.assertEqual(self.client.post(
            ROOT, json=self.command(), headers=self.bearer(),
        ).status_code, 201)
        self.stage_plan_available = False
        page = self.client.get(
            ROOT.replace("/cultivation-inputs", "/stage-observations"),
            headers=self.bearer(),
        )
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["state"], "NO_CURRENT_PLAN")
        self.assertEqual(page.json()["observations"], [])
        self.assertEqual(
            self.client.post(
                ROOT.replace("/cultivation-inputs", "/stage-observations"),
                json=self.stage_command(), headers=self.bearer(),
            ).status_code, 409,
        )

    def test_idempotent_replay_stale_revision_and_invalid_schema_values(self):
        command = self.command()
        one = self.client.post(ROOT, json=command, headers=self.bearer())
        self.assertEqual(one.status_code, 201)
        replay = self.client.post(ROOT, json=command, headers=self.bearer())
        self.assertEqual(replay.status_code, 201)
        self.assertTrue(replay.json()["idempotent_replay"])
        stale = self.client.post(
            ROOT, json=self.command(action="DEMO-PROFILE-STALE"),
            headers=self.bearer(),
        )
        self.assertEqual(stale.status_code, 409)
        invalid = self.client.post(
            ROOT, json=self.command(
                revision=1, action="DEMO-PROFILE-BAD",
                values={"field_alpha": "x", "field_choice": "unknown"},
            ), headers=self.bearer(),
        )
        self.assertEqual(invalid.status_code, 422)
        unknown = self.client.post(
            ROOT, json=self.command(
                revision=1, action="DEMO-PROFILE-EXTRA",
                values={"field_alpha": "x", "field_choice": "", "real_secret": "no"},
            ), headers=self.bearer(),
        )
        self.assertEqual(unknown.status_code, 422)

    def test_case_owner_role_and_external_access_authority_are_checked(self):
        for subject, roles in (
            ("synthetic-other", ("household",)),
            (OWNER, ("domestic_ops",)),
            (OWNER, ("export_ops",)),
        ):
            response = self.client.get(ROOT, headers=self.bearer(subject, roles))
            self.assertIn(response.status_code, (403, 404))
        self.assertEqual(
            self.client.get(ROOT.replace(REF, "DEMO-E-PROFILE"),
                            headers=self.bearer()).status_code,
            404,
        )
        denied_app = create_app(
            self.config, self.flow, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
            household_profile_schema=self.schema,
            household_profile_access_authority=lambda *_: False,
        )
        denied = TestClient(denied_app, base_url=ORIGIN)
        self.assertEqual(denied.get(ROOT, headers=self.bearer()).status_code, 403)
        self.assertEqual(
            denied.post(ROOT, json=self.command(), headers=self.bearer()).status_code,
            403,
        )

    def test_mutation_requires_bearer_not_browser_cookie(self):
        self.browser_session()
        response = self.client.post(ROOT, json=self.command())
        self.assertEqual(response.status_code, 401)

    def test_existing_user_shell_renders_schema_safely_and_saves_with_csrf(self):
        session = self.browser_session()
        page = self.client.get(PAGE)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("اطلاعات ساختاریافته پرونده کشت", page.text)
        self.assertIn("فیلد آزمایشی &lt;الف&gt;", page.text)
        self.assertNotIn("فیلد آزمایشی <الف>", page.text)
        rendered_action = re.search(
            r'name="action_id" value="(DEMO-PROFILE-[A-Z0-9]+)"', page.text,
        )
        self.assertIsNotNone(rendered_action)
        form = {
            "csrf": session.csrf, "action_id": rendered_action.group(1),
            "case_version": "2", "profile_revision": "0",
            "field_alpha": "sample ui value", "field_choice": "sample-a",
        }
        saved = self.client.post(
            PAGE, content=urlencode(form),
            headers={"Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 303, saved.text)
        replay = self.client.post(
            PAGE, content=urlencode(form),
            headers={"Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(replay.status_code, 303, replay.text)
        conflicting_replay = self.client.post(
            PAGE, content=urlencode({**form, "field_alpha": "changed payload"}),
            headers={"Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(conflicting_replay.status_code, 409, conflicting_replay.text)
        shown = self.client.get(PAGE)
        self.assertIn("sample ui value", shown.text)
        history_path = PAGE + "/revisions/1"
        self.assertIn(history_path, shown.text)
        self.client.post(
            ROOT, json=self.command(
                revision=1, action="DEMO-PROFILE-UI-HISTORY-2",
                values={"field_alpha": "newer synthetic value",
                        "field_choice": "sample-b"},
            ), headers=self.bearer(),
        )
        history = self.client.get(history_path)
        self.assertEqual(history.status_code, 200, history.text)
        self.assertIn("sample ui value", history.text)
        self.assertNotIn("newer synthetic value", history.text)
        self.assertIn("/cultivation-inputs/compare", self.client.get(PAGE).text)
        comparison = self.client.get(
            PAGE + "/compare?before_revision=1&after_revision=2",
        )
        self.assertEqual(comparison.status_code, 200, comparison.text)
        self.assertIn("sample ui value", comparison.text)
        self.assertIn("newer synthetic value", comparison.text)
        self.assertIn("گزینه", comparison.text)
        self.assertEqual(self.client.get(
            PAGE + "/compare?before_revision=2&after_revision=1",
        ).status_code, 422)
        restore_page = self.client.get(PAGE + "/revisions/1")
        self.assertEqual(restore_page.status_code, 200, restore_page.text)
        self.assertIn("ثبت این مقادیر به‌عنوان نسخه جدید", restore_page.text)
        restore_action = re.search(
            r'name="action_id" value="(DEMO-RESTORE-[A-Z0-9]+)"',
            restore_page.text,
        )
        expected_revision = re.search(
            r'name="expected_profile_revision" value="(\d+)"',
            restore_page.text,
        )
        self.assertIsNotNone(restore_action)
        self.assertIsNotNone(expected_revision)
        restore_form = {
            "csrf": session.csrf, "action_id": restore_action.group(1),
            "case_version": "2",
            "expected_profile_revision": expected_revision.group(1),
        }
        restore_path = PAGE + "/revisions/1/restore"
        restored = self.client.post(
            restore_path, content=urlencode(restore_form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(restored.status_code, 303, restored.text)
        current_profile = self.ledger.read_owned_profile(
            REF, Principal(OWNER, frozenset({"household"})),
        )
        self.assertEqual(current_profile["current_revision"], 3)
        self.assertEqual(current_profile["current_values"], {
            "field_alpha": "sample ui value", "field_choice": "sample-a",
        })
        replay_restore = self.client.post(
            restore_path, content=urlencode(restore_form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(replay_restore.status_code, 303, replay_restore.text)
        stale_restore_page = self.client.get(PAGE + "/revisions/2")
        stale_action = re.search(
            r'name="action_id" value="(DEMO-RESTORE-[A-Z0-9]+)"',
            stale_restore_page.text,
        )
        stale_revision = re.search(
            r'name="expected_profile_revision" value="(\d+)"',
            stale_restore_page.text,
        )
        self.ledger.append_owned_profile(
            REF, Principal(OWNER, frozenset({"household"})),
            action_id="DEMO-PROFILE-RESTORE-CONCURRENT",
            expected_case_version=2, expected_revision=3,
            values={"field_alpha": "concurrent update", "field_choice": "sample-b"},
        )
        stale_restore = self.client.post(
            PAGE + "/revisions/2/restore",
            content=urlencode({
                "csrf": session.csrf, "action_id": stale_action.group(1),
                "case_version": "2",
                "expected_profile_revision": stale_revision.group(1),
            }),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(stale_restore.status_code, 409, stale_restore.text)
        bad = dict(form, csrf="wrong")
        rejected = self.client.post(
            PAGE, content=urlencode(bad),
            headers={"Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(rejected.status_code, 403)

    def test_default_app_has_no_profile_routes_and_schema_change_hides_old_values(self):
        default = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(default.get(ROOT).status_code, 404)
        self.assertEqual(default.post(ROOT, json=self.command()).status_code, 404)
        self.client.post(ROOT, json=self.command(), headers=self.bearer())
        self.client.post(
            ROOT, json=self.command(
                revision=1, action="DEMO-PROFILE-SCHEMA-CHANGE-2",
                values={"field_alpha": "second old-schema value",
                        "field_choice": "sample-b"},
            ), headers=self.bearer(),
        )
        changed = HouseholdInputSchema(
            "RONAS-DOMESTIC-INPUT", 2,
            (HouseholdInputField("other_field", "فیلد جدید"),),
        )
        changed_ledger = SqliteSyntheticHouseholdProfileLedger(
            self.path, self.records, profile_schema=changed,
            trusted_revoke_authorizer=lambda *_: False,
            trusted_human_review_authorizer=lambda *_: False,
        )
        view = changed_ledger.read_owned_profile(
            REF, Principal(OWNER, frozenset({"household"})),
        )

        self.assertTrue(view["schema_changed"])
        self.assertEqual(view["current_values"], {})
        old_revision = changed_ledger.read_owned_profile_revision(
            REF, Principal(OWNER, frozenset({"household"})), 1,
        )
        self.assertTrue(old_revision["schema_changed"])
        self.assertEqual(old_revision["values"], {})
        comparison = changed_ledger.compare_owned_profile_revisions(
            REF, Principal(OWNER, frozenset({"household"})), 1, 2,
        )
        self.assertTrue(comparison["schema_changed"])
        self.assertEqual(comparison["changes"], [])

    def test_profile_revision_comparison_is_owner_scoped_ordered_and_audited(self):
        owner = Principal(OWNER, frozenset({"household"}))
        first = self.ledger.append_owned_profile(
            REF, owner, action_id="DEMO-PROFILE-COMPARE-1",
            expected_case_version=2, expected_revision=0,
            values={"field_alpha": "private before", "field_choice": "sample-a"},
        )
        self.ledger.append_owned_profile(
            REF, owner, action_id="DEMO-PROFILE-COMPARE-2",
            expected_case_version=2, expected_revision=1,
            values={"field_alpha": "private after", "field_choice": "sample-a"},
        )
        result = self.ledger.compare_owned_profile_revisions(REF, owner, 1, 2)
        self.assertEqual(first["profile_revision"], 1)
        self.assertEqual(result["changes"], [{
            "key": "field_alpha", "before": "private before", "after": "private after",
        }])
        self.assertIsNone(self.ledger.compare_owned_profile_revisions(
            REF, Principal("synthetic-other", frozenset({"household"})), 1, 2,
        ))
        self.assertIsNone(self.ledger.compare_owned_profile_revisions(REF, owner, 1, 3))
        with self.assertRaises(ValueError):
            self.ledger.compare_owned_profile_revisions(REF, owner, 2, 1)
        self.assertTrue(self.ledger.verify_integrity())

    def test_tampered_profile_history_fails_closed(self):
        self.client.post(ROOT, json=self.command(), headers=self.bearer())
        with self.ledger._transaction() as db:
            db.execute("DROP TRIGGER household_profile_no_update")
            db.execute(
                "UPDATE household_profile_revision SET values_json=? WHERE ref=?",
                ('{"field_alpha":"tampered"}', REF),
            )
        self.assertEqual(self.client.get(ROOT, headers=self.bearer()).status_code, 503)


    def test_internal_runtime_lineage_requires_current_profile_and_hides_values(self):
        self.assertIsNone(self.ledger.internal_proposal_lineage(REF))
        owner = Principal(OWNER, frozenset({"household"}))
        self.ledger.append_owned_profile(
            REF, owner, action_id="DEMO-PROFILE-RUNTIME-1",
            expected_case_version=2, expected_revision=0,
            values={"field_alpha": "private synthetic value",
                    "field_choice": "sample-a"},
        )
        lineage = self.ledger.internal_proposal_lineage(REF)
        self.assertEqual(lineage[0:2], (2, 1))
        self.assertEqual(len(lineage[2]), 64)
        self.assertNotIn("private synthetic value", repr(lineage))

        class BasisAuthority:
            def read_current_basis(self, case_ref, run_ref):
                return ProposalRuntimeBasis(case_ref, 2, "2" * 64, "3" * 64)

        authority = ProfileBackedProposalContextAuthority(self.ledger, BasisAuthority())
        context = authority.read_current_context(REF, "DEMO-RUN-PROFILE-1")
        self.assertEqual(context.input_revision, 1)
        self.assertEqual(context.input_snapshot_digest, lineage[2])
        self.assertFalse(hasattr(context, "input_values"))

    def test_profile_lineage_flows_to_existing_assigned_specialist_handoff(self):
        owner = Principal(OWNER, frozenset({"household"}))
        self.ledger.append_owned_profile(
            REF, owner, action_id="DEMO-PROFILE-SPECIALIST-1",
            expected_case_version=2, expected_revision=0,
            values={"field_alpha": "private synthetic value",
                    "field_choice": "sample-a"},
        )
        case_version, profile_revision, snapshot_digest = (
            self.ledger.internal_proposal_lineage(REF)
        )
        proposal = InternalCultivationProposal(
            household_case_ref=REF, household_case_version=case_version,
            household_input_revision=profile_revision,
            household_input_snapshot_digest=snapshot_digest,
            scientific_basis_manifest_digest="2" * 64,
            internal_model_artifact_digest="3" * 64,
            internal_run_ref="DEMO-RUN-SPECIALIST-1",
            proposal_content_digest="4" * 64,
            proposed_stages=(ProposedCultivationStage(
                "DEMO-STAGE-PROFILE", "5" * 64, "6" * 64,
            ),),
        )
        specialist = "synthetic-agronomist-profile"
        workspace = SyntheticAgronomyWorkspace(
            self.ledger,
            (SyntheticAgronomyAssignment(REF, specialist, case_version),),
            trusted_assignment_active=lambda subject, ref, version: (
                subject == specialist and ref == REF and version == case_version
            ),
            proposal_fixtures=(proposal,),
        )
        app = create_app(
            self.config, self.flow, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger, agronomy_workspace=workspace,
            household_profile_schema=self.schema,
            household_profile_access_authority=self.allowed,
        )
        client = TestClient(app, base_url=ORIGIN)
        specialist_root = "/api/v1/agronomy/assigned-drafts/" + REF
        first = client.get(
            specialist_root + "/internal-plan-proposal",
            headers=self.bearer(specialist, ("agronomy_expert",)),
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["input_revision"], 1)
        self.assertEqual(first.json()["proposed_stage_refs"], ["DEMO-STAGE-PROFILE"])
        self.assertNotIn("private synthetic value", first.text)

        self.ledger.append_owned_profile(
            REF, owner, action_id="DEMO-PROFILE-SPECIALIST-2",
            expected_case_version=2, expected_revision=1,
            values={"field_alpha": "private corrected synthetic value",
                    "field_choice": "sample-b"},
        )
        stale = client.get(
            specialist_root + "/internal-plan-proposal",
            headers=self.bearer(specialist, ("agronomy_expert",)),
        )
        self.assertEqual(stale.status_code, 503, stale.text)
        self.assertNotIn("DEMO-STAGE-PROFILE", stale.text)
        self.assertNotIn("private corrected synthetic value", stale.text)

    def test_profile_correction_during_internal_generation_discards_proposal(self):
        owner = Principal(OWNER, frozenset({"household"}))
        self.ledger.append_owned_profile(
            REF, owner, action_id="DEMO-PROFILE-RACE-1",
            expected_case_version=2, expected_revision=0,
            values={"field_alpha": "synthetic before", "field_choice": "sample-a"},
        )

        class BasisAuthority:
            def read_current_basis(self, case_ref, run_ref):
                return ProposalRuntimeBasis(case_ref, 2, "2" * 64, "3" * 64)

        authority = ProfileBackedProposalContextAuthority(self.ledger, BasisAuthority())

        class CorrectingAdapter:
            def __init__(self):
                self.contexts = []

            def generate(self, context):
                self.contexts.append(context)
                stages = (CandidateStage("DEMO-STAGE-PROFILE", "5" * 64, "6" * 64),)
                output = CandidateOutput(
                    context.model_artifact_digest,
                    candidate_structure_digest(context.model_artifact_digest, stages),
                    stages,
                )
                self.ledger.append_owned_profile(
                    REF, owner, action_id="DEMO-PROFILE-RACE-2",
                    expected_case_version=2, expected_revision=1,
                    values={"field_alpha": "synthetic corrected", "field_choice": "sample-b"},
                )
                return output

        adapter = CorrectingAdapter()
        adapter.ledger = self.ledger
        with self.assertRaises(ProposalRuntimeStale):
            run_current_synthetic_internal_proposal(
                REF, "DEMO-RUN-PROFILE-1", authority, adapter,
            )
        self.assertEqual(len(adapter.contexts), 1)
        self.assertEqual(adapter.contexts[0].input_revision, 1)
        self.assertEqual(self.ledger.internal_proposal_lineage(REF)[:2], (2, 2))


    def test_surplus_draft_api_enforces_bearer_owner_and_revision(self):
        ledger = SqliteSyntheticSurplusDraftLedger(
            str(self.path.parent / "surplus-drafts.sqlite3"),
            self.schema, self.allowed,
        )
        client = TestClient(
            self.make_app(surplus_draft_ledger=ledger), base_url=ORIGIN,
        )
        path = (
            f"/api/v1/domestic/household-intake/my-drafts/{REF}"
            "/surplus-offers/DEMO-OFFER-API-1"
        )
        disabled = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(disabled.get(path).status_code, 404)
        self.assertEqual(disabled.put(path, json={}).status_code, 404)
        command = {
            "action_id": "DEMO-OFFER-API-A1",
            "expected_revision": 0,
            "values": {"field_alpha": "synthetic product", "field_choice": "sample-a"},
        }
        created = client.put(path, json=command, headers=self.bearer())
        self.assertEqual(created.status_code, 201, created.text)
        self.assertFalse(created.json()["published"])
        self.assertFalse(created.json()["real_data"])
        self.assertNotIn("producer_subject", created.json())
        self.assertEqual(created.json()["revision"], 1)
        read = client.get(path, headers=self.bearer())
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()["values"], command["values"])
        other = client.get(
            path, headers=self.bearer("synthetic-other", ("household",)),
        )
        self.assertEqual(other.status_code, 404)
        stale = dict(command, action_id="DEMO-OFFER-API-A2")
        self.assertEqual(
            client.put(path, json=stale, headers=self.bearer()).status_code, 409,
        )
        session = self.browser_session()
        sid = next(key for key, value in self.sessions.sessions.items()
                   if value is session)
        client.cookies.set("__Host-ronas_session", sid)
        cookie_only = client.put(path, json=stale)
        self.assertEqual(cookie_only.status_code, 401)

    def test_surplus_draft_history_exposes_only_same_schema_revision_diffs(self):
        ledger = SqliteSyntheticSurplusDraftLedger(
            str(self.path.parent / "surplus-draft-diffs.sqlite3"),
            self.schema, self.allowed,
        )
        client = TestClient(
            self.make_app(surplus_draft_ledger=ledger), base_url=ORIGIN,
        )
        owner = Principal(OWNER, frozenset({"household"}))
        offer_ref = "DEMO-OFFER-DIFF-1"
        first = {"field_alpha": "initial product", "field_choice": "sample-a"}
        ledger.save(owner, REF, offer_ref, action_id="DEMO-DIFF-A1",
                    expected_revision=0, values=first)
        ledger.save(owner, REF, offer_ref, action_id="DEMO-DIFF-A2",
                    expected_revision=1, values=dict(first))
        ledger.save(
            owner, REF, offer_ref, action_id="DEMO-DIFF-A3",
            expected_revision=2,
            values={"field_alpha": "revised product", "field_choice": "sample-a"},
        )

        api_path = (
            f"/api/v1/domestic/household-intake/my-drafts/{REF}"
            f"/surplus-offers/{offer_ref}/revisions"
        )
        response = client.get(api_path, headers=self.bearer())
        self.assertEqual(response.status_code, 200, response.text)
        history = response.json()
        self.assertEqual(
            history["contract_version"], "ronas.domestic.surplus-draft-history.v2",
        )
        revisions = history["revisions"]
        self.assertTrue(revisions[0]["diff_available"])
        self.assertEqual(revisions[0]["changes"], [
            {"field": "field_alpha", "before": None, "after": "initial product"},
            {"field": "field_choice", "before": None, "after": "sample-a"},
        ])
        self.assertEqual(revisions[1]["changes"], [])
        self.assertEqual(revisions[2]["changes"], [
            {"field": "field_alpha", "before": "initial product",
             "after": "revised product"},
        ])
        denied = client.get(
            api_path, headers=self.bearer("synthetic-other-owner", ("household",)),
        )
        self.assertEqual(denied.status_code, 404)

        session = self.browser_session()
        sid = next(key for key, value in self.sessions.sessions.items()
                   if value is session)
        client.cookies.set("__Host-ronas_session", sid)
        page_path = f"/my-drafts/{REF}/surplus-offers/{offer_ref}/revisions"
        page = client.get(page_path)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("تفاوت با نسخهٔ قبل", page.text)
        self.assertIn("initial product", page.text)
        self.assertIn("revised product", page.text)
        self.assertIn("در این نسخه تغییری نسبت به نسخهٔ قبل ثبت نشده است", page.text)
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.assertEqual(len(ledger.history_owned(owner, REF, offer_ref)), 3)

    def test_surplus_draft_api_fails_closed_on_tampered_receipt_chain(self):
        ledger = SqliteSyntheticSurplusDraftLedger(
            str(self.path.parent / "surplus-drafts-tampered.sqlite3"),
            self.schema, self.allowed,
        )
        client = TestClient(
            self.make_app(surplus_draft_ledger=ledger), base_url=ORIGIN,
        )
        path = (
            f"/api/v1/domestic/household-intake/my-drafts/{REF}"
            "/surplus-offers/DEMO-OFFER-TAMPER-1"
        )
        command = {
            "action_id": "DEMO-OFFER-TAMPER-A1",
            "expected_revision": 0,
            "values": {"field_alpha": "synthetic product",
                       "field_choice": "sample-a"},
        }
        created = client.put(path, json=command, headers=self.bearer())
        self.assertEqual(created.status_code, 201, created.text)
        with ledger._connect() as db:
            db.execute("DROP TRIGGER surplus_draft_revision_no_update")
            db.execute(
                "UPDATE domestic_surplus_draft_revision SET values_json=? "
                "WHERE action_id=?",
                ('{"field_alpha":"tampered private value",'
                 '"field_choice":"sample-a"}', command["action_id"]),
            )

        read = client.get(path, headers=self.bearer())
        self.assertEqual(read.status_code, 503, read.text)
        self.assertEqual(read.json()["detail"], "DRAFT_INTEGRITY_FAILURE")
        self.assertNotIn("tampered private value", read.text)
        update = dict(
            command, action_id="DEMO-OFFER-TAMPER-A2", expected_revision=1,
            values={"field_alpha": "another synthetic value",
                    "field_choice": "sample-b"},
        )
        saved = client.put(path, json=update, headers=self.bearer())
        self.assertEqual(saved.status_code, 503, saved.text)
        self.assertEqual(saved.json()["detail"], "DRAFT_INTEGRITY_FAILURE")
        with ledger._connect() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM domestic_surplus_draft_revision "
                "WHERE household_ref=? AND offer_ref=?",
                (REF, "DEMO-OFFER-TAMPER-1"),
            ).fetchone()[0], 1)

    def test_surplus_draft_list_is_owner_scoped_and_redacts_private_values(self):
        def list_owner_authority(principal, ref, schema_ref):
            return (self.allowed(principal, ref, schema_ref)
                    and principal.subject == OWNER and ref == REF)

        ledger = SqliteSyntheticSurplusDraftLedger(
            str(self.path.parent / "surplus-draft-list.sqlite3"),
            self.schema, list_owner_authority,
        )
        app = create_app(
            self.config, self.flow, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
            household_profile_schema=self.schema,
            household_profile_access_authority=list_owner_authority,
            household_surplus_draft_ledger=ledger,
        )
        client = TestClient(app, base_url=ORIGIN)
        owner = Principal(OWNER, frozenset({"household"}))
        ledger.save(
            owner, REF, "DEMO-OFFER-LIST-1", action_id="DEMO-LIST-A1",
            expected_revision=0,
            values={"field_alpha": "SECRET PRIVATE TOMATO", "field_choice": "sample-a"},
        )
        ledger.save(
            owner, REF, "DEMO-OFFER-LIST-2", action_id="DEMO-LIST-B1",
            expected_revision=0,
            values={"field_alpha": "SECOND SECRET VALUE", "field_choice": "sample-b"},
        )
        api_path = (
            f"/api/v1/domestic/household-intake/my-drafts/{REF}/surplus-offers"
        )
        response = client.get(api_path, headers=self.bearer())
        self.assertEqual(response.status_code, 200, response.text)
        listed = response.json()["offers"]
        self.assertEqual([item["offer_ref"] for item in listed],
                         ["DEMO-OFFER-LIST-1", "DEMO-OFFER-LIST-2"])
        self.assertEqual([item["revision"] for item in listed], [1, 1])
        self.assertTrue(all(item["published"] is False for item in listed))
        self.assertNotIn("values", response.json())
        self.assertNotIn("producer_subject", response.text)
        self.assertNotIn("SECRET PRIVATE TOMATO", response.text)
        self.assertNotIn("SECOND SECRET VALUE", response.text)
        denied = client.get(
            api_path, headers=self.bearer("synthetic-other-owner", ("household",)),
        )
        self.assertEqual(denied.status_code, 404)
        disabled = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(disabled.get(api_path, headers=self.bearer()).status_code, 404)

        session = self.browser_session()
        sid = next(key for key, value in self.sessions.sessions.items()
                   if value is session)
        client.cookies.set("__Host-ronas_session", sid)
        ui = client.get(f"/my-drafts/{REF}/surplus-offers")
        self.assertEqual(ui.status_code, 200, ui.text)
        self.assertIn("DEMO-OFFER-LIST-1", ui.text)
        self.assertIn("DEMO-OFFER-LIST-2", ui.text)
        self.assertIn("نسخه 1", ui.text)
        self.assertNotIn("SECRET PRIVATE TOMATO", ui.text)
        self.assertNotIn("SECOND SECRET VALUE", ui.text)
        self.assertEqual(ui.headers["cache-control"], "no-store")

    def test_household_starts_surplus_draft_without_entering_offer_id(self):
        ledger = SqliteSyntheticSurplusDraftLedger(
            str(self.path.parent / "surplus-draft-onboarding.sqlite3"),
            self.schema, self.allowed,
        )
        client = TestClient(
            self.make_app(surplus_draft_ledger=ledger), base_url=ORIGIN,
        )
        session = self.browser_session()
        sid = next(key for key, value in self.sessions.sessions.items()
                   if value is session)
        client.cookies.set("__Host-ronas_session", sid)

        profile = client.get(PAGE)
        self.assertEqual(profile.status_code, 200, profile.text)
        self.assertIn("فهرست و شروع پیش‌نویس مازاد", profile.text)
        self.assertNotIn('name="offer_ref"', profile.text)

        listing = client.get(f"/my-drafts/{REF}/surplus-offers")
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertIn("شروع پیش‌نویس مازاد جدید", listing.text)
        self.assertNotIn('name="offer_ref"', listing.text)
        self.assertEqual(
            ledger.list_owned(Principal(OWNER, frozenset({"household"})), REF), (),
        )

        started = client.get(
            f"/my-drafts/{REF}/surplus-offers/new", follow_redirects=False,
        )
        self.assertEqual(started.status_code, 303, started.text)
        abandoned_ref = parse_qs(urlsplit(started.headers["location"]).query)["offer_ref"][0]
        self.assertRegex(abandoned_ref, r"^DEMO-OFFER-[0-9A-F]{32}$")
        abandoned_editor = client.get(started.headers["location"])
        self.assertEqual(abandoned_editor.status_code, 200, abandoned_editor.text)
        self.assertIn("پیش‌نویس جدید و خصوصی", abandoned_editor.text)
        self.assertIn("انصراف و دور انداختن فرم ذخیره‌نشده", abandoned_editor.text)
        cancelled = client.get(f"/my-drafts/{REF}/surplus-offers")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(
            ledger.list_owned(Principal(OWNER, frozenset({"household"})), REF), (),
        )

        started = client.get(
            f"/my-drafts/{REF}/surplus-offers/new", follow_redirects=False,
        )
        generated_ref = parse_qs(urlsplit(started.headers["location"]).query)["offer_ref"][0]
        self.assertNotEqual(generated_ref, abandoned_ref)
        editor = client.get(started.headers["location"])
        self.assertEqual(editor.status_code, 200, editor.text)

        form = {
            "csrf": session.csrf, "offer_ref": generated_ref,
            "action_id": "DEMO-ONBOARDING-SAVE-1", "expected_revision": "0",
            "field_alpha": "نمونهٔ محلی", "field_choice": "sample-a",
        }
        saved = client.post(
            f"/my-drafts/{REF}/surplus-offers", content=urlencode(form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 303, saved.text)
        stored = ledger.read_owned(
            Principal(OWNER, frozenset({"household"})), REF, generated_ref,
        )
        self.assertEqual(stored.revision, 1)
        self.assertEqual(stored.values["field_alpha"], "نمونهٔ محلی")

    def test_surplus_draft_schema_change_hides_old_values_and_accepts_new_revision(self):
        old_schema = HouseholdInputSchema(
            "RONAS-DOMESTIC-INPUT", 1,
            (HouseholdInputField(
                "legacy_field", "فیلد قدیمی", "text",
                required=True, max_length=80,
            ),),
        )
        new_schema = HouseholdInputSchema(
            "RONAS-DOMESTIC-INPUT", 2,
            (HouseholdInputField(
                "current_field", "فیلد جاری", "text",
                required=True, max_length=80,
            ),),
        )
        db_path = str(self.path.parent / "surplus-schema-change.sqlite3")
        offer_ref = "DEMO-OFFER-SCHEMA-CHANGE"
        owner = Principal(OWNER, frozenset({"household"}))
        old_ledger = SqliteSyntheticSurplusDraftLedger(
            db_path, old_schema, self.allowed,
        )
        first = old_ledger.save(
            owner, REF, offer_ref, action_id="DEMO-SCHEMA-OLD-1",
            expected_revision=0, values={"legacy_field": "private old meaning"},
        )
        current_ledger = SqliteSyntheticSurplusDraftLedger(
            db_path, new_schema, self.allowed,
        )
        client = TestClient(
            self.make_app(surplus_draft_ledger=current_ledger), base_url=ORIGIN,
        )
        api_path = (
            f"/api/v1/domestic/household-intake/my-drafts/{REF}"
            f"/surplus-offers/{offer_ref}"
        )
        api_view = client.get(api_path, headers=self.bearer())
        self.assertEqual(api_view.status_code, 200, api_view.text)
        self.assertTrue(api_view.json()["schema_changed"])
        self.assertEqual(api_view.json()["schema_version"], 1)
        self.assertEqual(api_view.json()["active_schema_version"], 2)
        self.assertEqual(api_view.json()["values"], {})
        self.assertNotIn("private old meaning", api_view.text)

        session = self.browser_session()
        sid = next(key for key, value in self.sessions.sessions.items()
                   if value is session)
        client.cookies.set("__Host-ronas_session", sid)
        page = client.get(
            f"/my-drafts/{REF}/surplus-offers", params={"offer_ref": offer_ref},
        )
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("طرح‌واره تغییر کرده", page.text)
        self.assertNotIn("private old meaning", page.text)
        self.assertNotIn("legacy_field", page.text)
        self.assertIn('name="current_field"', page.text)

        form = {
            "csrf": session.csrf,
            "offer_ref": offer_ref,
            "action_id": "DEMO-SCHEMA-NEW-2",
            "expected_revision": "1",
            "current_field": "value under active schema",
        }
        saved = client.post(
            f"/my-drafts/{REF}/surplus-offers", content=urlencode(form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 303, saved.text)
        latest = current_ledger.read_owned(owner, REF, offer_ref)
        self.assertEqual(latest.revision, 2)
        self.assertEqual(latest.schema_version, 2)
        self.assertEqual(latest.values, {"current_field": "value under active schema"})
        self.assertEqual(latest.previous_receipt_digest, first.receipt_digest)

        history_api = client.get(
            api_path + "/revisions", headers=self.bearer(),
        )
        self.assertEqual(history_api.status_code, 200, history_api.text)
        revisions = history_api.json()["revisions"]
        self.assertEqual([row["revision"] for row in revisions], [1, 2])
        self.assertEqual(revisions[0]["values"], {})
        self.assertTrue(revisions[0]["schema_changed"])
        self.assertFalse(revisions[0]["diff_available"])
        self.assertEqual(revisions[0]["changes"], [])
        self.assertEqual(revisions[1]["values"],
                         {"current_field": "value under active schema"})
        self.assertFalse(revisions[1]["diff_available"])
        self.assertEqual(revisions[1]["changes"], [])
        self.assertNotIn("private old meaning", history_api.text)
        original_chain_reader = current_ledger._chain_rows

        def storage_failure(*_args):
            raise sqlite3.OperationalError("private database location")

        current_ledger._chain_rows = storage_failure
        try:
            unavailable = client.get(
                api_path + "/revisions", headers=self.bearer(),
            )
        finally:
            current_ledger._chain_rows = original_chain_reader
        self.assertEqual(unavailable.status_code, 503, unavailable.text)
        self.assertEqual(unavailable.json()["detail"], "DRAFT_STORAGE_UNAVAILABLE")
        self.assertNotIn("private database location", unavailable.text)
        hidden_history = client.get(
            api_path + "/revisions",
            headers=self.bearer("synthetic-other-owner", ("household",)),
        )
        self.assertEqual(hidden_history.status_code, 404)
        disabled = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(
            disabled.get(api_path + "/revisions", headers=self.bearer()).status_code,
            404,
        )

        history_page = client.get(
            f"/my-drafts/{REF}/surplus-offers/{offer_ref}/revisions",
        )
        self.assertEqual(history_page.status_code, 200, history_page.text)
        self.assertEqual(history_page.headers["cache-control"], "no-store")
        self.assertIn("نسخه 1", history_page.text)
        self.assertIn("نسخه 2", history_page.text)
        self.assertIn("value under active schema", history_page.text)
        self.assertNotIn("private old meaning", history_page.text)
        self.assertNotIn("legacy_field", history_page.text)
        self.assertIn("تفاوت مقادیر قابل مقایسه نیست", history_page.text)


    def test_surplus_draft_household_ui_uses_csrf_utf8_and_version_conflicts(self):
        ledger = SqliteSyntheticSurplusDraftLedger(
            str(self.path.parent / "surplus-drafts-ui.sqlite3"),
            self.schema, self.allowed,
        )
        client = TestClient(
            self.make_app(surplus_draft_ledger=ledger), base_url=ORIGIN,
        )
        session = self.browser_session()
        sid = next(key for key, value in self.sessions.sessions.items()
                   if value is session)
        client.cookies.set("__Host-ronas_session", sid)
        profile = client.get(PAGE)
        self.assertEqual(profile.status_code, 200, profile.text)
        self.assertIn("فهرست و شروع پیش‌نویس مازاد", profile.text)
        draft_path = f"/my-drafts/{REF}/surplus-offers"
        page = client.get(draft_path, params={"offer_ref": "DEMO-OFFER-UI-1"})
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("پیش‌نویس جدید و خصوصی", page.text)
        form = {
            "csrf": session.csrf,
            "offer_ref": "DEMO-OFFER-UI-1",
            "action_id": "DEMO-OFFER-UI-TEST-1",
            "expected_revision": "0",
            "field_alpha": "گوجه <b>آزمایشی</b>",
            "field_choice": "sample-a",
        }
        saved = client.post(
            f"/my-drafts/{REF}/surplus-offers", content=urlencode(form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 303, saved.text)
        self.assertEqual(saved.headers["location"], draft_path)
        listing_after_save = client.get(saved.headers["location"])
        self.assertIn("DEMO-OFFER-UI-1", listing_after_save.text)
        self.assertIn("نسخه 1", listing_after_save.text)
        shown = client.get(draft_path, params={"offer_ref": "DEMO-OFFER-UI-1"})
        self.assertIn("گوجه &lt;b&gt;آزمایشی&lt;/b&gt;", shown.text)
        self.assertNotIn("گوجه <b>آزمایشی</b>", shown.text)
        self.assertIn("نسخه 1", shown.text)
        bad_csrf = dict(form, action_id="DEMO-OFFER-UI-BAD-CSRF", csrf="wrong")
        denied = client.post(
            f"/my-drafts/{REF}/surplus-offers", content=urlencode(bad_csrf),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(denied.status_code, 403)
        bad_origin = dict(form, action_id="DEMO-OFFER-UI-BAD-ORIGIN")
        denied_origin = client.post(
            f"/my-drafts/{REF}/surplus-offers", content=urlencode(bad_origin),
            headers={"Origin": "https://attacker.example",
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(denied_origin.status_code, 403)
        stale = dict(form, action_id="DEMO-OFFER-UI-STALE")
        conflict = client.post(
            f"/my-drafts/{REF}/surplus-offers", content=urlencode(stale),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertFalse(ledger.read_owned(
            Principal(OWNER, frozenset({"household"})), REF, "DEMO-OFFER-UI-1",
        ).published)

    def test_surplus_readiness_ui_shows_safe_owner_projection(self):
        producer = OWNER
        offer_ref = "DEMO-OFFER-SURPLUS-1"
        hidden_digest = "d" * 64

        def resolver(principal, household_ref, requested_offer):
            if (principal.subject != producer or household_ref != REF
                    or requested_offer != offer_ref):
                return None
            offer = OfferRevision(
                offer_ref, REF, producer, 1, hidden_digest,
            )
            return offer, PublicationAuthorities(current_offer=offer)

        app = self.make_app(surplus_authority=resolver)
        readiness_route = "/my-drafts/{ref}/surplus-publication-readiness"

        def registered_paths(routes):
            found = []
            for route in routes:
                if getattr(route, "path", None) == readiness_route:
                    found.append(route)
                nested = getattr(route, "original_router", None)
                if nested is not None:
                    found.extend(registered_paths(nested.routes))
            return found

        self.assertEqual(len(registered_paths(app.routes)), 1)
        client = TestClient(app, base_url=ORIGIN)
        session = self.browser_session()
        sid = next(key for key, value in self.sessions.sessions.items()
                   if value is session)
        client.cookies.set("__Host-ronas_session", sid)

        profile = client.get(PAGE)
        self.assertEqual(profile.status_code, 200, profile.text)
        self.assertIn("بررسی آمادگی فنی", profile.text)
        response = client.get(
            f"/my-drafts/{REF}/surplus-publication-readiness",
            params={"offer_ref": offer_ref},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("پیشنهاد هنوز در وضعیت پیش‌نویس غیرعمومی است", response.text)
        self.assertIn("تأیید تولیدکننده ثبت نشده است", response.text)
        self.assertIn("وضعیت انتشار: منتشر نشده", response.text)
        self.assertIn("به‌معنای انتشار", response.text)
        self.assertNotIn(hidden_digest, response.text)
        self.assertNotIn("readiness_digest", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn(
            f'/my-drafts/{REF}/surplus-offers">بازگشت به فهرست پیشنهادها',
            response.text,
        )

    def test_surplus_readiness_ui_hides_cross_household_and_redacts_authority_error(self):
        calls = []

        def wrong_owner(principal, household_ref, offer_ref):
            calls.append((principal.subject, household_ref, offer_ref))
            if principal.subject == OWNER:
                raise RuntimeError("private authority secret")
            offer = OfferRevision(
                offer_ref, household_ref, OWNER, 1, "d" * 64,
            )
            return offer, PublicationAuthorities(current_offer=offer)

        app = self.make_app(surplus_authority=wrong_owner)
        client = TestClient(app, base_url=ORIGIN)
        session = self.browser_session()
        sid = next(key for key, value in self.sessions.sessions.items()
                   if value is session)
        client.cookies.set("__Host-ronas_session", sid)

        hidden = client.get(
            f"/my-drafts/{REF}/surplus-publication-readiness",
            params={"offer_ref": "DEMO-OFFER-SECRET"},
        )
        self.assertEqual(hidden.status_code, 503)
        self.assertNotIn("private authority secret", hidden.text)
        self.assertIn("بعداً دوباره تلاش کنید", hidden.text)
        self.assertEqual(len(calls), 1)

        other = "synthetic-other-owner"
        session_id = secrets.token_urlsafe(40)
        self.sessions.sessions[session_id] = BrowserSession(
            other, frozenset({"household"}), self.token(other),
            secrets.token_urlsafe(32), int(time.time()) + 300,
        )
        client.cookies.set("__Host-ronas_session", session_id)
        denied = client.get(
            f"/my-drafts/{REF}/surplus-publication-readiness",
            params={"offer_ref": "DEMO-OFFER-SECRET"},
        )
        self.assertEqual(denied.status_code, 404)
        self.assertNotIn("private authority secret", denied.text)
        self.assertEqual(len(calls), 2)

    def test_surplus_readiness_binds_to_persisted_latest_revision_and_schema(self):
        path = str(self.path.parent / "surplus-readiness-bound.sqlite3")
        ledger = SqliteSyntheticSurplusDraftLedger(
            path, self.schema, self.allowed,
        )
        owner = Principal(OWNER, frozenset({"household"}))
        offer_ref = "DEMO-OFFER-BOUND-1"
        ledger.save(
            owner, REF, offer_ref, action_id="DEMO-BOUND-A1",
            expected_revision=0,
            values={"field_alpha": "first value", "field_choice": "sample-a"},
        )
        old = OfferRevision(
            offer_ref, REF, OWNER, 1,
            ledger.read_owned(owner, REF, offer_ref).payload_digest,
        )
        producer = PublicationAttestation(
            "DEMO-ATTEST-PRODUCER-1", offer_ref, 1, old.payload_digest,
            "PRODUCER", OWNER, "a" * 64, True, True,
        )
        quality = PublicationAttestation(
            "DEMO-ATTEST-QUALITY-1", offer_ref, 1, old.payload_digest,
            "QUALITY_SAFETY", "synthetic-independent-reviewer", "b" * 64,
            True, True,
        )

        def old_authority(_principal, _household_ref, _offer_ref):
            return old, PublicationAuthorities(
                current_offer=old, producer_approval=producer,
                quality_safety_verification=quality,
                seller_eligibility_verified=True,
                household_permission_active=True, marketplace_gate_open=True,
            )

        client = TestClient(self.make_app(
            surplus_authority=old_authority, surplus_draft_ledger=ledger,
        ), base_url=ORIGIN)
        readiness_path = (
            f"/api/v1/domestic/household-intake/my-drafts/{REF}"
            f"/surplus-offers/{offer_ref}/publication-readiness"
        )
        first = client.get(readiness_path, headers=self.bearer())
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["contract_version"],
                         "ronas.domestic.surplus-publication-gate.v2")
        self.assertTrue(first.json()["can_publish"])
        self.assertEqual(first.json()["revision"], 1)

        ledger.save(
            owner, REF, offer_ref, action_id="DEMO-BOUND-A2",
            expected_revision=1,
            values={"field_alpha": "second value", "field_choice": "sample-a"},
        )
        changed = client.get(readiness_path, headers=self.bearer())
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["revision"], 2)
        self.assertFalse(changed.json()["can_publish"])
        self.assertEqual(
            set(changed.json()["blockers"]),
            {"OFFER_VERSION_CHANGED", "PRODUCER_APPROVAL_STALE",
             "QUALITY_SAFETY_VERIFICATION_STALE"},
        )

        session = self.browser_session()
        sid = next(key for key, value in self.sessions.sessions.items()
                   if value is session)
        client.cookies.set("__Host-ronas_session", sid)
        page = client.get(
            f"/my-drafts/{REF}/surplus-publication-readiness",
            params={"offer_ref": offer_ref},
        )
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("نسخه پیشنهاد تغییر کرده است", page.text)

        changed_schema = HouseholdInputSchema(
            self.schema.schema_ref, self.schema.version + 1,
            (HouseholdInputField("field_alpha", "فیلد تغییر یافته"),),
        )
        stale_schema_ledger = SqliteSyntheticSurplusDraftLedger(
            path, changed_schema, self.allowed,
        )
        stale_schema_client = TestClient(self.make_app(
            surplus_authority=old_authority,
            surplus_draft_ledger=stale_schema_ledger,
        ), base_url=ORIGIN)
        stale = stale_schema_client.get(readiness_path, headers=self.bearer())
        self.assertEqual(stale.status_code, 200, stale.text)
        self.assertFalse(stale.json()["can_publish"])
        self.assertIn("OFFER_SCHEMA_CHANGED", stale.json()["blockers"])
        self.assertNotIn("first value", stale.text)
        self.assertEqual(len(ledger.history_owned(owner, REF, offer_ref)), 2)

    def test_surplus_readiness_route_is_absent_without_explicit_authority(self):
        client = TestClient(self.app, base_url=ORIGIN)
        session = self.browser_session()
        sid = next(key for key, value in self.sessions.sessions.items()
                   if value is session)
        client.cookies.set("__Host-ronas_session", sid)
        response = client.get(
            f"/my-drafts/{REF}/surplus-publication-readiness",
            params={"offer_ref": "DEMO-OFFER-1"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("بررسی آمادگی فنی", client.get(PAGE).text)


if __name__ == "__main__":
    unittest.main()
