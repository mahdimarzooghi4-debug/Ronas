"""Opt-in signed read-only view of technical external-authority enquiries.

No public route to request checks, record responses or approve evidence.
"""
from collections.abc import Callable
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from .auth import Principal
from .gate_evidence_authority_enquiry_sqlite import SqliteSyntheticAuthorityEnquiryLedger
from .gate_evidence_handoff_sqlite import HandoffIntegrityError, HandoffNotAuthorized


def build_authority_enquiry_read_router(
    ledger: SqliteSyntheticAuthorityEnquiryLedger,
    verified_principal: Callable[..., Principal],
) -> APIRouter:
    if not isinstance(ledger, SqliteSyntheticAuthorityEnquiryLedger):
        raise ValueError("explicit synthetic authority enquiry ledger required")
    router = APIRouter()

    @router.get("/api/v1/admin/gate-evidence/{domain}/authority-enquiries")
    def read_authority_enquiries(
        domain: str, p: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            return ledger.read_check_status(p, domain)
        except HandoffNotAuthorized as exc:
            raise HTTPException(
                status_code=404, detail="AUTHORITY_ENQUIRY_NOT_FOUND",
            ) from exc
        except (HandoffIntegrityError, sqlite3.DatabaseError) as exc:
            raise HTTPException(
                status_code=503, detail="TECHNICAL_HANDOFF_UNAVAILABLE",
            ) from exc

    return router
