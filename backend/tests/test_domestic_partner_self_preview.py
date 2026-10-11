"""Synthetic local-buyer/equipment-seller user journeys: signed, own-only, read-only."""
import json
import secrets
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.domestic_partner_workspace import (
    CONTRACT_VERSION, SyntheticDomesticPartnerSeed,
    SyntheticDomesticPartnerWorkspace,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession

ISS, API, WEB = "https://id.example.test/realms/ronas", "ronas-api", "ronas-web"
ORIGIN = "https://ronas.example.test"
API_ROUTES = {
    "local_buyer": "/api/v1/local-buyer/my-preview",
    "equipment_seller": "/api/v1/equipment-seller/my-preview",
}
HTML_ROUTES = {
    "local_buyer": "/local-buyer/my-preview",
    "equipment_seller": "/equipment-seller/my-preview",
}
SUBJECTS = {
    "local_buyer": "synthetic-buyer-001",
    "equipment_seller": "synthetic-equipment-001",
}
REFS = {
    "local_buyer": "DEMO-BUY-001",
    "equipment_seller": "DEMO-EQP-001",
}
FIELDS = {
    "local_buyer": {
        "identity": None, "requested_products": None,
        "requested_quantity": None, "delivery_location": None, "budget": None,
    },
    "equipment_seller": {
        "identity": None, "equipment_catalogue": None, "stock": None,
        "service_area": None, "equipment_suitability": None,
    },
}


class Sessions:
    def __init__(self):
        self.items = {}

    def get_session(self, sid):
        return self.items.get(sid)

    def revoke_session(self, sid):
        self.items.pop(sid, None)


class DomesticPartnerSelfPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "domestic-partner-demo-key", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(ISS, API, WEB, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        self.active = {
            ("local_buyer", "DEMO-BUY-001"),
            ("local_buyer", "DEMO-BUY-002"),
            ("equipment_seller", "DEMO-EQP-001"),
            ("equipment_seller", "DEMO-EQP-002"),
            ("local_buyer", "DEMO-BUY-DUAL"),
            ("equipment_seller", "DEMO-EQP-DUAL"),
        }
        self.workspace = self.make_workspace()
        self.sessions = Sessions()

        async def no_exchange(_code, _verifier):
            raise AssertionError("no external identity provider")

        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.sessions, no_exchange,
        )
        self.client = self.make_client()

    def seeds(self):
        return (
            SyntheticDomesticPartnerSeed(
                "local_buyer", "DEMO-BUY-001", "synthetic-buyer-001", 2),
            SyntheticDomesticPartnerSeed(
                "local_buyer", "DEMO-BUY-002", "synthetic-buyer-002", 1),
            SyntheticDomesticPartnerSeed(
                "equipment_seller", "DEMO-EQP-001", "synthetic-equipment-001", 3),
            SyntheticDomesticPartnerSeed(
                "equipment_seller", "DEMO-EQP-002", "synthetic-equipment-002", 1),
            SyntheticDomesticPartnerSeed(
                "local_buyer", "DEMO-BUY-DUAL", "synthetic-dual-person", 1),
            SyntheticDomesticPartnerSeed(
                "equipment_seller", "DEMO-EQP-DUAL", "synthetic-dual-person", 2),
        )

    def make_workspace(self, *, seeds=None, checker=None):
        return SyntheticDomesticPartnerWorkspace(
            self.seeds() if seeds is None else seeds,
            trusted_self_access=checker or (
                lambda role, subject, ref, version: (
                    (role, ref) in self.active
                    and subject.startswith("synthetic-")
                    and type(version) is int and version >= 1
                )
            ),
        )

    def make_client(self, *, enabled=True):
        return TestClient(
            create_app(
                self.config, self.flow,
                **({"domestic_partner_workspace": self.workspace} if enabled else {}),
            ), base_url=ORIGIN,
        )

    def signed(self, subject, roles, *, expired=False):
        now = int(time.time())
        return jwt.encode({
            "iss": ISS, "aud": API, "azp": WEB, "sub": subject,
            "typ": "Bearer", "iat": now-5, "nbf": now-5,
            "exp": now-20 if expired else now+500,
            "resource_access": {API: {"roles": list(roles)}},
        }, self.key, algorithm="RS256", headers={"kid": "domestic-partner-demo-key"})

    def bearer(self, subject, roles):
        return {"Authorization": "Bearer " + self.signed(subject, roles)}

    def api(self, role, *, subject=None, roles=None, params=None, client=None):
        return (client or self.client).get(
            API_ROUTES[role], params=params,
            headers=self.bearer(subject or SUBJECTS[role],
                                roles if roles is not None else (role,)),
        )

    def login(self, subject, roles):
        sid = secrets.token_urlsafe(40)
        self.sessions.items[sid] = BrowserSession(
            subject, frozenset(roles), self.signed(subject, roles),
            secrets.token_urlsafe(32), int(time.time()) + 260,
        )
        self.client.cookies.set("__Host-ronas_session", sid)
        return sid

    def test_each_role_has_own_distinct_null_only_preparation_contract(self):
        for role in API_ROUTES:
            with self.subTest(role=role):
                response = self.api(role)
                self.assertEqual(response.status_code, 200, response.text)
                data = response.json()
                self.assertEqual(data["contract_version"], CONTRACT_VERSION)
                self.assertEqual(data["environment"], "SHARED_USER_PARTNER")
                self.assertEqual(data["engine"], "DOMESTIC")
                self.assertEqual(data["role"], role)
                self.assertEqual(data["profile_ref"], REFS[role])
                self.assertEqual(data["profile_state"], "NOT_SUBMITTED_DEMO")
                self.assertEqual(data["source"], "SYNTHETIC_ONLY")
                self.assertEqual(data["preparation_fields"], FIELDS[role])
                for key in (
                    "identity_verified", "purpose_consent_verified",
                    "product_or_equipment_verified", "suitability_verified",
                    "domestic_gate_approved", "data_submission_enabled",
                    "commercial_actions_enabled", "order_or_offer_exists",
                    "payment_enabled", "real_data",
                ):
                    self.assertIs(data[key], False)
                self.assertNotIn(SUBJECTS[role], response.text)
                self.assertNotIn("synthetic-dual-person", response.text)
                self.assertEqual(response.headers["cache-control"], "no-store")

    def test_same_role_multiple_subjects_cannot_select_another_profile(self):
        for role, second_subject, second_ref in (
            ("local_buyer", "synthetic-buyer-002", "DEMO-BUY-002"),
            ("equipment_seller", "synthetic-equipment-002", "DEMO-EQP-002"),
        ):
            first = self.api(role)
            second = self.api(role, subject=second_subject)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json()["profile_ref"], second_ref)
            self.assertNotIn(second_ref, first.text)
            self.assertNotIn(REFS[role], second.text)
            selected = self.api(
                role, params={"subject": second_subject, "ref": second_ref},
            )
            self.assertEqual(selected.json()["profile_ref"], REFS[role])

    def test_cross_role_and_same_subject_dual_role_isolation(self):
        for role, forbidden in (
            ("local_buyer", "equipment_seller"),
            ("equipment_seller", "local_buyer"),
        ):
            self.assertEqual(
                self.api(forbidden, subject=SUBJECTS[role], roles=(role,)).status_code,
                404,
            )
            self.assertEqual(
                self.api(forbidden, subject=SUBJECTS[role],
                         roles=(forbidden,)).status_code, 404,
            )
        both = ("local_buyer", "equipment_seller")
        buyer = self.api("local_buyer", subject="synthetic-dual-person",
                         roles=both)
        equipment = self.api("equipment_seller", subject="synthetic-dual-person",
                             roles=both)
        self.assertEqual(buyer.json()["profile_ref"], "DEMO-BUY-DUAL")
        self.assertEqual(equipment.json()["profile_ref"], "DEMO-EQP-DUAL")
        self.active.remove(("local_buyer", "DEMO-BUY-DUAL"))
        self.assertEqual(
            self.api("local_buyer", subject="synthetic-dual-person",
                     roles=both).status_code, 404,
        )
        self.assertEqual(
            self.api("equipment_seller", subject="synthetic-dual-person",
                     roles=both).status_code, 200,
        )

    def test_other_signed_admin_or_supplier_role_not_a_partner_grant(self):
        for role in API_ROUTES:
            for other_role in (
                "household", "agronomy_expert", "export_supplier",
                "domestic_ops", "export_ops", "governance", "finance",
            ):
                with self.subTest(role=role, other_role=other_role):
                    r = self.api(role, roles=(other_role,))
                    self.assertEqual(r.status_code, 404)
                    self.assertNotIn("DEMO-", r.text)
        self.assertEqual(
            self.api("local_buyer", subject="synthetic-unknown-buyer").status_code,
            404,
        )

    def test_current_authority_revocation_takes_effect_for_old_signed_token(self):
        for role in API_ROUTES:
            self.assertEqual(self.api(role).status_code, 200)
            self.active.remove((role, REFS[role]))
            response = self.api(role)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "PREVIEW_NOT_FOUND"})
            self.assertNotIn(REFS[role], response.text)

    def test_only_literal_true_grants_view_and_checker_failure_is_sanitized(self):
        for value in (1, "true", None, False, [], 0):
            self.workspace._live_access = lambda *_: value
            for role in API_ROUTES:
                self.assertEqual(self.api(role).status_code, 404)
        def unavailable(*_):
            raise RuntimeError("internal fixture authority details")
        self.workspace._live_access = unavailable
        for role in API_ROUTES:
            response = self.api(role)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {
                "detail": "DOMESTIC_PARTNER_PREVIEW_UNAVAILABLE",
            })
            self.assertNotIn(REFS[role], response.text)

    def test_role_capability_flags_are_opt_in_and_do_not_grant_a_view(self):
        for role, capability in (
            ("local_buyer", "OWN_SYNTHETIC_LOCAL_BUYER_PREVIEW"),
            ("equipment_seller", "OWN_SYNTHETIC_EQUIPMENT_SELLER_PREVIEW"),
        ):
            path = "/api/v1/me/user-workspaces/" + role
            actual = self.client.get(
                path, headers=self.bearer(SUBJECTS[role], (role,)),
            )
            self.assertEqual(actual.status_code, 200)
            self.assertEqual(actual.json()["local_test_reads"], [capability])
            self.assertFalse(actual.json()["business_actions_enabled"])
            disabled = self.make_client(enabled=False).get(
                path, headers=self.bearer(SUBJECTS[role], (role,)),
            )
            self.assertEqual(disabled.status_code, 200)
            self.assertEqual(disabled.json()["local_test_reads"], [])
            no_seed = self.client.get(
                path, headers=self.bearer("synthetic-no-partner", (role,)),
            )
            self.assertEqual(no_seed.status_code, 200)
            self.assertEqual(self.api(
                role, subject="synthetic-no-partner",
            ).status_code, 404)

    def test_persian_role_navigation_and_personal_pages_in_same_shared_ui(self):
        for role in API_ROUTES:
            self.client.cookies.clear()
            self.login(SUBJECTS[role], (role,))
            home = self.client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("/workspace/" + role, home.text)
            workspace = self.client.get("/workspace/" + role)
            self.assertEqual(workspace.status_code, 200)
            self.assertIn(HTML_ROUTES[role], workspace.text)
            page = self.client.get(HTML_ROUTES[role])
            self.assertEqual(page.status_code, 200, page.text)
            self.assertIn(REFS[role], page.text)
            self.assertIn("هیچ اطلاعاتی ارسال نشده است", page.text)
            self.assertIn("پیشنهاد، سفارش، قیمت، پرداخت", page.text)
            self.assertNotIn(SUBJECTS[role], page.text)
            self.assertEqual(page.headers["cache-control"], "no-store")
            self.assertIn("frame-ancestors 'none'",
                          page.headers["content-security-policy"])
            other = "equipment_seller" if role == "local_buyer" else "local_buyer"
            self.assertEqual(self.client.get(HTML_ROUTES[other]).status_code, 404)

    def test_revoked_current_authority_hides_link_and_html_for_prior_cookie(self):
        for role in API_ROUTES:
            self.client.cookies.clear()
            self.active.add((role, REFS[role]))
            self.login(SUBJECTS[role], (role,))
            self.assertIn(HTML_ROUTES[role],
                          self.client.get("/workspace/" + role).text)
            self.active.remove((role, REFS[role]))
            self.assertNotIn(HTML_ROUTES[role],
                             self.client.get("/workspace/" + role).text)
            denied = self.client.get(HTML_ROUTES[role])
            self.assertEqual(denied.status_code, 404)
            self.assertNotIn(REFS[role], denied.text)

    def test_provider_outage_returns_503_in_role_page_and_html(self):
        self.login(SUBJECTS["local_buyer"], ("local_buyer",))
        self.workspace._live_access = lambda *_: (
            (_ for _ in ()).throw(RuntimeError("fixture secret"))
        )
        for path in ("/workspace/local_buyer", HTML_ROUTES["local_buyer"]):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("fixture secret", response.text)

    def test_signed_browser_logout_blocks_both_html_and_cookie_api_reads(self):
        for role in API_ROUTES:
            self.client.cookies.clear()
            sid = self.login(SUBJECTS[role], (role,))
            self.assertEqual(self.client.get(HTML_ROUTES[role]).status_code, 200)
            self.assertEqual(self.client.get(API_ROUTES[role]).status_code, 200)
            self.sessions.revoke_session(sid)
            self.assertEqual(self.client.get(HTML_ROUTES[role]).status_code, 401)
            self.assertEqual(self.client.get(API_ROUTES[role]).status_code, 401)

    def test_expired_forged_bearer_never_uses_other_valid_cookie(self):
        self.login(SUBJECTS["local_buyer"], ("local_buyer",))
        route = API_ROUTES["local_buyer"]
        for value in ("forged", self.signed(
            SUBJECTS["local_buyer"], ("local_buyer",), expired=True
        )):
            denied = self.client.get(
                route, headers={"Authorization": "Bearer " + value},
            )
            self.assertEqual(denied.status_code, 401)
        self.assertEqual(self.client.get(route).status_code, 200)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(route).status_code, 401)

    def test_default_runtime_and_mutations_are_absent(self):
        disabled = TestClient(create_app(self.config), base_url=ORIGIN)
        for role in API_ROUTES:
            self.assertEqual(disabled.get(
                API_ROUTES[role], headers=self.bearer(SUBJECTS[role], (role,)),
            ).status_code, 404)
            self.assertEqual(disabled.get(HTML_ROUTES[role]).status_code, 404)
            self.login(SUBJECTS[role], (role,))
            for route in (API_ROUTES[role], HTML_ROUTES[role]):
                for method in ("post", "patch", "put", "delete"):
                    with self.subTest(route=route, method=method):
                        self.assertEqual(
                            getattr(self.client, method)(route).status_code, 405,
                        )
        with self.assertRaises(ValueError):
            create_app(self.config,
                       domestic_partner_workspace=self.workspace)
        with self.assertRaises(ValueError):
            create_app(self.config, self.flow,
                       domestic_partner_workspace=object())

    def test_duplicate_non_demo_or_boolean_version_rejected(self):
        buyer = SyntheticDomesticPartnerSeed(
            "local_buyer", "DEMO-BUY-001", "synthetic-buyer-001", 2
        )
        for seeds in (
            (buyer, buyer),
            (buyer, SyntheticDomesticPartnerSeed(
                "local_buyer", "DEMO-BUY-002", "synthetic-buyer-001", 1,
            )),
            (buyer, SyntheticDomesticPartnerSeed(
                "equipment_seller", "DEMO-BUY-001", "synthetic-equipment-001", 1,
            )),
        ):
            with self.assertRaises(ValueError):
                self.make_workspace(seeds=seeds)
        for role, ref, subject, version in (
            ("wrong", "DEMO-BUY-001", "synthetic-buyer-001", 1),
            ("local_buyer", "NOT-DEMO", "synthetic-buyer-001", 1),
            ("local_buyer", "DEMO-BUY-001", "real-person", 1),
            ("equipment_seller", "DEMO-EQP-001", "synthetic-equipment-001", True),
        ):
            with self.assertRaises(ValueError):
                SyntheticDomesticPartnerSeed(role, ref, subject, version)

    def test_not_seeded_stays_not_found_without_inventing_profile(self):
        self.workspace = self.make_workspace(seeds=())
        client = self.make_client()
        for role in API_ROUTES:
            denied = self.api(role, client=client)
            self.assertEqual(denied.status_code, 404)
            self.assertNotIn("DEMO", denied.text)


    def overview(self, *, subject="synthetic-dual-person",
                 roles=("local_buyer", "equipment_seller"), client=None):
        return (client or self.client).get(
            "/api/v1/domestic-partners/my-preparation",
            headers=self.bearer(subject, roles),
        )

    def test_personal_overview_shows_only_own_independently_authorized_roles(self):
        response = self.overview()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(
            body["contract_version"],
            "ronas.domestic-partner.preparation-overview.v1",
        )
        self.assertEqual(body["environment"], "SHARED_USER_PARTNER")
        self.assertEqual(body["engine"], "DOMESTIC")
        self.assertEqual(body["source"], "SYNTHETIC_ONLY")
        self.assertEqual(body["business_readiness"], "NOT_EVALUATED")
        self.assertIs(body["commercial_actions_enabled"], False)
        self.assertIs(body["counterpart_matching_enabled"], False)
        self.assertIs(body["data_submission_enabled"], False)
        self.assertIs(body["real_data"], False)
        self.assertEqual(
            [(item["role"], item["profile_ref"], item["profile_version"])
             for item in body["items"]],
            [("local_buyer", "DEMO-BUY-DUAL", 1),
             ("equipment_seller", "DEMO-EQP-DUAL", 2)],
        )
        for item in body["items"]:
            self.assertEqual(item["business_readiness"], "NOT_EVALUATED")
            self.assertEqual(item["profile_state"], "NOT_SUBMITTED_DEMO")
            self.assertEqual(item["unknown_display_slots"],
                             list(FIELDS[item["role"]]))
            self.assertIs(item["commercial_actions_enabled"], False)
        for forbidden in (
            "DEMO-BUY-001", "DEMO-BUY-002", "DEMO-EQP-001", "DEMO-EQP-002",
            "synthetic-dual-person", "synthetic-buyer", "synthetic-equipment",
            "order_id", "counterpart_ref", "price",
        ):
            self.assertNotIn(forbidden, response.text)

    def test_overview_single_role_cannot_observe_other_role_seed(self):
        for role in API_ROUTES:
            result = self.overview(subject=SUBJECTS[role], roles=(role,))
            self.assertEqual(result.status_code, 200)
            self.assertEqual(len(result.json()["items"]), 1)
            self.assertEqual(result.json()["items"][0]["profile_ref"], REFS[role])
            other = "equipment_seller" if role == "local_buyer" else "local_buyer"
            self.assertNotIn(REFS[other], result.text)
        # Even if a user signs a second role, they need an independent seed.
        response = self.overview(
            subject="synthetic-buyer-001",
            roles=("local_buyer", "equipment_seller"),
        )
        self.assertEqual(
            [(item["role"], item["profile_ref"])
             for item in response.json()["items"]],
            [("local_buyer", "DEMO-BUY-001")],
        )

    def test_overview_current_revocation_hides_only_that_profile(self):
        self.assertEqual(len(self.overview().json()["items"]), 2)
        self.active.remove(("local_buyer", "DEMO-BUY-DUAL"))
        response = self.overview()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(item["role"], item["profile_ref"]) for item in response.json()["items"]],
            [("equipment_seller", "DEMO-EQP-DUAL")],
        )
        self.assertNotIn("DEMO-BUY-DUAL", response.text)
        self.active.remove(("equipment_seller", "DEMO-EQP-DUAL"))
        empty = self.overview()
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["items"], [])
        self.assertNotIn("DEMO-EQP-DUAL", empty.text)

    def test_overview_checker_exception_fails_closed_without_partial_profiles(self):
        def check(role, subject, ref, version):
            if role == "equipment_seller":
                raise RuntimeError("private fixture authority failed")
            return True
        self.workspace._live_access = check
        response = self.overview()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {
            "detail": "DOMESTIC_PARTNER_PREVIEW_UNAVAILABLE",
        })
        for secret in (
            "DEMO-BUY-DUAL", "DEMO-EQP-DUAL", "private fixture authority",
        ):
            self.assertNotIn(secret, response.text)

    def test_overview_signed_partner_role_required_even_for_empty_list(self):
        for role in (
            "domestic_ops", "household", "export_ops",
            "agronomy_expert", "export_supplier", "governance",
        ):
            response = self.overview(
                subject="synthetic-dual-person", roles=(role,),
            )
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "PREVIEW_NOT_FOUND"})
        no_seed = self.overview(subject="synthetic-no-partner", roles=("local_buyer",))
        self.assertEqual(no_seed.status_code, 200)
        self.assertEqual(no_seed.json()["items"], [])
        self.assertNotIn("DEMO", str(no_seed.json()["items"]))

    def test_persian_unified_landing_for_dual_and_individual_roles(self):
        sid = self.login("synthetic-dual-person",
                         ("local_buyer", "equipment_seller"))
        for role in API_ROUTES:
            self.assertIn(
                "/domestic-partners/my-preparation",
                self.client.get("/workspace/" + role).text,
            )
        page = self.client.get("/domestic-partners/my-preparation")
        self.assertEqual(page.status_code, 200, page.text)
        for term in (
            "آماده‌سازی شخصی من", "خریدار محلی", "فروشنده تجهیزات",
            "DEMO-BUY-DUAL", "DEMO-EQP-DUAL",
            "/local-buyer/my-preview", "/equipment-seller/my-preview",
            "آمادگی تجاری", "هنوز داده‌ای ثبت نشده",
            "ارتباط با خانوار", "تطبیق خریدار و فروشنده",
        ):
            self.assertIn(term, page.text)
        for fragment in (
            "synthetic-dual-person", "DEMO-BUY-001", "DEMO-EQP-001",
        ):
            self.assertNotIn(fragment, page.text)
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.assertIn("frame-ancestors 'none'",
                      page.headers["content-security-policy"])
        self.sessions.revoke_session(sid)
        self.assertEqual(self.client.get(
            "/domestic-partners/my-preparation"
        ).status_code, 401)

    def test_persian_overview_isolation_and_empty_revoked_state(self):
        self.login("synthetic-buyer-001", ("local_buyer",))
        page = self.client.get("/domestic-partners/my-preparation")
        self.assertEqual(page.status_code, 200)
        self.assertIn("DEMO-BUY-001", page.text)
        self.assertNotIn("DEMO-EQP-001", page.text)
        self.assertNotIn("/equipment-seller/my-preview", page.text)
        self.active.remove(("local_buyer", "DEMO-BUY-001"))
        revoked = self.client.get("/domestic-partners/my-preparation")
        self.assertEqual(revoked.status_code, 200)
        self.assertIn("هیچ پیش‌نمای مجاز", revoked.text)
        self.assertNotIn("DEMO-BUY-001", revoked.text)

    def test_persian_overview_role_and_authority_failure_no_disclosure(self):
        self.login("synthetic-dual-person", ("finance",))
        denied = self.client.get("/domestic-partners/my-preparation")
        self.assertEqual(denied.status_code, 404)
        self.assertNotIn("DEMO-", denied.text)
        self.client.cookies.clear()
        self.login("synthetic-dual-person",
                   ("local_buyer", "equipment_seller"))
        self.workspace._live_access = lambda role, *_: (
            (_ for _ in ()).throw(RuntimeError("SECRET_PROVIDER_TRACE"))
            if role == "equipment_seller" else True
        )
        failed = self.client.get("/domestic-partners/my-preparation")
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn("DEMO-BUY-DUAL", failed.text)
        self.assertNotIn("SECRET_PROVIDER_TRACE", failed.text)

    def test_overview_default_off_and_no_http_mutations(self):
        url = "/api/v1/domestic-partners/my-preparation"
        html = "/domestic-partners/my-preparation"
        disabled = self.make_client(enabled=False)
        self.assertEqual(disabled.get(
            url, headers=self.bearer("synthetic-buyer-001", ("local_buyer",)),
        ).status_code, 404)
        self.assertEqual(disabled.get(html).status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(url, headers={
            "Authorization": "Bearer forged",
        }).status_code, 401)
        for path in (url, html):
            for method in ("post", "put", "patch", "delete"):
                with self.subTest(path=path, method=method):
                    self.assertEqual(getattr(self.client, method)(
                        path, headers=self.bearer(
                            "synthetic-dual-person",
                            ("local_buyer", "equipment_seller"),
                        ),
                    ).status_code, 405)



if __name__ == "__main__":
    unittest.main()
