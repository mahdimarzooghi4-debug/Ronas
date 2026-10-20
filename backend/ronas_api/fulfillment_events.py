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
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .auth import Principal

_PROVIDERS = {"courier": "courier", "local-hub": "local_hub"}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_EVENT_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")


class FulfillmentEventError(Exception):
    pass


class FulfillmentEventConflict(FulfillmentEventError):
    pass


class FulfillmentEventUnavailable(FulfillmentEventError):
    pass


@dataclass(frozen=True, slots=True)
class HouseholdOrderReferencePage:
    """Bounded, stable page of opaque order references from the order source."""

    order_refs: tuple[str, ...]
    next_cursor: str | None
    snapshot_ref: str
    has_more: bool
    limit: int

    def __post_init__(self):
        if (type(self.order_refs) is not tuple
                or type(self.limit) is not int or not 1 <= self.limit <= 100
                or len(self.order_refs) > self.limit
                or any(not isinstance(ref, str) or not _ID.fullmatch(ref)
                       for ref in self.order_refs)
                or len(set(self.order_refs)) != len(self.order_refs)
                or not isinstance(self.snapshot_ref, str)
                or not _ID.fullmatch(self.snapshot_ref)
                or type(self.has_more) is not bool
                or (self.has_more and (not isinstance(self.next_cursor, str)
                                       or not _ID.fullmatch(self.next_cursor)))
                or (not self.has_more and self.next_cursor is not None)):
            raise ValueError("invalid household order reference page")


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
        if not _EVENT_CODE.fullmatch(value):
            raise ValueError("opaque provider event code required")
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

def _canonical_row(provider: str, row) -> bytes:
    return json.dumps({
        "provider": provider,
        "provider_event_id": row["provider_event_id"],
        "order_ref": row["order_ref"],
        "assignment_ref": row["assignment_ref"],
        "event_code": row["event_code"],
        "occurred_at": row["occurred_at"].astimezone(timezone.utc).isoformat(),
        "payload_digest": row["payload_digest"].strip(),
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
                            or not hmac.compare_digest(
                                hashlib.sha256(_canonical_row(provider, existing)).hexdigest(),
                                digest)):
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

    def read(self, provider: str, principal: Principal, order_ref: str, *,
             limit: int = 20, after_sequence: int = 0,
             snapshot_sequence: int | None = None) -> dict:
        if provider not in _PROVIDERS or _PROVIDERS[provider] not in principal.roles:
            raise PermissionError("provider role required")
        return self._read_page(
            provider, principal, order_ref, limit=limit,
            after_sequence=after_sequence, snapshot_sequence=snapshot_sequence,
            check_provider_assignment=True,
        )

    def read_for_household(self, provider: str, principal: Principal, order_ref: str,
                           order_access_authority, *, limit: int = 20,
                           after_sequence: int = 0,
                           snapshot_sequence: int | None = None) -> dict:
        if "household" not in principal.roles:
            raise PermissionError("household role required")
        if not callable(order_access_authority):
            raise PermissionError("current order authority unavailable")
        try:
            authorized = order_access_authority(principal, order_ref) is True
        except Exception:
            authorized = False
        if not authorized:
            raise PermissionError("current order access is not authorized")
        return self._read_page(
            provider, principal, order_ref, limit=limit,
            after_sequence=after_sequence, snapshot_sequence=snapshot_sequence,
            check_provider_assignment=False,
        )

    def _read_page(self, provider: str, principal: Principal, order_ref: str, *,
                   limit: int, after_sequence: int,
                   snapshot_sequence: int | None,
                   check_provider_assignment: bool) -> dict:
        if provider not in _PROVIDERS:
            raise ValueError("invalid fulfillment provider")
        if not _ID.fullmatch(order_ref):
            raise ValueError("invalid order reference")
        if (type(limit) is not int or not 1 <= limit <= 100
                or type(after_sequence) is not int or after_sequence < 0
                or snapshot_sequence is not None
                   and (type(snapshot_sequence) is not int or snapshot_sequence < 0)):
            raise ValueError("invalid fulfillment event page")
        try:
            with self._connect() as db:
                head = db.execute("""SELECT COALESCE(MAX(sequence), 0) AS sequence
                    FROM ronas_domestic_fulfillment_event
                    WHERE order_ref=%s AND provider=%s""",
                    (order_ref, provider)).fetchone()["sequence"]
                snapshot = head if snapshot_sequence is None else snapshot_sequence
                if snapshot > head or after_sequence > snapshot:
                    raise ValueError("invalid fulfillment event snapshot")
                previous = "0" * 64
                if after_sequence:
                    predecessor = db.execute("""SELECT * FROM ronas_domestic_fulfillment_event
                        WHERE order_ref=%s AND provider=%s AND sequence=%s""",
                        (order_ref, provider, after_sequence)).fetchone()
                    if predecessor is None:
                        raise ValueError("invalid fulfillment event cursor")
                    if (check_provider_assignment and not self._authorized(
                            principal, provider, order_ref,
                            predecessor["assignment_ref"])):
                        raise PermissionError("current assignment is not authorized")
                    previous = predecessor["event_digest"]
                rows = list(db.execute("""SELECT * FROM ronas_domestic_fulfillment_event
                    WHERE order_ref=%s AND provider=%s AND sequence>%s AND sequence<=%s
                    ORDER BY sequence LIMIT %s""",
                    (order_ref, provider, after_sequence, snapshot, limit + 1)))
        except (FulfillmentEventUnavailable, PermissionError, ValueError):
            raise
        except psycopg.Error as exc:
            raise FulfillmentEventUnavailable from exc

        has_more = len(rows) > limit
        page = rows[:limit]
        previous = ("0" * 64 if after_sequence == 0 else previous)
        views = []
        for offset, row in enumerate(page, 1):
            expected_sequence = after_sequence + offset
            if row["sequence"] != expected_sequence or row["previous_digest"] != previous:
                raise FulfillmentEventUnavailable
            canonical = _canonical_row(provider, row)
            actual = hashlib.sha256(
                bytes.fromhex(previous) + expected_sequence.to_bytes(8, "big") + canonical
            ).hexdigest()
            if not hmac.compare_digest(actual, row["event_digest"]):
                raise FulfillmentEventUnavailable
            if (check_provider_assignment and not self._authorized(
                    principal, provider, order_ref, row["assignment_ref"])):
                raise PermissionError("current assignment is not authorized")
            previous = actual
            views.append(self._view(row, replay=False))
        next_after = page[-1]["sequence"] if page and has_more else None
        return {
            "order_ref": order_ref, "provider": provider, "events": views,
            "limit": limit, "after_sequence": after_sequence,
            "snapshot_sequence": snapshot, "has_more": has_more,
            "next_after_sequence": next_after,
        }

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


def read_household_order_reference_page(
    principal: Principal, listing_authority, order_access_authority, *,
    after_ref: str | None = None, snapshot_ref: str | None = None,
    limit: int = 20,
) -> HouseholdOrderReferencePage:
    """List references only; live per-order access is rechecked before return."""
    if "household" not in principal.roles:
        raise PermissionError("household role required")
    if (not callable(listing_authority) or not callable(order_access_authority)
            or type(limit) is not int or not 1 <= limit <= 100
            or after_ref is not None and (
                not isinstance(after_ref, str) or not _ID.fullmatch(after_ref)
                or snapshot_ref is None
            )
            or snapshot_ref is not None and (
                not isinstance(snapshot_ref, str) or not _ID.fullmatch(snapshot_ref)
            )):
        raise ValueError("invalid household order page request")
    try:
        page = listing_authority(
            principal, after_ref=after_ref, snapshot_ref=snapshot_ref, limit=limit,
        )
    except Exception as exc:
        raise FulfillmentEventUnavailable from exc
    if (not isinstance(page, HouseholdOrderReferencePage)
            or page.limit != limit
            or snapshot_ref is not None and page.snapshot_ref != snapshot_ref):
        raise FulfillmentEventUnavailable
    visible: list[str] = []
    for order_ref in page.order_refs:
        try:
            if order_access_authority(principal, order_ref) is True:
                visible.append(order_ref)
        except Exception as exc:
            raise FulfillmentEventUnavailable from exc
    return HouseholdOrderReferencePage(
        tuple(visible), page.next_cursor, page.snapshot_ref,
        page.has_more, page.limit,
    )


def build_fulfillment_event_router(ledger: PostgresFulfillmentEventLedger,
                                   principal_dependency,
                                   household_order_access_authority=None,
                                   household_order_listing_authority=None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/domestic/fulfillment", tags=["fulfillment-api"])

    @router.get("/household-orders")
    def list_household_orders(
        limit: int = Query(default=20, ge=1, le=100),
        after_ref: str | None = Query(default=None, max_length=128),
        snapshot_ref: str | None = Query(default=None, max_length=128),
        principal: Principal = Depends(principal_dependency),
    ):
        if (not callable(household_order_access_authority)
                or not callable(household_order_listing_authority)):
            raise HTTPException(503, "HOUSEHOLD_ORDER_SOURCE_UNAVAILABLE")
        try:
            result = read_household_order_reference_page(
                principal, household_order_listing_authority,
                household_order_access_authority, after_ref=after_ref,
                snapshot_ref=snapshot_ref, limit=limit,
            )
            return {
                "contract_version": "ronas.domestic.fulfillment.household-order-page.v1",
                "order_refs": list(result.order_refs),
                "next_cursor": result.next_cursor,
                "snapshot_ref": result.snapshot_ref,
                "has_more": result.has_more,
                "limit": result.limit,
            }
        except PermissionError:
            raise HTTPException(403, "HOUSEHOLD_ROLE_REQUIRED") from None
        except ValueError:
            raise HTTPException(422, "INVALID_HOUSEHOLD_ORDER_PAGE") from None
        except FulfillmentEventUnavailable:
            raise HTTPException(503, "HOUSEHOLD_ORDER_SOURCE_UNAVAILABLE") from None

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
                    limit: int = Query(default=20, ge=1, le=100),
                    after_sequence: int = Query(default=0, ge=0),
                    snapshot_sequence: int | None = Query(default=None, ge=0),
                    principal: Principal = Depends(principal_dependency)):
        try:
            return ledger.read(
                provider, principal, order_ref, limit=limit,
                after_sequence=after_sequence,
                snapshot_sequence=snapshot_sequence,
            )
        except PermissionError:
            raise HTTPException(403, "FULFILLMENT_ASSIGNMENT_FORBIDDEN") from None
        except ValueError:
            raise HTTPException(422, "INVALID_FULFILLMENT_EVENT_PAGE") from None
        except FulfillmentEventUnavailable:
            raise HTTPException(503, "FULFILLMENT_EVENT_LEDGER_UNAVAILABLE") from None

    @router.get("/household-orders/{order_ref}/providers/{provider}/events")
    def read_household_events(
        order_ref: str, provider: str,
        limit: int = Query(default=20, ge=1, le=100),
        after_sequence: int = Query(default=0, ge=0),
        snapshot_sequence: int | None = Query(default=None, ge=0),
        principal: Principal = Depends(principal_dependency),
    ):
        if not callable(household_order_access_authority):
            raise HTTPException(503, "HOUSEHOLD_ORDER_AUTHORITY_UNAVAILABLE")
        try:
            result = ledger.read_for_household(
                provider, principal, order_ref, household_order_access_authority,
                limit=limit, after_sequence=after_sequence,
                snapshot_sequence=snapshot_sequence,
            )
            return {
                "order_ref": result["order_ref"],
                "provider": result["provider"],
                "events": [{
                    "sequence": event["sequence"],
                    "provider_event_code": event["event_code"],
                    "occurred_at": event["occurred_at"],
                    "meaning": "PROVIDER_ASSERTION_ONLY",
                } for event in result["events"]],
                "limit": result["limit"],
                "after_sequence": result["after_sequence"],
                "snapshot_sequence": result["snapshot_sequence"],
                "has_more": result["has_more"],
                "next_after_sequence": result["next_after_sequence"],
            }
        except PermissionError:
            raise HTTPException(404, "FULFILLMENT_EVENTS_NOT_FOUND") from None
        except ValueError:
            raise HTTPException(422, "INVALID_FULFILLMENT_EVENT_PAGE") from None
        except FulfillmentEventUnavailable:
            raise HTTPException(503, "FULFILLMENT_EVENT_LEDGER_UNAVAILABLE") from None

    return router
