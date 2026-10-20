"""Household shipment-event page composed inside the existing user shell."""
import json
import secrets
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from ronas_api.auth import Principal
from ronas_api.app import create_app
from ronas_api.fulfillment_events import PostgresFulfillmentEventLedger
from ronas_api.keycloak import KeycloakConfig
from ronas_api.oidc_browser import BrowserOIDC, BrowserOIDCConfig, BrowserSession
from ronas_api.ui_bff import build_authenticated_ui_router

ISS = "https://identity.example.test/realms/ronas"
ORIGIN = "https://ronas.example.test"
API, BROWSER = "ronas-api", "ronas-web"


class SessionStore:
    def __init__(self):
        self.sessions = {}

    def get_session(self, sid):
        return self.sessions.get(sid)


class EventLedger:
    def __init__(self):
        self.calls = []

    def read_for_household(self, provider, principal, order_ref, authority, **page):
        if not authority(principal, order_ref):
            raise PermissionError("forbidden")
        self.calls.append((provider, principal, order_ref, page))
        return {
            "order_ref": order_ref,
            "provider": provider,
            "events": [{
                "sequence": 3,
                "event_code": "PICKED_UP",
                "occurred_at": "2026-10-20T11:00:00+00:00",
                "meaning": "PROVIDER_ASSERTION_ONLY",
            }],
            "limit": page["limit"],
            "after_sequence": page["after_sequence"],
            "snapshot_sequence": 7,
            "has_more": True,
            "next_after_sequence": 3,
        }


class FulfillmentUserPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "one", "use": "sig", "alg": "RS256"})
        cls.config = KeycloakConfig(ISS, API, BROWSER, json.dumps({"keys": [jwk]}).encode())

    def setUp(self):
        self.store = SessionStore()

        async def no_exchange(code, verifier):
            raise AssertionError("no identity exchange in page tests")

        self.flow = BrowserOIDC(
            BrowserOIDCConfig(self.config, ORIGIN + "/api/auth/callback"),
            self.store, no_exchange,
        )
        self.ledger = EventLedger()
        app = FastAPI()
        app.include_router(build_authenticated_ui_router(
            self.flow,
            fulfillment_event_ledger=self.ledger,
            fulfillment_household_order_access_authority=lambda principal, ref: (
                principal.subject == "owner-1" and ref == "ORDER-1"
            ),
        ))
        self.client = TestClient(app, base_url=ORIGIN)

    def sign_in(self, roles):
        now = int(time.time())
        signed = jwt.encode({
            "iss": ISS, "aud": [API], "sub": "owner-1", "azp": BROWSER,
            "typ": "Bearer", "iat": now - 5, "nbf": now - 5, "exp": now + 700,
            "resource_access": {API: {"roles": roles}},
        }, self.key, algorithm="RS256", headers={"kid": "one"})
        sid = secrets.token_urlsafe(36)
        self.store.sessions[sid] = BrowserSession(
            "owner-1", frozenset(roles), signed, "csrf", now + 650,
        )
        self.client.cookies.set("__Host-ronas_session", sid)

    def test_household_card_links_to_one_existing_user_shell(self):
        self.sign_in(["household"])
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/my-fulfillment"', response.text)
        self.assertNotIn("پیگیری رویدادهای سفارش", self.client.get("/admin").text)

    def test_tracking_page_shows_only_escaped_opaque_assertions_and_stable_cursor(self):
        self.sign_in(["household"])
        response = self.client.get("/my-fulfillment", params={
            "order_ref": "ORDER-1", "provider": "courier", "limit": 10,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("PICKED_UP", response.text)
        self.assertIn("به‌تنهایی وضعیت تحویل", response.text)
        self.assertIn("after_sequence=3", response.text)
        self.assertIn("snapshot_sequence=7", response.text)
        self.assertEqual(self.ledger.calls[0][1], Principal("owner-1", frozenset({"household"})))
        self.assertEqual(self.ledger.calls[0][3], {
            "limit": 10, "after_sequence": 0, "snapshot_sequence": None,
        })

    def test_unauthorized_order_is_not_disclosed_and_input_is_not_reflected(self):
        self.sign_in(["household"])
        response = self.client.get("/my-fulfillment", params={
            "order_ref": '<img src=x onerror=alert(1)>',
        })
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("<img", response.text)
        self.assertNotIn("ORDER-1", response.text)

    def test_non_household_role_cannot_open_tracking_page(self):
        self.sign_in(["domestic_ops"])
        response = self.client.get("/my-fulfillment")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.ledger.calls, [])

    def test_page_parameters_are_bounded_before_ledger_access(self):
        self.sign_in(["household"])
        response = self.client.get("/my-fulfillment", params={
            "order_ref": "ORDER-1", "after_sequence": 2147483648,
        })
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.ledger.calls, [])

    def test_provider_api_alone_does_not_mount_household_tracking_page(self):
        # Route composition is tested without opening a PostgreSQL connection.
        ledger = object.__new__(PostgresFulfillmentEventLedger)
        with patch("ronas_api.app.build_authenticated_ui_router",
                   return_value=APIRouter()) as ui_builder:
            create_app(self.config, self.flow, fulfillment_event_ledger=ledger)
        self.assertIsNone(ui_builder.call_args.kwargs["fulfillment_event_ledger"])
        self.assertIsNone(
            ui_builder.call_args.kwargs["fulfillment_household_order_access_authority"]
        )

    def test_household_tracking_mounts_only_with_live_order_authority(self):
        ledger = object.__new__(PostgresFulfillmentEventLedger)
        authority = lambda principal, order_ref: True
        with patch("ronas_api.app.build_authenticated_ui_router",
                   return_value=APIRouter()) as ui_builder:
            create_app(
                self.config, self.flow, fulfillment_event_ledger=ledger,
                fulfillment_household_order_access_authority=authority,
            )
        self.assertIs(ui_builder.call_args.kwargs["fulfillment_event_ledger"], ledger)
        self.assertIs(
            ui_builder.call_args.kwargs["fulfillment_household_order_access_authority"],
            authority,
        )


if __name__ == "__main__":
    unittest.main()
