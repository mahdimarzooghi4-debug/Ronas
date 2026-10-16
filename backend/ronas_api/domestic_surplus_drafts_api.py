"""Owner-scoped HTTP API for private surplus draft revisions."""
import sqlite3
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from .auth import Principal
from .domestic_surplus_drafts import (
    SurplusDraftLedger, SurplusDraftConflict,
    SurplusDraftIntegrityError, SurplusDraftStorageError,
    is_surplus_draft_ledger,
)


def _revision_diff(current: Any, previous: Any | None, active_schema_digest: str) -> dict[str, Any]:
    """Return only same-schema value changes; never interpret legacy fields."""
    if current.schema_digest != active_schema_digest:
        return {"diff_available": False, "changes": []}
    if previous is not None and previous.schema_digest != active_schema_digest:
        return {"diff_available": False, "changes": []}
    before = {} if previous is None else previous.values
    changes = [
        {
            "field": field,
            "before": before.get(field),
            "after": current.values.get(field),
        }
        for field in sorted(set(before) | set(current.values))
        if before.get(field) != current.values.get(field)
    ]
    return {"diff_available": True, "changes": changes}


def build_domestic_surplus_drafts_router(
    ledger: SurplusDraftLedger,
    verified_principal: Callable[..., Principal],
    input_revision_reader: Callable[[str, Principal], dict | None] | None = None,
) -> APIRouter:
    if (not is_surplus_draft_ledger(ledger)
            or not callable(verified_principal)
            or input_revision_reader is not None
            and not callable(input_revision_reader)):
        raise ValueError("explicit draft ledger and verified identity required")
    router = APIRouter()
    base = (
        "/api/v1/domestic/household-intake/my-drafts/{household_ref}"
        "/surplus-offers/{offer_ref}"
    )

    def project(record) -> dict[str, Any]:
        return {
            "contract_version": "ronas.domestic.surplus-draft.v2",
            "household_ref": record.household_ref,
            "offer_ref": record.offer_ref,
            "schema_ref": record.schema_ref,
            "schema_version": record.schema_version,
            "schema_digest": record.schema_digest,
            "active_schema_ref": ledger.schema.schema_ref,
            "active_schema_version": ledger.schema.version,
            "active_schema_digest": ledger.schema.digest,
            "schema_changed": record.schema_digest != ledger.schema.digest,
            "revision": record.revision,
            "input_revision": record.input_revision,
            "values": (record.values if record.schema_digest == ledger.schema.digest
                       else {}),
            "payload_digest": record.payload_digest,
            "receipt_digest": record.receipt_digest,
            "published": False,
            "real_data": False,
        }

    collection = (
        "/api/v1/domestic/household-intake/my-drafts/{household_ref}"
        "/surplus-offers"
    )

    @router.get(collection)
    def list_drafts(
        household_ref: str,
        principal: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            records = ledger.list_owned(principal, household_ref)
        except LookupError as exc:
            raise HTTPException(404, detail="DRAFT_NOT_FOUND") from exc
        except SurplusDraftIntegrityError as exc:
            raise HTTPException(503, detail="DRAFT_INTEGRITY_FAILURE") from exc
        except SurplusDraftStorageError as exc:
            raise HTTPException(503, detail="DRAFT_STORAGE_UNAVAILABLE") from exc
        except RuntimeError as exc:
            raise HTTPException(503, detail="DRAFT_AUTHORITY_UNAVAILABLE") from exc
        except sqlite3.Error as exc:
            raise HTTPException(503, detail="DRAFT_STORAGE_UNAVAILABLE") from exc
        return {
            "contract_version": "ronas.domestic.surplus-draft-list.v2",
            "household_ref": household_ref,
            "offers": [
                {
                    "offer_ref": record.offer_ref,
                    "schema_ref": record.schema_ref,
                    "schema_version": record.schema_version,
                    "schema_digest": record.schema_digest,
                    "active_schema_ref": ledger.schema.schema_ref,
                    "active_schema_version": ledger.schema.version,
                    "active_schema_digest": ledger.schema.digest,
                    "schema_changed": record.schema_digest != ledger.schema.digest,
                    "revision": record.revision,
                    "input_revision": record.input_revision,
                    "published": False,
                    "real_data": False,
                }
                for record in records
            ],
        }

    @router.get(base + "/revisions")
    def read_draft_history(
        household_ref: str,
        offer_ref: str,
        principal: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            records = ledger.history_owned(principal, household_ref, offer_ref)
        except LookupError as exc:
            raise HTTPException(404, detail="DRAFT_NOT_FOUND") from exc
        except SurplusDraftIntegrityError as exc:
            raise HTTPException(503, detail="DRAFT_INTEGRITY_FAILURE") from exc
        except SurplusDraftStorageError as exc:
            raise HTTPException(503, detail="DRAFT_STORAGE_UNAVAILABLE") from exc
        except RuntimeError as exc:
            raise HTTPException(503, detail="DRAFT_AUTHORITY_UNAVAILABLE") from exc
        except sqlite3.Error as exc:
            raise HTTPException(503, detail="DRAFT_STORAGE_UNAVAILABLE") from exc
        return {
            "contract_version": "ronas.domestic.surplus-draft-history.v3",
            "household_ref": household_ref,
            "offer_ref": offer_ref,
            "revisions": [
                {
                    "schema_ref": record.schema_ref,
                    "schema_version": record.schema_version,
                    "schema_digest": record.schema_digest,
                    "schema_changed": record.schema_digest != ledger.schema.digest,
                    "revision": record.revision,
                    "input_revision": record.input_revision,
                    "values": (record.values
                               if record.schema_digest == ledger.schema.digest else {}),
                    **_revision_diff(
                        record, records[index - 1] if index else None,
                        ledger.schema.digest,
                    ),
                    "payload_digest": record.payload_digest,
                    "receipt_digest": record.receipt_digest,
                    "published": False,
                    "real_data": False,
                }
                for index, record in enumerate(records)
            ],
        }

    @router.get(base)
    def read_draft(
        household_ref: str,
        offer_ref: str,
        principal: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            return project(ledger.read_owned(principal, household_ref, offer_ref))
        except LookupError as exc:
            raise HTTPException(404, detail="DRAFT_NOT_FOUND") from exc
        except SurplusDraftIntegrityError as exc:
            raise HTTPException(503, detail="DRAFT_INTEGRITY_FAILURE") from exc
        except SurplusDraftStorageError as exc:
            raise HTTPException(503, detail="DRAFT_STORAGE_UNAVAILABLE") from exc
        except RuntimeError as exc:
            raise HTTPException(503, detail="DRAFT_AUTHORITY_UNAVAILABLE") from exc

    @router.put(base)
    def save_draft(
        household_ref: str,
        offer_ref: str,
        request: Request,
        response: Response,
        payload: dict = Body(...),
        principal: Principal = Depends(verified_principal),
    ) -> dict:
        if not request.headers.get("authorization", "").startswith("Bearer "):
            raise HTTPException(401, detail="BEARER_TOKEN_REQUIRED")
        required = {"action_id", "expected_revision", "values"}
        allowed = required | {"input_revision"}
        if not required.issubset(payload) or not set(payload).issubset(allowed):
            raise HTTPException(422, detail="INVALID_SURPLUS_DRAFT_COMMAND")
        if input_revision_reader is not None:
            try:
                input_state = input_revision_reader(household_ref, principal)
            except Exception as exc:
                raise HTTPException(
                    503, detail="HOUSEHOLD_INPUT_HISTORY_UNAVAILABLE",
                ) from exc
            if input_state is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            current_input_revision = input_state["current_input_revision"]
            if payload.get("input_revision") != current_input_revision:
                raise HTTPException(
                    409, detail="HOUSEHOLD_INPUT_REVISION_CHANGED",
                )
        try:
            record = ledger.save(
                principal, household_ref, offer_ref,
                action_id=payload["action_id"],
                expected_revision=payload["expected_revision"],
                values=payload["values"],
                input_revision=payload.get("input_revision"),
            )
        except SurplusDraftConflict as exc:
            raise HTTPException(409, detail="SURPLUS_DRAFT_VERSION_CONFLICT") from exc
        except LookupError as exc:
            raise HTTPException(404, detail="DRAFT_NOT_FOUND") from exc
        except SurplusDraftIntegrityError as exc:
            raise HTTPException(503, detail="DRAFT_INTEGRITY_FAILURE") from exc
        except SurplusDraftStorageError as exc:
            raise HTTPException(503, detail="DRAFT_STORAGE_UNAVAILABLE") from exc
        except RuntimeError as exc:
            raise HTTPException(503, detail="DRAFT_AUTHORITY_UNAVAILABLE") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, detail="INVALID_SURPLUS_DRAFT") from exc
        response.status_code = 201 if record.revision == 1 else 200
        return project(record)

    return router
