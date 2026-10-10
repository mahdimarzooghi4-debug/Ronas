"""LOCAL/TEST agronomist role and exact synthetic case-scoped workspace.

No real expert certification, household consent, crop advice or plan creation.
All identities and data are test fixtures; signed role alone grants nothing.
"""
import json
import secrets
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.agronomy_workspace import (
    SyntheticAgronomyAssignment, SyntheticAgronomyWorkspace,
)
from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.grant_ledger_sqlite import LedgerIntegrityError
from ronas_api.human_review_sqlite import SqliteSyntheticHumanReviewLedger
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant

ISS = "https://id.example.test/realms/ronas"
API, WEB, ORIGIN = "ronas-api", "ronas-web", "https://ronas.example.test"
ROOT = "/api/v1/agronomy/assigned-drafts"
ROLE = "/workspace/agronomy_expert"
DETAIL = "/agronomy/assigned-drafts/DEMO-D-001"


class Sessions:
    def __init__(self):
        self.records = {}

    def get_session(self, sid):
        return self.records.get(sid)

    def revoke_session(self, sid):
        self.records.pop(sid, None)


class AgronomyWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "agronomy-test", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "agronomy.db"
        self.active = {"DEMO-D-001", "DEMO-D-002"}
        self.ledger, self.workspace = self.reopen()
        self.sessions = Sessions()

        async def no_exchange(_code, _verifier):
            raise AssertionError("no actual identity provider attached")

        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.sessions, no_exchange,
        )
        self.client = self.client_for()

    def cases(self):
        return (
            ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-001", 2, (
                ScopedGrant("synthetic-ops-001", "domestic_ops"),
                ScopedGrant("synthetic-ops-reviewer", "domestic_ops"),
            )),
            ScopedDraft("DEMO-D-002", "DOMESTIC", "synthetic-household-002", 4, (
                ScopedGrant("synthetic-ops-001", "domestic_ops"),
            )),
            ScopedDraft("DEMO-D-003", "DOMESTIC", "synthetic-household-003", 1, (
                ScopedGrant("synthetic-ops-001", "domestic_ops"),
            )),
            ScopedDraft("DEMO-E-001", "EXPORT", "synthetic-export-owner", 3, (
                ScopedGrant("synthetic-export-ops", "export_ops"),
            ), source_ref="DEMO-SOURCE-001"),
        )

    def reopen(self, *, assignments=None):
        ledger = SqliteSyntheticHumanReviewLedger(
            self.path, self.cases(),
            trusted_revoke_authorizer=lambda actor, engine, ref: (
                actor == "synthetic-controller"
            ),
            trusted_human_review_authorizer=lambda actor, engine, ref: (
                actor == "synthetic-ops-reviewer" and engine == "DOMESTIC"
                and ref == "DEMO-D-001"
            ),
        )
        if assignments is None:
            assignments = (
                SyntheticAgronomyAssignment(
                    "DEMO-D-001", "synthetic-agronomist-001", 2,
                ),
                SyntheticAgronomyAssignment(
                    "DEMO-D-002", "synthetic-agronomist-001", 4,
                ),
                SyntheticAgronomyAssignment(
                    "DEMO-D-003", "synthetic-agronomist-other", 1,
                ),
            )
        workspace = SyntheticAgronomyWorkspace(
            ledger, assignments,
            trusted_assignment_active=lambda actor, ref, version: (
                actor.startswith("synthetic-agronomist-") and ref in self.active
                and version in (2, 4)
            ),
        )
        return ledger, workspace

    def client_for(self, *, ledger=None, workspace=None, flow=None):
        ledger = ledger or self.ledger
        workspace = workspace or self.workspace
        return TestClient(create_app(
            self.config, self.flow if flow is None else flow,
            scoped_registry=ledger, technical_review_ledger=ledger,
            agronomy_workspace=workspace,
        ), base_url=ORIGIN)

    def signed(self, subject="synthetic-agronomist-001", roles=("agronomy_expert",),
               *, expired=False):
        now = int(time.time())
        return jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "typ": "Bearer",
            "sub": subject, "iat": now - 5, "nbf": now - 5,
            "exp": now - 10 if expired else now + 500,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "agronomy-test"})

    def headers(self, subject="synthetic-agronomist-001",
                roles=("agronomy_expert",), **kwargs):
        return {"Authorization": "Bearer " + self.signed(subject, roles, **kwargs)}

    def session(self, subject="synthetic-agronomist-001",
                roles=("agronomy_expert",)):
        sid = secrets.token_urlsafe(40)
        self.sessions.records[sid] = BrowserSession(
            subject, frozenset(roles), self.signed(subject, roles),
            secrets.token_urlsafe(32), int(time.time()) + 250,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        return sid

    def test_exact_role_and_case_assignment_lists_only_two_drafts(self):
        r = self.client.get(ROOT, headers=self.headers())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([item["ref"] for item in r.json()["items"]],
                         ["DEMO-D-001", "DEMO-D-002"])
        self.assertIsNone(r.json()["next_cursor"])
        self.assertNotIn("DEMO-D-003", r.text)
        self.assertNotIn("DEMO-E-001", r.text)
        self.assertFalse(r.json()["items"][0]["plan_accepted"])
        self.assertFalse(r.json()["items"][0]["agronomist_qualification_verified"])
        self.assertEqual(r.headers["cache-control"], "no-store")

    def test_exact_case_preview_never_infers_crop_or_scientific_approval(self):
        r = self.client.get(ROOT + "/DEMO-D-001", headers=self.headers())
        self.assertEqual(r.status_code, 200, r.text)
        item = r.json()
        self.assertEqual(item["ref"], "DEMO-D-001")
        self.assertEqual(item["known_versions"], [2])
        self.assertEqual(item["technical_review_state"], "UNREQUESTED")
        self.assertEqual(item["cultivation_inputs"], {
            "crop": None, "growing_area": None, "water": None,
            "soil": None, "location": None,
        })
        self.assertEqual(item["plan_state"], "NOT_AUTHORED")
        for field in ("agronomist_qualification_verified", "purpose_consent_verified",
                      "scientific_review_approved", "plan_accepted", "real_data",
                      "business_actions_enabled"):
            self.assertFalse(item[field])
        for forbidden in ("synthetic-household-001", "synthetic-ops-001",
                          "request_ref", "decision_ref", "source_ref"):
            self.assertNotIn(forbidden, r.text)

    def test_stale_role_and_case_grant_are_independently_checked(self):
        for subject, roles, ref in (
            ("synthetic-agronomist-001", ("household",), "DEMO-D-001"),
            ("synthetic-ops-001", ("domestic_ops",), "DEMO-D-001"),
            ("synthetic-agronomist-other", ("agronomy_expert",), "DEMO-D-001"),
            ("synthetic-agronomist-001", ("agronomy_expert",), "DEMO-D-003"),
            ("synthetic-agronomist-001", ("agronomy_expert",), "DEMO-E-001"),
            ("synthetic-agronomist-001", ("agronomy_expert",), "DEMO-UNKNOWN"),
        ):
            with self.subTest(subject=subject, roles=roles, ref=ref):
                r = self.client.get(ROOT + "/" + ref,
                                    headers=self.headers(subject, roles))
                self.assertEqual(r.status_code, 404)
                self.assertNotIn("cultivation_inputs", r.text)

    def test_signed_role_alone_with_no_specific_assignment_is_empty(self):
        response = self.client.get(ROOT, headers=self.headers(
            subject="synthetic-new-agronomist"
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])
        self.assertNotIn("DEMO-D-001", response.text)

    def test_live_assignment_revocation_denies_with_prior_valid_jwt(self):
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers()
        ).status_code, 200)
        self.active.remove("DEMO-D-001")
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers()
        ).status_code, 404)
        self.assertEqual([item["ref"] for item in self.client.get(
            ROOT, headers=self.headers()
        ).json()["items"]], ["DEMO-D-002"])
        self.assertTrue(self.ledger.verify_integrity())

    def test_authority_failure_is_sanitized_503_and_does_not_disclose_case(self):
        self.workspace._live_authority = lambda *_: (
            (_ for _ in ()).throw(RuntimeError("private grant provider failure"))
        )
        r = self.client.get(ROOT + "/DEMO-D-001", headers=self.headers())
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"detail": "SYNTHETIC_AGRONOMY_UNAVAILABLE"})
        self.assertNotIn("DEMO-D-001", r.text)

    def test_read_audit_records_allowed_and_denied_without_staff_grant_mutation(self):
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers()
        ).status_code, 200)
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-003", headers=self.headers()
        ).status_code, 404)
        audit = [a for a in self.ledger.audit_snapshot()
                 if a.access_mode == "AGRONOMY_ASSIGNED_CASE"]
        self.assertEqual([x.kind for x in audit], ["READ_ALLOWED", "READ_DENIED"])
        self.assertEqual(self.ledger.grant_revision("DOMESTIC", "DEMO-D-001"), 0)

    def test_list_keyset_page_filters_only_live_assigned_items(self):
        r1 = self.client.get(ROOT, params={"limit": 1}, headers=self.headers())
        self.assertEqual([x["ref"] for x in r1.json()["items"]], ["DEMO-D-001"])
        self.assertEqual(r1.json()["next_cursor"], "DEMO-D-001")
        self.active.remove("DEMO-D-001")
        r2 = self.client.get(ROOT, params={
            "limit": 1, "after_ref": r1.json()["next_cursor"],
        }, headers=self.headers())
        self.assertEqual([x["ref"] for x in r2.json()["items"]], ["DEMO-D-002"])
        self.assertIsNone(r2.json()["next_cursor"])

    def test_existing_domestic_review_stages_do_not_approve_crop_plan(self):
        maker = Principal("synthetic-ops-001", frozenset({"domestic_ops"}))
        self.ledger.request_evidence_review(
            engine="DOMESTIC", ref="DEMO-D-001", actor=maker,
            expected_case_version=2, expected_review_revision=0,
            action_id="DEMO-AGRONOMY-REQUEST", request_ref="DEMO-AGRONOMY-REQ",
            evidence_ref="DEMO-AGRONOMY-EVIDENCE",
        )
        item = self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers()
        ).json()
        self.assertEqual(item["technical_review_state"], "EVIDENCE_REVIEW_REQUESTED")
        self.assertEqual(item["technical_review_steps"],
                         [{"revision": 1, "stage": "TECH_REVIEW_REQUESTED"}])
        self.assertFalse(item["plan_accepted"])
        self.assertFalse(item["scientific_review_approved"])
        self.assertNotIn("DEMO-AGRONOMY-EVIDENCE", str(item))

    def test_html_navigation_only_shows_signed_agronomy_assignments(self):
        self.session()
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("/workspace/agronomy_expert", home.text)
        work = self.client.get(ROLE)
        self.assertEqual(work.status_code, 200, work.text)
        self.assertIn("/agronomy/assigned-drafts/DEMO-D-001", work.text)
        self.assertNotIn("DEMO-D-003", work.text)
        detail = self.client.get(DETAIL)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertIn("محصول: تعیین نشده", detail.text)
        self.assertIn("طرح کشت تولید نشده است", detail.text)
        self.assertIn("صلاحیت حرفه‌ای", detail.text)
        self.assertNotIn("synthetic-household-001", detail.text)
        self.assertIn("frame-ancestors 'none'", detail.headers["content-security-policy"])
        self.assertEqual(detail.headers["cache-control"], "no-store")

    def test_other_role_cannot_open_agronomy_html_and_logout_denies(self):
        self.session(subject="synthetic-ops-001", roles=("domestic_ops",))
        self.assertEqual(self.client.get(ROLE).status_code, 404)
        self.assertEqual(self.client.get(DETAIL).status_code, 404)
        self.client.cookies.clear()
        sid = self.session()
        self.assertEqual(self.client.get(DETAIL).status_code, 200)
        self.sessions.revoke_session(sid)
        self.assertEqual(self.client.get(DETAIL).status_code, 401)
        self.assertEqual(self.client.get(ROOT + "/DEMO-D-001").status_code, 401)

    def test_bad_token_default_app_and_post_remain_unavailable(self):
        self.assertEqual(self.client.get(ROOT).status_code, 401)
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-001", headers={"Authorization": "Bearer fake"}
        ).status_code, 401)
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers(expired=True)
        ).status_code, 401)
        default = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(default.get(
            ROOT, headers=self.headers()
        ).status_code, 404)
        self.assertEqual(self.client.post(
            ROOT + "/DEMO-D-001", headers=self.headers(),
            json={"crop": "invented", "approve": True}
        ).status_code, 405)

    def test_mismatched_ledger_or_bad_explicit_assignment_is_rejected(self):
        independent, other = self.reopen()
        with self.assertRaises(ValueError):
            create_app(
                self.config, self.flow, scoped_registry=self.ledger,
                technical_review_ledger=self.ledger, agronomy_workspace=other,
            )
        with self.assertRaises(ValueError):
            SyntheticAgronomyWorkspace(self.ledger, (
                SyntheticAgronomyAssignment(
                    "DEMO-E-001", "synthetic-agronomist-001", 3,
                ),
            ), trusted_assignment_active=lambda *_: True)
        with self.assertRaises(ValueError):
            SyntheticAgronomyWorkspace(self.ledger, (
                SyntheticAgronomyAssignment(
                    "DEMO-D-001", "synthetic-agronomist-001", 99,
                ),
            ), trusted_assignment_active=lambda *_: True)

    def test_history_tamper_fails_closed_without_exposing_cultivation_fields(self):
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER case_history_no_delete")
            db.execute("DELETE FROM case_history WHERE engine='DOMESTIC' "
                       "AND ref='DEMO-D-001'")
        response = self.client.get(ROOT + "/DEMO-D-001", headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("cultivation_inputs", response.text)

    def test_failed_read_audit_rolls_back_entire_expert_case_read(self):
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER deny_agronomy_audit BEFORE INSERT ON audit_event
                WHEN NEW.payload LIKE '%AGRONOMY_ASSIGNED_CASE%'
                BEGIN SELECT RAISE(ABORT, 'audit failed'); END;
            """)
        response = self.client.get(ROOT + "/DEMO-D-001", headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(),
                         {"detail": "SYNTHETIC_AGRONOMY_UNAVAILABLE"})
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER deny_agronomy_audit")
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers()
        ).status_code, 200)

    def test_live_access_denial_is_independent_of_domestic_ops_grant(self):
        self.ledger.revoke_grant(
            engine="DOMESTIC", ref="DEMO-D-001",
            subject="synthetic-ops-001", role="domestic_ops",
            actor="synthetic-controller", expected_grant_revision=0,
            action_id="DEMO-AGRONOMY-OPS-REVOKE",
            reason_ref="DEMO-AGRONOMY-OPS-REASON",
        )
        # The two roles have independent policies; domestic_ops revocation
        # must not silently mutate a separately authorized agronomy fixture.
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers()
        ).status_code, 200)
        self.active.remove("DEMO-D-001")
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers()
        ).status_code, 404)

    def test_role_metadata_advertises_only_enabled_synthetic_expert_reads(self):
        path = "/api/v1/me/user-workspaces/agronomy_expert"
        allowed = self.client.get(path, headers=self.headers())
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["local_test_reads"],
                         ["ASSIGNED_SYNTHETIC_AGRONOMY_DRAFTS"])
        self.assertFalse(allowed.json()["business_actions_enabled"])
        disabled = TestClient(create_app(
            self.config, self.flow, scoped_registry=self.ledger,
            technical_review_ledger=self.ledger,
        ), base_url=ORIGIN)
        result = disabled.get(path, headers=self.headers())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["local_test_reads"], [])
        self.assertEqual(self.client.get(
            path, headers=self.headers(roles=("domestic_ops",))
        ).status_code, 404)

    def test_assignment_revocation_filters_role_page_as_well_as_api(self):
        self.session()
        self.assertIn("DEMO-D-001", self.client.get(ROLE).text)
        self.active.remove("DEMO-D-001")
        role = self.client.get(ROLE)
        self.assertEqual(role.status_code, 200)
        self.assertNotIn("DEMO-D-001", role.text)
        self.assertIn("DEMO-D-002", role.text)
        self.assertEqual(self.client.get(DETAIL).status_code, 404)


    def owner_status(self, *, ref="DEMO-D-001",
                     subject="synthetic-household-001"):
        return self.client.get(
            "/api/v1/domestic/household-intake/my-drafts/"
            + ref + "/technical-status",
            headers=self.headers(subject=subject, roles=("household",)),
        )

    def test_shared_preparation_contract_is_identical_for_owner_and_expert(self):
        owner = self.owner_status()
        expert = self.client.get(ROOT + "/DEMO-D-001", headers=self.headers())
        self.assertEqual(owner.status_code, 200, owner.text)
        self.assertEqual(expert.status_code, 200, expert.text)
        left, right = owner.json(), expert.json()
        self.assertEqual(left["cultivation_preparation"],
                         right["cultivation_preparation"])
        preparation = left["cultivation_preparation"]
        self.assertEqual(preparation["contract_version"],
                         "ronas.domestic.preparation-preview.v1")
        self.assertEqual(preparation["case_version"], 2)
        self.assertEqual(preparation["technical_review_state"], "UNREQUESTED")
        self.assertEqual(preparation["review_revision"], 0)
        self.assertEqual(preparation["input_state"], "NOT_RECORDED_IN_DEMO")
        self.assertEqual(preparation["cultivation_inputs"], {
            "crop": None, "growing_area": None, "water": None,
            "soil": None, "location": None,
        })
        self.assertEqual(preparation["plan_state"], "NOT_AUTHORED")
        self.assertFalse(preparation["scientific_review_approved"])
        self.assertFalse(preparation["agronomist_qualification_verified"])
        self.assertFalse(preparation["purpose_consent_verified"])
        self.assertFalse(preparation["business_actions_enabled"])
        self.assertEqual(right["cultivation_inputs"],
                         preparation["cultivation_inputs"])
        self.assertEqual(right["plan_state"], preparation["plan_state"])
        self.assertNotIn("synthetic-agronomist", owner.text)
        self.assertNotIn("synthetic-household", expert.text)

    def test_shared_preparation_follows_only_observed_review_stages(self):
        maker = Principal("synthetic-ops-001", frozenset({"domestic_ops"}))
        reviewer = Principal("synthetic-ops-reviewer", frozenset({"domestic_ops"}))
        self.ledger.request_evidence_review(
            engine="DOMESTIC", ref="DEMO-D-001", actor=maker,
            expected_case_version=2, expected_review_revision=0,
            action_id="DEMO-SHARED-PREVIEW-REQUEST",
            request_ref="DEMO-SHARED-PREVIEW-REF",
            evidence_ref="DEMO-SHARED-PREVIEW-EVIDENCE",
        )
        first = self.owner_status().json()["cultivation_preparation"]
        self.assertEqual(first["technical_review_state"],
                         "EVIDENCE_REVIEW_REQUESTED")
        self.assertEqual(first["review_revision"], 1)
        self.assertEqual(first, self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers()
        ).json()["cultivation_preparation"])
        self.ledger.record_human_response(
            engine="DOMESTIC", ref="DEMO-D-001", actor=reviewer,
            expected_case_version=2, expected_review_revision=1,
            action_id="DEMO-SHARED-PREVIEW-RESPONSE",
            request_ref="DEMO-SHARED-PREVIEW-REF",
            evidence_ref="DEMO-SHARED-PREVIEW-RESPONSE-EVIDENCE",
            decision_ref="DEMO-SHARED-PREVIEW-PRIVATE-NOTE",
        )
        final = self.owner_status().json()["cultivation_preparation"]
        self.assertEqual(final["technical_review_state"],
                         "HUMAN_RESPONSE_RECORDED")
        self.assertEqual(final["review_revision"], 2)
        self.assertEqual(final, self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers()
        ).json()["cultivation_preparation"])
        self.assertTrue(all(v is None for v in final["cultivation_inputs"].values()))
        for key in ("plan_accepted", "scientific_review_approved",
                    "agronomist_qualification_verified",
                    "purpose_consent_verified", "business_actions_enabled"):
            self.assertIs(final[key], False)
        self.assertNotIn("DEMO-SHARED-PREVIEW-PRIVATE-NOTE",
                         str(final))
        self.assertTrue(self.ledger.verify_integrity())

    def test_role_boundaries_do_not_inherit_opposite_party_permissions(self):
        path = ROOT + "/DEMO-D-001"
        self.assertEqual(self.client.get(path, headers=self.headers(
            subject="synthetic-household-001", roles=("household",)
        )).status_code, 404)
        self.assertEqual(self.owner_status(subject="synthetic-agronomist-001")
                         .status_code, 404)
        self.assertEqual(self.client.get(
            "/api/v1/domestic/household-intake/my-drafts/DEMO-D-001/technical-status",
            headers=self.headers()
        ).status_code, 404)
        self.assertEqual(self.owner_status(ref="DEMO-D-002").status_code, 404)
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-003", headers=self.headers()
        ).status_code, 404)

    def test_expert_assignment_revocation_never_changes_owner_preparation(self):
        initial = self.owner_status().json()["cultivation_preparation"]
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers()
        ).status_code, 200)
        self.active.remove("DEMO-D-001")
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers()
        ).status_code, 404)
        owner = self.owner_status()
        self.assertEqual(owner.status_code, 200)
        self.assertEqual(owner.json()["cultivation_preparation"], initial)
        self.assertNotIn("agronomist_assigned", owner.json())
        self.assertTrue(self.ledger.verify_integrity())

    def test_household_and_expert_read_audits_remain_distinct(self):
        self.assertEqual(self.owner_status().status_code, 200)
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers()
        ).status_code, 200)
        audited = [
            e for e in self.ledger.audit_snapshot()
            if e.access_mode in (
                "HOUSEHOLD_TECHNICAL_STATUS", "AGRONOMY_ASSIGNED_CASE"
            )
        ]
        self.assertEqual([a.access_mode for a in audited], [
            "HOUSEHOLD_TECHNICAL_STATUS", "AGRONOMY_ASSIGNED_CASE"
        ])
        self.assertTrue(all(e.kind == "READ_ALLOWED" for e in audited))

    def test_household_and_expert_html_show_same_unknown_fields(self):
        self.session(subject="synthetic-household-001", roles=("household",))
        household = self.client.get("/my-drafts/DEMO-D-001")
        self.assertEqual(household.status_code, 200, household.text)
        self.client.cookies.clear()
        self.session()
        expert = self.client.get(DETAIL)
        self.assertEqual(expert.status_code, 200, expert.text)
        for marker in ("محصول: تعیین نشده", "مساحت: تعیین نشده",
                       "آب: تعیین نشده", "خاک: تعیین نشده",
                       "موقعیت: تعیین نشده", "طرح کشت تولید نشده است",
                       "معیار کفایت اطلاعات"):
            self.assertIn(marker, household.text)
            self.assertIn(marker, expert.text)
        self.assertNotIn("synthetic-agronomist", household.text)
        self.assertNotIn("synthetic-household", expert.text)
        self.assertIn("frame-ancestors 'none'",
                      household.headers["content-security-policy"])
        self.assertEqual(expert.headers["cache-control"], "no-store")

    def test_preparation_contract_rejects_invalid_review_and_input_approval(self):
        from ronas_api.domestic_preparation_preview import (
            domestic_preparation_preview,
        )
        from ronas_api.ui_bff import readonly_domestic_preparation_html
        states = ("UNREQUESTED", "EVIDENCE_REVIEW_REQUESTED",
                  "HUMAN_RESPONSE_RECORDED")
        for options in (
            {"case_version": True, "review_revision": 0,
             "technical_review_state": "UNREQUESTED"},
            {"case_version": 2, "review_revision": True,
             "technical_review_state": "UNREQUESTED"},
            {"case_version": 2, "review_revision": 2,
             "technical_review_state": "EVIDENCE_REVIEW_REQUESTED"},
            {"case_version": 2, "review_revision": 3,
             "technical_review_state": "HUMAN_RESPONSE_RECORDED"},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                domestic_preparation_preview(
                    valid_review_states=states, **options,
                )
        clean = domestic_preparation_preview(
            case_version=2, review_revision=0,
            technical_review_state="UNREQUESTED",
            valid_review_states=states,
        )
        self.assertIn("محصول: تعیین نشده",
                      readonly_domestic_preparation_html(clean))
        clean["cultivation_inputs"]["crop"] = "invented"
        with self.assertRaises(ValueError):
            readonly_domestic_preparation_html(clean)

    def test_corrupted_review_history_blocks_both_preview_read_paths(self):
        maker = Principal("synthetic-ops-001", frozenset({"domestic_ops"}))
        self.ledger.request_evidence_review(
            engine="DOMESTIC", ref="DEMO-D-001", actor=maker,
            expected_case_version=2, expected_review_revision=0,
            action_id="DEMO-SHARED-CORRUPT-REQUEST",
            request_ref="DEMO-SHARED-CORRUPT-REF",
            evidence_ref="DEMO-SHARED-CORRUPT-EVIDENCE",
        )
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER review_no_update")
            db.execute(
                "UPDATE technical_review_step SET request_ref='DEMO-TAMPERED'"
                " WHERE engine='DOMESTIC' AND ref='DEMO-D-001'"
            )
        owner = self.owner_status()
        expert = self.client.get(ROOT + "/DEMO-D-001", headers=self.headers())
        self.assertEqual(owner.status_code, 503)
        self.assertEqual(expert.status_code, 503)
        self.assertNotIn("cultivation_preparation", owner.text)
        self.assertNotIn("cultivation_preparation", expert.text)



    def test_progress_timeline_empty_when_no_technical_event_recorded(self):
        owner = self.owner_status()
        expert = self.client.get(ROOT + "/DEMO-D-001", headers=self.headers())
        self.assertEqual(owner.status_code, 200)
        self.assertEqual(expert.status_code, 200)
        for result in (owner, expert):
            preview = result.json()["cultivation_preparation"]
            self.assertEqual(preview["technical_timeline"], [])
            self.assertEqual(preview["timeline_semantics"],
                             "OBSERVED_TECHNICAL_STEPS_ONLY")
            self.assertEqual(preview["review_revision"], 0)
            self.assertFalse(preview["plan_accepted"])
            self.assertNotIn("request_ref", result.text)

    def test_timeline_has_only_first_persisted_request_not_future_response(self):
        maker = Principal("synthetic-ops-001", frozenset({"domestic_ops"}))
        self.ledger.request_evidence_review(
            engine="DOMESTIC", ref="DEMO-D-001", actor=maker,
            expected_case_version=2, expected_review_revision=0,
            action_id="DEMO-PROGRESS-ACTION-REQUEST",
            request_ref="DEMO-PROGRESS-PRIVATE-REQUEST",
            evidence_ref="DEMO-PROGRESS-PRIVATE-EVIDENCE",
        )
        owner = self.owner_status()
        expert = self.client.get(ROOT + "/DEMO-D-001", headers=self.headers())
        expected = [{"revision": 1, "technical_event": "TECH_REVIEW_REQUESTED"}]
        for response in (owner, expert):
            self.assertEqual(response.status_code, 200)
            preview = response.json()["cultivation_preparation"]
            self.assertEqual(preview["technical_timeline"], expected)
            self.assertFalse(preview["scientific_review_approved"])
            self.assertNotIn("DEMO-PROGRESS-PRIVATE", response.text)

    def test_timeline_full_response_remains_only_technical_not_plan(self):
        maker = Principal("synthetic-ops-001", frozenset({"domestic_ops"}))
        reviewer = Principal("synthetic-ops-reviewer", frozenset({"domestic_ops"}))
        self.ledger.request_evidence_review(
            engine="DOMESTIC", ref="DEMO-D-001", actor=maker,
            expected_case_version=2, expected_review_revision=0,
            action_id="DEMO-PROGRESS-ACTION-REQUEST",
            request_ref="DEMO-PROGRESS-PRIVATE-REQUEST",
            evidence_ref="DEMO-PROGRESS-PRIVATE-EVIDENCE",
        )
        self.ledger.record_human_response(
            engine="DOMESTIC", ref="DEMO-D-001", actor=reviewer,
            expected_case_version=2, expected_review_revision=1,
            action_id="DEMO-PROGRESS-ACTION-RESPONSE",
            request_ref="DEMO-PROGRESS-PRIVATE-REQUEST",
            evidence_ref="DEMO-PROGRESS-PRIVATE-RESP",
            decision_ref="DEMO-PROGRESS-PRIVATE-DECISION",
        )
        expected = [
            {"revision": 1, "technical_event": "TECH_REVIEW_REQUESTED"},
            {"revision": 2, "technical_event": "TECH_HUMAN_RESPONSE_RECORDED"},
        ]
        for response in (
            self.owner_status(),
            self.client.get(ROOT + "/DEMO-D-001", headers=self.headers()),
        ):
            self.assertEqual(response.status_code, 200)
            preview = response.json()["cultivation_preparation"]
            self.assertEqual(preview["technical_timeline"], expected)
            self.assertEqual(preview["technical_review_state"],
                             "HUMAN_RESPONSE_RECORDED")
            self.assertFalse(preview["plan_accepted"])
            self.assertFalse(preview["agronomist_qualification_verified"])
            self.assertFalse(preview["scientific_review_approved"])
            self.assertNotIn("DEMO-PROGRESS-PRIVATE", response.text)
        self.assertTrue(self.ledger.verify_integrity())

    def test_both_html_timelines_show_only_observed_labels_in_persian(self):
        self.session(subject="synthetic-household-001", roles=("household",))
        empty_owner = self.client.get("/my-drafts/DEMO-D-001")
        self.assertEqual(empty_owner.status_code, 200)
        self.assertIn("هنوز رویداد بررسی فنی ثبت نشده است.", empty_owner.text)
        self.assertNotIn("مرحله 1:", empty_owner.text)
        self.client.cookies.clear()
        self.session()
        empty_expert = self.client.get(DETAIL)
        self.assertEqual(empty_expert.status_code, 200)
        self.assertIn("هنوز رویداد بررسی فنی ثبت نشده است.", empty_expert.text)
        self.assertIn('aria-label="سابقه پیگیری فنی"', empty_expert.text)
        self.assertNotIn("مرحله 2:", empty_expert.text)

    def test_timeline_renderer_rejects_forged_or_missing_steps(self):
        from ronas_api.domestic_preparation_preview import (
            REVIEW_STATES, domestic_preparation_preview,
        )
        from ronas_api.ui_bff import readonly_domestic_preparation_html
        with self.assertRaises(ValueError):
            domestic_preparation_preview(
                case_version=2, review_revision=1,
                technical_review_state="EVIDENCE_REVIEW_REQUESTED",
                valid_review_states=REVIEW_STATES,
                observed_review_steps=(),
            )
        with self.assertRaises(ValueError):
            domestic_preparation_preview(
                case_version=2, review_revision=1,
                technical_review_state="EVIDENCE_REVIEW_REQUESTED",
                valid_review_states=REVIEW_STATES,
                observed_review_steps=("TECH_HUMAN_RESPONSE_RECORDED",),
            )
        valid = domestic_preparation_preview(
            case_version=2, review_revision=1,
            technical_review_state="EVIDENCE_REVIEW_REQUESTED",
            valid_review_states=REVIEW_STATES,
            observed_review_steps=("TECH_REVIEW_REQUESTED",),
        )
        self.assertIn("مرحله 1:", readonly_domestic_preparation_html(valid))
        valid["technical_timeline"].append({
            "revision": 2, "technical_event": "TECH_HUMAN_RESPONSE_RECORDED",
        })
        with self.assertRaises(ValueError):
            readonly_domestic_preparation_html(valid)

    def test_timeline_disclosure_does_not_inherit_another_roles_access(self):
        self.assertEqual(self.owner_status(subject="synthetic-agronomist-001")
                         .status_code, 404)
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers(
                subject="synthetic-household-001", roles=("household",)
            )
        ).status_code, 404)
        self.active.remove("DEMO-D-001")
        self.assertEqual(self.client.get(
            ROOT + "/DEMO-D-001", headers=self.headers()
        ).status_code, 404)
        self.assertEqual(self.owner_status().status_code, 200)



if __name__ == "__main__":
    unittest.main()
