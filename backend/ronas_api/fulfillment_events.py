"""API-only append-only ledger for provider-originated Domestic delivery events.

Event codes remain opaque. This component records an authorized provider's
assertion; it never infers delivery completion, customer receipt, or quality.
Only identifiers and a payload digest are stored; address/customer payloads are
not accepted by this API.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .auth import Principal

_PROVIDERS = {"courier": "courier", "local-hub": "local_hub"}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class FulfillmentEventError(Exception):
    pass


class FulfillmentEventConflict(FulfillmentEventError):
    pass


class FulfillmentEventUnavailable(FulfillmentEventError):
    pass


class FulfillmentEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider_event_id: str = Field(min_length=1, max_length=128)
    order_ref: str = Field(min_length=1, max_length=128)
    assignment_ref: str = Field(min_length=1, max_length=128)
    event_code: str = Field(min_length=1, max_length=80)
    occurred_at: datetime
    payload_digest: str = Field(min_length=64, max_length=64)

    @field_validator("provider_event_id", "order_ref", "assignment_ref")
    @classmethod
    def safe_identifier(cls, value: str) -> str:
        if not _ID.fullmatch(value):
            raise ValueError("opaque bounded identifier required")
        return value

    @field_validator("event_code")
    @classmethod
    def bounded_event_code(cls, value: str) -> str:
        if not value or any(ord(ch) < 0x20 for ch in value):
            raise ValueError("printable opaque event code required")
        return value

    @field_validator("occurred_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone-aware event time required")
        return value.astimezone(timezone.utc)

    @field_validator("payload_digest")
    @classmethod
    def valid_digest(cls, value: str) -> str:
        if not _DIGEST.fullmatch(value):
            raise ValueError("lowercase SHA-256 digest required")
        return value


def _canonical(provider: str, data: FulfillmentEventInput) -> bytes:
    return json.dumps({
        "provider": provider,
        "provider_event_id": data.provider_event_id,
        "order_ref": data.order_ref,
        "assignment_ref": data.assignment_ref,
        "event_code": data.event_code,
        "occurred_at": data.occurred_at.isoformat(),
        "payload_digest": data.payload_digest,
    }, sort_keys=True, separators=(",", ":")).encode()


class PostgresFulfillmentEventLedger:
    """Immutable per-order event stream guarded by live assignment authority."""

    def __init__(self, dsn: str, current_assignment_authority, *, connect_timeout: int = 3):
        if (not isinstance(dsn, str) or not dsn or len(dsn) > 4096 or "\x00" in dsn
                or not callable(current_assignment_authority)
                or type(connect_timeout) is not int or not 1 <= connect_timeout <= 15):
            raise ValueError("PostgreSQL DSN and live assignment authority required")
        self._dsn = dsn
        self._authority = current_assignment_authority
        self._connect_timeout = connect_timeout
        self._initialize()

    def _connect(self):
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout,
                               application_name="ronas-fulfillment-events",
                               row_factory=dict_row)

    def _initialize(self):
        try:
            with self._connect() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS ronas_domestic_fulfillment_event (
                    provider TEXT NOT NULL CHECK (provider IN ('courier','local-hub')),
                    provider_event_id TEXT NOT NULL,
                    order_ref TEXT NOT NULL,
                    assignment_ref TEXT NOT NULL,
                    sequence BIGINT NOT NULL CHECK (sequence > 0),
                    event_code TEXT NOT NULL,
                    occurred_at TIMESTAMPTZ NOT NULL,
                    payload_digest CHAR(64) NOT NULL,
                    event_digest CHAR(64) NOT NULL,
                    previous_digest CHAR(64) NOT NULL,
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY(provider, provider_event_id),
                    UNIQUE(order_ref, provider, sequence)
                )""")
                db.execute("""CREATE INDEX IF NOT EXISTS ronas_domestic_fulfillment_order
                    ON ronas_domestic_fulfillment_event(order_ref, sequence)""")
                db.execute("""CREATE OR REPLACE FUNCTION ronas_reject_fulfillment_mutation()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'fulfillment event history is immutable'; END;
                    $$""")
                db.execute("""DO $$ BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                        WHERE tgname='ronas_domestic_fulfillment_immutable'
                        AND tgrelid='ronas_domestic_fulfillment_event'::regclass
                        AND NOT tgisinternal) THEN
                      CREATE TRIGGER ronas_domestic_fulfillment_immutable
                      BEFORE UPDATE OR DELETE ON ronas_domestic_fulfillment_event
                      FOR EACH ROW EXECUTE FUNCTION ronas_reject_fulfillment_mutation();
                    END IF;
                    END $$""")
        except psycopg.Error as exc:
            raise FulfillmentEventUnavailable from exc

    def _authorized(self, principal: Principal, provider: str,
                    order_ref: str, assignment_ref: str) -> bool:
        try:
            return self._authority(principal, provider, order_ref, assignment_ref) is True
        except Exception:
            return False

    def append(self, provider: str, principal: Principal,
               data: FulfillmentEventInput) -> dict:
        if provider not in _PROVIDERS or _PROVIDERS[provider] not in principal.roles:
            raise PermissionError("provider role required")
        if not self._authorized(principal, provider, data.order_ref, data.assignment_ref):
            raise PermissionError("current assignment is not authorized")
        payload = _canonical(provider, data)
        digest = hashlib.sha256(payload).hexdigest()
        try:
            with self._connect() as db:
                # Serialize writes per order; parallel provider retries remain idempotent.
                db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                           (provider + ":" + data.order_ref,))
                existing = db.execute("""SELECT * FROM ronas_domestic_fulfillment_event
                    WHERE provider=%s AND provider_event_id=%s""",
                    (provider, data.provider_event_id)).fetchone()
                if existing:
                    if (existing["order_ref"] != data.order_ref
                            or existing["assignment_ref"] != data.assignment_ref
                            or not hmac.compare_digest(existing["event_digest"], digest)):
                        raise FulfillmentEventConflict("provider event id was reused")
                    return self._view(existing, replay=True)
                last = db.execute("""SELECT sequence,event_digest
                    FROM ronas_domestic_fulfillment_event WHERE order_ref=%s AND provider=%s
                    ORDER BY sequence DESC LIMIT 1""", (data.order_ref, provider)).fetchone()
                sequence = 1 if last is None else last["sequence"] + 1
                previous = "0" * 64 if last is None else last["event_digest"]
                chain_digest = hashlib.sha256(
                    bytes.fromhex(previous) + sequence.to_bytes(8, "big") + payload
                ).hexdigest()
                row = db.execute("""INSERT INTO ronas_domestic_fulfillment_event
                    (provider,provider_event_id,order_ref,assignment_ref,sequence,event_code,
                     occurred_at,payload_digest,event_digest,previous_digest)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (provider, data.provider_event_id, data.order_ref, data.assignment_ref,
                     sequence, data.event_code, data.occurred_at, data.payload_digest,
                     chain_digest, previous)).fetchone()
                return self._view(row, replay=False)
        except FulfillmentEventConflict:
            raise
        except psycopg.Error as exc:
            raise FulfillmentEventUnavailable from exc

    def read(self, provider: str, principal: Principal, order_ref: str) -> dict:
        if provider not in _PROVIDERS or _PROVIDERS[provider] not in principal.roles:
            raise PermissionError("provider role required")
        if not _ID.fullmatch(order_ref):
            raise ValueError("invalid order reference")
        # Resolve the currently assigned provider on every read; caller must supply
        # assignment reference via authority lookup without exposing order payloads.
        try:
            with self._connect() as db:
                rows = list(db.execute("""SELECT * FROM ronas_domestic_fulfillment_event
                    WHERE order_ref=%s AND provider=%s ORDER BY sequence""",
                    (order_ref, provider)))
        except psycopg.Error as exc:
            raise FulfillmentEventUnavailable from exc
        if not rows:
            return {"order_ref": order_ref, "provider": provider, "events": []}
        # Authority is evaluated against each recorded assignment, so a revoked or
        # reassigned provider cannot use a stale event stream.
        if any(not self._authorized(principal, provider, order_ref, row["assignment_ref"])
               for row in rows):
            raise PermissionError("current assignment is not authorized")
        previous = "0" * 64
        views = []
        for expected_sequence, row in enumerate(rows, 1):
            if row["sequence"] != expected_sequence or row["previous_digest"] != previous:
                raise FulfillmentEventUnavailable
            view = self._view(row, replay=False)
            # Verify chain integrity without storing private payload content.
            canonical = json.dumps({
                "provider": provider, "provider_event_id": row["provider_event_id"],
                "order_ref": order_ref, "assignment_ref": row["assignment_ref"],
                "event_code": row["event_code"],
                "occurred_at": row["occurred_at"].astimezone(timezone.utc).isoformat(),
                "payload_digest": row["payload_digest"].strip(),
            }, sort_keys=True, separators=(",", ":")).encode()
            actual = hashlib.sha256(
                bytes.fromhex(previous) + expected_sequence.to_bytes(8, "big") + canonical
            ).hexdigest()
            if not hmac.compare_digest(actual, row["event_digest"]):
                raise FulfillmentEventUnavailable
            previous = actual
            views.append(view)
        return {"order_ref": order_ref, "provider": provider, "events": views}

    @staticmethod
    def _view(row, *, replay: bool) -> dict:
        return {
            "provider": row["provider"], "provider_event_id": row["provider_event_id"],
            "order_ref": row["order_ref"], "assignment_ref": row["assignment_ref"],
            "sequence": row["sequence"], "event_code": row["event_code"],
            "occurred_at": row["occurred_at"].astimezone(timezone.utc).isoformat(),
            "payload_digest": row["payload_digest"].strip(),
            "event_digest": row["event_digest"], "idempotent_replay": replay,
            "meaning": "PROVIDER_ASSERTION_ONLY",
        }


def build_fulfillment_event_router(ledger: PostgresFulfillmentEventLedger,
                                   principal_dependency) -> APIRouter:
    router = APIRouter(prefix="/api/v1/domestic/fulfillment", tags=["fulfillment-api"])

    @router.post("/{provider}/orders/{order_ref}/events", status_code=201)
    def append_event(provider: str, order_ref: str, body: FulfillmentEventInput,
                     response: Response,
                     principal: Principal = Depends(principal_dependency)):
        if body.order_ref != order_ref:
            raise HTTPException(422, "ORDER_REFERENCE_MISMATCH")
        try:
            result = ledger.append(provider, principal, body)
            response.status_code = 200 if result["idempotent_replay"] else 201
            return result
        except PermissionError:
            raise HTTPException(403, "FULFILLMENT_ASSIGNMENT_FORBIDDEN") from None
        except FulfillmentEventConflict:
            raise HTTPException(409, "PROVIDER_EVENT_ID_CONFLICT") from None
        except FulfillmentEventUnavailable:
            raise HTTPException(503, "FULFILLMENT_EVENT_LEDGER_UNAVAILABLE") from None

    @router.get("/{provider}/orders/{order_ref}/events")
    def read_events(provider: str, order_ref: str,
                    principal: Principal = Depends(principal_dependency)):
        try:
            return ledger.read(provider, principal, order_ref)
        except PermissionError:
            raise HTTPException(403, "FULFILLMENT_ASSIGNMENT_FORBIDDEN") from None
        except ValueError:
            raise HTTPException(422, "INVALID_ORDER_REFERENCE") from None
        except FulfillmentEventUnavailable:
            raise HTTPException(503, "FULFILLMENT_EVENT_LEDGER_UNAVAILABLE") from None

    return router
