"""Owner-scoped HTTP API for private surplus draft revisions."""
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from .auth import Principal
from .domestic_surplus_drafts import (
    SqliteSyntheticSurplusDraftLedger, SurplusDraftConflict,
    SurplusDraftIntegrityError,
)


def build_domestic_surplus_drafts_router(
    ledger: SqliteSyntheticSurplusDraftLedger,
    verified_principal: Callable[..., Principal],
) -> APIRouter:
    if (not isinstance(ledger, SqliteSyntheticSurplusDraftLedger)
            or not callable(verified_principal)):
        raise ValueError("explicit draft ledger and verified identity required")
    router = APIRouter()
    base = (
        "/api/v1/domestic/household-intake/my-drafts/{household_ref}"
        "/surplus-offers/{offer_ref}"
    )

    def project(record) -> dict[str, Any]:
        return {
            "contract_version": "ronas.domestic.surplus-draft.v1",
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
            "values": (record.values if record.schema_digest == ledger.schema.digest
                       else {}),
            "payload_digest": record.payload_digest,
            "receipt_digest": record.receipt_digest,
            "published": False,
            "real_data": False,
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
        if set(payload) != {"action_id", "expected_revision", "values"}:
            raise HTTPException(422, detail="INVALID_SURPLUS_DRAFT_COMMAND")
        try:
            record = ledger.save(
                principal, household_ref, offer_ref,
                action_id=payload["action_id"],
                expected_revision=payload["expected_revision"],
                values=payload["values"],
            )
        except SurplusDraftConflict as exc:
            raise HTTPException(409, detail="SURPLUS_DRAFT_VERSION_CONFLICT") from exc
        except LookupError as exc:
            raise HTTPException(404, detail="DRAFT_NOT_FOUND") from exc
        except SurplusDraftIntegrityError as exc:
            raise HTTPException(503, detail="DRAFT_INTEGRITY_FAILURE") from exc
        except RuntimeError as exc:
            raise HTTPException(503, detail="DRAFT_AUTHORITY_UNAVAILABLE") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, detail="INVALID_SURPLUS_DRAFT") from exc
        response.status_code = 201 if record.revision == 1 else 200
        return project(record)

    return router
