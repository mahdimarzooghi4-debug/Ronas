"""Explicitly opt-in, signed read-only agronomy expert user workspace.

No real identity/professional verification, consent, agronomy advice or
cultivation plan approval. A role by itself confers no case permission.
"""
from collections.abc import Callable
import sqlite3

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from .auth import Principal
from .agronomy_workspace import SyntheticAgronomyWorkspace
from .household_input_profiles import SqliteSyntheticHouseholdProfileLedger
from .domestic_stage_observation import CurrentStageContext, StageObservationConflict
from .stage_observation_artifacts import StageArtifactStore, StageArtifactStoreError
from .grant_ledger_sqlite import LedgerIntegrityError
from .expert_review_questions_sqlite import (
    SqliteSyntheticExpertQuestionLedger, ReviewQuestionConflict,
)
from .internal_expert_evidence_comparison import EvidenceRevisionConflict
from .internal_specialist_scope_change_impact import SpecialistEvidenceRevisionConflict
from .internal_specialist_review_context import SyntheticContextFingerprintConflict


class SyntheticQuestionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    track: StrictStr
    expected_case_version: StrictInt
    expected_input_revision: StrictInt
    expected_question_revision: StrictInt
    reason_ref: StrictStr
    evidence_ref: StrictStr
    stage_ref: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    expected_stage_observation_revision: StrictInt | None = Field(
        default=None, ge=1,
    )
    expected_stage_observation_receipt_digest: StrictStr | None = Field(
        default=None, min_length=64, max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class SyntheticReceiptInspectionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    expected_case_version: StrictInt
    expected_input_revision: StrictInt
    expected_question_revision: StrictInt


class SyntheticStageReceiptInspectionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr = Field(min_length=1, max_length=96)
    expected_case_version: StrictInt = Field(ge=1)
    stage_ref: StrictStr = Field(min_length=1, max_length=64)
    expected_observation_revision: StrictInt = Field(ge=1)
    expected_observation_receipt_digest: StrictStr = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$",
    )


def build_agronomy_workspace_router(
    workspace: SyntheticAgronomyWorkspace,
    verified_principal: Callable[..., Principal],
    *,
    stage_context_authority: Callable[[str], CurrentStageContext | None] | None = None,
    stage_artifact_store: StageArtifactStore | None = None,
) -> APIRouter:
    if not isinstance(workspace, SyntheticAgronomyWorkspace):
        raise ValueError("explicit agronomy workspace required")
    if stage_context_authority is not None and not callable(stage_context_authority):
        raise ValueError("callable current stage context authority required")
    if stage_artifact_store is not None and (
            stage_context_authority is None
            or not all(callable(getattr(stage_artifact_store, name, None))
                       for name in ("get", "put", "contains"))):
        raise ValueError("stage artifact adapter requires current context authority")
    router = APIRouter()

    if stage_context_authority is not None:
        @router.get("/api/v1/agronomy/assigned-drafts/{ref}/stage-observations")
        def assigned_stage_observations(
            ref: str, p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                result = workspace.read_assigned_stage_observations(
                    ref, p, context_authority=stage_context_authority,
                )
            except StageObservationConflict as exc:
                raise HTTPException(
                    409, detail="STAGE_OBSERVATION_CONTEXT_CHANGED",
                ) from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result

        if isinstance(workspace.ledger, SqliteSyntheticHouseholdProfileLedger):
            @router.post(
                "/api/v1/agronomy/assigned-drafts/{ref}/stage-observations/"
                "inspections",
                status_code=201,
            )
            def inspect_assigned_stage_receipt(
                ref: str, command: SyntheticStageReceiptInspectionCommand,
                authorization: str | None = Header(default=None),
                p: Principal = Depends(verified_principal),
            ) -> dict:
                if (not isinstance(authorization, str)
                        or not authorization.startswith("Bearer ")):
                    raise HTTPException(
                        401, detail="BEARER_REQUIRED_FOR_MUTATION",
                    )
                try:
                    result = workspace.inspect_assigned_stage_receipt(
                        ref, p, action_id=command.action_id,
                        expected_case_version=command.expected_case_version,
                        stage_ref=command.stage_ref,
                        expected_observation_revision=(
                            command.expected_observation_revision
                        ),
                        expected_observation_receipt_digest=(
                            command.expected_observation_receipt_digest
                        ),
                    )
                except ReviewQuestionConflict as exc:
                    raise HTTPException(
                        409, detail="STAGE_RECEIPT_CONTEXT_CHANGED",
                    ) from exc
                except (LedgerIntegrityError, sqlite3.Error) as exc:
                    raise HTTPException(
                        503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                    ) from exc
                except ValueError as exc:
                    raise HTTPException(
                        422, detail="INVALID_STAGE_RECEIPT_INSPECTION",
                    ) from exc
                if result is None:
                    raise HTTPException(404, detail="DRAFT_NOT_FOUND")
                return result

    if stage_artifact_store is not None:
        @router.get(
            "/api/v1/agronomy/assigned-drafts/{ref}/stage-observations/"
            "artifacts/{stage_ref}/{digest}",
        )
        def assigned_stage_artifact(
            ref: str, stage_ref: str, digest: str,
            p: Principal = Depends(verified_principal),
        ) -> Response:
            try:
                stored = workspace.read_assigned_stage_artifact(
                    ref, stage_ref, digest, p, store=stage_artifact_store,
                )
            except StageArtifactStoreError as exc:
                raise HTTPException(
                    503, detail="STAGE_ARTIFACT_STORE_UNAVAILABLE",
                ) from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if stored is None:
                raise HTTPException(404, detail="STAGE_ARTIFACT_NOT_FOUND")
            artifact, content = stored
            return Response(
                content=content, media_type=artifact.content_type,
                headers={
                    "Content-Disposition": 'attachment; filename="stage-observation"',
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )


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


        @router.get(
            "/api/v1/agronomy/assigned-drafts/{ref}/provenance-dossier",
        )
        def assigned_provenance_dossier(
            ref: str, p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                result = workspace.read_assigned_synthetic_provenance_dossier(ref, p)
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result


        @router.get(
            "/api/v1/agronomy/assigned-drafts/{ref}/historical-binding-drift",
        )
        def assigned_historical_binding_drift(
            ref: str, p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                result = workspace.read_assigned_synthetic_historical_binding_drift(
                    ref, p,
                )
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result


        @router.get(
            "/api/v1/agronomy/assigned-drafts/{ref}/review-handoff-fingerprint",
        )
        def assigned_review_handoff_fingerprint(
            ref: str, p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                result = workspace.read_assigned_synthetic_review_handoff_fingerprint(
                    ref, p,
                )
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result


        @router.get(
            "/api/v1/agronomy/assigned-drafts/{ref}/review-evidence-timeline",
        )
        def assigned_evidence_timeline(
            ref: str, p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                result = workspace.read_assigned_synthetic_evidence_timeline(ref, p)
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result

        @router.get(
            "/api/v1/agronomy/assigned-drafts/{ref}/review-evidence-compare",
        )
        def assigned_evidence_comparison(
            ref: str,
            from_revision: int = Query(ge=1),
            to_revision: int = Query(ge=1),
            p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                result = workspace.compare_assigned_synthetic_evidence_revisions(
                    ref, p, from_revision=from_revision, to_revision=to_revision,
                )
            except EvidenceRevisionConflict as exc:
                raise HTTPException(
                    409, detail="SYNTHETIC_EVIDENCE_REVISION_CONFLICT",
                ) from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result


        @router.get(
            "/api/v1/agronomy/assigned-drafts/{ref}/specialist-scope-evidence",
        )
        def assigned_specialist_scope_evidence(
            ref: str, p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                result = workspace.read_assigned_specialist_scope_evidence(ref, p)
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result


        @router.get(
            "/api/v1/agronomy/assigned-drafts/{ref}/specialist-scope-change-impact",
        )
        def assigned_specialist_scope_change_impact(
            ref: str, observed_revision: int = Query(ge=0),
            p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                result = workspace.compare_assigned_specialist_scope_evidence(
                    ref, p, observed_revision=observed_revision,
                )
            except SpecialistEvidenceRevisionConflict as exc:
                raise HTTPException(
                    409, detail="SYNTHETIC_SPECIALIST_EVIDENCE_REVISION_CONFLICT",
                ) from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result


        @router.get(
            "/api/v1/agronomy/assigned-drafts/{ref}/review-context-impact",
        )
        def assigned_review_context_impact(
            ref: str,
            observed_specialist_revision: int = Query(ge=0),
            expected_context_fingerprint: str | None = Query(
                default=None, min_length=64, max_length=64,
                pattern=r"^[0-9a-f]{64}$",
            ),
            p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                result = workspace.read_assigned_synthetic_review_context_impact(
                    ref, p,
                    observed_specialist_revision=observed_specialist_revision,
                    expected_context_fingerprint=expected_context_fingerprint,
                )
            except SyntheticContextFingerprintConflict as exc:
                raise HTTPException(
                    409, detail="SYNTHETIC_REVIEW_CONTEXT_CHANGED",
                ) from exc
            except SpecialistEvidenceRevisionConflict as exc:
                raise HTTPException(
                    409, detail="SYNTHETIC_SPECIALIST_EVIDENCE_REVISION_CONFLICT",
                ) from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result

        @router.get(
            "/api/v1/agronomy/assigned-drafts/{ref}/review-context-versioned",
        )
        def assigned_review_context_versioned(
            ref: str,
            observed_specialist_revision: int = Query(ge=0),
            expected_context_fingerprint: str | None = Query(
                default=None,min_length=64,max_length=64,
                pattern=r"^[0-9a-f]{64}$",
            ),
            p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                result=workspace.read_assigned_synthetic_review_context_impact(
                    ref,p,observed_specialist_revision=observed_specialist_revision,
                    expected_context_fingerprint=expected_context_fingerprint,
                    require_versioned_authorities=True,
                )
            except SyntheticContextFingerprintConflict as exc:
                raise HTTPException(
                    409,detail="SYNTHETIC_REVIEW_CONTEXT_CHANGED"
                ) from exc
            except SpecialistEvidenceRevisionConflict as exc:
                raise HTTPException(
                    409,detail="SYNTHETIC_SPECIALIST_EVIDENCE_REVISION_CONFLICT"
                ) from exc
            except (LedgerIntegrityError,sqlite3.Error) as exc:
                raise HTTPException(
                    503,detail="SYNTHETIC_AGRONOMY_UNAVAILABLE"
                ) from exc
            if result is None:
                raise HTTPException(404,detail="DRAFT_NOT_FOUND")
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
                    stage_context_authority=stage_context_authority,
                    stage_ref=command.stage_ref,
                    expected_stage_observation_revision=(
                        command.expected_stage_observation_revision
                    ),
                    expected_stage_observation_receipt_digest=(
                        command.expected_stage_observation_receipt_digest
                    ),
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
