"""Schema-driven owner profile intake is versioned, private, and guarded."""
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.domestic_stage_observation import CurrentStageContext, StageRequirement
from ronas_api.household_input_profiles import (
    HouseholdInputField, HouseholdInputSchema,
    SqliteSyntheticHouseholdProfileLedger,
)
from ronas_api.stage_observation_artifacts import (
    PrivateFilesystemStageArtifactStore, StageArtifactStoreError,
)
from ronas_api.postgres_stage_artifacts import PostgresStageArtifactStore
from ronas_api.postgres_household_progress_notes import PostgresHouseholdProgressNoteLedger
from ronas_api.keycloak import KeycloakConfig
from ronas_api.local_keycloak_bff import (
    LocalBFFSettings, PostgresLocalBFFSettings, create_local_test_bff,
    create_postgres_local_test_bff,
)
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant
from ronas_api.agronomy_workspace import (
    SyntheticAgronomyAssignment, SyntheticAgronomyWorkspace,
)
from ronas_api.expert_review_questions_sqlite import SqliteSyntheticExpertQuestionLedger
from ronas_api.domestic_surplus_publication import (
    OfferRevision, PublicationAttestation, PublicationAuthorities,
)
from ronas_api.domestic_surplus_drafts import (
    SqliteSyntheticSurplusDraftLedger, SurplusDraftStorageError,
)
from ronas_api.domestic_surplus_producer_consent import SqliteSyntheticProducerConsentLedger
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
POSTGRES_DSN = os.environ.get("RONAS_TEST_POSTGRES_DSN")
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

    def test_local_bff_forwards_shared_progress_journal_to_household_api(self):
        calls = []
        journal = object.__new__(PostgresHouseholdProgressNoteLedger)
        journal._schema_ref = self.schema.schema_ref
        journal._authority = self.allowed
        journal._context_reader = self.ledger.progress_note_context
        journal.read_owned_progress_notes = lambda ref, principal, **page: (
            calls.append((ref, principal.subject, page))
            or {"notes": [], "current_revision": 0, "real_data": False}
        )
        key_file = self.path.parent / "local-bff-composition.key"
        key_file.write_bytes(secrets.token_bytes(32))
        key_file.chmod(0o600)
        loopback = "https://127.0.0.1:8765"
        app = create_local_test_bff(
            LocalBFFSettings(
                self.config, loopback + "/api/auth/callback",
                self.path.parent / "local-bff-session.db", key_file,
            ),
            case_ledger=self.ledger, household_profile_schema=self.schema,
            household_profile_access_authority=self.allowed,
            household_progress_note_ledger=journal,
        )
        response = TestClient(app, base_url=loopback).get(
            f"/api/v1/domestic/household-intake/my-drafts/{REF}/progress-notes",
            headers=self.bearer(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(calls, [(
            REF, OWNER, {"limit": 20, "after_revision": 0, "snapshot_revision": None},
        )])

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
                 surplus_draft_ledger=None, surplus_consent_ledger=None,
                 stage_context_authority=None,
                 profile_access_authority=None):
        return create_app(
            self.config, self.flow, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
            household_profile_schema=self.schema if schema else None,
            household_profile_access_authority=(
                profile_access_authority
                if profile_access_authority is not None
                else self.allowed if authority else None
            ),
            household_stage_context_authority=(
                (stage_context_authority or self.stage_context)
                if stage_authority and schema else None
            ),
            household_stage_artifact_store=artifact_store,
            household_surplus_publication_authority=surplus_authority,
            household_surplus_draft_ledger=surplus_draft_ledger,
            household_surplus_producer_consent_ledger=surplus_consent_ledger,
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

    def test_profile_write_rejects_oversized_field_map_before_ledger_mutation(self):
        invalid_values = (
            {f"field_{index}": "x" for index in range(7)},
            {"f" * 33: "x"},
            {"field_alpha": "x" * 301},
        )
        for values in invalid_values:
            with self.subTest(size=len(values), value_length=max(map(len, values.values()))):
                response = self.client.post(
                    ROOT, json=self.command(values=values), headers=self.bearer(),
                )
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            self.ledger.read_owned_profile(
                REF, Principal(OWNER, frozenset({"household"})),
            )["current_revision"], 0,
        )
        self.assertTrue(self.ledger.verify_integrity())

 
    def test_profile_write_rejects_oversized_json_body_before_model_parsing(self):
        payload = json.dumps(self.command(values={"field_alpha": "x" * 5000}))
        response = self.client.post(
            ROOT, content=payload,
            headers={**self.bearer(), "Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(
            response.json()["detail"], "HOUSEHOLD_PROFILE_REQUEST_TOO_LARGE",
        )
        self.assertEqual(
            self.ledger.read_owned_profile(
                REF, Principal(OWNER, frozenset({"household"})),
            )["current_revision"], 0,
        )
        self.assertTrue(self.ledger.verify_integrity())

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
        changed_timestamp = self.client.post(
            path, json={**command, "observed_at": "2026-10-13T10:20:30+00:00"},
            headers=self.bearer(),
        )
        self.assertEqual(changed_timestamp.status_code, 409)
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

    def test_stage_artifact_bearer_api_is_current_context_and_receipt_bound(self):
        self.assertEqual(self.client.post(
            ROOT, json=self.command(), headers=self.bearer(),
        ).status_code, 201)
        store = PrivateFilesystemStageArtifactStore(
            self.artifact_root, b"x" * 32,
        )
        api_client = TestClient(
            self.make_app(artifact_store=store), base_url=ORIGIN,
        )
        root = ROOT.replace("/cultivation-inputs", "/stage-observations")
        upload_path = root + "/artifacts/DEMO-STAGE-01"
        image = b"\x89PNG\r\n\x1a\n" + b"bearer-stage-upload"
        headers = {
            **self.bearer(), "Content-Type": "image/png",
            "X-Ronas-Case-Version": "2", "X-Ronas-Input-Revision": "1",
            "X-Ronas-Plan-Digest": self.stage_plan_digest,
            "X-Ronas-Requirements-Digest": "a" * 64,
        }

        self.assertEqual(api_client.put(
            upload_path, content=image,
            headers={k: v for k, v in headers.items()
                     if k != "Authorization"},
        ).status_code, 401)
        stale = dict(headers, **{"X-Ronas-Plan-Digest": "f" * 64})
        rejected_context = api_client.put(upload_path, content=image, headers=stale)
        self.assertEqual(rejected_context.status_code, 409,
                         rejected_context.text)
        rejected_type = api_client.put(
            upload_path, content=image,
            headers=dict(headers, **{"Content-Type": "application/pdf"}),
        )
        self.assertEqual(rejected_type.status_code, 422,
                         rejected_type.text)
        oversized = api_client.put(
            upload_path, content=image,
            headers=dict(headers, **{
                "Content-Length": str(8 * 1024 * 1024 + 1),
            }),
        )
        self.assertEqual(oversized.status_code, 413, oversized.text)
        mismatch = api_client.put(
            upload_path, content=image,
            headers=dict(headers, **{"Content-Length": str(len(image) - 1)}),
        )
        self.assertEqual(mismatch.status_code, 400, mismatch.text)

        uploaded = api_client.put(upload_path, content=image, headers=headers)
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        digest = hashlib.sha256(image).hexdigest()
        self.assertEqual(uploaded.json(), {
            "digest": digest, "content_type": "image/png",
            "byte_length": len(image), "stored": True,
        })
        download_path = upload_path + "/" + digest
        artifact_audit_start = len(self.ledger.audit_snapshot())
        unlinked = api_client.get(download_path, headers=self.bearer())
        self.assertEqual(unlinked.status_code, 404)

        receipt = self.stage_command(action="DEMO-STAGE-ARTIFACT-API")
        receipt["observation_artifact_digest"] = digest
        saved = api_client.post(root, json=receipt, headers=self.bearer())
        self.assertEqual(saved.status_code, 201, saved.text)
        downloaded = api_client.get(download_path, headers=self.bearer())
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.content, image)
        self.assertEqual(downloaded.headers["content-type"], "image/png")
        self.assertEqual(downloaded.headers["cache-control"], "no-store")
        self.assertEqual(downloaded.headers["x-content-type-options"], "nosniff")

        self.browser_session()
        browser_client = TestClient(
            self.make_app(artifact_store=store), base_url=ORIGIN,
        )
        browser_client.cookies.set(
            "__Host-ronas_session", self.client.cookies.get("__Host-ronas_session"),
        )
        browser_download = browser_client.get(
            "/my-drafts/" + REF + "/stage-observations/artifacts/"
            + "DEMO-STAGE-01/" + digest,
        )
        self.assertEqual(browser_download.status_code, 200, browser_download.text)
        self.assertEqual(browser_download.content, image)

        class FailedAuditStore:
            def put(inner_self, *args, **kwargs):
                return store.put(*args, **kwargs)

            def get(inner_self, *args, **kwargs):
                return store.get(*args, **kwargs)

            def contains(inner_self, *args, **kwargs):
                return store.contains(*args, **kwargs)

            def record_access(inner_self, *args, **kwargs):
                raise StageArtifactStoreError("audit unavailable")

        failed_audit_client = TestClient(
            self.make_app(artifact_store=FailedAuditStore()), base_url=ORIGIN,
        )
        failed_audit = failed_audit_client.get(
            download_path, headers=self.bearer(),
        )
        self.assertEqual(failed_audit.status_code, 503)
        self.assertNotEqual(failed_audit.content, image)

        access = {"allowed": True}

        def changing_access(principal, ref, schema_ref):
            return (access["allowed"]
                    and self.allowed(principal, ref, schema_ref))

        class RevokeDuringRead:
            def put(inner_self, *args, **kwargs):
                return store.put(*args, **kwargs)

            def get(inner_self, owner, case_ref, artifact_digest):
                result = store.get(owner, case_ref, artifact_digest)
                access["allowed"] = False
                return result

            def contains(inner_self, *args, **kwargs):
                return store.contains(*args, **kwargs)

        race_client = TestClient(self.make_app(
            artifact_store=RevokeDuringRead(),
            profile_access_authority=changing_access,
        ), base_url=ORIGIN)
        raced_api = race_client.get(download_path, headers=self.bearer())
        self.assertEqual(raced_api.status_code, 404, raced_api.text)
        self.assertNotEqual(raced_api.content, image)

        access["allowed"] = True
        browser_race_client = TestClient(self.make_app(
            artifact_store=RevokeDuringRead(),
            profile_access_authority=changing_access,
        ), base_url=ORIGIN)
        browser_race_client.cookies.set(
            "__Host-ronas_session", self.client.cookies.get("__Host-ronas_session"),
        )
        raced_browser = browser_race_client.get(
            "/my-drafts/" + REF + "/stage-observations/artifacts/"
            + "DEMO-STAGE-01/" + digest,
        )
        self.assertEqual(raced_browser.status_code, 404, raced_browser.text)
        household_audit = [
            entry for entry in self.ledger.audit_snapshot()[artifact_audit_start:]
            if entry.access_mode == "HOUSEHOLD_STAGE_ARTIFACT"
        ]
        self.assertEqual([entry.kind for entry in household_audit], [
            "READ_DENIED", "READ_ALLOWED", "READ_ALLOWED",
            "READ_DENIED", "READ_DENIED",
        ])
        self.assertTrue(all(
            entry.reason_ref == "DEMO-STAGE-01"
            and entry.target_digest == hashlib.sha256(
                digest.encode("utf-8")
            ).hexdigest()
            for entry in household_audit
        ))

        wrong_owner = api_client.get(
            download_path,
            headers=self.bearer("synthetic-other", ("household",)),
        )
        self.assertEqual(wrong_owner.status_code, 404)
        self.assertTrue(self.ledger.verify_integrity())

    def test_specialist_artifact_reads_audit_exact_file_and_fail_closed_races(self):
        self.assertEqual(self.client.post(
            ROOT, json=self.command(), headers=self.bearer(),
        ).status_code, 201)
        image = b"\x89PNG\r\n\x1a\n" + b"specialist-audit-scope"
        stored = self.artifact_store.put(
            OWNER, REF + ":DEMO-STAGE-01", "image/png", image,
        )
        stage_root = ROOT.replace("/cultivation-inputs", "/stage-observations")
        command = self.stage_command(action="DEMO-SPECIALIST-ARTIFACT-AUDIT")
        command["observation_artifact_digest"] = stored.digest
        saved = self.client.post(
            stage_root, json=command, headers=self.bearer(),
        )
        self.assertEqual(saved.status_code, 201, saved.text)

        specialist = "synthetic-agronomy-artifact-reader"
        active = {"value": True}
        workspace = SyntheticAgronomyWorkspace(
            self.ledger,
            (SyntheticAgronomyAssignment(REF, specialist, 2),),
            trusted_assignment_active=lambda actor, ref, version: (
                active["value"] and actor == specialist
                and ref == REF and version == 2
            ),
        )
        principal = Principal(specialist, frozenset({"agronomy_expert"}))
        before = len(self.ledger.audit_snapshot())
        result = workspace.read_assigned_stage_artifact(
            REF, "DEMO-STAGE-01", stored.digest, principal,
            store=self.artifact_store,
        )
        self.assertEqual(result[1], image)

        class RevokeDuringRead:
            def get(inner_self, owner, case_ref, digest):
                result = self.artifact_store.get(owner, case_ref, digest)
                active["value"] = False
                return result

        denied_race = workspace.read_assigned_stage_artifact(
            REF, "DEMO-STAGE-01", stored.digest, principal,
            store=RevokeDuringRead(),
        )
        self.assertIsNone(denied_race)

        active["value"] = True

        class MissingArtifact:
            def get(inner_self, owner, case_ref, digest):
                return None

        missing = workspace.read_assigned_stage_artifact(
            REF, "DEMO-STAGE-01", stored.digest, principal,
            store=MissingArtifact(),
        )
        self.assertIsNone(missing)
        events = [event for event in self.ledger.audit_snapshot()[before:]
                  if event.access_mode == "AGRONOMY_ASSIGNED_STAGE_ARTIFACT"]
        self.assertEqual([event.kind for event in events], [
            "READ_ALLOWED", "READ_DENIED", "READ_DENIED",
        ])
        self.assertTrue(all(event.reason_ref == "DEMO-STAGE-01"
                            for event in events))
        self.assertTrue(all(
            event.target_digest == hashlib.sha256(
                stored.digest.encode("utf-8")
            ).hexdigest() for event in events
        ))
        self.assertTrue(self.ledger.verify_integrity())

    def test_composed_app_has_one_receipt_authorized_household_artifact_route(self):
        app = self.make_app(artifact_store=self.artifact_store)
        path = (
            "/api/v1/domestic/household-intake/my-drafts/{ref}/"
            "stage-observations/artifacts/{stage_ref}/{digest}"
        )
        matches = [route for included in app.routes
                   for route in getattr(
                       getattr(included, "original_router", None), "routes", (),
                   )
                   if getattr(route, "path", None) == path
                   and "GET" in getattr(route, "methods", set())]
        self.assertEqual(len(matches), 1)
        self.assertIn("download_stage_observation_artifact",
                      matches[0].name)

    def test_stage_artifact_upload_rechecks_context_after_stream_before_storage(self):
        self.assertEqual(self.client.post(
            ROOT, json=self.command(), headers=self.bearer(),
        ).status_code, 201)
        root = ROOT.replace("/cultivation-inputs", "/stage-observations")
        image = b"\x89PNG\r\n\x1a\n" + b"stale-context-upload"
        digest = hashlib.sha256(image).hexdigest()
        upload_headers = {
            **self.bearer(), "Content-Type": "image/png",
            "X-Ronas-Case-Version": "2", "X-Ronas-Input-Revision": "1",
            "X-Ronas-Plan-Digest": self.stage_plan_digest,
            "X-Ronas-Requirements-Digest": "a" * 64,
        }

        api_context = self.stage_context(REF)
        api_reads = []

        def api_racing_context(ref):
            api_reads.append(ref)
            return api_context if len(api_reads) == 1 else None

        api = TestClient(self.make_app(
            artifact_store=self.artifact_store,
            stage_context_authority=api_racing_context,
        ), base_url=ORIGIN)
        api_result = api.put(
            root + "/artifacts/DEMO-STAGE-01", content=image,
            headers=upload_headers,
        )
        self.assertEqual(api_result.status_code, 409, api_result.text)
        self.assertEqual(api_result.json()["detail"],
                         "STAGE_OBSERVATION_CONTEXT_CHANGED")
        self.assertEqual(api_reads, [REF, REF])
        self.assertFalse(self.artifact_store.contains(
            OWNER, REF + ":DEMO-STAGE-01", digest,
        ))

        browser_reads = []

        def browser_racing_context(ref):
            browser_reads.append(ref)
            return api_context if len(browser_reads) == 1 else None

        browser = TestClient(self.make_app(
            artifact_store=self.artifact_store,
            stage_context_authority=browser_racing_context,
        ), base_url=ORIGIN)
        session = self.browser_session()
        browser.cookies.set(
            "__Host-ronas_session",
            self.client.cookies.get("__Host-ronas_session"),
        )
        browser_result = browser.put(
            "/my-drafts/" + REF + "/stage-observations/artifacts",
            content=image,
            headers={
                "Origin": ORIGIN, "X-CSRF-Token": session.csrf,
                "Content-Type": "image/png", "X-Ronas-Case-Version": "2",
                "X-Ronas-Input-Revision": "1",
                "X-Ronas-Plan-Digest": self.stage_plan_digest,
                "X-Ronas-Stage-Ref": "DEMO-STAGE-01",
                "X-Ronas-Requirements-Digest": "a" * 64,
            },
        )
        self.assertEqual(browser_result.status_code, 409, browser_result.text)
        self.assertEqual(browser_result.json()["detail"],
                         "STAGE_OBSERVATION_CONTEXT_CHANGED")
        self.assertEqual(browser_reads, [REF, REF])
        self.assertFalse(self.artifact_store.contains(
            OWNER, REF + ":DEMO-STAGE-01", digest,
        ))

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
        self.assertIn("هیچ تغییری ثبت نشد", conflict.text)
        self.assertIn('href="/my-drafts/' + REF
                      + '/stage-observations"', conflict.text)
        self.assertNotIn("d" * 64, conflict.text)
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
        stale_form = dict(form, action_id="DEMO-STAGE-OBS-OLD-CONTEXT")
        stale = self.client.post(
            path, content=urlencode(stale_form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertIn("این فرمان با نسخه جاری پرونده", stale.text)
        self.assertNotIn("DEMO-STAGE-OBS-OLD-CONTEXT", stale.text)
        self.assertTrue(self.ledger.verify_integrity())

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
        for invalid_length in ("-1", "+1", "not-a-length"):
            with self.subTest(content_length=invalid_length):
                malformed = dict(upload_headers, **{"Content-Length": invalid_length})
                rejected_length = self.client.put(
                    upload_path, content=image, headers=malformed,
                )
                self.assertEqual(rejected_length.status_code, 400)
                self.assertEqual(
                    rejected_length.json()["detail"], "INVALID_CONTENT_LENGTH",
                )
        oversized = dict(
            upload_headers,
            **{"Content-Length": str(8 * 1024 * 1024 + 1)},
        )
        rejected_size = self.client.put(
            upload_path, content=image, headers=oversized,
        )
        self.assertEqual(rejected_size.status_code, 413)
        mismatched = dict(upload_headers, **{"Content-Length": str(len(image) - 1)})
        mismatch = self.client.put(upload_path, content=image, headers=mismatched)
        self.assertEqual(mismatch.status_code, 400, mismatch.text)
        self.assertEqual(mismatch.json()["detail"], "CONTENT_LENGTH_MISMATCH")
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

    @unittest.skipUnless(POSTGRES_DSN, "RONAS_TEST_POSTGRES_DSN is not configured")
    def test_postgres_bff_composes_owner_progress_journal_with_shared_case_authority(self):
        ref = "DEMO-D-PGNOTE-" + secrets.token_hex(6).upper()
        records = (ScopedDraft(ref, "DOMESTIC", OWNER, 2, ()),)
        cases = SqliteSyntheticHouseholdProfileLedger(
            self.path.parent / ("progress-" + secrets.token_hex(6) + ".db"),
            records, profile_schema=self.schema,
            trusted_revoke_authorizer=lambda *_: False,
            trusted_human_review_authorizer=lambda *_: False,
        )
        notes = PostgresHouseholdProgressNoteLedger(
            POSTGRES_DSN, self.schema.schema_ref, self.allowed,
            cases.progress_note_context, secrets.token_bytes(32),
            secrets.token_bytes(32),
        )
        callback = "https://127.0.0.1:8765/api/auth/callback"
        key_file = self.path.parent / "postgres-progress-session.key"
        key_file.write_bytes(secrets.token_bytes(32))
        key_file.chmod(0o600)
        app = create_postgres_local_test_bff(
            PostgresLocalBFFSettings(self.config, callback, POSTGRES_DSN, key_file),
            case_ledger=cases, household_profile_schema=self.schema,
            household_profile_access_authority=self.allowed,
            household_progress_note_ledger=notes,
        )
        client = TestClient(app, base_url="https://127.0.0.1:8765")
        api = f"/api/v1/domestic/household-intake/my-drafts/{ref}/progress-notes"
        saved = client.post(api, headers=self.bearer(), json={
            "action_id": "DEMO-PGNOTE-" + secrets.token_hex(8).upper(),
            "expected_case_version": 2, "expected_revision": 0,
            "expected_input_revision": 0, "reported_at": "2026-10-17T12:00:00+00:00",
            "note": "DEMO: BFF-composed journal entry",
        })
        self.assertEqual(saved.status_code, 201, saved.text)
        read = client.get(api, headers=self.bearer())
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()["notes"][0]["note"],
                         "DEMO: BFF-composed journal entry")
        forbidden = client.get(api, headers=self.bearer(subject="synthetic-other"))
        self.assertEqual(forbidden.status_code, 404, forbidden.text)
        self.assertTrue(cases.verify_integrity())

    @unittest.skipUnless(POSTGRES_DSN, "RONAS_TEST_POSTGRES_DSN is not configured")
    def test_keycloak_browser_writes_postgres_progress_and_second_bff_reads_it(self):
        callback_origin = "https://127.0.0.1:8765"
        callback = callback_origin + "/api/auth/callback"
        ref = "DEMO-D-PGBROWSER-" + secrets.token_hex(6).upper()
        cases = SqliteSyntheticHouseholdProfileLedger(
            self.path.parent / ("browser-progress-" + secrets.token_hex(6) + ".db"),
            (ScopedDraft(ref, "DOMESTIC", OWNER, 2, ()),),
            profile_schema=self.schema,
            trusted_revoke_authorizer=lambda *_: False,
            trusted_human_review_authorizer=lambda *_: False,
        )
        encryption_key, scope_key = secrets.token_bytes(32), secrets.token_bytes(32)
        key_file = self.path.parent / "postgres-browser-progress.key"
        key_file.write_bytes(secrets.token_bytes(32))
        key_file.chmod(0o600)
        settings = PostgresLocalBFFSettings(
            KeycloakConfig(ISS, API, WEB, self.config.jwks_json),
            callback, POSTGRES_DSN, key_file,
        )
        nonce_holder = {}
        issued = {}

        def token_response(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(
                str(request.url), ISS + "/protocol/openid-connect/token",
            )
            now = int(time.time())
            claims = {"iss": ISS, "sub": OWNER, "iat": now - 5, "exp": now + 450}
            access = jwt.encode(
                {**claims, "aud": API, "azp": WEB, "typ": "Bearer",
                 "nbf": now - 5,
                 "resource_access": {API: {"roles": ["household"]}}},
                self.key, algorithm="RS256", headers={"kid": "profile-test"},
            )
            identity = jwt.encode(
                {**claims, "aud": WEB, "azp": WEB,
                 "nonce": nonce_holder["nonce"]},
                self.key, algorithm="RS256", headers={"kid": "profile-test"},
            )
            issued["access_token"] = access
            return httpx.Response(200, json={
                "token_type": "Bearer", "access_token": access,
                "id_token": identity,
            })

        def build_app():
            # Each BFF owns a distinct adapter object with the same scoped keys;
            # only PostgreSQL carries the journal between processes.
            notes = PostgresHouseholdProgressNoteLedger(
                POSTGRES_DSN, self.schema.schema_ref, self.allowed,
                cases.progress_note_context, encryption_key, scope_key,
            )
            return create_postgres_local_test_bff(
                settings, transport=httpx.MockTransport(token_response),
                case_ledger=cases, household_profile_schema=self.schema,
                household_profile_access_authority=self.allowed,
                household_progress_note_ledger=notes,
            )

        first_app, second_app = build_app(), build_app()
        browser_a = TestClient(first_app, base_url=callback_origin,
                               follow_redirects=False)
        browser_b = TestClient(second_app, base_url=callback_origin,
                               follow_redirects=False)
        state_hash = session_hash = None
        history_path = f"/my-drafts/{ref}/progress-notes"
        try:
            start = browser_a.get("/api/auth/start")
            self.assertEqual(start.status_code, 303, start.text)
            query = parse_qs(urlsplit(start.headers["location"]).query)
            nonce_holder["nonce"] = query["nonce"][0]
            state_hash = hashlib.sha256(query["state"][0].encode("ascii")).hexdigest()
            browser_b.cookies.update(browser_a.cookies)
            callback_response = browser_b.get(
                "/api/auth/callback", params={
                    "code": "progress-browser-code", "state": query["state"][0],
                },
            )
            self.assertEqual(callback_response.status_code, 303,
                             callback_response.text)
            session = browser_b.get("/api/auth/session")
            self.assertEqual(session.status_code, 200, session.text)
            self.assertNotIn("access_token", session.text)
            sid = browser_b.cookies.get("__Host-ronas_session")
            session_hash = hashlib.sha256(sid.encode("ascii")).hexdigest()

            form = {
                "csrf": session.json()["csrf"],
                "action_id": "DEMO-PROGRESS-" + secrets.token_hex(8).upper(),
                "case_version": "2", "revision": "0", "input_revision": "0",
                "corrects_revision": "0",
                "reported_at": "2026-10-17T13:00:00+00:00",
                "note": "DEMO: browser journal persisted across BFFs",
            }
            saved = browser_b.post(
                history_path, content=urlencode(form), headers={
                    "Origin": callback_origin,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            self.assertEqual(saved.status_code, 303, saved.text)

            browser_a.cookies.update(browser_b.cookies)
            history = browser_a.get(history_path)
            self.assertEqual(history.status_code, 200, history.text)
            self.assertIn("DEMO: browser journal persisted across BFFs", history.text)
            api = f"/api/v1/domestic/household-intake/my-drafts/{ref}/progress-notes"
            api_history = browser_a.get(api, headers={
                "Authorization": "Bearer " + issued["access_token"],
            })
            self.assertEqual(api_history.status_code, 200, api_history.text)
            self.assertEqual(api_history.json()["current_revision"], 1)
            self.assertEqual(first_app.state.ronas_local_bff_session_backend,
                             "postgresql")
            self.assertEqual(second_app.state.ronas_local_bff_session_backend,
                             "postgresql")
            with psycopg.connect(POSTGRES_DSN) as db:
                stored = db.execute(
                    "SELECT note_ciphertext FROM ronas_domestic_progress_note "
                    "WHERE household_ref=%s", (ref,),
                ).fetchone()
                events = db.execute(
                    "SELECT event_kind FROM ronas_domestic_progress_access "
                    "WHERE household_ref=%s ORDER BY event_sequence", (ref,),
                ).fetchall()
            self.assertIsNotNone(stored)
            self.assertNotIn(b"browser journal persisted", bytes(stored[0]))
            self.assertEqual({row[0] for row in events}, {"APPEND", "READ"})
            self.assertTrue(cases.verify_integrity())
        finally:
            browser_a.close()
            browser_b.close()
            with psycopg.connect(POSTGRES_DSN) as db:
                if state_hash is not None:
                    db.execute(
                        "DELETE FROM ronas_browser_pending_login WHERE state_hash=%s",
                        (state_hash,),
                    )
                if session_hash is not None:
                    db.execute(
                        "DELETE FROM ronas_browser_session_refresh_lock "
                        "WHERE sid_hash=%s", (session_hash,),
                    )
                    db.execute(
                        "DELETE FROM ronas_browser_session WHERE sid_hash=%s",
                        (session_hash,),
                    )

    @unittest.skipUnless(POSTGRES_DSN, "RONAS_TEST_POSTGRES_DSN is not configured")
    def test_postgres_artifact_store_completes_household_and_specialist_bff_flow(self):
        image = b"\x89PNG\r\n\x1a\n" + b"postgres-backed-browser-flow"
        store = PostgresStageArtifactStore(
            POSTGRES_DSN, secrets.token_bytes(32),
            scope_key=secrets.token_bytes(32),
        )
        case_artifact_ref = REF + ":DEMO-STAGE-01"
        owner_hash, case_hash = store._scope(OWNER, case_artifact_ref)
        with psycopg.connect(POSTGRES_DSN) as db:
            db.execute(
                "DELETE FROM ronas_stage_artifact WHERE owner_hash=%s AND case_hash=%s",
                (owner_hash, case_hash),
            )
        try:
            profile = self.client.post(ROOT, json=self.command(), headers=self.bearer())
            self.assertEqual(profile.status_code, 201, profile.text)
            specialist = "synthetic-agronomy-postgres-stage-reviewer"
            active = {True}
            workspace = SyntheticAgronomyWorkspace(
                self.ledger,
                (SyntheticAgronomyAssignment(REF, specialist, 2),),
                trusted_assignment_active=lambda actor, ref, version: (
                    actor == specialist and ref == REF and version == 2 and bool(active)
                ),
            )
            self.client = TestClient(create_app(
                self.config, self.flow,
                scoped_registry=self.ledger,
                technical_review_ledger=self.ledger,
                household_profile_schema=self.schema,
                household_profile_access_authority=self.allowed,
                household_stage_context_authority=self.stage_context,
                household_stage_artifact_store=store,
                agronomy_workspace=workspace,
            ), base_url=ORIGIN)

            session = self.browser_session()
            page_path = PAGE.replace("/cultivation-inputs", "/stage-observations")
            upload_headers = {
                "Origin": ORIGIN, "X-CSRF-Token": session.csrf,
                "Content-Type": "image/png", "X-Ronas-Case-Version": "2",
                "X-Ronas-Input-Revision": "1",
                "X-Ronas-Plan-Digest": self.stage_plan_digest,
                "X-Ronas-Stage-Ref": "DEMO-STAGE-01",
                "X-Ronas-Requirements-Digest": "a" * 64,
            }
            uploaded = self.client.put(
                page_path + "/artifacts", content=image, headers=upload_headers,
            )
            self.assertEqual(uploaded.status_code, 201, uploaded.text)
            digest = uploaded.json()["digest"]
            api_artifact_path = (
                f"/api/v1/domestic/household-intake/my-drafts/{REF}"
                f"/stage-observations/artifacts/DEMO-STAGE-01/{digest}"
            )
            denied_before_receipt = self.client.get(
                api_artifact_path, headers=self.bearer(),
            )
            self.assertEqual(denied_before_receipt.status_code, 404)
            command = self.stage_command(action="DEMO-POSTGRES-STAGE-RECEIPT")
            form = {
                "csrf": session.csrf, "action_id": command["action_id"],
                "case_version": str(command["expected_case_version"]),
                "input_revision": str(command["expected_input_revision"]),
                "input_snapshot_digest": command["expected_input_snapshot_digest"],
                "plan_digest": command["expected_plan_digest"],
                "stage_ref": command["stage_ref"],
                "requirements_digest": command[
                    "expected_observation_requirements_digest"
                ],
                "observation_revision": "0", "corrects_revision": "0",
                "artifact_digest": digest,
            }
            saved = self.client.post(
                page_path, content=urlencode(form),
                headers={"Origin": ORIGIN,
                         "Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False,
            )
            self.assertEqual(saved.status_code, 303, saved.text)
            owner_download = self.client.get(
                f"/my-drafts/{REF}/stage-observations/artifacts/"
                f"DEMO-STAGE-01/{digest}",
            )
            self.assertEqual(owner_download.status_code, 200, owner_download.text)
            self.assertEqual(owner_download.content, image)
            self.assertEqual(owner_download.headers["cache-control"], "no-store")

            audit_owner, audit_case = store._scope(
                OWNER, case_artifact_ref, digest,
            )
            with psycopg.connect(POSTGRES_DSN) as db:
                owner_access = db.execute(
                    "SELECT decision FROM ronas_stage_artifact_access_event "
                    "WHERE owner_hash=%s AND case_hash=%s "
                    "ORDER BY event_sequence", (audit_owner, audit_case),
                ).fetchall()
            self.assertEqual([row[0] for row in owner_access], [
                "READ_DENIED", "READ_ALLOWED",
            ])

            with psycopg.connect(POSTGRES_DSN) as db:
                row = db.execute(
                    "SELECT ciphertext FROM ronas_stage_artifact "
                    "WHERE owner_hash=%s AND case_hash=%s AND digest=%s",
                    (owner_hash, case_hash, digest),
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertNotIn(image, bytes(row[0]))

            self.browser_session(specialist, ("agronomy_expert",))
            specialist_download = self.client.get(
                f"/agronomy/assigned-drafts/{REF}/stage-observations/artifacts/"
                f"DEMO-STAGE-01/{digest}",
            )
            self.assertEqual(specialist_download.status_code, 200,
                             specialist_download.text)
            self.assertEqual(specialist_download.content, image)
            api_download = self.client.get(
                f"/api/v1/agronomy/assigned-drafts/{REF}/stage-observations/"
                f"artifacts/DEMO-STAGE-01/{digest}",
                headers=self.bearer(specialist, ("agronomy_expert",)),
            )
            self.assertEqual(api_download.status_code, 200, api_download.text)
            self.assertEqual(api_download.content, image)

            active.clear()
            revoked = self.client.get(
                f"/agronomy/assigned-drafts/{REF}/stage-observations/artifacts/"
                f"DEMO-STAGE-01/{digest}",
            )
            self.assertEqual(revoked.status_code, 404, revoked.text)
            revoked_api = self.client.get(
                f"/api/v1/agronomy/assigned-drafts/{REF}/stage-observations/"
                f"artifacts/DEMO-STAGE-01/{digest}",
                headers=self.bearer(specialist, ("agronomy_expert",)),
            )
            self.assertEqual(revoked_api.status_code, 404, revoked_api.text)
            specialist_audit = [
                entry for entry in self.ledger.audit_snapshot()
                if entry.access_mode == "AGRONOMY_ASSIGNED_STAGE_ARTIFACT"
            ]
            self.assertEqual([entry.kind for entry in specialist_audit], [
                "READ_ALLOWED", "READ_ALLOWED", "READ_DENIED", "READ_DENIED",
            ])
            self.assertTrue(all(
                entry.reason_ref == "DEMO-STAGE-01"
                and entry.target_digest == hashlib.sha256(
                    digest.encode("utf-8")
                ).hexdigest()
                for entry in specialist_audit
            ))
            self.assertTrue(self.ledger.verify_integrity())
        finally:
            with psycopg.connect(POSTGRES_DSN) as db:
                db.execute(
                    "DELETE FROM ronas_stage_artifact "
                    "WHERE owner_hash=%s AND case_hash=%s",
                    (owner_hash, case_hash),
                )

    @unittest.skipUnless(POSTGRES_DSN, "RONAS_TEST_POSTGRES_DSN is not configured")
    def test_postgres_pkce_session_and_stage_artifact_cross_bff_instances(self):
        """Join Bearer upload, browser receipt, and PostgreSQL-backed BFF reads."""
        callback_origin = "https://127.0.0.1:8765"
        callback = callback_origin + "/api/auth/callback"
        realm = KeycloakConfig(
            ISS, API, WEB, self.config.jwks_json,
        )
        key_file = self.path.parent / "postgres-bff-session.key"
        key_file.write_bytes(secrets.token_bytes(32))
        key_file.chmod(0o600)
        settings = PostgresLocalBFFSettings(
            realm, callback, POSTGRES_DSN, key_file,
        )
        store = PostgresStageArtifactStore(
            POSTGRES_DSN, secrets.token_bytes(32), scope_key=b"q" * 32,
        )
        image = b"\x89PNG\r\n\x1a\n" + b"ronas-cross-instance-pg-flow"
        case_artifact_ref = REF + ":DEMO-STAGE-01"
        owner_hash, case_hash = store._scope(OWNER, case_artifact_ref)
        with psycopg.connect(POSTGRES_DSN) as db:
            db.execute(
                "DELETE FROM ronas_stage_artifact WHERE owner_hash=%s AND case_hash=%s",
                (owner_hash, case_hash),
            )

        nonce_holder = {}
        access_holder = {}
        state_hash = None
        session_hash = None

        def token_response(req):
            self.assertEqual(req.method, "POST")
            self.assertEqual(
                str(req.url), ISS + "/protocol/openid-connect/token",
            )
            self.assertIn(b"code_verifier=", req.content)
            now = int(time.time())
            common = {
                "iss": ISS, "sub": OWNER, "iat": now - 5, "exp": now + 450,
            }
            access = jwt.encode(
                {**common, "aud": API, "azp": WEB, "typ": "Bearer",
                 "nbf": now - 5,
                 "resource_access": {API: {"roles": ["household"]}}},
                self.key, algorithm="RS256", headers={"kid": "profile-test"},
            )
            access_holder["token"] = access
            identity = jwt.encode(
                {**common, "aud": WEB, "azp": WEB,
                 "nonce": nonce_holder["nonce"]},
                self.key, algorithm="RS256", headers={"kid": "profile-test"},
            )
            return httpx.Response(200, json={
                "token_type": "Bearer", "access_token": access,
                "id_token": identity,
            })

        workspace = SyntheticAgronomyWorkspace(
            self.ledger,
            (SyntheticAgronomyAssignment(REF, "synthetic-pg-flow-specialist", 2),),
            trusted_assignment_active=lambda *_: True,
        )
        def build_app():
            return create_postgres_local_test_bff(
                settings, transport=httpx.MockTransport(token_response),
                case_ledger=self.ledger, agronomy_workspace=workspace,
                household_profile_schema=self.schema,
                household_profile_access_authority=self.allowed,
                household_stage_context_authority=self.stage_context,
                household_stage_artifact_store=store,
            )

        first_app, second_app = build_app(), build_app()
        browser_a = TestClient(first_app, base_url=callback_origin,
                               follow_redirects=False)
        browser_b = TestClient(second_app, base_url=callback_origin,
                               follow_redirects=False)
        try:
            profile = self.client.post(
                ROOT, json=self.command(), headers=self.bearer(),
            )
            self.assertEqual(profile.status_code, 201, profile.text)
            start = browser_a.get("/api/auth/start")
            self.assertEqual(start.status_code, 303, start.text)
            query = parse_qs(urlsplit(start.headers["location"]).query)
            self.assertEqual(query["code_challenge_method"], ["S256"])
            self.assertEqual(query["redirect_uri"], [callback])
            state_hash = hashlib.sha256(
                query["state"][0].encode("ascii"),
            ).hexdigest()
            nonce_holder["nonce"] = query["nonce"][0]
            browser_b.cookies.update(browser_a.cookies)
            callback_response = browser_b.get(
                "/api/auth/callback", params={
                    "code": "cross-instance-code", "state": query["state"][0],
                },
            )
            self.assertEqual(callback_response.status_code, 303,
                             callback_response.text)
            session = browser_b.get("/api/auth/session")
            self.assertEqual(session.status_code, 200, session.text)
            self.assertNotIn("access_token", session.text)
            sid = browser_b.cookies.get("__Host-ronas_session")
            self.assertIsInstance(sid, str)
            session_hash = hashlib.sha256(sid.encode("ascii")).hexdigest()

            page = "/my-drafts/" + REF + "/stage-observations"
            artifact_path = (
                "/api/v1/domestic/household-intake/my-drafts/" + REF
                + "/stage-observations/artifacts/DEMO-STAGE-01"
            )
            api_headers = {
                "Authorization": "Bearer " + access_holder["token"],
                "Content-Type": "image/png",
                "X-Ronas-Case-Version": "2",
                "X-Ronas-Input-Revision": "1",
                "X-Ronas-Plan-Digest": self.stage_plan_digest,
                "X-Ronas-Requirements-Digest": "a" * 64,
            }
            upload = browser_b.put(
                artifact_path, content=image, headers=api_headers,
            )
            self.assertEqual(upload.status_code, 201, upload.text)
            digest = upload.json()["digest"]
            api_download_path = artifact_path + "/" + digest
            self.assertEqual(browser_b.get(
                api_download_path,
                headers={"Authorization": api_headers["Authorization"]},
            ).status_code, 404)
            command = self.stage_command(action="DEMO-PG-CROSS-BFF-RECEIPT")
            form = {
                "csrf": session.json()["csrf"], "action_id": command["action_id"],
                "case_version": str(command["expected_case_version"]),
                "input_revision": str(command["expected_input_revision"]),
                "input_snapshot_digest": command["expected_input_snapshot_digest"],
                "plan_digest": command["expected_plan_digest"],
                "stage_ref": command["stage_ref"],
                "requirements_digest": command[
                    "expected_observation_requirements_digest"],
                "observation_revision": "0", "corrects_revision": "0",
                "artifact_digest": digest,
            }
            saved = browser_b.post(
                page, content=urlencode(form), headers={
                    "Origin": callback_origin,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            self.assertEqual(saved.status_code, 303, saved.text)

            # App A resolves App B's PostgreSQL-backed cookie session, then
            # authorizes and serves the exact artifact linked by the shared ledger.
            browser_a.cookies.update(browser_b.cookies)
            history = browser_a.get(page)
            self.assertEqual(history.status_code, 200, history.text)
            self.assertIn(digest, history.text)
            downloaded = browser_a.get(
                page + "/artifacts/DEMO-STAGE-01/" + digest,
            )
            self.assertEqual(downloaded.status_code, 200, downloaded.text)
            self.assertEqual(downloaded.content, image)
            self.assertEqual(downloaded.headers["cache-control"], "no-store")
            api_download = browser_a.get(
                api_download_path,
                headers={"Authorization": api_headers["Authorization"]},
            )
            self.assertEqual(api_download.status_code, 200, api_download.text)
            self.assertEqual(api_download.content, image)
            self.assertIn("no-store", api_download.headers["cache-control"])
            self.assertEqual(api_download.headers["x-content-type-options"], "nosniff")
            self.assertEqual(first_app.state.ronas_local_bff_session_backend,
                             "postgresql")
            self.assertEqual(second_app.state.ronas_local_bff_session_backend,
                             "postgresql")
            with psycopg.connect(POSTGRES_DSN) as db:
                ciphertext = db.execute(
                    "SELECT ciphertext FROM ronas_stage_artifact "
                    "WHERE owner_hash=%s AND case_hash=%s AND digest=%s",
                    (owner_hash, case_hash, digest),
                ).fetchone()[0]
            self.assertNotIn(image, bytes(ciphertext))
            self.assertTrue(self.ledger.verify_integrity())
        finally:
            browser_a.close()
            browser_b.close()
            with psycopg.connect(POSTGRES_DSN) as db:
                db.execute(
                    "DELETE FROM ronas_stage_artifact "
                    "WHERE owner_hash=%s AND case_hash=%s",
                    (owner_hash, case_hash),
                )
                if state_hash is not None:
                    db.execute(
                        "DELETE FROM ronas_browser_pending_login WHERE state_hash=%s",
                        (state_hash,),
                    )
                if session_hash is not None:
                    db.execute(
                        "DELETE FROM ronas_browser_session_refresh_lock "
                        "WHERE sid_hash=%s", (session_hash,),
                    )
                    db.execute(
                        "DELETE FROM ronas_browser_session WHERE sid_hash=%s",
                        (session_hash,),
                    )

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
        self.ledger.append_owned_input_manifest(
            REF, Principal(OWNER, frozenset({"household"})),
            action_id="DEMO-SURPLUS-API-INPUT-1", expected_case_version=2,
            expected_input_revision=0, synthetic_manifest_digest="f" * 64,
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
            "input_revision": 1,
            "values": {"field_alpha": "synthetic product", "field_choice": "sample-a"},
        }
        created = client.put(path, json=command, headers=self.bearer())
        self.assertEqual(created.status_code, 201, created.text)
        self.assertFalse(created.json()["published"])
        self.assertFalse(created.json()["real_data"])
        self.assertNotIn("producer_subject", created.json())
        self.assertEqual(created.json()["revision"], 1)
        self.assertEqual(created.json()["input_revision"], 1)
        read = client.get(path, headers=self.bearer())
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()["values"], command["values"])
        other = client.get(
            path, headers=self.bearer("synthetic-other", ("household",)),
        )
        self.assertEqual(other.status_code, 404)
        self.ledger.append_owned_input_manifest(
            REF, Principal(OWNER, frozenset({"household"})),
            action_id="DEMO-SURPLUS-API-INPUT-2", expected_case_version=2,
            expected_input_revision=1, synthetic_manifest_digest="1" * 64,
        )
        stale = dict(command, action_id="DEMO-OFFER-API-A2")
        stale_response = client.put(path, json=stale, headers=self.bearer())
        self.assertEqual(stale_response.status_code, 409)
        self.assertEqual(
            stale_response.json()["detail"], "HOUSEHOLD_INPUT_REVISION_CHANGED",
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
            history["contract_version"], "ronas.domestic.surplus-draft-history.v3",
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
        owner = Principal(OWNER, frozenset({"household"}))
        self.ledger.append_owned_input_manifest(
            REF, owner, action_id="DEMO-SURPLUS-INPUT-INITIAL",
            expected_case_version=2, expected_input_revision=0,
            synthetic_manifest_digest="d" * 64,
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
            "input_revision": "1",
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
        self.assertEqual(ledger.read_owned(
            owner, REF, "DEMO-OFFER-UI-1",
        ).input_revision, 1)
        self.ledger.append_owned_input_manifest(
            REF, owner, action_id="DEMO-SURPLUS-INPUT-CORRECTED",
            expected_case_version=2, expected_input_revision=1,
            synthetic_manifest_digest="e" * 64,
        )
        stale_list = client.get(draft_path)
        self.assertIn("اطلاعات خانوار تغییر کرده", stale_list.text)
        stale_form = client.post(
            f"/my-drafts/{REF}/surplus-offers", content=urlencode(form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(stale_form.status_code, 409)
        self.assertIn("HOUSEHOLD_INPUT_REVISION_CHANGED", stale_form.text)
        self.assertEqual(ledger.read_owned(
            owner, REF, "DEMO-OFFER-UI-1",
        ).revision, 1)
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

    def test_surplus_ui_maps_storage_outage_separately_from_authority_failure(self):
        ledger = SqliteSyntheticSurplusDraftLedger(
            str(self.path.parent / "surplus-drafts-storage-failure.sqlite3"),
            self.schema, self.allowed,
        )
        def storage_unavailable(*_args):
            raise SurplusDraftStorageError("database unavailable")

        ledger.list_owned = storage_unavailable
        client = TestClient(
            self.make_app(surplus_draft_ledger=ledger), base_url=ORIGIN,
        )
        session = self.browser_session()
        sid = next(key for key, value in self.sessions.sessions.items()
                   if value is session)
        client.cookies.set("__Host-ronas_session", sid)
        response = client.get(f"/my-drafts/{REF}/surplus-offers")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "SURPLUS_DRAFT_UNAVAILABLE")

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

    def test_surplus_producer_consent_browser_form_approves_and_withdraws_exact_version(self):
        draft_path = str(self.path.parent / "surplus-consent-drafts.sqlite3")
        draft_ledger = SqliteSyntheticSurplusDraftLedger(
            draft_path, self.schema, self.allowed,
        )
        owner = Principal(OWNER, frozenset({"household"}))
        offer_ref = "DEMO-OFFER-CONSENT-UI"
        saved = draft_ledger.save(
            owner, REF, offer_ref, action_id="DEMO-CONSENT-DRAFT",
            expected_revision=0,
            values={"field_alpha": "sample offer", "field_choice": "sample-a"},
        )
        consent = SqliteSyntheticProducerConsentLedger(
            str(self.path.parent / "surplus-consent-journal.sqlite3"),
            draft_ledger,
        )

        def resolver(principal, household_ref, requested_offer):
            current = draft_ledger.read_owned(principal, household_ref, requested_offer)
            return OfferRevision(
                current.offer_ref, current.household_ref, current.producer_subject,
                current.revision, current.payload_digest,
            ), PublicationAuthorities()

        app = self.make_app(
            surplus_authority=resolver, surplus_draft_ledger=draft_ledger,
            surplus_consent_ledger=consent,
        )
        client = TestClient(app, base_url=ORIGIN)
        session = self.browser_session()
        sid = next(key for key, value in self.sessions.sessions.items()
                   if value is session)
        client.cookies.set("__Host-ronas_session", sid)
        path = f"/my-drafts/{REF}/surplus-publication-readiness"
        readiness = client.get(path, params={"offer_ref": offer_ref})
        self.assertEqual(readiness.status_code, 200, readiness.text)
        self.assertIn("موافقت با انتشار همین نسخه", readiness.text)
        self.assertIn("به‌تنهایی باعث انتشار نمی‌شود", readiness.text)
        form = {
            "csrf": session.csrf, "action_id": "DEMO-CONSENT-UI-1",
            "offer_revision": str(saved.revision),
            "payload_digest": saved.payload_digest, "approved": "true",
        }
        posted = client.post(
            f"/my-drafts/{REF}/surplus-offers/{offer_ref}/publication-consent",
            content=urlencode(form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(posted.status_code, 303, posted.text)
        approved = client.get(path, params={"offer_ref": offer_ref})
        self.assertIn("پس‌گرفتن موافقت انتشار همین نسخه", approved.text)
        self.assertNotIn("تأیید تولیدکننده ثبت نشده است", approved.text)
        self.assertIn("بررسی مستقل کیفیت و ایمنی ثبت نشده است", approved.text)
        self.assertIn("وضعیت انتشار: منتشر نشده", approved.text)
        form.update(action_id="DEMO-CONSENT-UI-2", approved="false")
        withdrawn = client.post(
            f"/my-drafts/{REF}/surplus-offers/{offer_ref}/publication-consent",
            content=urlencode(form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(withdrawn.status_code, 303, withdrawn.text)
        after_withdrawal = client.get(path, params={"offer_ref": offer_ref})
        self.assertIn("موافقت با انتشار همین نسخه", after_withdrawal.text)
        self.assertIn("تأیید تولیدکننده ثبت نشده است", after_withdrawal.text)
        self.assertFalse(draft_ledger.read_owned(
            owner, REF, offer_ref,
        ).published)

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
        self.ledger.append_owned_input_manifest(
            REF, owner, action_id="DEMO-BOUND-INPUT-1",
            expected_case_version=2, expected_input_revision=0,
            synthetic_manifest_digest="7" * 64,
        )
        offer_ref = "DEMO-OFFER-BOUND-1"
        ledger.save(
            owner, REF, offer_ref, action_id="DEMO-BOUND-A1",
            expected_revision=0, input_revision=1,
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
                         "ronas.domestic.surplus-publication-gate.v3")
        self.assertTrue(first.json()["can_publish"])
        self.assertEqual(first.json()["revision"], 1)

        ledger.save(
            owner, REF, offer_ref, action_id="DEMO-BOUND-A2",
            expected_revision=1, input_revision=1,
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
        self.ledger.append_owned_input_manifest(
            REF, owner, action_id="DEMO-BOUND-INPUT-2",
            expected_case_version=2, expected_input_revision=1,
            synthetic_manifest_digest="8" * 64,
        )
        stale_household_input = client.get(readiness_path, headers=self.bearer())
        self.assertEqual(stale_household_input.status_code, 200)
        self.assertIn(
            "HOUSEHOLD_INPUT_REVISION_CHANGED",
            stale_household_input.json()["blockers"],
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
