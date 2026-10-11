"""Opt-in synthetic household-owned manifest version history and correction.

The only admitted write accepts a local synthetic SHA-shaped manifest key.
It cannot receive cultivation information, personal details or legal consent.
Keycloak Bearer access (not ambient session cookies) is required to mutate.
"""
from collections.abc import Callable
import sqlite3

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from .auth import Principal
from .grant_ledger_sqlite import LedgerIntegrityError
from .household_input_ledger_sqlite import (
    InputRevisionConflict, SqliteSyntheticHouseholdInputLedger,
)
from .expert_review_questions_sqlite import (
    SqliteSyntheticExpertQuestionLedger, ReviewQuestionConflict,
)


class SyntheticManifestCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    expected_case_version: StrictInt
    expected_input_revision: StrictInt
    synthetic_manifest_digest: StrictStr


class SyntheticHouseholdQuestionReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    track: StrictStr
    expected_case_version: StrictInt
    expected_input_revision: StrictInt
    expected_question_revision: StrictInt
    answer_ref: StrictStr
    evidence_ref: StrictStr


def build_household_input_router(
    ledger: SqliteSyntheticHouseholdInputLedger,
    verified_principal: Callable[..., Principal],
) -> APIRouter:
    if not isinstance(ledger, SqliteSyntheticHouseholdInputLedger):
        raise ValueError("explicit local synthetic input ledger required")
    router = APIRouter()

    @router.get("/api/v1/domestic/household-intake/my-drafts/{ref}/input-revisions")
    def own_input_revisions(
        ref: str, p: Principal = Depends(verified_principal),
    ) -> dict:
        try:
            result = ledger.read_owned_input_revisions(ref, p)
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(
                503, detail="SYNTHETIC_INPUT_HISTORY_UNAVAILABLE",
            ) from exc
        if result is None:
            raise HTTPException(404, detail="DRAFT_NOT_FOUND")
        return result

    @router.post("/api/v1/domestic/household-intake/my-drafts/{ref}/input-revisions",
                 status_code=201)
    def append_synthetic_manifest(
        ref: str, data: SyntheticManifestCorrection,
        authorization: str | None = Header(default=None),
        p: Principal = Depends(verified_principal),
    ) -> dict:
        # Cookie-only browser session must never be a mutating credential.
        # Verified principal dependency checks the actual Bearer signature.
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            raise HTTPException(401, detail="BEARER_REQUIRED_FOR_MUTATION")
        try:
            result = ledger.append_owned_input_manifest(
                ref, p, action_id=data.action_id,
                expected_case_version=data.expected_case_version,
                expected_input_revision=data.expected_input_revision,
                synthetic_manifest_digest=data.synthetic_manifest_digest,
            )
        except InputRevisionConflict as exc:
            raise HTTPException(409, detail="SYNTHETIC_INPUT_VERSION_CONFLICT") from exc
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(
                503, detail="SYNTHETIC_INPUT_HISTORY_UNAVAILABLE",
            ) from exc
        except ValueError as exc:
            raise HTTPException(422, detail="INVALID_SYNTHETIC_INPUT_REVISION") from exc
        if result is None:
            raise HTTPException(404, detail="DRAFT_NOT_FOUND")
        return result

    if isinstance(ledger, SqliteSyntheticExpertQuestionLedger):
        @router.get(
            "/api/v1/domestic/household-intake/my-drafts/{ref}/question-responses"
        )
        def own_household_question_responses(
            ref: str, p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                result = ledger.read_owned_question_responses(ref, p)
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_QUESTION_RESPONSE_UNAVAILABLE",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result

        @router.post(
            "/api/v1/domestic/household-intake/my-drafts/{ref}/question-responses",
            status_code=201,
        )
        def append_household_question_response(
            ref: str, command: SyntheticHouseholdQuestionReply,
            authorization: str | None = Header(default=None),
            p: Principal = Depends(verified_principal),
        ) -> dict:
            if (not isinstance(authorization, str)
                    or not authorization.startswith("Bearer ")):
                raise HTTPException(401, detail="BEARER_REQUIRED_FOR_MUTATION")
            try:
                result = ledger.append_owned_question_response(
                    ref, p, action_id=command.action_id,
                    track=command.track,
                    expected_question_revision=command.expected_question_revision,
                    expected_case_version=command.expected_case_version,
                    expected_input_revision=command.expected_input_revision,
                    answer_ref=command.answer_ref,
                    evidence_ref=command.evidence_ref,
                )
            except ReviewQuestionConflict as exc:
                raise HTTPException(
                    409, detail="SYNTHETIC_RESPONSE_VERSION_CONFLICT",
                ) from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_QUESTION_RESPONSE_UNAVAILABLE",
                ) from exc
            except ValueError as exc:
                raise HTTPException(
                    422, detail="INVALID_SYNTHETIC_RESPONSE",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result

    return router
