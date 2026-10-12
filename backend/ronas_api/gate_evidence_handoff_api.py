"""Optional read-only technical handoff summary; no public evidence upload."""
from collections.abc import Callable
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from .auth import Principal
from .gate_evidence_handoff_sqlite import (
    HandoffIntegrityError, HandoffNotAuthorized,
    SqliteSyntheticGateEvidenceHandoff,
)


def build_gate_handoff_read_router(
    ledger: SqliteSyntheticGateEvidenceHandoff,
    verified_principal: Callable[..., Principal],
) -> APIRouter:
    if not isinstance(ledger, SqliteSyntheticGateEvidenceHandoff):
        raise ValueError("explicit synthetic gate evidence ledger required")
    router = APIRouter()

    @router.get("/api/v1/admin/gate-evidence/{domain}/technical-handoff")
    def read_handoff(
        domain: str, p: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            return ledger.worklist(p, domain)
        except HandoffNotAuthorized as exc:
            # Same result for unknown/unassigned domain. An admin signed role
            # is NOT permission to approve any evidence or the gate.
            raise HTTPException(
                status_code=404, detail="GATE_HANDOFF_NOT_FOUND",
            ) from exc
        except (HandoffIntegrityError, sqlite3.DatabaseError) as exc:
            raise HTTPException(
                status_code=503, detail="TECHNICAL_HANDOFF_UNAVAILABLE",
            ) from exc

    @router.get("/api/v1/admin/gate-evidence/{domain}/admission-preflight")
    def read_admission_preflight(
        domain: str, p: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            return ledger.preflight_worklist(p, domain)
        except HandoffNotAuthorized as exc:
            raise HTTPException(
                status_code=404, detail="GATE_PREFLIGHT_NOT_FOUND",
            ) from exc
        except (HandoffIntegrityError, sqlite3.DatabaseError) as exc:
            raise HTTPException(
                status_code=503, detail="TECHNICAL_HANDOFF_UNAVAILABLE",
            ) from exc

    return router
