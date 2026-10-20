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
        self.prefix = "DEMO-RUN-" + suffix + "-"
        self.order = "DEMO-ORDER-" + suffix
        self.assignment = "DEMO-ASSIGN-" + suffix
        self.courier = Principal("synthetic-courier", frozenset({"courier"}))
        self.hub = Principal("synthetic-hub", frozenset({"local_hub"}))
        self.household = Principal("synthetic-household", frozenset({"household"}))
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
            provider_event_id=self.prefix + event_id, order_ref=order or self.order,
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
            "provider_event_id": self.prefix + "HTTP-EVENT", "order_ref": self.order,
            "assignment_ref": self.assignment, "event_code": "custom.code",
            "occurred_at": "2026-10-20T10:00:00Z", "payload_digest": "b" * 64,
        }
        url = f"/api/v1/domestic/fulfillment/courier/orders/{self.order}/events"
        response = client.post(url, json={**body, "raw_payload": {"address": "private"}})
        self.assertEqual(response.status_code, 422)
        response = client.post(url.replace(self.order, "DEMO-OTHER"), json=body)
        self.assertEqual(response.status_code, 422)
        prose = {**body, "provider_event_id": self.prefix + "PROSE",
                 "event_code": "Delivered to a person at this address"}
        self.assertEqual(client.post(url, json=prose).status_code, 422)
        response = client.post(url, json=body)
        self.assertEqual(response.status_code, 201, response.text)
        replay = client.post(url, json=body)
        self.assertEqual(replay.status_code, 200, replay.text)
        history = client.get(url + "?limit=1")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["events"][0]["event_code"], "custom.code")
        self.assertFalse(history.json()["has_more"])
        self.assertEqual(client.get(url + "?limit=101").status_code, 422)

    def test_household_tracking_is_owner_scoped_and_redacts_provider_internals(self):
        self.ledger.append(
            "courier", self.courier,
            self.event("HOUSEHOLD-TRACK", code="external.in_transit"),
        )
        app = FastAPI()
        app.include_router(build_fulfillment_event_router(
            self.ledger, lambda: self.courier,
            household_order_access_authority=lambda principal, order_ref:
                principal.subject == "synthetic-household" and order_ref == self.order,
        ))
        client = TestClient(app)
        url = (
            f"/api/v1/domestic/fulfillment/household-orders/{self.order}"
            "/providers/courier/events"
        )
        response = client.get(url)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["events"][0]["provider_event_code"], "external.in_transit")
        self.assertEqual(body["events"][0]["meaning"], "PROVIDER_ASSERTION_ONLY")
        for private_field in (
            "assignment_ref", "provider_event_id", "payload_digest", "event_digest",
        ):
            self.assertNotIn(private_field, response.text)

        other_app = FastAPI()
        other_app.include_router(build_fulfillment_event_router(
            self.ledger, lambda: self.household,
            household_order_access_authority=lambda _principal, _order_ref: False,
        ))
        denied = TestClient(other_app).get(url)
        self.assertEqual(denied.status_code, 404)

    def test_event_pages_keep_a_stable_snapshot_and_verify_page_linkage(self):
        for n in range(1, 5):
            self.ledger.append(
                "courier", self.courier,
                self.event(f"PAGE-{n}", code=f"external.{n}"),
            )
        first = self.ledger.read(
            "courier", self.courier, self.order, limit=2,
        )
        self.assertEqual([e["sequence"] for e in first["events"]], [1, 2])
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_after_sequence"], 2)
        self.assertEqual(first["snapshot_sequence"], 4)

        self.ledger.append(
            "courier", self.courier,
            self.event("PAGE-5", code="external.5"),
        )
        second = self.ledger.read(
            "courier", self.courier, self.order, limit=2,
            after_sequence=first["next_after_sequence"],
            snapshot_sequence=first["snapshot_sequence"],
        )
        self.assertEqual([e["sequence"] for e in second["events"]], [3, 4])
        self.assertFalse(second["has_more"])
        self.assertIsNone(second["next_after_sequence"])

        with self.assertRaises(ValueError):
            self.ledger.read(
                "courier", self.courier, self.order, limit=2,
                after_sequence=5, snapshot_sequence=4,
            )
        with self.assertRaises(ValueError):
            self.ledger.read("courier", self.courier, self.order, limit=101)

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
