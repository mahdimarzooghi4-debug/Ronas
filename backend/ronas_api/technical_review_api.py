"""Opt-in, read-only synthetic review history HTTP adapter.

Not mounted in default runtime. Auth comes exclusively from a trusted
Keycloak-verified app dependency; the ledger must additionally authorize
each exact-case read. No response records a Business approval.
"""
from collections.abc import Callable
import sqlite3

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from .auth import Principal
from .grant_ledger_sqlite import LedgerIntegrityError
from .human_review_sqlite import SqliteSyntheticHumanReviewLedger
from .export_research_question import ExportResearchQuestionConflict


class SyntheticExportQuestionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    expected_case_version: StrictInt
    expected_question_revision: StrictInt
    product_ref: StrictStr
    destination_ref: StrictStr


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

    @router.get("/api/v1/admin/export/research/cases")
    def export_research_cases(
        technical_state: str = Query(default="ALL"),
        after_ref: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=50),
        p: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            return ledger.list_export_research_cases(
                p, technical_state=technical_state, after_ref=after_ref,
                limit=limit,
            )
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(
                status_code=503, detail="TECHNICAL_REVIEW_UNAVAILABLE",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="INVALID_EXPORT_RESEARCH_QUEUE",
            ) from exc

    @router.get("/api/v1/admin/export/research/drafts/{ref}/technical-review")
    def export_review(ref: str, p: Principal = Depends(verified_principal)) -> dict:
        return lookup("EXPORT", ref, p)

    @router.get("/api/v1/admin/export/research/drafts/{ref}/versions")
    def export_research_versions(
        ref: str, p: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            result = ledger.read_export_research_version_history(ref, p)
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(
                status_code=503, detail="TECHNICAL_REVIEW_UNAVAILABLE",
            ) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="DRAFT_NOT_FOUND")
        return result

    @router.get("/api/v1/admin/export/research/drafts/{ref}/workspace")
    def export_research_workspace(
        ref: str, p: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            result = ledger.read_export_research_workspace(ref, p)
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(
                status_code=503, detail="TECHNICAL_REVIEW_UNAVAILABLE",
            ) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="DRAFT_NOT_FOUND")
        return result

    @router.post(
        "/api/v1/admin/export/research/drafts/{ref}/local-test-question",
        status_code=201,
    )
    def record_export_local_question(
        ref: str, command: SyntheticExportQuestionCommand,
        authorization: str | None = Header(default=None),
        p: Principal = Depends(verified_principal),
    ) -> dict:
        # Mutating demo endpoints explicitly demand signed Bearer auth.
        # Session-cookie-only browser POST is forbidden (no CSRF bypass).
        if (not isinstance(authorization, str)
                or not authorization.startswith("Bearer ")):
            raise HTTPException(401, detail="BEARER_REQUIRED")
        try:
            result = ledger.record_export_research_question(
                ref, p,
                expected_case_version=command.expected_case_version,
                expected_question_revision=command.expected_question_revision,
                action_id=command.action_id,
                product_ref=command.product_ref,
                destination_ref=command.destination_ref,
            )
        except ExportResearchQuestionConflict as exc:
            raise HTTPException(
                409, detail="EXPORT_LOCAL_QUESTION_CHANGED",
            ) from exc
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(
                503, detail="TECHNICAL_REVIEW_UNAVAILABLE",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                422, detail="INVALID_EXPORT_LOCAL_QUESTION",
            ) from exc
        if result is None:
            raise HTTPException(404, detail="DRAFT_NOT_FOUND")
        return result

    return router
