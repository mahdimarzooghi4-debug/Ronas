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


if __name__ == "__main__":
    unittest.main()
