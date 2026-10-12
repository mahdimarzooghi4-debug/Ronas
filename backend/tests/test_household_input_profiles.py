"""Schema-driven owner profile intake is versioned, private, and guarded."""
import json
from pathlib import Path
import secrets
import tempfile
import time
import unittest
from urllib.parse import urlencode

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
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant
from ronas_api.agronomy_workspace import (
    SyntheticAgronomyAssignment, SyntheticAgronomyWorkspace,
)
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

    def make_app(self, *, schema=True, authority=True, stage_authority=True):
        return create_app(
            self.config, self.flow, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
            household_profile_schema=self.schema if schema else None,
            household_profile_access_authority=self.allowed if authority else None,
            household_stage_context_authority=(
                self.stage_context if stage_authority and schema else None
            ),
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
        stale = self.client.post(
            path, json=stale_command, headers=self.bearer(),
        )
        self.assertEqual(stale.status_code, 409)
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
        values = self.stage_command()
        form = {
            "csrf": session.csrf,
            "case_version": str(values["expected_case_version"]),
            "input_revision": str(values["expected_input_revision"]),
            "input_snapshot_digest": values["expected_input_snapshot_digest"],
            "plan_digest": values["expected_plan_digest"],
            "stage_ref": values["stage_ref"],
            "requirements_digest":
                values["expected_observation_requirements_digest"],
            "observation_revision": "0",
            "artifact_digest": values["observation_artifact_digest"],
        }
        saved = self.client.post(
            path, content=urlencode(form),
            headers={"Origin": ORIGIN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 303, saved.text)
        self.assertIn("رسید جاری", self.client.get(path).text)
        self.assertTrue(self.ledger.verify_integrity())

        self.client.post(
            ROOT, json=self.command(
                revision=1, action="DEMO-PROFILE-UI-STAGE-2",
                values={"field_alpha": "updated", "field_choice": "sample-b"},
            ), headers=self.bearer(),
        )
        history = self.client.get(path)
        self.assertIn("رسید قدیمی", history.text)
        self.assertNotIn("· رسید جاری ·", history.text)

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
        form = {
            "csrf": session.csrf, "case_version": "2", "profile_revision": "0",
            "field_alpha": "sample ui value", "field_choice": "sample-a",
        }
        saved = self.client.post(
            PAGE, content=urlencode(form),
            headers={"Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 303, saved.text)
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


if __name__ == "__main__":
    unittest.main()
