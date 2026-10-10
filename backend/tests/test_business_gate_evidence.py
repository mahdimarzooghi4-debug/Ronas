"""Read-only Business gate evidence snapshot, not a gate evaluator.

The local self-signed token is generated solely for tests. A Business Gate
may be changed only by a separate authoritative owner decision, NOT by these
code paths or the status of a synthetic ledger or CI checks.
"""
import json
import hashlib
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch
import secrets
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.business_gate_evidence import (
    BUSINESS_SOURCE_SHA, DOSSIERS, SNAPSHOT_STATE, dossier_detail,
    visible_dossiers, verify_pinned_business_sources, BusinessSourceSnapshotError,
    PINNED_BUSINESS_SOURCE_BLOBS, SOURCE_INTEGRITY_STATE,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession


ORIGIN = "https://ronas.example.test"
ISS, API, WEB = "https://identity.example.test/realms/ronas", "ronas-api", "ronas-web"
ROOT = "/api/v1/admin/gate-evidence"
HTML = "/admin/gate-evidence/"
COOKIE = "__Host-ronas_session"


class LocalSessions:
    def __init__(self):
        self.records = {}

    def get_session(self, sid):
        return self.records.get(sid)

    def revoke_session(self, sid):
        self.records.pop(sid, None)


class GateEvidenceSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        public.update({"kid": "gate-metadata-key", "use": "sig", "alg": "RS256"})
        cls.config = KeycloakConfig(
            ISS, API, WEB, json.dumps({"keys": [public]}).encode()
        )

    def setUp(self):
        self.sessions = LocalSessions()

        async def no_exchange(_code, _verifier):
            raise AssertionError("There is no real Keycloak provider in these tests")

        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.sessions, no_exchange,
        )
        self.client = TestClient(
            create_app(self.config, self.flow), base_url=ORIGIN,
            follow_redirects=False,
        )

    def signed(self, roles=("governance",), *, expired=False):
        now = int(time.time())
        return jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "typ": "Bearer",
            "sub": "synthetic-review-user", "iat": now - 5,
            "nbf": now - 5, "exp": now - 10 if expired else now + 500,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "gate-metadata-key"})

    def headers(self, roles=("governance",), *, expired=False):
        return {"Authorization": "Bearer " + self.signed(roles, expired=expired)}

    def login(self, roles=("governance",), *, expired=False):
        sid = secrets.token_urlsafe(40)
        self.sessions.records[sid] = BrowserSession(
            "synthetic-review-user", frozenset(roles),
            self.signed(roles, expired=expired), secrets.token_urlsafe(32),
            int(time.time()) + 300,
        )
        self.client.cookies.set(COOKIE, sid)
        return sid

    def test_dossiers_are_pinned_to_three_existing_business_gate_sources(self):
        self.assertEqual(BUSINESS_SOURCE_SHA,
                         "5492690e91955e64353824ffa4ec3250286fdf68")
        self.assertEqual(SNAPSHOT_STATE, "PINNED_DRAFT_SNAPSHOT_NOT_LIVE")
        self.assertEqual([(d.domain, d.gate_issue, len(d.evidence))
                          for d in DOSSIERS],
                         [("DOMESTIC", 2, 6), ("EXPORT", 3, 6),
                          ("FINANCE", 4, 7)])
        self.assertEqual(len({
            e.evidence_id for d in DOSSIERS for e in d.evidence
        }), 19)
        self.assertTrue(all("docs/business/" in d.source_path for d in DOSSIERS))

    def test_source_evidence_ids_match_pinned_domestic_export_finance(self):
        self.assertEqual([e.evidence_id for e in DOSSIERS[0].evidence],
                         [f"D1-B-{i:02}" for i in range(1, 7)])
        self.assertEqual([e.evidence_id for e in DOSSIERS[1].evidence],
                         [f"E0-B-{i:02}" for i in range(1, 7)])
        self.assertEqual([e.evidence_id for e in DOSSIERS[2].evidence],
                         [f"FIN-{i:03}" for i in range(1, 8)])
        self.assertEqual(DOSSIERS[0].evidence[3].source_status,
                         "AI GOVERNANCE APPROVED; REAL MODEL/RUNTIME/EVALUATION NOT READY")
        self.assertEqual(DOSSIERS[1].evidence[3].source_status,
                         "PRINCIPLE DEFINED; CONTRACT NOT APPROVED")
        self.assertEqual(DOSSIERS[2].evidence[1].source_status,
                         "OPEN / NO CORRECTED FIGURE")

    def test_governance_can_read_source_metadata_for_three_gates(self):
        r = self.client.get(ROOT, headers=self.headers())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([x["domain"] for x in r.json()["items"]],
                         ["DOMESTIC", "EXPORT", "FINANCE"])
        self.assertTrue(all(x["gate_status_at_source"] == "OPEN"
                            for x in r.json()["items"]))
        self.assertTrue(all(not x["actions_enabled"] for x in r.json()["items"]))
        self.assertEqual(r.json()["business_source_sha"], BUSINESS_SOURCE_SHA)
        self.assertEqual(r.json()["snapshot_state"], SNAPSHOT_STATE)
        self.assertEqual(r.headers["cache-control"], "no-store")

    def test_domestic_role_gets_only_domestic_not_export_or_finance(self):
        headers = self.headers(("domestic_ops",))
        r = self.client.get(ROOT, headers=headers)
        self.assertEqual([x["domain"] for x in r.json()["items"]], ["DOMESTIC"])
        for domain in ("EXPORT", "FINANCE", "UNKNOWN"):
            self.assertEqual(self.client.get(
                ROOT + "/" + domain, headers=headers,
            ).status_code, 404)
        self.assertEqual(self.client.get(
            ROOT + "/DOMESTIC", headers=headers
        ).status_code, 200)

    def test_export_and_finance_roles_are_independent(self):
        for role, domain in (("export_ops", "EXPORT"), ("finance", "FINANCE")):
            with self.subTest(role=role):
                headers = self.headers((role,))
                r = self.client.get(ROOT, headers=headers)
                self.assertEqual([x["domain"] for x in r.json()["items"]],
                                 [domain])
                d = self.client.get(ROOT + "/" + domain, headers=headers)
                self.assertEqual(d.status_code, 200)
                self.assertEqual(d.json()["domain"], domain)
                self.assertEqual(d.json()["gate_status_at_source"], "OPEN")

    def test_multi_role_admin_gets_only_signed_union(self):
        headers = self.headers(("domestic_ops", "finance", "local_buyer"))
        r = self.client.get(ROOT, headers=headers)
        self.assertEqual([x["domain"] for x in r.json()["items"]],
                         ["DOMESTIC", "FINANCE"])
        self.assertEqual(self.client.get(
            ROOT + "/EXPORT", headers=headers,
        ).status_code, 404)

    def test_user_partner_role_cannot_browse_admin_gate_data(self):
        headers = self.headers(("household", "local_buyer", "export_supplier"))
        self.assertEqual(self.client.get(ROOT, headers=headers).status_code, 403)
        self.assertEqual(self.client.get(
            ROOT + "/DOMESTIC", headers=headers,
        ).status_code, 404)
        self.assertEqual(self.client.get(HTML + "FINANCE",
                                         headers=headers).status_code, 401)

    def test_missing_forged_expired_identity_rejected_before_gate_read(self):
        self.assertEqual(self.client.get(ROOT).status_code, 401)
        for token in ("forged", self.signed(expired=True)):
            r = self.client.get(ROOT, headers={"Authorization": "Bearer " + token})
            self.assertEqual(r.status_code, 401)
            self.assertNotIn("FIN-001", r.text)
        self.assertEqual(self.client.get(HTML + "DOMESTIC").status_code, 401)

    def test_role_header_query_and_unknown_domain_cannot_escalate(self):
        headers = self.headers(("export_ops",))
        headers.update({"X-Role": "governance", "X-Gate-Approval": "PASS"})
        self.assertEqual([x["domain"] for x in self.client.get(
            ROOT, params={"domain": "FINANCE"}, headers=headers,
        ).json()["items"]], ["EXPORT"])
        self.assertEqual(self.client.get(
            ROOT + "/FINANCE", headers=headers,
        ).status_code, 404)
        self.assertEqual(self.client.get(
            ROOT + "/not-in-registry", headers=headers,
        ).status_code, 404)

    def test_evidence_detail_exposes_only_source_status_no_authority(self):
        for d in DOSSIERS:
            with self.subTest(domain=d.domain):
                res = self.client.get(ROOT + "/" + d.domain,
                                      headers=self.headers())
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data["source_path"], d.source_path)
                self.assertEqual(data["review_authority"], "UNASSIGNED")
                self.assertEqual(data["snapshot_state"], SNAPSHOT_STATE)
                self.assertEqual(len(data["evidence_items"]), len(d.evidence))
                self.assertTrue(all(e["verified_here"] is False
                                    for e in data["evidence_items"]))
                self.assertNotIn("approved_by", data)
                self.assertNotIn("payment_authorized", data)
                self.assertNotIn("PASS", res.text)

    def test_immutable_projection_never_changes_business_gate_state(self):
        d = DOSSIERS[0]
        original = dossier_detail(d)
        original["gate_status_at_source"] = "PASS"
        original["evidence_items"][0]["source_status"] = "VERIFIED"
        fresh = dossier_detail(d)
        self.assertEqual(fresh["gate_status_at_source"], "OPEN")
        self.assertEqual(fresh["evidence_items"][0]["source_status"],
                         "OPEN / NO PILOT SELECTED")
        self.assertFalse(fresh["actions_enabled"])
        self.assertEqual(visible_dossiers(Principal(
            "synthetic-user", frozenset({"governance"})
        )), DOSSIERS)

    def test_governance_html_links_only_to_pinned_source_and_gate_issue(self):
        self.login()
        r = self.client.get(HTML + "DOMESTIC")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("D1-B-01", r.text)
        self.assertIn(BUSINESS_SOURCE_SHA, r.text)
        self.assertIn("/blob/" + BUSINESS_SOURCE_SHA + "/docs/business/73-", r.text)
        self.assertIn("/issues/2", r.text)
        self.assertIn("تصمیم زنده گیت", r.text)
        self.assertIn("OPEN", r.text)
        self.assertIn("frame-ancestors 'none'", r.headers["content-security-policy"])
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertNotIn("synthetic-review-user", r.text)

    def test_unified_admin_links_are_limited_to_each_signed_domain(self):
        self.login(("domestic_ops",))
        r = self.client.get("/admin")
        self.assertEqual(r.status_code, 200)
        self.assertIn(HTML + "DOMESTIC", r.text)
        self.assertNotIn(HTML + "EXPORT", r.text)
        self.assertNotIn(HTML + "FINANCE", r.text)
        self.assertEqual(self.client.get(HTML + "EXPORT").status_code, 404)

    def test_governance_admin_contains_only_three_gate_metadata_links(self):
        self.login(("governance",))
        r = self.client.get("/admin")
        self.assertEqual(r.status_code, 200)
        for domain in ("DOMESTIC", "EXPORT", "FINANCE"):
            self.assertIn(HTML + domain, r.text)
            detail = self.client.get(HTML + domain)
            self.assertEqual(detail.status_code, 200)
        self.assertNotIn("DEMO-D-001", r.text)

    def test_logout_blocks_html_and_explicit_bad_bearer_no_cookie_fallback(self):
        sid = self.login(("finance",))
        self.assertEqual(self.client.get(HTML + "FINANCE").status_code, 200)
        self.assertEqual(self.client.get(
            ROOT, headers={"Authorization": "Bearer bad"},
        ).status_code, 401)
        self.sessions.revoke_session(sid)
        self.assertEqual(self.client.get(HTML + "FINANCE").status_code, 401)
        self.assertEqual(self.client.get(ROOT).status_code, 401)

    def _copy_pinned_sources(self, root: Path) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        for relative in PINNED_BUSINESS_SOURCE_BLOBS:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(repo_root / relative, destination)

    def test_verifier_matches_exact_git_objects_and_original_status_cards(self):
        actual = verify_pinned_business_sources()
        self.assertEqual(actual, PINNED_BUSINESS_SOURCE_BLOBS)
        response = self.client.get(ROOT + "/FINANCE", headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source_integrity_state"],
                         SOURCE_INTEGRITY_STATE)
        self.assertEqual(response.json()["source_blob_id"],
                         PINNED_BUSINESS_SOURCE_BLOBS[DOSSIERS[2].source_path])
        self.assertEqual(self.client.get(
            ROOT, headers=self.headers()
        ).json()["source_integrity_state"], SOURCE_INTEGRITY_STATE)

    def test_independent_copy_of_both_source_files_is_attested(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self._copy_pinned_sources(folder)
            self.assertEqual(
                verify_pinned_business_sources(root=folder),
                PINNED_BUSINESS_SOURCE_BLOBS,
            )

    def test_any_domestic_or_finance_document_edit_fails_closed(self):
        for relative in PINNED_BUSINESS_SOURCE_BLOBS:
            with self.subTest(relative=relative):
                with tempfile.TemporaryDirectory() as tmp:
                    folder = Path(tmp)
                    self._copy_pinned_sources(folder)
                    source = folder / relative
                    source.write_bytes(source.read_bytes() + b"CHANGED")
                    with self.assertRaises(BusinessSourceSnapshotError):
                        verify_pinned_business_sources(root=folder)

    def test_missing_document_or_incomplete_source_manifest_fails_closed(self):
        for relative in PINNED_BUSINESS_SOURCE_BLOBS:
            with self.subTest(relative=relative):
                with tempfile.TemporaryDirectory() as tmp:
                    folder = Path(tmp)
                    self._copy_pinned_sources(folder)
                    (folder / relative).unlink()
                    with self.assertRaises(BusinessSourceSnapshotError):
                        verify_pinned_business_sources(root=folder)

    def test_rehashed_changed_source_status_is_not_trusted(self):
        relative = DOSSIERS[0].source_path
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self._copy_pinned_sources(folder)
            source = folder / relative
            raw = source.read_bytes()
            self.assertIn(b"OPEN / NO PILOT SELECTED", raw)
            changed = raw.replace(
                b"**OPEN / NO PILOT SELECTED**",
                b"**ACCEPTED WITHOUT EVIDENCE**",
                1,
            )
            source.write_bytes(changed)
            new_blob = hashlib.sha1(
                b"blob " + str(len(changed)).encode() + b"\0" + changed
            ).hexdigest()
            with patch.dict(PINNED_BUSINESS_SOURCE_BLOBS,
                            {relative: new_blob}):
                with self.assertRaises(BusinessSourceSnapshotError):
                    verify_pinned_business_sources(root=folder)

    def test_source_file_redirected_outside_checkout_fails_closed(self):
        relative = DOSSIERS[0].source_path
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "checkout"
            folder.mkdir()
            self._copy_pinned_sources(folder)
            external = Path(tmp) / "outside.md"
            shutil.copyfile(folder / relative, external)
            (folder / relative).unlink()
            (folder / relative).symlink_to(external)
            with self.assertRaises(BusinessSourceSnapshotError):
                verify_pinned_business_sources(root=folder)

    def test_source_version_drift_sanitizes_all_authorized_api_details(self):
        domestic_source = DOSSIERS[0].source_path
        with patch.dict(PINNED_BUSINESS_SOURCE_BLOBS,
                        {domestic_source: "f" * 40}):
            for url in (ROOT, ROOT + "/DOMESTIC",
                        ROOT + "/EXPORT", ROOT + "/FINANCE"):
                with self.subTest(url=url):
                    r = self.client.get(url, headers=self.headers())
                    self.assertEqual(r.status_code, 503)
                    self.assertEqual(
                        r.json(),
                        {"detail": "PINNED_BUSINESS_SOURCE_UNAVAILABLE"},
                    )
                    self.assertNotIn("FIN-001", r.text)
                    self.assertNotIn("D1-B-01", r.text)

    def test_source_drift_disables_html_gate_detail_not_unrelated_admin(self):
        self.login(("governance",))
        self.assertIn(HTML + "DOMESTIC", self.client.get("/admin").text)
        with patch.dict(PINNED_BUSINESS_SOURCE_BLOBS,
                        {DOSSIERS[1].source_path: "f" * 40}):
            detail = self.client.get(HTML + "DOMESTIC")
            self.assertEqual(detail.status_code, 503)
            self.assertEqual(
                detail.json(), {"detail": "PINNED_BUSINESS_SOURCE_UNAVAILABLE"}
            )
            self.assertNotIn("D1-B-01", detail.text)
            admin = self.client.get("/admin")
            self.assertEqual(admin.status_code, 200)
            self.assertIn("نسخه محلی اسناد شواهد معتبر نیست", admin.text)
            self.assertNotIn(HTML + "DOMESTIC", admin.text)
            self.assertNotIn(HTML + "EXPORT", admin.text)
            self.assertNotIn(HTML + "FINANCE", admin.text)
        self.assertIn(HTML + "DOMESTIC", self.client.get("/admin").text)

    def test_unassigned_domain_is_hidden_even_when_source_is_corrupted(self):
        headers = self.headers(("domestic_ops",))
        with patch.dict(PINNED_BUSINESS_SOURCE_BLOBS,
                        {DOSSIERS[0].source_path: "0" * 40}):
            self.assertEqual(
                self.client.get(ROOT + "/EXPORT", headers=headers).status_code,
                404,
            )
            self.assertEqual(
                self.client.get(ROOT, headers=headers).status_code, 503,
            )

    def test_default_app_does_not_mount_gate_evidence_or_html(self):
        default = TestClient(create_app(self.config), base_url=ORIGIN)
        self.assertEqual(default.get(
            ROOT, headers=self.headers()
        ).status_code, 404)
        self.assertEqual(default.get(
            HTML + "DOMESTIC", headers=self.headers()
        ).status_code, 404)

    def test_no_mutation_or_evidence_upload_routes(self):
        for path in (ROOT, ROOT + "/DOMESTIC", HTML + "DOMESTIC"):
            with self.subTest(path=path):
                r = self.client.post(path, json={"gate_status": "PASS"},
                                     headers=self.headers())
                self.assertEqual(r.status_code, 405)
                self.assertNotIn("PASS", r.text)


if __name__ == "__main__":
    unittest.main()
