"""LOCAL/TEST owner-only list of immutable synthetic Domestic cases.

This is a read-only household self-view, not enrollment, consent, production
records or a cultivation decision. The default runtime does not mount it.
"""
from collections.abc import Callable
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import Principal
from .grant_ledger_sqlite import LedgerIntegrityError, SqliteSyntheticGrantLedger


def build_owned_household_router(
    ledger: SqliteSyntheticGrantLedger,
    verified_principal: Callable[..., Principal],
) -> APIRouter:
    if not isinstance(ledger, SqliteSyntheticGrantLedger):
        raise ValueError("explicit locally persistent case owner ledger required")
    router = APIRouter()

    @router.get("/api/v1/domestic/household-intake/my-drafts")
    def owned_drafts(
        after_ref: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=50),
        p: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            return ledger.list_owned_domestic_drafts(
                p, after_ref=after_ref, limit=limit,
            )
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(
                status_code=503, detail="SYNTHETIC_LEDGER_UNAVAILABLE",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="INVALID_OWNED_CASE_QUERY",
            ) from exc

    return router
