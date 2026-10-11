"""Explicitly opt-in, signed read-only agronomy expert user workspace.

No real identity/professional verification, consent, agronomy advice or
cultivation plan approval. A role by itself confers no case permission.
"""
from collections.abc import Callable
import sqlite3

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from .auth import Principal
from .agronomy_workspace import SyntheticAgronomyWorkspace
from .grant_ledger_sqlite import LedgerIntegrityError
from .expert_review_questions_sqlite import (
    SqliteSyntheticExpertQuestionLedger, ReviewQuestionConflict,
)


class SyntheticQuestionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    track: StrictStr
    expected_case_version: StrictInt
    expected_input_revision: StrictInt
    expected_question_revision: StrictInt
    reason_ref: StrictStr
    evidence_ref: StrictStr


class SyntheticReceiptInspectionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    expected_case_version: StrictInt
    expected_input_revision: StrictInt
    expected_question_revision: StrictInt


def build_agronomy_workspace_router(
    workspace: SyntheticAgronomyWorkspace,
    verified_principal: Callable[..., Principal],
) -> APIRouter:
    if not isinstance(workspace, SyntheticAgronomyWorkspace):
        raise ValueError("explicit agronomy workspace required")
    router = APIRouter()


    # Explicit opt-in ONLY. No POST route on the existing/default workspace.
    if isinstance(workspace.ledger, SqliteSyntheticExpertQuestionLedger):

        @router.get(
            "/api/v1/agronomy/assigned-drafts/{ref}/review-evidence-index",
        )
        def assigned_evidence_index(
            ref: str, p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                result = workspace.read_assigned_synthetic_evidence_index(ref, p)
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result

        @router.get("/api/v1/agronomy/assigned-drafts/{ref}/review-questions")
        def assigned_review_questions(
            ref: str, p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                result = workspace.read_assigned_synthetic_review_questions(ref, p)
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result

        @router.post(
            "/api/v1/agronomy/assigned-drafts/{ref}/review-questions",
            status_code=201,
        )
        def record_review_question(
            ref: str, command: SyntheticQuestionCommand,
            authorization: str | None = Header(default=None),
            p: Principal = Depends(verified_principal),
        ) -> dict:
            # No ambient browser-cookie mutation, no scientific approval.
            if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
                raise HTTPException(401, detail="BEARER_REQUIRED_FOR_MUTATION")
            try:
                result = workspace.record_assigned_synthetic_review_question(
                    ref, p,
                    action_id=command.action_id,
                    track=command.track,
                    expected_case_version=command.expected_case_version,
                    expected_input_revision=command.expected_input_revision,
                    expected_question_revision=command.expected_question_revision,
                    reason_ref=command.reason_ref,
                    evidence_ref=command.evidence_ref,
                )
            except ReviewQuestionConflict as exc:
                raise HTTPException(
                    409, detail="SYNTHETIC_QUESTION_VERSION_CONFLICT",
                ) from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            except ValueError as exc:
                raise HTTPException(
                    422, detail="INVALID_SYNTHETIC_REVIEW_QUESTION",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result

        @router.post(
            "/api/v1/agronomy/assigned-drafts/{ref}/response-receipt-inspections",
            status_code=201,
        )
        def inspect_assigned_response_receipt(
            ref: str, command: SyntheticReceiptInspectionCommand,
            authorization: str | None = Header(default=None),
            p: Principal = Depends(verified_principal),
        ) -> dict:
            if (not isinstance(authorization, str)
                    or not authorization.startswith("Bearer ")):
                raise HTTPException(401, detail="BEARER_REQUIRED_FOR_MUTATION")
            try:
                result = workspace.inspect_assigned_synthetic_response_receipt(
                    ref, p, action_id=command.action_id,
                    expected_case_version=command.expected_case_version,
                    expected_input_revision=command.expected_input_revision,
                    expected_question_revision=command.expected_question_revision,
                )
            except ReviewQuestionConflict as exc:
                raise HTTPException(
                    409, detail="SYNTHETIC_RECEIPT_CONTEXT_CHANGED",
                ) from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            except ValueError as exc:
                raise HTTPException(
                    422, detail="INVALID_SYNTHETIC_RECEIPT_INSPECTION",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result

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

    @router.get("/api/v1/agronomy/assigned-drafts/{ref}/expert-review-preparation")
    def assigned_expert_review_preparation(
        ref: str, p: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            data = workspace.read_assigned_expert_review_preparation(ref, p)
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(
                status_code=503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
            ) from exc
        if data is None:
            raise HTTPException(status_code=404, detail="DRAFT_NOT_FOUND")
        return data

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
