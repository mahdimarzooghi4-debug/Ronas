"""Explicitly opt-in, signed read-only agronomy expert user workspace.

No real identity/professional verification, consent, agronomy advice or
cultivation plan approval. A role by itself confers no case permission.
"""
from collections.abc import Callable
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import Principal
from .agronomy_workspace import SyntheticAgronomyWorkspace
from .grant_ledger_sqlite import LedgerIntegrityError


def build_agronomy_workspace_router(
    workspace: SyntheticAgronomyWorkspace,
    verified_principal: Callable[..., Principal],
) -> APIRouter:
    if not isinstance(workspace, SyntheticAgronomyWorkspace):
        raise ValueError("explicit agronomy workspace required")
    router = APIRouter()

    @router.get("/api/v1/agronomy/assigned-drafts")
    def assigned_cases(
        after_ref: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=50),
        technical_state: str = Query(default="ALL"),
        p: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            return workspace.list_assigned_cases(
                p, after_ref=after_ref, limit=limit,
                technical_state=technical_state,
            )
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(
                status_code=503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="INVALID_ASSIGNED_CASE_QUERY",
            ) from exc

    @router.get("/api/v1/agronomy/assigned-drafts/{ref}/internal-plan-proposal")
    def assigned_internal_proposal(
        ref: str, p: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            data = workspace.read_assigned_proposal_structure(ref, p)
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(
                status_code=503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
            ) from exc
        if data is None:
            raise HTTPException(status_code=404, detail="DRAFT_NOT_FOUND")
        return data

    @router.get("/api/v1/agronomy/assigned-drafts/{ref}")
    def assigned_case(
        ref: str, p: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            data = workspace.read_assigned_case(ref, p)
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(
                status_code=503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
            ) from exc
        if data is None:
            raise HTTPException(status_code=404, detail="DRAFT_NOT_FOUND")
        return data

    return router
