"""LOCAL/TEST signed specialist questions: append-only audit, no decisions."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import re
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



    def provenance_dossier_url(self):
        return "/api/v1/agronomy/assigned-drafts/DEMO-D-1/provenance-dossier"

    def test_provenance_dossier_full_chain_and_three_track_redaction(self):
        src = ScientificSourceCandidate(
            ref="DEMO-SCI-A", version=1, content_sha256="a" * 64,
            rights_document_ref="DEMO-RIGHTS-A",
            rights_document_sha256="b" * 64,
            science_review_request_ref="DEMO-SCI-REVIEW-A",
            science_review_material_sha256="c" * 64,
        )
        basis = ScientificBasisCandidate(
            ref="DEMO-BASIS-A", version=2, sources=(src,),
        )
        self.science_current[:] = [src]
        self.workspace = self.specialist(
            proposal=self.proposal(science=basis.manifest_digest),
            science_basis=basis,
        )
        self.client = self.make_client()
        self.seed_input()
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post(
            action="DEMO-Q-SCI", track=TRACKS[1],
        ).status_code, 201)
        self.assertEqual(self.post(
            action="DEMO-Q-PLAN", track=TRACKS[2],
        ).status_code, 201)
        self.assertEqual(self.owner_reply().status_code, 201)
        self.assertEqual(self.inspect().status_code, 201)
        result = self.client.get(
            self.provenance_dossier_url(), headers=self.headers(),
        )
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertEqual(data["input"]["current_synthetic_revision"], 1)
        self.assertEqual(data["science"]["basis_candidate_revision"], 2)
        self.assertEqual(data["science"]["source_candidate_count"], 1)
        self.assertEqual(data["proposal"]["synthetic_stage_count"], 1)
        self.assertEqual([x["track"] for x in data["tracks"]], list(TRACKS))
        self.assertEqual([x["latest_question_fixture_binding_matches"]
                          for x in data["tracks"]], [True, True, True])
        self.assertTrue(data["tracks"][0]["expert_receipt_sighted_not_reviewed"])
        self.assertTrue(all(x["review_outcome"] == "NOT_REVIEWED"
                            for x in data["tracks"]))
        self.assertFalse(data["qualified_specialist_verified"])
        self.assertFalse(data["proposal"]["individual_plan_accepted"])
        self.assertFalse(data["science"]["service_use_rights_verified"])
        for forbidden in (
            "DEMO-ANSWER-A", "DEMO-OWNER-EVIDENCE",
            "DEMO-RIGHTS-A", "DEMO-SCI-A", "DEMO-Q-PLAN",
            "DEMO-STAGE-A", "DEMO-RUN-1", "1" * 64,
            basis.manifest_digest,
        ):
            self.assertNotIn(forbidden, result.text)
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertEqual(len([
            e for e in self.ledger.audit_snapshot()
            if e.access_mode == "AGRONOMY_SYNTHETIC_PROVENANCE_DOSSIER"
        ]), 1)

    def test_provenance_dossier_stale_input_fails_without_partial_result(self):
        self.seed_input()
        self.post()
        self.seed_input(revision=1, digest="7" * 64, action="DEMO-INPUT-B")
        failed = self.client.get(
            self.provenance_dossier_url(), headers=self.headers(),
        )
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn("DEMO-REASON-A", failed.text)
        self.assertFalse(any(
            x.access_mode == "AGRONOMY_SYNTHETIC_PROVENANCE_DOSSIER"
            for x in self.ledger.audit_snapshot()
        ))
        self.assertTrue(self.ledger.verify_integrity())

    def test_provenance_dossier_no_catalogue_is_not_science_approval(self):
        self.seed_input()
        self.post()
        ok = self.client.get(
            self.provenance_dossier_url(), headers=self.headers(),
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        lane = ok.json()["tracks"][0]
        self.assertFalse(lane["latest_question_fixture_binding_matches"])
        self.assertEqual(ok.json()["science"]["catalogue_fixture_state"],
                         "NO_CURRENT_CATALOGUE_CHECK")
        self.assertFalse(ok.json()["real_review_decision_recorded"])

    def test_provenance_dossier_source_rights_drift_fails_closed(self):
        src = ScientificSourceCandidate(
            ref="DEMO-SCI-A", version=1, content_sha256="a" * 64,
            rights_document_ref="DEMO-RIGHTS-A",
            rights_document_sha256="b" * 64,
            science_review_request_ref="DEMO-SCI-REVIEW-A",
            science_review_material_sha256="c" * 64,
        )
        basis = ScientificBasisCandidate(
            ref="DEMO-BASIS-A", version=1, sources=(src,),
        )
        self.science_current[:] = [src]
        self.workspace = self.specialist(
            proposal=self.proposal(science=basis.manifest_digest),
            science_basis=basis,
        )
        self.client = self.make_client()
        self.seed_input()
        self.assertEqual(self.client.get(
            self.provenance_dossier_url(), headers=self.headers()
        ).status_code, 200)
        self.science_current[:] = [
            replace(src, rights_document_sha256="d" * 64)
        ]
        self.assertEqual(self.client.get(
            self.provenance_dossier_url(), headers=self.headers()
        ).status_code, 503)
        self.assertTrue(self.ledger.verify_integrity())

    def test_provenance_dossier_role_scope_default_and_integrity_failure(self):
        endpoint = self.provenance_dossier_url()
        self.assertEqual(self.client.get(endpoint).status_code, 401)
        self.assertEqual(self.client.get(
            endpoint, headers=self.headers(OWNER, ("household",)),
        ).status_code, 404)
        self.assertEqual(self.client.get(
            endpoint.replace("DEMO-D-1", "DEMO-E-1"),
            headers=self.headers(),
        ).status_code, 404)
        self.assertEqual(self.client.post(
            endpoint, json={}, headers=self.headers(),
        ).status_code, 405)
        self.active = False
        self.assertEqual(self.client.get(
            endpoint, headers=self.headers(),
        ).status_code, 404)
        self.active = True
        self.assertEqual(TestClient(create_app(self.config)).get(
            endpoint, headers=self.headers(),
        ).status_code, 404)
        self.seed_input()
        self.post()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER expert_question_no_update")
            db.execute(
                "UPDATE expert_review_question SET reason_ref='DEMO-FORGED'")
        result = self.client.get(endpoint, headers=self.headers())
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("DEMO-FORGED", result.text)


    def drift_url(self):
        return "/api/v1/agronomy/assigned-drafts/DEMO-D-1/historical-binding-drift"

    def test_historical_binding_drift_keeps_owner_receipt_and_three_lanes(self):
        self.seed_input()
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.owner_reply().status_code, 201)
        self.assertEqual(self.inspect().status_code, 201)
        self.assertEqual(self.post(
            track=TRACKS[1], action="DEMO-SCI-Q",
        ).status_code, 201)
        self.assertEqual(self.post(
            track=TRACKS[2], action="DEMO-PLAN-Q",
        ).status_code, 201)
        response = self.client.get(self.drift_url(), headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual([r["track"] for r in data["tracks"]], list(TRACKS))
        self.assertEqual([r["historical_question_count"] for r in data["tracks"]],
                         [1, 1, 1])
        self.assertEqual(data["source_candidate_pointer_state"],
                         "NO_SEPARATE_SOURCE_CATALOGUE")
        self.assertEqual(data["tracks"][0]["questions"][0]["structural_context"],
                         "SCIENTIFIC_CATALOGUE_NOT_CHECKED")
        self.assertTrue(data["tracks"][0]["questions"][0]
                        ["historical_receipt_sighted_not_reviewed"])
        self.assertTrue(all(
            not item["eligible_for_operational_reuse"]
            for track in data["tracks"] for item in track["questions"]
        ))
        for secret in ("DEMO-ANSWER-A", "DEMO-OWNER-EVIDENCE",
                       "DEMO-REASON-A", "DEMO-EVIDENCE-A",
                       "DEMO-STAGE-A", "DEMO-RUN-1", "1" * 64):
            self.assertNotIn(secret, response.text)
        self.assertFalse(data["plan_accepted"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(len([
            e for e in self.ledger.audit_snapshot()
            if e.access_mode == "AGRONOMY_SYNTHETIC_HISTORICAL_BINDING_DRIFT"
        ]), 1)

    def test_historical_binding_drift_after_input_correction_and_new_question(self):
        self.seed_input()
        self.post()
        self.owner_reply()
        self.inspect()
        self.post(action="DEMO-Q-B", revision=1)
        self.seed_input(revision=1, digest="7" * 64, action="DEMO-INPUT-B")
        response = self.client.get(self.drift_url(), headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["tracks"][0]["questions"]
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0]["superseded_by_newer_question"])
        self.assertTrue(items[0]["historical_receipt_sighted_not_reviewed"])
        self.assertEqual([x["structural_context"] for x in items], [
            "HOUSEHOLD_INPUT_REVISION_OR_FINGERPRINT_CHANGED"] * 2)
        self.assertEqual(self.client.get(
            self.provenance_dossier_url(), headers=self.headers()
        ).status_code, 503)
        self.assertTrue(self.ledger.verify_integrity())

    def test_historical_binding_drift_source_candidate_change_is_not_approval(self):
        src = ScientificSourceCandidate(
            ref="DEMO-SCI-DRIFT", version=1, content_sha256="a" * 64,
            rights_document_ref="DEMO-RIGHTS-DRIFT",
            rights_document_sha256="b" * 64,
            science_review_request_ref="DEMO-SCI-REVIEW-DRIFT",
            science_review_material_sha256="c" * 64,
        )
        basis = ScientificBasisCandidate(
            ref="DEMO-BASIS-DRIFT", version=1, sources=(src,),
        )
        self.science_current[:] = [src]
        self.workspace = self.specialist(
            proposal=self.proposal(science=basis.manifest_digest),
            science_basis=basis,
        )
        self.client = self.make_client()
        self.seed_input()
        self.post()
        first = self.client.get(self.drift_url(), headers=self.headers())
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["tracks"][0]["questions"][0]
                         ["structural_context"],
                         "STRUCTURAL_FIXTURE_MATCH_ONLY_UNREVIEWED")
        self.science_current[:] = [
            replace(src, rights_document_sha256="d" * 64)
        ]
        drifted = self.client.get(self.drift_url(), headers=self.headers())
        self.assertEqual(drifted.status_code, 200, drifted.text)
        self.assertEqual(drifted.json()["tracks"][0]["questions"][0]
                         ["structural_context"],
                         "SCIENTIFIC_SOURCE_CANDIDATE_POINTERS_CHANGED")
        self.assertEqual(self.client.get(
            self.provenance_dossier_url(), headers=self.headers()
        ).status_code, 503)
        self.assertFalse(drifted.json()["scientific_validity_verified"])

    def test_historical_drift_source_unavailable_or_malformed_fails_503(self):
        src = ScientificSourceCandidate(
            ref="DEMO-SCI-DRIFT", version=1, content_sha256="a" * 64,
            rights_document_ref="DEMO-RIGHTS-DRIFT",
            rights_document_sha256="b" * 64,
            science_review_request_ref="DEMO-SCI-REVIEW-DRIFT",
            science_review_material_sha256="c" * 64,
        )
        basis = ScientificBasisCandidate(
            ref="DEMO-BASIS-DRIFT", version=1, sources=(src,),
        )
        self.science_current[:] = [src]
        self.workspace = self.specialist(
            proposal=self.proposal(science=basis.manifest_digest),
            science_basis=basis,
        )
        self.client = self.make_client()
        self.seed_input()
        self.post()
        self.science_current[:] = [src, src]
        self.assertEqual(self.client.get(
            self.drift_url(), headers=self.headers()
        ).status_code, 503)
        self.assertTrue(self.ledger.verify_integrity())
        self.workspace._trusted_scientific_sources = (
            lambda: (_ for _ in ()).throw(RuntimeError("source unavailable"))
        )
        self.assertEqual(self.client.get(
            self.drift_url(), headers=self.headers()
        ).status_code, 503)

    def test_historical_drift_requires_signed_role_assignment_and_intact_ledger(self):
        path = self.drift_url()
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(
            path, headers=self.headers(OWNER, ("household",))
        ).status_code, 404)
        self.assertEqual(self.client.get(
            path.replace("DEMO-D-1", "DEMO-E-1"),
            headers=self.headers(),
        ).status_code, 404)
        self.assertEqual(self.client.post(
            path, headers=self.headers(), json={}
        ).status_code, 405)
        self.active = False
        self.assertEqual(self.client.get(
            path, headers=self.headers()
        ).status_code, 404)
        self.active = True
        self.assertEqual(TestClient(create_app(self.config)).get(
            path, headers=self.headers()
        ).status_code, 404)
        self.seed_input()
        self.post()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER expert_question_no_update")
            db.execute(
                "UPDATE expert_review_question SET science_digest=?", ("f" * 64,)
            )
        bad = self.client.get(path, headers=self.headers())
        self.assertEqual(bad.status_code, 503)
        self.assertNotIn("f" * 64, bad.text)


    def handoff_fingerprint_url(self):
        return ("/api/v1/agronomy/assigned-drafts/DEMO-D-1/"
                "review-handoff-fingerprint")

    def test_handoff_fingerprint_stable_until_owner_reply_sighting_or_question(self):
        self.seed_input()
        url = self.handoff_fingerprint_url()
        before = self.client.get(url, headers=self.headers())
        self.assertEqual(before.status_code, 200, before.text)
        empty = before.json()["context_fingerprint_sha256"]
        self.assertEqual(empty, self.client.get(
            url, headers=self.headers()).json()["context_fingerprint_sha256"])
        self.post()
        first = self.client.get(url, headers=self.headers())
        self.assertEqual(first.status_code, 200, first.text)
        self.assertNotEqual(first.json()["context_fingerprint_sha256"], empty)
        self.assertTrue(first.json()["tracks"][0]
                        ["latest_question_fixture_binding_matches"] is False)
        self.owner_reply()
        second = self.client.get(url, headers=self.headers())
        self.assertNotEqual(second.json()["context_fingerprint_sha256"],
                            first.json()["context_fingerprint_sha256"])
        self.inspect()
        third = self.client.get(url, headers=self.headers())
        self.assertNotEqual(third.json()["context_fingerprint_sha256"],
                            second.json()["context_fingerprint_sha256"])
        self.assertTrue(third.json()["tracks"][0]
                        ["latest_specialist_receipt_sighting_present"])
        self.assertFalse(third.json()["independent_decision_recorded"])
        self.assertEqual(third.json()["source_candidate_pointer_state"],
                         "NO_SEPARATE_SOURCE_CATALOGUE")
        self.assertEqual(len([
            x for x in self.ledger.audit_snapshot()
            if x.access_mode == "AGRONOMY_SYNTHETIC_REVIEW_HANDOFF_FINGERPRINT"
        ]), 5)
        for text in ("DEMO-ANSWER-A", "DEMO-OWNER-EVIDENCE",
                     "DEMO-REASON-A", "DEMO-EVIDENCE-A", "DEMO-RUN-1",
                     "DEMO-STAGE-A", "1" * 64):
            self.assertNotIn(text, third.text)

    def test_handoff_fingerprint_tracks_three_independent_lanes(self):
        self.seed_input()
        for i, track in enumerate(TRACKS):
            self.assertEqual(self.post(
                action="DEMO-Q-LANE-" + str(i), track=track,
            ).status_code, 201)
        result = self.client.get(
            self.handoff_fingerprint_url(), headers=self.headers())
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual([t["track"] for t in result.json()["tracks"]],
                         list(TRACKS))
        self.assertEqual([t["historical_question_count"]
                          for t in result.json()["tracks"]], [1, 1, 1])
        self.assertTrue(all(t["review_outcome"] == "NOT_REVIEWED"
                            for t in result.json()["tracks"]))
        self.assertFalse(result.json()["plan_accepted"])

    def test_handoff_fingerprint_current_source_fixture_and_rights_drift(self):
        src = ScientificSourceCandidate(
            ref="DEMO-SCI-FP", version=1, content_sha256="a" * 64,
            rights_document_ref="DEMO-RIGHTS-FP",
            rights_document_sha256="b" * 64,
            science_review_request_ref="DEMO-SCI-REVIEW-FP",
            science_review_material_sha256="c" * 64,
        )
        basis = ScientificBasisCandidate(
            ref="DEMO-BASIS-FP", version=1, sources=(src,),
        )
        self.science_current[:] = [src]
        self.workspace = self.specialist(
            proposal=self.proposal(science=basis.manifest_digest),
            science_basis=basis,
        )
        self.client = self.make_client()
        self.seed_input()
        self.post()
        first = self.client.get(
            self.handoff_fingerprint_url(), headers=self.headers())
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["source_candidate_pointer_state"],
                         "SOURCE_CANDIDATE_POINTERS_PINNED_UNVERIFIED")
        self.assertTrue(first.json()["tracks"][0]
                        ["latest_question_fixture_binding_matches"])
        self.science_current[:] = [
            replace(src, rights_document_sha256="d" * 64)
        ]
        self.assertEqual(self.client.get(
            self.handoff_fingerprint_url(), headers=self.headers()
        ).status_code, 503)
        self.assertTrue(self.ledger.verify_integrity())

    def test_handoff_fingerprint_rejects_stale_input_and_tampering(self):
        self.seed_input()
        self.post()
        self.seed_input(revision=1, digest="7" * 64, action="DEMO-INPUT-B")
        failure = self.client.get(
            self.handoff_fingerprint_url(), headers=self.headers())
        self.assertEqual(failure.status_code, 503)
        self.assertNotIn("DEMO-REASON-A", failure.text)
        self.workspace = self.specialist(
            proposal=self.proposal(revision=2, digest="7" * 64))
        self.client = self.make_client()
        updated = self.client.get(
            self.handoff_fingerprint_url(), headers=self.headers())
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertFalse(updated.json()["tracks"][0]
                         ["latest_question_fixture_binding_matches"])
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER expert_question_no_update")
            db.execute(
                "UPDATE expert_review_question SET evidence_ref='DEMO-TAMPERED'"
            )
        self.assertEqual(self.client.get(
            self.handoff_fingerprint_url(), headers=self.headers()
        ).status_code, 503)

    def test_handoff_fingerprint_signed_case_scope_and_opt_in(self):
        endpoint = self.handoff_fingerprint_url()
        self.assertEqual(self.client.get(endpoint).status_code, 401)
        self.assertEqual(self.client.get(
            endpoint, headers=self.headers(OWNER, ("household",)),
        ).status_code, 404)
        self.assertEqual(self.client.get(
            endpoint.replace("DEMO-D-1", "DEMO-E-1"),
            headers=self.headers(),
        ).status_code, 404)
        self.assertEqual(self.client.post(
            endpoint, json={}, headers=self.headers()
        ).status_code, 405)
        self.active = False
        self.assertEqual(self.client.get(
            endpoint, headers=self.headers()
        ).status_code, 404)
        self.active = True
        self.assertEqual(TestClient(create_app(self.config)).get(
            endpoint, headers=self.headers()
        ).status_code, 404)


    def comparison_timeline_url(self):
        return "/api/v1/agronomy/assigned-drafts/DEMO-D-1/review-evidence-timeline"

    def comparison_url(self, first, last):
        return ("/api/v1/agronomy/assigned-drafts/DEMO-D-1/"
                f"review-evidence-compare?from_revision={first}&to_revision={last}")

    def test_case_local_comparison_historical_input_question_reply_sighting(self):
        self.seed_input()
        self.post()
        self.owner_reply()
        self.inspect()
        self.seed_input(revision=1, digest="7"*64, action="DEMO-INPUT-B")
        timeline = self.client.get(
            self.comparison_timeline_url(), headers=self.headers())
        self.assertEqual(timeline.status_code, 200, timeline.text)
        self.assertEqual(timeline.json()["latest_evidence_revision"], 5)
        self.assertEqual([e["event_kind"] for e in timeline.json()["revisions"]], [
            "HOUSEHOLD_INPUT_REVISION", "EXPERT_QUESTION",
            "OWNER_RESPONSE_RECEIPT", "EXPERT_RECEIPT_SIGHTING",
            "HOUSEHOLD_INPUT_REVISION",
        ])
        compare = self.client.get(self.comparison_url(2, 4), headers=self.headers())
        self.assertEqual(compare.status_code, 200, compare.text)
        data = compare.json()
        self.assertEqual([x["track"] for x in data["track_deltas"]], list(TRACKS))
        self.assertEqual(data["track_deltas"][0]["added_owner_response_count"], 1)
        self.assertEqual(data["track_deltas"][0]["added_receipt_sighting_count"], 1)
        self.assertFalse(data["input_revision_changed"])
        self.assertFalse(data["historical_ai_proposal_reconstructible"])
        self.assertFalse(data["historical_science_catalogue_reconstructible"])
        after = self.client.get(self.comparison_url(4, 5), headers=self.headers())
        self.assertEqual(after.status_code, 200, after.text)
        self.assertTrue(after.json()["input_revision_changed"])
        self.assertEqual(after.json()["to"]["latest_input_revision"], 2)
        again = self.client.get(self.comparison_url(2, 4), headers=self.headers())
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["to"]["evidence_fingerprint_sha256"],
                         data["to"]["evidence_fingerprint_sha256"])
        for forbidden in ("DEMO-ANSWER-A", "DEMO-OWNER-EVIDENCE",
                          "DEMO-REASON-A", "DEMO-EVIDENCE-A", "1"*64,
                          "2"*64, "4"*64, "DEMO-RUN-1"):
            self.assertNotIn(forbidden, compare.text)
        self.assertEqual(compare.headers["cache-control"], "no-store")
        self.assertEqual(len([
            e for e in self.ledger.audit_snapshot()
            if e.access_mode == "AGRONOMY_SYNTHETIC_EVIDENCE_COMPARISON"
        ]), 3)
        self.assertTrue(self.ledger.verify_integrity())

    def test_case_local_comparison_tracks_are_independent(self):
        self.seed_input()
        for i, track in enumerate(TRACKS):
            self.assertEqual(self.post(
                track=track, action=f"DEMO-TRACK-{i}",
            ).status_code, 201)
        comparison = self.client.get(
            self.comparison_url(1, 4), headers=self.headers())
        self.assertEqual(comparison.status_code, 200, comparison.text)
        self.assertEqual([x["added_question_count"]
                          for x in comparison.json()["track_deltas"]],
                         [1, 1, 1])
        self.assertTrue(all(
            x["review_outcome"] == "NOT_REVIEWED"
            and x["eligible_for_operational_reuse"] is False
            for x in comparison.json()["track_deltas"]
        ))

    def test_case_local_comparison_rejects_unauthorized_invalid_and_tampered(self):
        self.seed_input()
        self.post()
        endpoint = self.comparison_url(1, 2)
        self.assertEqual(self.client.get(endpoint).status_code, 401)
        self.assertEqual(self.client.get(
            endpoint, headers=self.headers(OWNER, ("household",))
        ).status_code, 404)
        self.assertEqual(self.client.get(
            endpoint.replace("DEMO-D-1", "DEMO-E-1"),
            headers=self.headers()
        ).status_code, 404)
        self.active = False
        self.assertEqual(self.client.get(
            endpoint, headers=self.headers()).status_code, 404)
        self.active = True
        for a, b, expected in [(1,1,409),(2,1,409),(1,999,409),(0,2,422)]:
            with self.subTest(a=a,b=b):
                self.assertEqual(self.client.get(
                    self.comparison_url(a,b), headers=self.headers()
                ).status_code, expected)
        self.assertEqual(self.client.post(
            endpoint, json={}, headers=self.headers()
        ).status_code, 405)
        app = TestClient(create_app(self.config))
        self.assertEqual(app.get(
            endpoint, headers=self.headers()
        ).status_code, 404)
        self.assertEqual(app.get(
            self.comparison_timeline_url(),
            headers=self.headers(),
        ).status_code, 404)
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER expert_question_no_update")
            db.execute(
                "UPDATE expert_review_question SET evidence_ref='DEMO-FORGED'"
            )
        bad = self.client.get(endpoint, headers=self.headers())
        self.assertEqual(bad.status_code, 503)
        self.assertNotIn("DEMO-FORGED", bad.text)


    def test_synthetic_catalogue_current_callback_invalidates_withheld_source(self):
        from ronas_api.internal_scientific_catalogue import (
            SyntheticScientificCatalogue, SyntheticSourceCatalogueEvent,
            RECORDED, WITHHELD,
        )
        src = ScientificSourceCandidate(
            ref="DEMO-SCI-CATALOG", version=1, content_sha256="a" * 64,
            rights_document_ref="DEMO-RIGHTS-CATALOG",
            rights_document_sha256="b" * 64,
            science_review_request_ref="DEMO-REVIEW-CATALOG",
            science_review_material_sha256="c" * 64,
        )
        basis = ScientificBasisCandidate(
            ref="DEMO-BASIS-CATALOG", version=1, sources=(src,),
        )
        source_history = {
            "current": SyntheticScientificCatalogue().with_event(
                SyntheticSourceCatalogueEvent(
                    action_ref="DEMO-SRC-A", source_ref=src.ref,
                    source_revision=1, operation=RECORDED, candidate=src,
                ),
            ),
        }
        self.workspace = self.specialist(
            proposal=self.proposal(science=basis.manifest_digest),
            science_basis=basis,
        )
        self.workspace._trusted_scientific_sources = (
            lambda: source_history["current"].current_sources()
        )
        self.client = self.make_client()
        self.seed_input()
        self.assertEqual(self.client.get(
            self.provenance_dossier_url(), headers=self.headers(),
        ).status_code, 200)
        self.assertEqual(self.client.get(
            self.handoff_fingerprint_url(), headers=self.headers(),
        ).status_code, 200)
        source_history["current"] = source_history["current"].with_event(
            SyntheticSourceCatalogueEvent(
                action_ref="DEMO-SRC-WITHHELD", source_ref=src.ref,
                source_revision=2, operation=WITHHELD,
                reason_ref="DEMO-REASON-WITHHELD",
            ),
        )
        self.assertEqual(self.client.get(
            self.provenance_dossier_url(), headers=self.headers(),
        ).status_code, 503)
        self.assertEqual(self.client.get(
            self.handoff_fingerprint_url(), headers=self.headers(),
        ).status_code, 503)
        self.assertTrue(self.ledger.verify_integrity())

    def test_synthetic_catalogue_new_rights_version_blocks_prior_proposal(self):
        from ronas_api.internal_scientific_catalogue import (
            SyntheticScientificCatalogue, SyntheticSourceCatalogueEvent,
            RECORDED,
        )
        src = ScientificSourceCandidate(
            ref="DEMO-SCI-CATALOG", version=1, content_sha256="a" * 64,
            rights_document_ref="DEMO-RIGHTS-CATALOG",
            rights_document_sha256="b" * 64,
            science_review_request_ref="DEMO-REVIEW-CATALOG",
            science_review_material_sha256="c" * 64,
        )
        basis = ScientificBasisCandidate(
            ref="DEMO-BASIS-CATALOG", version=1, sources=(src,),
        )
        first = SyntheticScientificCatalogue().with_event(
            SyntheticSourceCatalogueEvent(
                action_ref="DEMO-ADD-A", source_ref=src.ref,
                source_revision=1, operation=RECORDED, candidate=src,
            ),
        )
        state = {"current": first}
        self.workspace = self.specialist(
            proposal=self.proposal(science=basis.manifest_digest),
            science_basis=basis,
        )
        self.workspace._trusted_scientific_sources = (
            lambda: state["current"].current_sources()
        )
        self.client = self.make_client()
        self.seed_input()
        self.assertEqual(self.client.get(
            self.provenance_dossier_url(), headers=self.headers(),
        ).status_code, 200)
        state["current"] = first.with_event(
            SyntheticSourceCatalogueEvent(
                action_ref="DEMO-ADD-B", source_ref=src.ref,
                source_revision=2, operation=RECORDED,
                candidate=replace(
                    src, version=2, rights_document_sha256="d" * 64,
                ),
            ),
        )
        self.assertEqual(state["current"].compare(1, 2)[
            "changed_service_rights_document_pointer_count"], 1)
        self.assertEqual(self.client.get(
            self.provenance_dossier_url(), headers=self.headers(),
        ).status_code, 503)
        # Historical question and response evidence is still readable;
        # a source revision alone never deletes it or approves it.
        self.assertEqual(self.client.get(
            ROOT, headers=self.headers(),
        ).status_code, 200)
        self.assertTrue(self.ledger.verify_integrity())


    def specialist_scope_evidence_url(self):
        return ("/api/v1/agronomy/assigned-drafts/DEMO-D-1/"
                "specialist-scope-evidence")

    def specialist_governance_fixture(self):
        from ronas_api.internal_specialist_scope_contract import (
            SpecialistScopeEvidenceCandidate, SpecialistScopeEvidenceEvent,
            SyntheticSpecialistEvidenceRegistry, RECORDED,
        )
        scope=SpecialistScopeEvidenceCandidate(
            subject=EXPERT, case_ref="DEMO-D-1", case_version=3,
            evidence_revision=1,
            declared_review_tracks=(TRACKS[0], TRACKS[2]),
            qualification_evidence_ref="DEMO-QUAL-FIXTURE",
            qualification_evidence_sha256="a"*64,
            appointment_evidence_ref="DEMO-APPT-FIXTURE",
            appointment_evidence_sha256="b"*64,
            conflict_disclosure_ref="DEMO-CONFLICT-FIXTURE",
            conflict_disclosure_sha256="c"*64,
            conflict_declaration_state="POTENTIAL_CONFLICT_DECLARED",
        )
        record=SpecialistScopeEvidenceEvent(
            action_ref="DEMO-GOV-EV-A", subject=EXPERT,
            case_ref="DEMO-D-1", case_version=3,
            evidence_revision=1, operation=RECORDED, candidate=scope,
        )
        return SyntheticSpecialistEvidenceRegistry((record,))

    def test_specialist_scope_evidence_is_redacted_non_authorizing(self):
        from ronas_api.internal_specialist_scope_contract import (
            SyntheticSpecialistEvidenceRegistry,
        )
        state={"current":self.specialist_governance_fixture()}
        self.workspace._trusted_specialist_governance_snapshot = (
            lambda: state["current"]
        )
        url=self.specialist_scope_evidence_url()
        first=self.client.get(url, headers=self.headers())
        self.assertEqual(first.status_code, 200, first.text)
        r=first.json()
        self.assertEqual(r["evidence_state"],"EVIDENCE_POINTERS_PRESENT_UNVERIFIED")
        self.assertTrue(r["potential_conflict_disclosed"])
        self.assertFalse(r["conflict_independently_cleared"])
        self.assertFalse(r["scope_authorized_for_real_review"])
        self.assertFalse(r["plan_accepted"])
        self.assertEqual([t["declared_candidate_scope_present"]
                          for t in r["track_scopes"]],[True,False,True])
        self.assertTrue(all(not t["may_decide_cultivation_plan"]
                            for t in r["track_scopes"]))
        for secret in ("DEMO-QUAL-FIXTURE","DEMO-APPT-FIXTURE",
                       "DEMO-CONFLICT-FIXTURE","a"*64,"b"*64,"c"*64,EXPERT):
            self.assertNotIn(secret,first.text)
        self.assertEqual(first.headers["cache-control"],"no-store")
        self.assertEqual(sum(
            e.access_mode == "AGRONOMY_SYNTHETIC_SPECIALIST_SCOPE_EVIDENCE"
            for e in self.ledger.audit_snapshot()),1)
        state["current"]=SyntheticSpecialistEvidenceRegistry()
        other=self.client.get(url, headers=self.headers())
        self.assertEqual(other.status_code,200,other.text)
        self.assertEqual(other.json()["evidence_state"],
                         "NO_SYNTHETIC_EVIDENCE_CANDIDATE")
        self.assertFalse(other.json()["candidate_is_access_grant"])

    def test_specialist_scope_evidence_withdrawal_is_never_decision_clearance(self):
        from ronas_api.internal_specialist_scope_contract import (
            SpecialistScopeEvidenceEvent, WITHHELD,
        )
        history=self.specialist_governance_fixture()
        state={"current":history}
        self.workspace._trusted_specialist_governance_snapshot=(
            lambda:state["current"]
        )
        url=self.specialist_scope_evidence_url()
        self.assertEqual(self.client.get(url,headers=self.headers()).status_code,200)
        state["current"]=history.with_event(SpecialistScopeEvidenceEvent(
            action_ref="DEMO-GOV-WITHHOLD",subject=EXPERT,
            case_ref="DEMO-D-1",case_version=3,evidence_revision=2,
            operation=WITHHELD,reason_ref="DEMO-WITHHOLD-REASON",
        ))
        r=self.client.get(url,headers=self.headers())
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["evidence_state"],
                         "CANDIDATE_WITHHELD_NOT_AUTHORIZED")
        self.assertFalse(r.json()["scope_authorized_for_real_review"])
        self.assertEqual(history.project_assigned_case(
            subject=EXPERT,case_ref="DEMO-D-1",case_version=3
        )["candidate_revision"],1)
        self.assertTrue(self.ledger.verify_integrity())

    def test_specialist_scope_evidence_live_role_scope_and_authority_failure(self):
        url=self.specialist_scope_evidence_url()
        self.assertEqual(self.client.get(url).status_code,401)
        self.assertEqual(self.client.get(
            url,headers=self.headers(OWNER,("household",))
        ).status_code,404)
        self.assertEqual(self.client.get(
            url.replace("DEMO-D-1","DEMO-E-1"),headers=self.headers()
        ).status_code,404)
        self.assertEqual(self.client.post(
            url,headers=self.headers(),json={}
        ).status_code,405)
        self.active=False
        self.assertEqual(self.client.get(
            url,headers=self.headers()
        ).status_code,404)
        self.active=True
        self.assertEqual(TestClient(create_app(self.config)).get(
            url,headers=self.headers()
        ).status_code,404)
        state={"current":self.specialist_governance_fixture()}
        self.workspace._trusted_specialist_governance_snapshot=(
            lambda:state["current"]
        )
        self.assertEqual(self.client.get(url,headers=self.headers()).status_code,200)
        self.workspace._trusted_specialist_governance_snapshot=(
            lambda: (_ for _ in ()).throw(RuntimeError("offline"))
        )
        self.assertEqual(self.client.get(url,headers=self.headers()).status_code,503)
        self.workspace._trusted_specialist_governance_snapshot=lambda: {"approved":True}
        self.assertEqual(self.client.get(url,headers=self.headers()).status_code,503)
        self.assertTrue(self.ledger.verify_integrity())

    def test_specialist_scope_evidence_tampered_case_ledger_fails_closed(self):
        self.seed_input()
        self.post()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER expert_question_no_update")
            db.execute(
                "UPDATE expert_review_question SET reason_ref='DEMO-FORGED'"
            )
        r=self.client.get(
            self.specialist_scope_evidence_url(),headers=self.headers()
        )
        self.assertEqual(r.status_code,503)
        self.assertNotIn("DEMO-FORGED",r.text)


    def specialist_scope_change_impact_url(self, revision=0):
        return (
            "/api/v1/agronomy/assigned-drafts/DEMO-D-1/"
            f"specialist-scope-change-impact?observed_revision={revision}"
        )

    def test_specialist_evidence_change_impact_tracks_revision_and_unresolved_conflict(self):
        from ronas_api.internal_specialist_scope_contract import (
            SpecialistScopeEvidenceCandidate, SpecialistScopeEvidenceEvent,
            RECORDED,
        )
        first=self.specialist_governance_fixture()
        current={"snapshot":first}
        self.workspace._trusted_specialist_governance_snapshot=(
            lambda:current["snapshot"]
        )
        self.assertEqual(self.client.get(
            self.specialist_scope_change_impact_url(1),
            headers=self.headers(),
        ).status_code,200)
        updated=SpecialistScopeEvidenceCandidate(
            subject=EXPERT,case_ref="DEMO-D-1",case_version=3,
            evidence_revision=2,
            declared_review_tracks=(TRACKS[1],),
            qualification_evidence_ref="DEMO-QUAL-FIXTURE",
            qualification_evidence_sha256="a"*64,
            appointment_evidence_ref="DEMO-APPT-NEW",
            appointment_evidence_sha256="d"*64,
            conflict_disclosure_ref="DEMO-CONFLICT-FIXTURE",
            conflict_disclosure_sha256="c"*64,
            conflict_declaration_state="CONFLICT_NOT_ASSESSED",
        )
        current["snapshot"]=first.with_event(SpecialistScopeEvidenceEvent(
            action_ref="DEMO-SCOPE-UPDATE",subject=EXPERT,
            case_ref="DEMO-D-1",case_version=3,
            evidence_revision=2,operation=RECORDED,candidate=updated,
        ))
        r=self.client.get(
            self.specialist_scope_change_impact_url(1),
            headers=self.headers(),
        )
        self.assertEqual(r.status_code,200,r.text)
        data=r.json()
        self.assertTrue(data["version_changed"])
        self.assertTrue(data["appointment_evidence_pointer_changed"])
        self.assertTrue(data["conflict_declaration_changed"])
        self.assertEqual(data["observed_conflict_diagnostic"],
                         "POTENTIAL_CONFLICT_DISCLOSED_UNRESOLVED")
        self.assertEqual(data["current_conflict_diagnostic"],
                         "CONFLICT_NOT_INDEPENDENTLY_ASSESSED")
        self.assertFalse(data["scope_authorized_for_real_review"])
        self.assertEqual([x["current_candidate_scope_declared"] for x in
                          data["declared_track_scope_changes"]],
                         [False,True,False])
        for hidden in ("DEMO-QUAL-FIXTURE","DEMO-APPT-NEW",
                       "DEMO-CONFLICT-FIXTURE","a"*64,"c"*64,EXPERT):
            self.assertNotIn(hidden,r.text)
        self.assertEqual(r.headers["cache-control"],"no-store")
        self.assertEqual(sum(
            e.access_mode=="AGRONOMY_SYNTHETIC_SPECIALIST_SCOPE_CHANGE_IMPACT"
            for e in self.ledger.audit_snapshot()),2)

    def test_specialist_scope_change_impact_withheld_history_never_reused(self):
        from ronas_api.internal_specialist_scope_contract import (
            SpecialistScopeEvidenceEvent, WITHHELD,
        )
        first=self.specialist_governance_fixture()
        state={"snapshot":first}
        self.workspace._trusted_specialist_governance_snapshot=(
            lambda:state["snapshot"]
        )
        state["snapshot"]=first.with_event(SpecialistScopeEvidenceEvent(
            action_ref="DEMO-WITHDRAW-CURRENT",subject=EXPERT,
            case_ref="DEMO-D-1",case_version=3,
            evidence_revision=2,operation=WITHHELD,
            reason_ref="DEMO-WITHDRAW-REASON",
        ))
        r=self.client.get(self.specialist_scope_change_impact_url(1),
                          headers=self.headers())
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["structural_relationship"],
                         "CURRENT_CANDIDATE_WITHHELD_NO_REUSE")
        self.assertEqual(r.json()["current_conflict_diagnostic"],
                         "NO_CURRENT_CANDIDATE_CONFLICT_UNKNOWN")
        self.assertEqual(r.json()["candidate_withheld_since_observed_count"],1)
        self.assertFalse(r.json()["plan_accepted"])
        self.assertEqual(self.client.get(
            self.specialist_scope_evidence_url(),headers=self.headers()
        ).json()["evidence_state"],"CANDIDATE_WITHHELD_NOT_AUTHORIZED")

    def test_specialist_scope_change_impact_auth_scope_conflict_and_failclosed(self):
        url=self.specialist_scope_change_impact_url(0)
        self.assertEqual(self.client.get(url).status_code,401)
        self.assertEqual(self.client.get(
            url,headers=self.headers(OWNER,("household",))
        ).status_code,404)
        self.assertEqual(self.client.get(
            url.replace("DEMO-D-1","DEMO-E-1"),headers=self.headers()
        ).status_code,404)
        self.assertEqual(self.client.post(
            url,headers=self.headers(),json={}
        ).status_code,405)
        self.active=False
        self.assertEqual(self.client.get(
            url,headers=self.headers()
        ).status_code,404)
        self.active=True
        self.assertEqual(TestClient(create_app(self.config)).get(
            url,headers=self.headers()
        ).status_code,404)
        self.assertEqual(self.client.get(
            self.specialist_scope_change_impact_url(0),
            headers=self.headers(),
        ).status_code,200)
        self.workspace._trusted_specialist_governance_snapshot=(
            self.specialist_governance_fixture
        )
        for revision,status in ((-1,422),(2,409),("oops",422)):
            with self.subTest(revision=revision):
                self.assertEqual(self.client.get(
                    self.specialist_scope_change_impact_url(revision),
                    headers=self.headers(),
                ).status_code,status)
        self.workspace._trusted_specialist_governance_snapshot=(
            lambda:(_ for _ in ()).throw(RuntimeError("offline"))
        )
        self.assertEqual(self.client.get(
            url,headers=self.headers()
        ).status_code,503)
        self.assertTrue(self.ledger.verify_integrity())

    def test_specialist_scope_change_impact_ledger_corruption_fails_503(self):
        self.seed_input()
        self.post()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER expert_question_no_update")
            db.execute("UPDATE expert_review_question SET reason_ref='DEMO-FORGED'")
        result=self.client.get(
            self.specialist_scope_change_impact_url(0),
            headers=self.headers(),
        )
        self.assertEqual(result.status_code,503)
        self.assertNotIn("DEMO-FORGED",result.text)


    def review_context_impact_url(self, observed=0):
        return (
            "/api/v1/agronomy/assigned-drafts/DEMO-D-1/"
            f"review-context-impact?observed_specialist_revision={observed}"
        )

    def test_atomic_review_context_joins_current_all_domains_and_stable_read(self):
        source = ScientificSourceCandidate(
            ref="DEMO-SCI-ATOMIC", version=1, content_sha256="a"*64,
            rights_document_ref="DEMO-RIGHTS-ATOMIC",
            rights_document_sha256="b"*64,
            science_review_request_ref="DEMO-SCI-REVIEW-ATOMIC",
            science_review_material_sha256="c"*64,
        )
        basis = ScientificBasisCandidate(
            ref="DEMO-BASIS-ATOMIC", version=1, sources=(source,),
        )
        self.science_current[:] = [source]
        self.workspace = self.specialist(
            proposal=self.proposal(science=basis.manifest_digest),
            science_basis=basis,
        )
        self.workspace._trusted_specialist_governance_snapshot = (
            self.specialist_governance_fixture
        )
        self.client = self.make_client()
        self.seed_input()
        for idx, track in enumerate(TRACKS):
            self.assertEqual(self.post(
                track=track, action=f"DEMO-ATOMIC-Q-{idx}",
            ).status_code, 201)
        self.owner_reply()
        self.inspect()
        endpoint = self.review_context_impact_url(1)
        first = self.client.get(endpoint, headers=self.headers())
        self.assertEqual(first.status_code, 200, first.text)
        result = first.json()
        self.assertEqual(result["household_input"]["current_revision"], 1)
        self.assertEqual(result["household_input"][
            "case_local_immutable_evidence_event_count"], 6)
        self.assertEqual(result["scientific_source"][
            "current_candidate_pointer_state"],
            "SOURCE_CANDIDATE_POINTERS_PINNED_UNVERIFIED")
        self.assertEqual(result["internal_ai_proposal"]["current_fixture_state"],
                         "STRUCTURE_ONLY_UNREVIEWED")
        self.assertEqual(result["specialist_evidence"]["current_revision"], 1)
        self.assertEqual(result["specialist_evidence"]["current_conflict_diagnostic"],
                         "POTENTIAL_CONFLICT_DISCLOSED_UNRESOLVED")
        self.assertEqual([x["historical_question_count"] for x in result["tracks"]],
                         [1, 1, 1])
        self.assertEqual([x["current_declared_scope_candidate_present"]
                          for x in result["tracks"]], [True, False, True])
        self.assertTrue(all(x["latest_question_fixture_binding_matches"]
                            for x in result["tracks"]))
        self.assertTrue(all(not x["eligible_for_operational_reuse"]
                            for x in result["tracks"]))
        self.assertFalse(result["plan_accepted"])
        self.assertFalse(result["real_specialist_decision_recorded"])
        second = self.client.get(endpoint, headers=self.headers())
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["synthetic_context_fingerprint_sha256"],
                         result["synthetic_context_fingerprint_sha256"])
        self.assertEqual(first.headers["cache-control"], "no-store")
        for secret in ("DEMO-RIGHTS-ATOMIC", "DEMO-SCI-ATOMIC",
                       "DEMO-QUAL-FIXTURE", "DEMO-APPT-FIXTURE",
                       "DEMO-CONFLICT-FIXTURE", "DEMO-RUN-1",
                       "DEMO-STAGE-A", EXPERT, "1"*64,
                       basis.manifest_digest):
            self.assertNotIn(secret, first.text)
        self.assertEqual(sum(
            x.access_mode == "AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for x in self.ledger.audit_snapshot()
        ), 2)
        self.assertTrue(self.ledger.verify_integrity())

    def test_atomic_review_context_specialist_withholding_is_diagnostic_only(self):
        from ronas_api.internal_specialist_scope_contract import (
            SpecialistScopeEvidenceEvent, WITHHELD,
        )
        first = self.specialist_governance_fixture()
        state = {"registry": first}
        self.workspace._trusted_specialist_governance_snapshot = (
            lambda: state["registry"]
        )
        self.seed_input()
        baseline = self.client.get(
            self.review_context_impact_url(1), headers=self.headers())
        self.assertEqual(baseline.status_code, 200, baseline.text)
        state["registry"] = first.with_event(SpecialistScopeEvidenceEvent(
            action_ref="DEMO-ATOMIC-WITHHOLD", subject=EXPERT,
            case_ref="DEMO-D-1", case_version=3,
            evidence_revision=2, operation=WITHHELD,
            reason_ref="DEMO-ATOMIC-REASON",
        ))
        result = self.client.get(
            self.review_context_impact_url(1), headers=self.headers())
        self.assertEqual(result.status_code, 200, result.text)
        self.assertNotEqual(
            baseline.json()["synthetic_context_fingerprint_sha256"],
            result.json()["synthetic_context_fingerprint_sha256"],
        )
        self.assertEqual(result.json()["specialist_evidence"][
            "structural_relationship"], "CURRENT_CANDIDATE_WITHHELD_NO_REUSE")
        self.assertEqual(result.json()["specialist_evidence"][
            "current_conflict_diagnostic"],
            "NO_CURRENT_CANDIDATE_CONFLICT_UNKNOWN")
        self.assertTrue(result.json()["specialist_evidence"][
            "scope_candidate_withheld_since_observed"])
        self.assertFalse(result.json()["plan_accepted"])

    def test_atomic_review_context_current_input_drift_fails_closed(self):
        self.seed_input()
        self.post()
        self.seed_input(revision=1, digest="7"*64, action="DEMO-ATOMIC-INPUT-B")
        bad = self.client.get(
            self.review_context_impact_url(0), headers=self.headers())
        self.assertEqual(bad.status_code, 503)
        self.assertFalse(any(
            x.access_mode == "AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for x in self.ledger.audit_snapshot()
        ))
        self.assertEqual(self.client.get(
            self.drift_url(), headers=self.headers()).status_code, 200)
        self.assertTrue(self.ledger.verify_integrity())

    def test_atomic_review_context_source_rights_change_fails_closed(self):
        src = ScientificSourceCandidate(
            ref="DEMO-SCI-ATOMIC", version=1, content_sha256="a"*64,
            rights_document_ref="DEMO-RIGHTS-ATOMIC",
            rights_document_sha256="b"*64,
            science_review_request_ref="DEMO-SCI-REVIEW-ATOMIC",
            science_review_material_sha256="c"*64,
        )
        basis = ScientificBasisCandidate(
            ref="DEMO-BASIS-ATOMIC", version=1, sources=(src,),
        )
        self.science_current[:] = [src]
        self.workspace = self.specialist(
            proposal=self.proposal(science=basis.manifest_digest),
            science_basis=basis,
        )
        self.client = self.make_client()
        self.seed_input()
        self.assertEqual(self.client.get(
            self.review_context_impact_url(0),
            headers=self.headers()).status_code, 200)
        self.science_current[:] = [
            replace(src, rights_document_sha256="d"*64)
        ]
        changed = self.client.get(
            self.review_context_impact_url(0),
            headers=self.headers())
        self.assertEqual(changed.status_code, 503)
        self.assertNotIn("DEMO-RIGHTS-ATOMIC", changed.text)
        self.assertEqual(sum(
            x.access_mode == "AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for x in self.ledger.audit_snapshot()
        ), 1)

    def test_atomic_review_context_role_revision_default_and_integrity(self):
        endpoint = self.review_context_impact_url(0)
        self.assertEqual(self.client.get(endpoint).status_code, 401)
        self.assertEqual(self.client.get(
            endpoint, headers=self.headers(OWNER, ("household",))
        ).status_code, 404)
        self.assertEqual(self.client.get(
            endpoint.replace("DEMO-D-1","DEMO-E-1"),
            headers=self.headers()).status_code, 404)
        self.active = False
        self.assertEqual(self.client.get(
            endpoint, headers=self.headers()).status_code, 404)
        self.active = True
        self.assertEqual(self.client.post(
            endpoint, headers=self.headers(), json={}).status_code, 405)
        self.assertEqual(TestClient(create_app(self.config)).get(
            endpoint, headers=self.headers()).status_code, 404)
        self.seed_input()
        self.workspace._trusted_specialist_governance_snapshot = (
            self.specialist_governance_fixture
        )
        self.assertEqual(self.client.get(
            self.review_context_impact_url(999),
            headers=self.headers()).status_code, 409)
        self.assertEqual(self.client.get(
            self.review_context_impact_url(-1),
            headers=self.headers()).status_code, 422)
        self.workspace._trusted_specialist_governance_snapshot = (
            lambda: (_ for _ in ()).throw(RuntimeError("offline"))
        )
        self.assertEqual(self.client.get(
            endpoint, headers=self.headers()).status_code, 503)
        self.assertTrue(self.ledger.verify_integrity())
        self.workspace._trusted_specialist_governance_snapshot = None
        self.post()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER expert_question_no_update")
            db.execute(
                "UPDATE expert_review_question SET evidence_ref='DEMO-FORGED'"
            )
        forbidden = self.client.get(
            endpoint, headers=self.headers())
        self.assertEqual(forbidden.status_code, 503)
        self.assertNotIn("DEMO-FORGED", forbidden.text)


    def test_context_consistency_external_specialist_change_during_read(self):
        from ronas_api.internal_specialist_scope_contract import (
            SpecialistScopeEvidenceEvent, WITHHELD,
        )
        self.seed_input()
        original=self.specialist_governance_fixture()
        updated=original.with_event(SpecialistScopeEvidenceEvent(
            action_ref="DEMO-MID-WITHHOLD",subject=EXPERT,case_ref="DEMO-D-1",
            case_version=3,evidence_revision=2,operation=WITHHELD,
            reason_ref="DEMO-MID-REASON",
        ))
        calls=[0]
        def source():
            calls[0]+=1
            return original if calls[0]==1 else updated
        self.workspace._trusted_specialist_governance_snapshot=source
        response=self.client.get(
            self.review_context_impact_url(1),headers=self.headers())
        self.assertEqual(response.status_code,503,response.text)
        self.assertEqual(calls,[2])
        self.assertFalse(any(
            x.access_mode=="AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for x in self.ledger.audit_snapshot()))
        self.assertTrue(self.ledger.verify_integrity())

    def test_context_consistency_current_source_drift_during_read(self):
        src=ScientificSourceCandidate(
            ref="DEMO-SCI-DOUBLE",version=1,content_sha256="a"*64,
            rights_document_ref="DEMO-RIGHTS-DOUBLE",
            rights_document_sha256="b"*64,
            science_review_request_ref="DEMO-SCI-DOUBLE-REVIEW",
            science_review_material_sha256="c"*64,
        )
        basis=ScientificBasisCandidate(
            ref="DEMO-BASIS-DOUBLE",version=1,sources=(src,))
        self.workspace=self.specialist(
            proposal=self.proposal(science=basis.manifest_digest),
            science_basis=basis,
        )
        counter=[0]
        def current():
            counter[0]+=1
            if counter[0]==1:
                return (src,)
            return (replace(src,rights_document_sha256="d"*64),)
        self.workspace._trusted_scientific_sources=current
        self.client=self.make_client()
        self.seed_input()
        r=self.client.get(self.review_context_impact_url(0),
                          headers=self.headers())
        self.assertEqual(r.status_code,503,r.text)
        self.assertEqual(counter,[2])
        self.assertNotIn("DEMO-RIGHTS-DOUBLE",r.text)
        self.assertFalse(any(
            x.access_mode=="AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for x in self.ledger.audit_snapshot()))

    def test_context_consistency_revoke_live_assignment_mid_read(self):
        self.seed_input()
        def registry():
            self.active=False
            return self.specialist_governance_fixture()
        self.workspace._trusted_specialist_governance_snapshot=registry
        result=self.client.get(
            self.review_context_impact_url(1),headers=self.headers())
        self.assertEqual(result.status_code,503)
        self.assertEqual(self.client.get(
            self.review_context_impact_url(1),headers=self.headers()
        ).status_code,404)
        self.assertFalse(any(
            x.access_mode=="AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for x in self.ledger.audit_snapshot()))
        self.assertTrue(self.ledger.verify_integrity())

    def test_context_consistency_stale_client_fingerprint_rejected(self):
        self.seed_input()
        url=self.review_context_impact_url(0)
        initial=self.client.get(url,headers=self.headers())
        self.assertEqual(initial.status_code,200,initial.text)
        fingerprint=initial.json()["synthetic_context_fingerprint_sha256"]
        self.assertEqual(self.client.get(
            url+"&expected_context_fingerprint="+fingerprint,
            headers=self.headers()).status_code,200)
        self.assertEqual(self.post().status_code,201)
        stale=self.client.get(
            url+"&expected_context_fingerprint="+fingerprint,
            headers=self.headers())
        self.assertEqual(stale.status_code,409,stale.text)
        self.assertEqual(stale.json()["detail"],"SYNTHETIC_REVIEW_CONTEXT_CHANGED")
        self.assertEqual(self.client.get(
            url+"&expected_context_fingerprint=invalid",
            headers=self.headers()).status_code,422)
        fresh=self.client.get(url,headers=self.headers())
        self.assertEqual(fresh.status_code,200,fresh.text)
        self.assertNotEqual(fresh.json()["synthetic_context_fingerprint_sha256"],
                            fingerprint)
        self.assertEqual(sum(
            x.access_mode=="AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for x in self.ledger.audit_snapshot()),3)

    def test_context_consistency_stable_external_sources_double_checked(self):
        self.seed_input()
        calls=[0]
        original=self.specialist_governance_fixture()
        def source():
            calls[0]+=1
            return original
        self.workspace._trusted_specialist_governance_snapshot=source
        out=self.client.get(
            self.review_context_impact_url(1),headers=self.headers())
        self.assertEqual(out.status_code,200,out.text)
        self.assertEqual(calls,[2])
        self.assertFalse(out.json()["plan_accepted"])

    def versioned_review_context_url(self,observed=0):
        return ("/api/v1/agronomy/assigned-drafts/DEMO-D-1/"
                f"review-context-versioned?observed_specialist_revision={observed}")

    def set_revision_authorities(self,state):
        from ronas_api.internal_authority_revision_witness import (
            SCIENCE,SPECIALIST,ASSIGNMENT,SyntheticAuthorityWitness,
        )
        def callback(kind):
            return lambda actor,ref,version: SyntheticAuthorityWitness(
                kind,actor,ref,version,state[kind])
        self.workspace._authority_version_callbacks=tuple(
            callback(kind) for kind in (SCIENCE,SPECIALIST,ASSIGNMENT)
        )

    def test_versioned_context_requires_real_provider_callbacks(self):
        self.seed_input()
        r=self.client.get(
            self.versioned_review_context_url(),headers=self.headers())
        self.assertEqual(r.status_code,503,r.text)
        self.assertFalse(any(
            e.access_mode=="AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()))

    def test_versioned_context_catches_aba_across_requests(self):
        from ronas_api.internal_authority_revision_witness import (
            SCIENCE,SPECIALIST,ASSIGNMENT,
        )
        state={SCIENCE:1,SPECIALIST:1,ASSIGNMENT:1}
        self.set_revision_authorities(state)
        self.seed_input()
        url=self.versioned_review_context_url()
        first=self.client.get(url,headers=self.headers())
        self.assertEqual(first.status_code,200,first.text)
        original=first.json()
        token=original["synthetic_versioned_context_fingerprint_sha256"]
        self.assertFalse(original["cross_provider_atomicity_verified"])
        for kind in (SCIENCE,SPECIALIST,ASSIGNMENT):
            state[kind]+=2  # A -> B -> A; identical current pointer values
        stale=self.client.get(
            url+"&expected_context_fingerprint="+token,
            headers=self.headers())
        self.assertEqual(stale.status_code,409,stale.text)
        self.assertEqual(stale.json()["detail"],
                         "SYNTHETIC_REVIEW_CONTEXT_CHANGED")
        now=self.client.get(url,headers=self.headers())
        self.assertEqual(now.status_code,200,now.text)
        self.assertEqual(now.json()["synthetic_context_fingerprint_sha256"],
                         original["synthetic_context_fingerprint_sha256"])
        self.assertNotEqual(
            now.json()["synthetic_versioned_context_fingerprint_sha256"],token)
        self.assertEqual(self.client.get(
            url+"&expected_context_fingerprint="+now.json()[
                "synthetic_versioned_context_fingerprint_sha256"],
            headers=self.headers()).status_code,200)
        self.assertEqual(sum(
            e.access_mode=="AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()),3)
        self.assertTrue(self.ledger.verify_integrity())

    def test_versioned_context_catches_aba_within_read(self):
        from ronas_api.internal_authority_revision_witness import (
            SCIENCE,SPECIALIST,ASSIGNMENT,SyntheticAuthorityWitness,
        )
        self.seed_input()
        count={SCIENCE:0,SPECIALIST:0,ASSIGNMENT:0}
        def call(kind):
            def get(actor,ref,version):
                count[kind]+=1
                return SyntheticAuthorityWitness(
                    kind,actor,ref,version,1 if count[kind]==1 else 3)
            return get
        self.workspace._authority_version_callbacks=tuple(
            call(kind) for kind in (SCIENCE,SPECIALIST,ASSIGNMENT))
        failed=self.client.get(
            self.versioned_review_context_url(),headers=self.headers())
        self.assertEqual(failed.status_code,503,failed.text)
        self.assertEqual(count,{SCIENCE:2,SPECIALIST:2,ASSIGNMENT:2})
        self.assertFalse(any(
            e.access_mode=="AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()))

    def test_versioned_context_wrong_scope_role_and_unmounted(self):
        from ronas_api.internal_authority_revision_witness import (
            SCIENCE,SPECIALIST,ASSIGNMENT,SyntheticAuthorityWitness,
        )
        url=self.versioned_review_context_url()
        self.assertEqual(self.client.get(url).status_code,401)
        self.assertEqual(self.client.get(
            url,headers=self.headers(OWNER,("household",))
        ).status_code,404)
        self.active=False
        self.assertEqual(self.client.get(
            url,headers=self.headers()).status_code,404)
        self.active=True
        self.seed_input()
        self.set_revision_authorities({
            SCIENCE:1,SPECIALIST:1,ASSIGNMENT:1})
        self.workspace._authority_version_callbacks=(
            self.workspace._authority_version_callbacks[0],
            lambda actor,ref,version:SyntheticAuthorityWitness(
                SPECIALIST,actor,"DEMO-D-2",version,1),
            self.workspace._authority_version_callbacks[2],
        )
        self.assertEqual(self.client.get(
            url,headers=self.headers()).status_code,503)
        self.assertEqual(self.client.post(
            url,json={},headers=self.headers()).status_code,405)
        self.assertEqual(TestClient(create_app(self.config)).get(
            url,headers=self.headers()).status_code,404)
    def test_persisted_authority_witnesses_back_strict_context_and_detect_aba(self):
        from ronas_api.internal_authority_revision_journal_sqlite import (
            SqliteSyntheticAuthorityRevisionJournal,
        )
        from ronas_api.internal_authority_revision_witness import (
            SCIENCE, SPECIALIST, ASSIGNMENT,
        )
        from ronas_api.internal_specialist_scope_contract import (
            SyntheticSpecialistEvidenceRegistry,
        )
        journal=SqliteSyntheticAuthorityRevisionJournal(
            self.path.parent/"authority-evidence.db"
        )
        state={
            SCIENCE: tuple(),
            SPECIALIST: SyntheticSpecialistEvidenceRegistry(),
            ASSIGNMENT: True,
        }
        order=(SCIENCE,SPECIALIST,ASSIGNMENT)
        for kind in order:
            journal.record_snapshot(
                kind=kind,subject=EXPERT,case_ref="DEMO-D-1",case_version=3,
                snapshot=state[kind],action_ref=f"DEMO-INIT-{kind.replace('_','-')}",
                expected_generation=0,
            )
        reopened=SqliteSyntheticAuthorityRevisionJournal(
            self.path.parent/"authority-evidence.db"
        )
        self.workspace._trusted_specialist_governance_snapshot=(
            lambda: state[SPECIALIST]
        )
        self.workspace._live_authority=(
            lambda actor,ref,ver: (
                self.active is True and actor==EXPERT and ref=="DEMO-D-1"
                and ver==3 and state[ASSIGNMENT] is True
            )
        )
        self.workspace._authority_version_callbacks=tuple(
            reopened.callback(
                kind,lambda actor,ref,ver,key=kind:state[key],
            ) for kind in order
        )
        self.seed_input()
        endpoint=self.versioned_review_context_url()
        initial=self.client.get(endpoint,headers=self.headers())
        self.assertEqual(initial.status_code,200,initial.text)
        first=initial.json()
        old_token=first["synthetic_versioned_context_fingerprint_sha256"]
        self.assertFalse(first["cross_provider_atomicity_verified"])
        self.assertFalse(first["plan_accepted"])
        for kind in order:
            if kind==SCIENCE:
                value=(ScientificSourceCandidate(
                    ref="DEMO-ABA-SOURCE",version=1,
                    content_sha256="a"*64,
                    rights_document_ref="DEMO-ABA-RIGHTS",
                    rights_document_sha256="b"*64,
                    science_review_request_ref="DEMO-ABA-REVIEW",
                    science_review_material_sha256="c"*64,
                ),)
            elif kind==SPECIALIST:
                value=self.specialist_governance_fixture()
            else:
                value=False
            journal.record_snapshot(
                kind=kind,subject=EXPERT,case_ref="DEMO-D-1",case_version=3,
                snapshot=value,action_ref=f"DEMO-ABA-B-{kind.replace('_','-')}",
                expected_generation=1,
            )
            state[kind]=value
            journal.record_snapshot(
                kind=kind,subject=EXPERT,case_ref="DEMO-D-1",case_version=3,
                snapshot=(() if kind==SCIENCE else
                          SyntheticSpecialistEvidenceRegistry() if kind==SPECIALIST
                          else True),
                action_ref=f"DEMO-ABA-A-{kind.replace('_','-')}",expected_generation=2,
            )
            state[kind]=(() if kind==SCIENCE else
                         SyntheticSpecialistEvidenceRegistry() if kind==SPECIALIST
                         else True)
        self.assertTrue(reopened.verify_integrity())
        stale=self.client.get(
            endpoint+"&expected_context_fingerprint="+old_token,
            headers=self.headers(),
        )
        self.assertEqual(stale.status_code,409,stale.text)
        self.assertEqual(stale.json()["detail"],
                         "SYNTHETIC_REVIEW_CONTEXT_CHANGED")
        fresh=self.client.get(endpoint,headers=self.headers())
        self.assertEqual(fresh.status_code,200,fresh.text)
        self.assertEqual(first["synthetic_context_fingerprint_sha256"],
                         fresh.json()["synthetic_context_fingerprint_sha256"])
        self.assertNotEqual(old_token,
                            fresh.json()["synthetic_versioned_context_fingerprint_sha256"])
        self.assertEqual(sum(
            x.access_mode=="AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for x in self.ledger.audit_snapshot()),2)

    def test_persisted_authority_witnesses_reject_unjournaled_change_and_tamper(self):
        from ronas_api.internal_authority_revision_journal_sqlite import (
            SqliteSyntheticAuthorityRevisionJournal,
        )
        from ronas_api.internal_authority_revision_witness import (
            SCIENCE, SPECIALIST, ASSIGNMENT,
        )
        from ronas_api.internal_specialist_scope_contract import (
            SyntheticSpecialistEvidenceRegistry,
        )
        filename=self.path.parent/"authority-evidence.db"
        authority=SqliteSyntheticAuthorityRevisionJournal(filename)
        state={SCIENCE:tuple(),SPECIALIST:SyntheticSpecialistEvidenceRegistry(),
               ASSIGNMENT:True}
        kinds=(SCIENCE,SPECIALIST,ASSIGNMENT)
        for kind in kinds:
            authority.record_snapshot(
                kind=kind,subject=EXPERT,case_ref="DEMO-D-1",case_version=3,
                snapshot=state[kind],action_ref=f"DEMO-INTEGRITY-{kind.replace('_','-')}",
                expected_generation=0,
            )
        self.workspace._authority_version_callbacks=tuple(
            authority.callback(
                kind,lambda actor,ref,ver,key=kind:state[key],
            ) for kind in kinds
        )
        self.seed_input()
        url=self.versioned_review_context_url()
        self.assertEqual(self.client.get(
            url,headers=self.headers()).status_code,200)
        state[ASSIGNMENT]=False
        unchecked=self.client.get(url,headers=self.headers())
        self.assertEqual(unchecked.status_code,503,unchecked.text)
        self.assertNotIn("DEMO-INTEGRITY",unchecked.text)
        self.assertEqual(sum(
            e.access_mode=="AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()),1)
        state[ASSIGNMENT]=True
        with sqlite3.connect(filename) as db:
            db.execute("DROP TRIGGER authority_event_no_update")
            db.execute(
                "UPDATE authority_event SET generation=99 "
                "WHERE kind=? AND generation=1",(ASSIGNMENT,),
            )
        self.assertFalse(authority.verify_integrity())
        tampered=self.client.get(url,headers=self.headers())
        self.assertEqual(tampered.status_code,503,tampered.text)
        self.assertTrue(self.ledger.verify_integrity())


    def test_owned_local_journal_drives_strict_signed_read_with_aba(self):
        from ronas_api.internal_authority_revision_journal_sqlite import (
            SqliteSyntheticAuthorityRevisionJournal,
        )
        from ronas_api.internal_authority_revision_witness import (
            SCIENCE,SPECIALIST,ASSIGNMENT,
        )
        from ronas_api.internal_specialist_scope_contract import (
            SyntheticSpecialistEvidenceRegistry,
        )
        journal=SqliteSyntheticAuthorityRevisionJournal(
            self.path.parent/"owned-authority.db")
        scope=dict(subject=EXPERT,case_ref="DEMO-D-1",case_version=3)
        initial={SCIENCE:tuple(),
                 SPECIALIST:SyntheticSpecialistEvidenceRegistry(),
                 ASSIGNMENT:True}
        for kind,item in initial.items():
            journal.record_owned_snapshot(
                kind=kind,snapshot=item,action_ref=(
                    "DEMO-OWNED-START-"+kind.replace("_","-")
                ),expected_generation=0,**scope,
            )
        reopened=SqliteSyntheticAuthorityRevisionJournal(
            self.path.parent/"owned-authority.db")
        def owned(kind):
            return reopened.read_owned_snapshot(kind=kind,**scope)[0]
        self.workspace._trusted_specialist_governance_snapshot=(
            lambda:owned(SPECIALIST))
        self.workspace._live_authority=lambda actor,ref,version:(
            self.active is True and actor==EXPERT
            and ref=="DEMO-D-1" and version==3
            and owned(ASSIGNMENT) is True
        )
        self.workspace._authority_version_callbacks=tuple(
            reopened.owned_callback(kind)
            for kind in (SCIENCE,SPECIALIST,ASSIGNMENT)
        )
        self.seed_input()
        url=self.versioned_review_context_url()
        before=self.client.get(url,headers=self.headers())
        self.assertEqual(before.status_code,200,before.text)
        token=before.json()["synthetic_versioned_context_fingerprint_sha256"]
        journal.record_owned_snapshot(
            kind=ASSIGNMENT,snapshot=False,action_ref="DEMO-OWNED-REVOKE",
            expected_generation=1,**scope,
        )
        self.assertEqual(self.client.get(
            url,headers=self.headers()).status_code,404)
        journal.record_owned_snapshot(
            kind=ASSIGNMENT,snapshot=True,action_ref="DEMO-OWNED-REGRANT",
            expected_generation=2,**scope,
        )
        stale=self.client.get(
            url+"&expected_context_fingerprint="+token,
            headers=self.headers(),
        )
        self.assertEqual(stale.status_code,409,stale.text)
        after=self.client.get(url,headers=self.headers())
        self.assertEqual(after.status_code,200,after.text)
        self.assertEqual(
            before.json()["synthetic_context_fingerprint_sha256"],
            after.json()["synthetic_context_fingerprint_sha256"],
        )
        self.assertNotEqual(
            token,after.json()["synthetic_versioned_context_fingerprint_sha256"]
        )
        self.assertFalse(after.json()["plan_accepted"])
        self.assertTrue(reopened.verify_integrity())


    def setup_checkpointed_versioned_case(self):
        from ronas_api.internal_authority_revision_journal_sqlite import (
            SqliteSyntheticAuthorityRevisionJournal,
        )
        from ronas_api.internal_authority_local_checkpoint_sqlite import (
            SqliteLocalAuthorityCheckpoint,
        )
        from ronas_api.internal_authority_checkpointed_read import (
            LocalCheckpointedAuthorityRead,
        )
        from ronas_api.internal_authority_revision_witness import (
            SCIENCE, SPECIALIST, ASSIGNMENT,
        )
        from ronas_api.internal_specialist_scope_contract import (
            SyntheticSpecialistEvidenceRegistry,
        )
        journalpath=self.path.parent/"checkpoint-witness-journal.db"
        checkpointpath=self.path.parent/"checkpoint-witness-sidecar.db"
        journal=SqliteSyntheticAuthorityRevisionJournal(journalpath)
        checkpoint=SqliteLocalAuthorityCheckpoint(checkpointpath)
        scope=dict(subject=EXPERT,case_ref="DEMO-D-1",case_version=3)
        states={
            SCIENCE:tuple(),
            SPECIALIST:SyntheticSpecialistEvidenceRegistry(),
            ASSIGNMENT:True,
        }
        for kind,value in states.items():
            journal.record_owned_snapshot(
                kind=kind,snapshot=value,
                action_ref="DEMO-CHK-INIT-"+kind.replace("_","-"),
                expected_generation=0,**scope,
            )
        checkpoint.pin_current(journal)
        self.workspace._local_checkpointed_authority=(
            LocalCheckpointedAuthorityRead(journalpath,checkpointpath)
        )
        self.seed_input()
        return journal,checkpoint,journalpath,checkpointpath,scope

    def test_checkpointed_signed_versioned_read_requires_exact_pinned_files(self):
        journal,checkpoint,jpath,cpath,scope=(
            self.setup_checkpointed_versioned_case()
        )
        url=self.versioned_review_context_url()
        initial=self.client.get(url,headers=self.headers())
        self.assertEqual(initial.status_code,200,initial.text)
        result=initial.json()
        self.assertFalse(result["cross_provider_atomicity_verified"])
        self.assertFalse(result["plan_accepted"])
        self.assertFalse(result["real_specialist_decision_recorded"])
        self.assertEqual(len(result["tracks"]),3)
        self.assertTrue(all(
            x["review_outcome"]=="NOT_REVIEWED" for x in result["tracks"]
        ))
        self.assertEqual(result["authority_generation_values_exposed"]
                         if "authority_generation_values_exposed" in result
                         else False,False)
        self.assertEqual(sum(
            e.access_mode=="AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()),1)
        self.assertTrue(checkpoint.assert_current(journal)[
            "verified_against_separate_local_file"])

    def test_checkpointed_unpinned_advance_and_repin_never_auto_heal(self):
        from ronas_api.internal_authority_revision_witness import ASSIGNMENT
        journal,checkpoint,jpath,cpath,scope=(
            self.setup_checkpointed_versioned_case()
        )
        url=self.versioned_review_context_url()
        first=self.client.get(url,headers=self.headers())
        self.assertEqual(first.status_code,200,first.text)
        token=first.json()["synthetic_versioned_context_fingerprint_sha256"]
        journal.record_owned_snapshot(
            kind=ASSIGNMENT,snapshot=False,
            action_ref="DEMO-CHK-REVOKE",expected_generation=1,**scope,
        )
        self.assertEqual(self.client.get(
            url,headers=self.headers()).status_code,503)
        checkpoint.pin_current(journal)
        self.assertEqual(self.client.get(
            url,headers=self.headers()).status_code,404)
        journal.record_owned_snapshot(
            kind=ASSIGNMENT,snapshot=True,
            action_ref="DEMO-CHK-REGRANT",expected_generation=2,**scope,
        )
        self.assertEqual(self.client.get(
            url,headers=self.headers()).status_code,503)
        checkpoint.pin_current(journal)
        stale=self.client.get(
            url+"&expected_context_fingerprint="+token,
            headers=self.headers(),
        )
        self.assertEqual(stale.status_code,409,stale.text)
        self.assertEqual(stale.json()["detail"],
                         "SYNTHETIC_REVIEW_CONTEXT_CHANGED")
        now=self.client.get(url,headers=self.headers())
        self.assertEqual(now.status_code,200,now.text)
        self.assertNotEqual(token,now.json()[
            "synthetic_versioned_context_fingerprint_sha256"])
        self.assertEqual(sum(
            e.access_mode=="AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()),2)

    def test_checkpointed_missing_checkpoint_refuses_creation_or_success_audit(self):
        journal,checkpoint,jpath,cpath,scope=(
            self.setup_checkpointed_versioned_case()
        )
        cpath.unlink()
        response=self.client.get(
            self.versioned_review_context_url(),headers=self.headers())
        self.assertEqual(response.status_code,503,response.text)
        self.assertEqual(response.json()["detail"],
                         "SYNTHETIC_AGRONOMY_UNAVAILABLE")
        self.assertFalse(cpath.exists())
        self.assertFalse(any(
            e.access_mode=="AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()))

    def test_checkpointed_rolled_back_main_and_checkpoint_mismatch_denied(self):
        journal,checkpoint,jpath,cpath,scope=(
            self.setup_checkpointed_versioned_case()
        )
        old=self.path.parent/"checkpoint-old-main.db"
        with sqlite3.connect(jpath) as src:
            with sqlite3.connect(old) as dst:
                src.backup(dst)
        from ronas_api.internal_authority_revision_witness import SCIENCE
        journal.record_owned_snapshot(
            kind=SCIENCE,snapshot=tuple(),
            action_ref="DEMO-CHK-ADDED",expected_generation=1,**scope,
        )
        checkpoint.pin_current(journal)
        with sqlite3.connect(old) as src:
            with sqlite3.connect(jpath) as dst:
                src.backup(dst)
        response=self.client.get(
            self.versioned_review_context_url(),headers=self.headers())
        self.assertEqual(response.status_code,503,response.text)
        self.assertFalse(any(
            e.access_mode=="AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()))

    def test_checkpointed_source_or_guard_change_mid_read_fails(self):
        from ronas_api.internal_authority_revision_witness import SPECIALIST
        journal,checkpoint,jpath,cpath,scope=(
            self.setup_checkpointed_versioned_case()
        )
        # The first specialist owned-snapshot read is after the first
        # source-scoped/versioned witness. Advance without pinning while
        # another callback executes inside the same signed HTTP request.
        from ronas_api.internal_authority_local_checkpoint_sqlite import (
            LocalCheckpointMismatch,
        )
        # Inject a journal update from the independently checked live
        # assignment callback, between the two versioned observations.
        real=self.workspace._live_authority
        calls=[0]
        def live(actor,ref,version):
            calls[0]+=1
            if calls[0]==2:
                journal.record_owned_snapshot(
                    kind=SPECIALIST,
                    snapshot=journal.read_owned_snapshot(
                        kind=SPECIALIST,**scope,
                    )[0],
                    action_ref="DEMO-CHK-MID",
                    expected_generation=1,**scope,
                )
            return real(actor,ref,version)
        self.workspace._live_authority=live
        response=self.client.get(
            self.versioned_review_context_url(),headers=self.headers())
        self.assertEqual(response.status_code,503,response.text)
        self.assertEqual(calls,[2])
        self.assertFalse(any(
            e.access_mode=="AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()))
        with self.assertRaises(LocalCheckpointMismatch):
            checkpoint.assert_current(journal)

    def test_checkpointed_wrong_actor_and_default_app_still_denied(self):
        journal,checkpoint,jpath,cpath,scope=(
            self.setup_checkpointed_versioned_case()
        )
        url=self.versioned_review_context_url()
        self.assertEqual(self.client.get(url).status_code,401)
        self.assertEqual(self.client.get(
            url,headers=self.headers(OWNER,("household",))
        ).status_code,404)
        self.assertEqual(self.client.get(
            url.replace("DEMO-D-1","DEMO-E-1"),
            headers=self.headers()).status_code,404)
        self.assertEqual(self.client.post(
            url,headers=self.headers(),json={}).status_code,405)
        self.assertEqual(TestClient(create_app(self.config)).get(
            url,headers=self.headers()).status_code,404)
    def setup_source_owned_case(self):
        from ronas_api.internal_authority_source_owned_read import (
            SourceOwnedCandidateAuthorityRead, SourceOwnedCandidateObservation,
        )
        from ronas_api.internal_authority_revision_journal_sqlite import (
            snapshot_digest,
        )
        from ronas_api.internal_authority_revision_witness import (
            SCIENCE, SPECIALIST, ASSIGNMENT, SyntheticAuthorityWitness,
        )
        from ronas_api.internal_specialist_scope_contract import (
            SyntheticSpecialistEvidenceRegistry,
        )
        state = {
            "snapshots": {
                SCIENCE: tuple(),
                SPECIALIST: SyntheticSpecialistEvidenceRegistry(),
                ASSIGNMENT: True,
            },
            "generations": {k: 1 for k in (SCIENCE, SPECIALIST, ASSIGNMENT)},
            "calls": {k: 0 for k in (SCIENCE, SPECIALIST, ASSIGNMENT)},
            "mutate_after_first": None,
        }
        def callback(kind):
            def read(actor, ref, version):
                state["calls"][kind] += 1
                if (state["mutate_after_first"] == kind
                        and state["calls"][kind] == 2):
                    state["generations"][kind] += 1
                snapshot = state["snapshots"][kind]
                return SourceOwnedCandidateObservation(
                    witness=SyntheticAuthorityWitness(
                        kind, actor, ref, version, state["generations"][kind],
                    ),
                    snapshot=snapshot,
                    snapshot_digest_sha256=snapshot_digest(
                        kind, actor, ref, version, snapshot,
                    ),
                )
            return read
        self.workspace._source_owned_authority=SourceOwnedCandidateAuthorityRead(
            *(callback(k) for k in (SCIENCE, SPECIALIST, ASSIGNMENT))
        )
        self.seed_input()
        return state

    def test_source_owned_signed_read_binds_three_typed_snapshots(self):
        state = self.setup_source_owned_case()
        response = self.client.get(
            self.versioned_review_context_url(), headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        from ronas_api.internal_authority_revision_witness import KINDS
        self.assertEqual(state["calls"], {k: 2 for k in KINDS})
        self.assertFalse(response.json()["cross_provider_atomicity_verified"])
        self.assertFalse(response.json()["plan_accepted"])
        self.assertTrue(all(x["review_outcome"] == "NOT_REVIEWED"
                            for x in response.json()["tracks"]))
        self.assertNotIn("snapshot_digest_sha256", response.text)
        self.assertEqual(sum(
            e.access_mode == "AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()), 1)

    def test_source_owned_generation_aba_rejected_after_prior_read(self):
        from ronas_api.internal_authority_revision_witness import SCIENCE
        state = self.setup_source_owned_case()
        url = self.versioned_review_context_url()
        initial = self.client.get(url, headers=self.headers())
        self.assertEqual(initial.status_code, 200, initial.text)
        token = initial.json()["synthetic_versioned_context_fingerprint_sha256"]
        state["generations"][SCIENCE] += 2
        stale = self.client.get(
            url + "&expected_context_fingerprint=" + token,
            headers=self.headers(),
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["detail"],
                         "SYNTHETIC_REVIEW_CONTEXT_CHANGED")
        self.assertFalse(stale.json().get("plan_accepted", False))

    def test_source_owned_inflight_generation_change_has_no_success_audit(self):
        from ronas_api.internal_authority_revision_witness import SPECIALIST
        state = self.setup_source_owned_case()
        state["mutate_after_first"] = SPECIALIST
        response = self.client.get(
            self.versioned_review_context_url(), headers=self.headers())
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()["detail"],
                         "SYNTHETIC_AGRONOMY_UNAVAILABLE")
        self.assertFalse(any(
            e.access_mode == "AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()))

    def test_source_owned_same_generation_content_drift_is_rejected(self):
        from ronas_api.internal_authority_source_owned_read import (
            SourceOwnedCandidateAuthorityRead,
        )
        from ronas_api.internal_authority_revision_witness import SPECIALIST
        state = self.setup_source_owned_case()
        original = self.workspace._source_owned_authority
        def drift(actor, ref, version):
            if state["calls"][SPECIALIST] == 1:
                state["snapshots"][SPECIALIST] = (
                    self.specialist_governance_fixture()
                )
            return original.specialist_evidence(actor, ref, version)
        self.workspace._source_owned_authority = SourceOwnedCandidateAuthorityRead(
            original.scientific_source, drift, original.current_assignment,
        )
        response = self.client.get(
            self.versioned_review_context_url(), headers=self.headers())
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(state["generations"][SPECIALIST], 1)
        self.assertFalse(any(
            e.access_mode == "AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()))

    def test_source_owned_fingerprint_tracks_unshown_science_snapshot(self):
        from ronas_api.internal_authority_revision_witness import SCIENCE
        state = self.setup_source_owned_case()
        url = self.versioned_review_context_url()
        initial = self.client.get(url, headers=self.headers())
        self.assertEqual(initial.status_code, 200, initial.text)
        token = initial.json()["synthetic_versioned_context_fingerprint_sha256"]
        # No basis is configured: this candidate does NOT change the
        # redacted structural projection, only the source-owned digest.
        state["snapshots"][SCIENCE] = (ScientificSourceCandidate(
            ref="DEMO-SOURCE-NEW", version=1, content_sha256="a" * 64,
            rights_document_ref="DEMO-RIGHTS-NEW",
            rights_document_sha256="b" * 64,
            science_review_request_ref="DEMO-REVIEW-NEW",
            science_review_material_sha256="c" * 64,
        ),)
        after = self.client.get(url, headers=self.headers())
        self.assertEqual(after.status_code, 200, after.text)
        self.assertEqual(
            initial.json()["synthetic_context_fingerprint_sha256"],
            after.json()["synthetic_context_fingerprint_sha256"],
        )
        self.assertNotEqual(
            token, after.json()["synthetic_versioned_context_fingerprint_sha256"],
        )
        stale = self.client.get(
            url + "&expected_context_fingerprint=" + token,
            headers=self.headers(),
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(state["generations"][SCIENCE], 1)
        self.assertNotIn("DEMO-SOURCE-NEW", after.text)

    def test_source_owned_digest_mismatch_fails_without_success_audit(self):
        from ronas_api.internal_authority_source_owned_read import (
            SourceOwnedCandidateObservation, SourceOwnedCandidateAuthorityRead,
        )
        from ronas_api.internal_authority_revision_witness import (
            SCIENCE, SyntheticAuthorityWitness,
        )
        state = self.setup_source_owned_case()
        current = self.workspace._source_owned_authority
        def corrupt(actor, ref, version):
            return SourceOwnedCandidateObservation(
                witness=SyntheticAuthorityWitness(
                    SCIENCE, actor, ref, version, 1),
                snapshot=tuple(),
                snapshot_digest_sha256="0" * 64,
            )
        self.workspace._source_owned_authority = SourceOwnedCandidateAuthorityRead(
            corrupt, current.specialist_evidence, current.current_assignment,
        )
        response = self.client.get(
            self.versioned_review_context_url(), headers=self.headers())
        self.assertEqual(response.status_code, 503, response.text)
        self.assertFalse(any(
            e.access_mode == "AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()))

    def test_source_owned_wrong_case_witness_cannot_cross_scope(self):
        from ronas_api.internal_authority_source_owned_read import (
            SourceOwnedCandidateObservation, SourceOwnedCandidateAuthorityRead,
        )
        from ronas_api.internal_authority_revision_witness import (
            ASSIGNMENT, SyntheticAuthorityWitness,
        )
        from ronas_api.internal_authority_revision_journal_sqlite import (
            snapshot_digest,
        )
        self.setup_source_owned_case()
        current = self.workspace._source_owned_authority
        def wrong_case(actor, ref, version):
            other = "DEMO-D-2"
            return SourceOwnedCandidateObservation(
                witness=SyntheticAuthorityWitness(
                    ASSIGNMENT, actor, other, version, 1),
                snapshot=True,
                snapshot_digest_sha256=snapshot_digest(
                    ASSIGNMENT, actor, other, version, True,
                ),
            )
        self.workspace._source_owned_authority = SourceOwnedCandidateAuthorityRead(
            current.scientific_source, current.specialist_evidence, wrong_case,
        )
        response = self.client.get(
            self.versioned_review_context_url(), headers=self.headers())
        self.assertEqual(response.status_code, 503, response.text)
        self.assertFalse(any(
            e.access_mode == "AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()))

    def test_source_owned_revocation_requires_live_grant_and_role(self):
        from ronas_api.internal_authority_revision_witness import ASSIGNMENT
        state = self.setup_source_owned_case()
        url = self.versioned_review_context_url()
        state["snapshots"][ASSIGNMENT] = False
        self.assertEqual(self.client.get(
            url, headers=self.headers()).status_code, 404)
        state["snapshots"][ASSIGNMENT] = True
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(
            url, headers=self.headers(OWNER, ("household",))).status_code, 404)
        self.active = False
        self.assertEqual(self.client.get(
            url, headers=self.headers()).status_code, 404)
        self.assertFalse(any(
            e.access_mode == "AGRONOMY_SYNTHETIC_REVIEW_CONTEXT_IMPACT"
            for e in self.ledger.audit_snapshot()))

    def test_source_owned_excludes_counter_callbacks_and_local_checkpoint(self):
        from ronas_api.internal_authority_revision_witness import (
            SCIENCE, SPECIALIST, ASSIGNMENT,
        )
        from ronas_api.internal_authority_checkpointed_read import (
            LocalCheckpointedAuthorityRead,
        )
        self.setup_source_owned_case()
        source = self.workspace._source_owned_authority
        base = dict(
            ledger=self.ledger,
            assignments=(SyntheticAgronomyAssignment("DEMO-D-1", EXPERT, 3),),
            trusted_assignment_active=lambda *_: True,
            source_owned_authority=source,
        )
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            SyntheticAgronomyWorkspace(
                **base, trusted_science_authority_version=lambda *_: None,
            )
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            SyntheticAgronomyWorkspace(
                **base, local_checkpointed_authority=(
                    LocalCheckpointedAuthorityRead(
                        self.path.parent / "separate-a.db",
                        self.path.parent / "separate-b.db",
                    )
                ),
            )

    def evidence_index_url(self):
        return "/api/v1/agronomy/assigned-drafts/DEMO-D-1/review-evidence-index"

    def test_evidence_index_is_three_track_redacted_and_audited(self):
        self.seed_input()
        endpoint = self.evidence_index_url()
        empty = self.client.get(endpoint, headers=self.headers())
        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertEqual(len(empty.json()["tracks"]), 3)
        self.assertEqual(empty.json()["tracks"][0]["latest_evidence_marker"],
                         "NO_SYNTHETIC_QUESTION")
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post(
            track=TRACKS[1], action="DEMO-Q-SCI",
        ).status_code, 201)
        self.assertEqual(self.owner_reply().status_code, 201)
        self.assertEqual(self.inspect().status_code, 201)
        result = self.client.get(endpoint, headers=self.headers())
        self.assertEqual(result.status_code, 200, result.text)
        tracks = result.json()["tracks"]
        self.assertEqual([x["track"] for x in tracks], list(TRACKS))
        self.assertEqual([x["latest_evidence_marker"] for x in tracks], [
            "SYNTHETIC_RECEIPT_SEEN_NOT_REVIEWED",
            "QUESTION_RECORDED_NOT_REVIEWED", "NO_SYNTHETIC_QUESTION",
        ])
        self.assertTrue(tracks[0]["latest_question_matches_current_input_revision"])
        self.assertTrue(all(x["review_decision_recorded"] is False for x in tracks))
        self.assertTrue(all(x["source_lineage_current_verified"] is False
                            for x in tracks))
        for secret in (
            "DEMO-ANSWER-A", "DEMO-OWNER-EVIDENCE",
            "DEMO-REASON-A", "DEMO-EVIDENCE-A", "1" * 64,
        ):
            self.assertNotIn(secret, result.text)
        self.assertFalse(result.json()["professional_qualification_verified"])
        self.assertFalse(result.json()["plan_accepted"])
        events = [x for x in self.ledger.audit_snapshot()
                  if x.access_mode == "AGRONOMY_SYNTHETIC_EVIDENCE_INDEX"]
        self.assertEqual(len(events), 2)
        self.assertTrue(self.ledger.verify_integrity())

    def test_evidence_index_preserves_history_after_input_correction(self):
        self.seed_input()
        self.post()
        self.owner_reply()
        self.inspect()
        self.seed_input(revision=1, digest="7" * 64, action="DEMO-INPUT-B")
        result = self.client.get(
            self.evidence_index_url(), headers=self.headers())
        self.assertEqual(result.status_code, 200, result.text)
        lane = result.json()["tracks"][0]
        self.assertEqual(lane["latest_evidence_marker"],
                         "SYNTHETIC_RECEIPT_SEEN_NOT_REVIEWED")
        self.assertEqual(lane["historical_receipt_sighting_count"], 1)
        self.assertFalse(lane["latest_question_matches_current_input_revision"])
        self.assertFalse(result.json()["scientific_basis_and_rights_verified"])

    def test_evidence_index_requires_live_signed_assignment_and_no_post(self):
        endpoint = self.evidence_index_url()
        self.assertEqual(self.client.get(endpoint).status_code, 401)
        self.assertEqual(self.client.get(
            endpoint, headers=self.headers(OWNER, ("household",))
        ).status_code, 404)
        self.assertEqual(self.client.get(
            endpoint.replace("DEMO-D-1", "DEMO-E-1"),
            headers=self.headers(),
        ).status_code, 404)
        self.assertEqual(self.client.post(
            endpoint, headers=self.headers(), json={},
        ).status_code, 405)
        self.active = False
        self.assertEqual(self.client.get(
            endpoint, headers=self.headers()).status_code, 404)
        self.active = True
        self.assertEqual(TestClient(create_app(self.config)).get(
            endpoint, headers=self.headers()).status_code, 404)

    def test_evidence_index_integrity_failure_never_leaks_history(self):
        self.seed_input()
        self.post()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER expert_question_no_update")
            db.execute(
                "UPDATE expert_review_question SET reason_ref='DEMO-FORGED'")
        response = self.client.get(
            self.evidence_index_url(), headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("DEMO-FORGED", response.text)

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


    def login_browser_demo(self, subject: str, role: str):
        from ronas_api.oidc_browser import BrowserSession
        import secrets
        self.client.cookies.clear()
        sid = secrets.token_urlsafe(32)
        self.sessions[sid] = BrowserSession(
            subject, frozenset({role}),
            self.headers(subject, (role,))["Authorization"][7:],
            secrets.token_urlsafe(32), int(time.time()) + 200,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        return self.sessions[sid].csrf

    @staticmethod
    def demo_form(csrf, *, qrev=0, irev=1, track=TRACKS[0]):
        return {
            "csrf": csrf, "case_version": "3", "input_revision": str(irev),
            "question_revision": str(qrev), "track": track,
        }

    def test_browser_complete_expert_owner_inspection_roundtrip(self):
        self.seed_input()
        base = "/agronomy/assigned-drafts/DEMO-D-1/review-questions"
        csrf = self.login_browser_demo(EXPERT, "agronomy_expert")
        page = self.client.get(base)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("پرسش درباره کفایت داده", page.text)
        self.assertIn("form-action 'self'", page.headers["content-security-policy"])
        posted = self.client.post(
            base + "/demo-question", data=self.demo_form(csrf),
            headers={"Origin": "https://ronas.example.test"},
            follow_redirects=False,
        )
        self.assertEqual(posted.status_code, 303, posted.text)
        self.assertEqual(posted.headers["location"], base)
        self.assertIn("پرسش آزمایشی 1", self.client.get(base).text)
        self.assertEqual(self.client.post(
            base + "/demo-question", data=self.demo_form(csrf),
            headers={"Origin": "https://ronas.example.test"},
        ).status_code, 409)

        csrf = self.login_browser_demo(OWNER, "household")
        owner_path = "/my-drafts/DEMO-D-1/question-responses"
        owner_page = self.client.get(owner_path)
        self.assertEqual(owner_page.status_code, 200, owner_page.text)
        self.assertIn("ثبت مرجع پاسخ DEMO", owner_page.text)
        action_match = re.search(
            r'name="action_id" value="(DEMO-UI-R-[A-Z0-9]+)"',
            owner_page.text,
        )
        self.assertIsNotNone(action_match)
        answer = {
            "csrf": csrf, "action_id": action_match.group(1),
            "case_version": "3", "input_revision": "1",
            "question_revision": "1", "scenario": "DEMO-REPLY-BETA",
        }
        headers = {"Origin": "https://ronas.example.test"}
        res = self.client.post(
            owner_path + "/demo-reply", data=answer, headers=headers,
            follow_redirects=False,
        )
        self.assertEqual(res.status_code, 303, res.text)
        replay = self.client.post(
            owner_path + "/demo-reply", data=answer, headers=headers,
            follow_redirects=False,
        )
        self.assertEqual(replay.status_code, 303, replay.text)
        self.assertIn("DEMO-REPLY-BETA", self.client.get(owner_path).text)
        conflicting_replay = dict(answer, scenario="DEMO-REPLY-ALPHA")
        conflict = self.client.post(
            owner_path + "/demo-reply", data=conflicting_replay,
            headers=headers, follow_redirects=False,
        )
        self.assertEqual(conflict.status_code, 409)
        with self.ledger._transaction() as db:
            stored = db.execute(
                "SELECT count(*) FROM household_question_response "
                "WHERE ref='DEMO-D-1' AND track='HOUSEHOLD_INPUT_ADEQUACY' "
                "AND question_revision=1",
            ).fetchone()[0]
        self.assertEqual(stored, 1)

        csrf = self.login_browser_demo(EXPERT, "agronomy_expert")
        view = self.client.get(base)
        self.assertIn("پاسخ ساختاری خانوار دریافت شده", view.text)
        self.assertNotIn("DEMO-REPLY-BETA", view.text)
        self.assertIn("ثبت مشاهده رسید پاسخ DEMO", view.text)
        observed = {
            "csrf": csrf, "case_version": "3",
            "input_revision": "1", "question_revision": "1",
        }
        res = self.client.post(
            base + "/demo-inspection", data=observed,
            headers={"Origin": "https://ronas.example.test"},
            follow_redirects=False,
        )
        self.assertEqual(res.status_code, 303, res.text)
        final = self.client.get(base)
        self.assertIn("رسید پاسخ مشاهده شد (بدون داوری تخصصی)", final.text)
        self.assertNotIn("DEMO-REPLY-BETA", final.text)
        self.assertNotIn("ثبت مشاهده رسید پاسخ DEMO", final.text)
        self.assertEqual(self.client.post(
            base + "/demo-inspection", data=observed,
            headers={"Origin": "https://ronas.example.test"},
        ).status_code, 409)
        self.assertTrue(self.reopen().verify_integrity())

    def test_browser_expert_question_rejects_csrf_origin_and_wrong_role(self):
        self.seed_input()
        base = "/agronomy/assigned-drafts/DEMO-D-1/review-questions"
        csrf = self.login_browser_demo(EXPERT, "agronomy_expert")
        data = self.demo_form(csrf)
        for hdr, payload, expected in (
            ({}, data, 403),
            ({"Origin": "https://foreign.test"}, data, 403),
            ({"Origin": "https://ronas.example.test"},
             {**data, "csrf": "wrong"}, 403),
            ({"Origin": "https://ronas.example.test"},
             {**data, "track": "UNAUTHORIZED"}, 422),
            ({"Origin": "https://ronas.example.test"},
             {**data, "other": "PII"}, 422),
            ({"Origin": "https://ronas.example.test"},
             {**data, "input_revision": "00"}, 422),
        ):
            with self.subTest(payload=payload, hdr=hdr):
                result = self.client.post(
                    base + "/demo-question", data=payload, headers=hdr,
                )
                self.assertEqual(result.status_code, expected, result.text)
        self.active = False
        self.assertEqual(self.client.post(
            base + "/demo-question", data=data,
            headers={"Origin": "https://ronas.example.test"},
        ).status_code, 404)
        self.active = True
        self.login_browser_demo(OWNER, "household")
        self.assertEqual(self.client.post(
            base + "/demo-question", data=self.demo_form(
                self.sessions[self.client.cookies.get(
                    "__Host-ronas_session")].csrf,
            ), headers={"Origin": "https://ronas.example.test"},
        ).status_code, 404)
        self.assertEqual(self.client.get(
            "/api/v1/agronomy/assigned-drafts/DEMO-D-1/review-questions",
            headers=self.headers(),
        ).json()["questions"], [])

    def test_browser_household_response_stales_after_input_correction(self):
        self.seed_input()
        expert_csrf = self.login_browser_demo(EXPERT, "agronomy_expert")
        base = "/agronomy/assigned-drafts/DEMO-D-1/review-questions"
        self.assertEqual(self.client.post(
            base + "/demo-question", data=self.demo_form(expert_csrf),
            headers={"Origin": "https://ronas.example.test"},
        ).status_code, 200)
        owner_csrf = self.login_browser_demo(OWNER, "household")
        owner_path = "/my-drafts/DEMO-D-1/question-responses"
        data = {"csrf": owner_csrf, "action_id": "DEMO-UI-R-STALE-INPUT",
                "case_version": "3", "input_revision": "1",
                "question_revision": "1", "scenario": "DEMO-REPLY-ALPHA"}
        self.ledger.append_owned_input_manifest(
            "DEMO-D-1", self.owner, action_id="DEMO-BROWSER-STALE-INPUT",
            expected_case_version=3, expected_input_revision=1,
            synthetic_manifest_digest="b" * 64,
        )
        response = self.client.post(
            owner_path + "/demo-reply", data=data,
            headers={"Origin": "https://ronas.example.test"},
        )
        self.assertEqual(response.status_code, 409, response.text)
        history = self.client.get(owner_path)
        self.assertEqual(history.status_code, 200, history.text)
        self.assertIn("نسخه تاریخی", history.text)
        self.assertNotIn("ثبت مرجع پاسخ DEMO", history.text)
        self.assertTrue(self.reopen().verify_integrity())

    def test_assigned_expert_case_next_step_waits_and_then_receipt_only(self):
        self.seed_input()
        base = "/agronomy/assigned-drafts/DEMO-D-1"
        csrf = self.login_browser_demo(EXPERT, "agronomy_expert")
        initial = self.client.get(base)
        self.assertEqual(initial.status_code, 200, initial.text)
        self.assertIn("مرحله بعدی در همین پرونده", initial.text)
        self.assertIn("پرسش ساختاری آزمایشی", initial.text)
        qpath = base + "/review-questions"
        send = self.client.post(
            qpath + "/demo-question", data=self.demo_form(csrf),
            headers={"Origin": "https://ronas.example.test"},
            follow_redirects=False,
        )
        self.assertEqual(send.status_code, 303, send.text)
        wait = self.client.get(base)
        self.assertEqual(wait.status_code, 200, wait.text)
        self.assertIn("دریافت پاسخ مرجعی خانوار در انتظار است", wait.text)

        owner_csrf = self.login_browser_demo(OWNER, "household")
        owner = self.client.get("/my-drafts/DEMO-D-1")
        self.assertEqual(owner.status_code, 200, owner.text)
        self.assertIn("/question-responses#owner-demo-reply", owner.text)
        answer = self.client.post(
            "/my-drafts/DEMO-D-1/question-responses/demo-reply",
            data={"csrf": owner_csrf, "action_id": "DEMO-UI-R-NEXT-STEP",
                  "case_version": "3", "input_revision": "1",
                  "question_revision": "1", "scenario": "DEMO-REPLY-ALPHA"},
            headers={"Origin": "https://ronas.example.test"},
            follow_redirects=False,
        )
        self.assertEqual(answer.status_code, 303, answer.text)
        answered = self.client.get("/my-drafts/DEMO-D-1")
        self.assertIn("بررسی و تأیید تخصصی هنوز انجام نشده است", answered.text)

        expert_csrf = self.login_browser_demo(EXPERT, "agronomy_expert")
        inspect = self.client.get(base)
        self.assertEqual(inspect.status_code, 200, inspect.text)
        self.assertIn("رسید پاسخ خانوار قابل مشاهده است", inspect.text)
        self.assertNotIn("DEMO-REPLY-ALPHA", inspect.text)
        response = self.client.post(
            qpath + "/demo-inspection",
            data={"csrf": expert_csrf, "case_version": "3",
                  "input_revision": "1", "question_revision": "1"},
            headers={"Origin": "https://ronas.example.test"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        final = self.client.get(base)
        self.assertIn("هیچ بررسی علمی یا برنامه‌ای تصویب نشده", final.text)
        self.assertTrue(self.reopen().verify_integrity())

    def test_unassigned_expert_case_has_no_next_action(self):
        self.seed_input()
        self.login_browser_demo("synthetic-unassigned-expert", "agronomy_expert")
        denied = self.client.get("/agronomy/assigned-drafts/DEMO-D-1")
        self.assertEqual(denied.status_code, 404)
        self.assertNotIn("مرحله بعدی", denied.text)

if __name__ == "__main__":
    unittest.main()
