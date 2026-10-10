"""Opt-in, read-only synthetic review history HTTP adapter.

Not mounted in default runtime. Auth comes exclusively from a trusted
Keycloak-verified app dependency; the ledger must additionally authorize
each exact-case read. No response records a Business approval.
"""
from collections.abc import Callable
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import Principal
from .grant_ledger_sqlite import LedgerIntegrityError
from .human_review_sqlite import SqliteSyntheticHumanReviewLedger


def build_technical_review_read_router(
    ledger: SqliteSyntheticHumanReviewLedger,
    verified_principal: Callable[..., Principal],
) -> APIRouter:
    """This router is safe only when mounted with real Keycloak verification.

    Do not use a request-generated Principal or a generic AuthConfig.
    The application factory owns strict opt-in and identity wiring.
    """
    if not isinstance(ledger, SqliteSyntheticHumanReviewLedger):
        raise ValueError("an explicit synthetic human review ledger is required")
    router = APIRouter()

    def lookup(engine: str, ref: str, principal: Principal) -> dict:
        try:
            result = ledger.read_review_for_operator(engine, ref, principal)
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            # No unverified data is returned when the append-only audit or
            # SQLite integrity check fails. Do not expose ledger internals.
            raise HTTPException(status_code=503,
                                detail="TECHNICAL_REVIEW_UNAVAILABLE") from exc
        if result is None:
            # Identical response for unknown case / revoked or absent grant.
            raise HTTPException(status_code=404, detail="DRAFT_NOT_FOUND")
        return result

    def worklist(engine: str, principal: Principal, after_ref: str | None,
                 limit: int) -> dict:
        try:
            return ledger.list_technical_review_worklist(
                engine, principal, after_ref=after_ref, limit=limit
            )
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            # LedgerIntegrityError is a ValueError subclass; catch it first
            # so corrupted audit data never masquerades as client input.
            raise HTTPException(status_code=503,
                                detail="TECHNICAL_REVIEW_UNAVAILABLE") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422,
                                detail="INVALID_WORKLIST_QUERY") from exc

    @router.get("/api/v1/admin/domestic/household-intake/technical-review-worklist")
    def domestic_worklist(
        after_ref: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=50),
        p: Principal = Depends(verified_principal),
    ) -> dict:
        return worklist("DOMESTIC", p, after_ref, limit)

    @router.get("/api/v1/admin/export/research/technical-review-worklist")
    def export_worklist(
        after_ref: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=50),
        p: Principal = Depends(verified_principal),
    ) -> dict:
        return worklist("EXPORT", p, after_ref, limit)

    @router.get("/api/v1/admin/domestic/household-intake/drafts/{ref}/technical-review")
    def domestic_review(ref: str, p: Principal = Depends(verified_principal)) -> dict:
        return lookup("DOMESTIC", ref, p)

    @router.get("/api/v1/admin/export/research/drafts/{ref}/technical-review")
    def export_review(ref: str, p: Principal = Depends(verified_principal)) -> dict:
        return lookup("EXPORT", ref, p)

    return router
