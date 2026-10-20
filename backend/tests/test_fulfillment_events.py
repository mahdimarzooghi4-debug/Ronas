"""PostgreSQL and API contract tests for API-only Domestic fulfillment events."""
import os
import secrets
import unittest

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ronas_api.auth import Principal
from ronas_api.fulfillment_events import (
    FulfillmentEventConflict, FulfillmentEventInput, FulfillmentEventUnavailable,
    PostgresFulfillmentEventLedger, build_fulfillment_event_router,
)

DSN = os.environ.get("RONAS_TEST_POSTGRES_DSN")


@unittest.skipUnless(DSN, "CI PostgreSQL service is required")
class FulfillmentEventTests(unittest.TestCase):
    def setUp(self):
        suffix = secrets.token_hex(8)
        self.order = "DEMO-ORDER-" + suffix
        self.assignment = "DEMO-ASSIGN-" + suffix
        self.courier = Principal("synthetic-courier", frozenset({"courier"}))
        self.hub = Principal("synthetic-hub", frozenset({"local_hub"}))
        self.active = {("courier", self.order): self.assignment}
        self.ledger = PostgresFulfillmentEventLedger(
            DSN,
            lambda principal, provider, order_ref, assignment_ref:
                principal.subject == ("synthetic-courier" if provider == "courier"
                                      else "synthetic-hub")
                and self.active.get((provider, order_ref)) == assignment_ref,
        )

    def event(self, event_id="DEMO-EVENT-1", *, order=None, assignment=None,
              code="provider.status.unknown", payload_digest=None):
        return FulfillmentEventInput(
            provider_event_id=event_id, order_ref=order or self.order,
            assignment_ref=assignment or self.assignment,
            event_code=code, occurred_at="2026-10-20T10:00:00+03:30",
            payload_digest=payload_digest or "a" * 64,
        )

    def test_append_is_opaque_idempotent_ordered_and_does_not_store_payload(self):
        first = self.ledger.append("courier", self.courier, self.event())
        replay = self.ledger.append("courier", self.courier, self.event())
        second = self.ledger.append(
            "courier", self.courier,
            self.event("DEMO-EVENT-2", code="whatever.external.code"),
        )
        self.assertEqual(first["sequence"], 1)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(second["meaning"], "PROVIDER_ASSERTION_ONLY")
        stream = self.ledger.read("courier", self.courier, self.order)
        self.assertEqual([item["sequence"] for item in stream["events"]], [1, 2])
        with psycopg.connect(DSN) as db:
            stored = db.execute("""SELECT event_code,payload_digest
                FROM ronas_domestic_fulfillment_event WHERE order_ref=%s""",
                (self.order,)).fetchall()
        self.assertEqual(stored[0][0], "provider.status.unknown")
        self.assertNotIn(b"address", repr(stored).encode())

    def test_provider_event_id_collision_and_stale_assignment_conflict(self):
        self.ledger.append("courier", self.courier, self.event())
        with self.assertRaises(FulfillmentEventConflict):
            self.ledger.append("courier", self.courier,
                               self.event(code="different"))
        self.active[("courier", self.order)] = "DEMO-REASSIGNED"
        with self.assertRaises(PermissionError):
            self.ledger.read("courier", self.courier, self.order)
        with self.assertRaises(PermissionError):
            self.ledger.append("courier", self.courier, self.event("DEMO-EVENT-2"))

    def test_hub_and_courier_streams_are_role_and_assignment_scoped(self):
        self.active[("local-hub", self.order)] = "DEMO-HUB-ASSIGN"
        hub_event = self.event("DEMO-HUB-EVENT", assignment="DEMO-HUB-ASSIGN")
        result = self.ledger.append("local-hub", self.hub, hub_event)
        self.assertEqual(result["provider"], "local-hub")
        with self.assertRaises(PermissionError):
            self.ledger.append("courier", self.hub, self.event())

    def test_http_api_validates_path_and_never_accepts_raw_payload(self):
        app = FastAPI()
        app.include_router(build_fulfillment_event_router(
            self.ledger, lambda: self.courier,
        ))
        client = TestClient(app)
        body = {
            "provider_event_id": "DEMO-HTTP-EVENT", "order_ref": self.order,
            "assignment_ref": self.assignment, "event_code": "custom.code",
            "occurred_at": "2026-10-20T10:00:00Z", "payload_digest": "b" * 64,
        }
        url = f"/api/v1/domestic/fulfillment/courier/orders/{self.order}/events"
        response = client.post(url, json={**body, "raw_payload": {"address": "private"}})
        self.assertEqual(response.status_code, 422)
        response = client.post(url.replace(self.order, "DEMO-OTHER"), json=body)
        self.assertEqual(response.status_code, 422)
        response = client.post(url, json=body)
        self.assertEqual(response.status_code, 201, response.text)
        replay = client.post(url, json=body)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(client.get(url).json()["events"][0]["event_code"], "custom.code")

    def test_ledger_detects_tampering_and_database_rejects_mutation(self):
        self.ledger.append("courier", self.courier, self.event())
        with self.assertRaises(psycopg.errors.RaiseException):
            with psycopg.connect(DSN) as db:
                db.execute("""UPDATE ronas_domestic_fulfillment_event
                    SET event_code='changed' WHERE order_ref=%s""", (self.order,))
        with psycopg.connect(DSN) as db:
            db.execute("ALTER TABLE ronas_domestic_fulfillment_event DISABLE TRIGGER USER")
            db.execute("""UPDATE ronas_domestic_fulfillment_event SET event_digest=%s
                WHERE order_ref=%s""", ("0" * 64, self.order))
            db.execute("ALTER TABLE ronas_domestic_fulfillment_event ENABLE TRIGGER USER")
        with self.assertRaises(FulfillmentEventUnavailable):
            self.ledger.read("courier", self.courier, self.order)


if __name__ == "__main__":
    unittest.main()
