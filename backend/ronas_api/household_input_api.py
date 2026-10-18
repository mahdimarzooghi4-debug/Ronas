"""Opt-in synthetic household-owned manifest version history and correction.

The only admitted write accepts a local synthetic SHA-shaped manifest key.
It cannot receive cultivation information, personal details or legal consent.
Keycloak Bearer access (not ambient session cookies) is required to mutate.
"""
from collections.abc import Callable
import re
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from .auth import Principal
from .domestic_stage_observation import (
    CurrentStageContext, StageObservationCommand, StageObservationConflict,
)
from .grant_ledger_sqlite import LedgerIntegrityError
from .household_input_ledger_sqlite import (
    InputRevisionConflict, SqliteSyntheticHouseholdInputLedger,
)
from .expert_review_questions_sqlite import (
    SqliteSyntheticExpertQuestionLedger, ReviewQuestionConflict,
)
from .household_input_profiles import (
    HouseholdInputSchema, SqliteSyntheticHouseholdProfileLedger,
)
from .stage_observation_artifacts import (
    MAX_ARTIFACT_BYTES, StageArtifactStore, StageArtifactStoreError,
    _check_upload_size, _declared_upload_size,
)
from .postgres_household_progress_notes import PostgresHouseholdProgressNoteLedger

HouseholdProfileKey = Annotated[StrictStr, Field(max_length=32)]
HouseholdProfileValue = Annotated[StrictStr, Field(max_length=300)]


class SyntheticManifestCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    expected_case_version: StrictInt
    expected_input_revision: StrictInt
    synthetic_manifest_digest: StrictStr


class SyntheticProgressNote(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    expected_case_version: StrictInt
    expected_revision: StrictInt
    expected_input_revision: StrictInt
    corrects_revision: StrictInt = 0
    reported_at: StrictStr
    note: StrictStr



class HouseholdStageObservationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr = Field(min_length=1, max_length=96)
    expected_observation_revision: StrictInt
    corrects_revision: StrictInt = 0
    expected_case_version: StrictInt
    expected_input_revision: StrictInt
    expected_input_snapshot_digest: StrictStr = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$",
    )
    expected_plan_digest: StrictStr = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$",
    )
    stage_ref: StrictStr = Field(min_length=1, max_length=64)
    expected_observation_requirements_digest: StrictStr = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$",
    )
    observed_at: StrictStr = Field(min_length=1, max_length=40)
    observation_artifact_digest: StrictStr = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$",
    )


class HouseholdProfileCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    expected_case_version: StrictInt
    expected_revision: StrictInt
    # Bound key count and size at parsing time; schema validation comes later.
    values: dict[HouseholdProfileKey, HouseholdProfileValue] = Field(max_length=6)


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
    profile_schema: HouseholdInputSchema | None = None,
    profile_access_authority: Callable[[Principal, str, str], bool] | None = None,
    stage_context_authority: Callable[[str], CurrentStageContext | None] | None = None,
    stage_artifact_store: StageArtifactStore | None = None,
    progress_note_ledger: PostgresHouseholdProgressNoteLedger | None = None,
) -> APIRouter:
    if not isinstance(ledger, SqliteSyntheticHouseholdInputLedger):
        raise ValueError("explicit local synthetic input ledger required")
    if profile_schema is not None:
        if (not isinstance(ledger, SqliteSyntheticHouseholdProfileLedger)
                or ledger.profile_schema != profile_schema
                or not callable(profile_access_authority)):
            raise ValueError("profile intake needs same ledger, schema, and access authority")
    elif profile_access_authority is not None:
        raise ValueError("profile authority without profile schema")
    if stage_context_authority is not None:
        if (profile_schema is None
                or not callable(stage_context_authority)):
            raise ValueError("stage observations require current context authority")
    if stage_artifact_store is not None and (
            stage_context_authority is None or profile_schema is None):
        raise ValueError("stage artifact store requires the current stage context")
    if progress_note_ledger is not None and not isinstance(
            progress_note_ledger, PostgresHouseholdProgressNoteLedger):
        raise ValueError("progress note store must be the explicit PostgreSQL adapter")
    notes = progress_note_ledger or ledger
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

    @router.get("/api/v1/domestic/household-intake/my-drafts/{ref}/progress-notes")
    def own_progress_notes(ref: str, p: Principal = Depends(verified_principal)) -> dict:
        try:
            result = notes.read_owned_progress_notes(ref, p)
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(503, detail="SYNTHETIC_PROGRESS_HISTORY_UNAVAILABLE") from exc
        if result is None:
            raise HTTPException(404, detail="DRAFT_NOT_FOUND")
        return result

    @router.post("/api/v1/domestic/household-intake/my-drafts/{ref}/progress-notes",
                 status_code=201)
    def append_progress_note(
        ref: str, data: SyntheticProgressNote,
        authorization: str | None = Header(default=None),
        p: Principal = Depends(verified_principal),
    ) -> dict:
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            raise HTTPException(401, detail="BEARER_REQUIRED_FOR_MUTATION")
        try:
            result = notes.append_owned_progress_note(
                ref, p, action_id=data.action_id,
                expected_case_version=data.expected_case_version,
                expected_revision=data.expected_revision,
                expected_input_revision=data.expected_input_revision,
                corrects_revision=(data.corrects_revision or None),
                reported_at=data.reported_at, note=data.note,
            )
        except InputRevisionConflict as exc:
            raise HTTPException(409, detail="SYNTHETIC_PROGRESS_VERSION_CONFLICT") from exc
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(503, detail="SYNTHETIC_PROGRESS_HISTORY_UNAVAILABLE") from exc
        except ValueError as exc:
            raise HTTPException(422, detail="INVALID_SYNTHETIC_PROGRESS_NOTE") from exc
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


    if profile_schema is not None and profile_access_authority is not None:
        profile_ledger = ledger

        def profile_allowed(p: Principal, ref: str) -> bool:
            try:
                return profile_access_authority(
                    p, ref, profile_schema.schema_ref,
                ) is True
            except Exception as exc:
                raise HTTPException(
                    503, detail="HOUSEHOLD_PROFILE_AUTHORITY_UNAVAILABLE",
                ) from exc

        def record_stage_artifact_access(
            ref: str, p: Principal, stage_ref: str, digest: str, *,
            permitted: bool,
        ) -> bool:
            recorder = getattr(stage_artifact_store, "record_access", None)
            if callable(recorder):
                try:
                    return recorder(
                        p.subject, ref, stage_ref, digest,
                        permitted=permitted,
                    ) is True
                except StageArtifactStoreError as exc:
                    raise HTTPException(
                        503, detail="STAGE_ARTIFACT_AUDIT_UNAVAILABLE",
                    ) from exc
            try:
                return profile_ledger.record_owned_stage_artifact_access(
                    ref, p, stage_ref=stage_ref, artifact_digest=digest,
                    permitted=permitted,
                ) is True
            except ValueError:
                return False
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="STAGE_OBSERVATIONS_UNAVAILABLE",
                ) from exc

        @router.get(
            "/api/v1/domestic/household-intake/my-drafts/{ref}/cultivation-inputs",
        )
        def read_cultivation_inputs(
            ref: str, p: Principal = Depends(verified_principal),
        ) -> dict:
            if not profile_allowed(p, ref):
                raise HTTPException(403, detail="HOUSEHOLD_PROFILE_ACCESS_DENIED")
            try:
                result = profile_ledger.read_owned_profile(ref, p)
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="HOUSEHOLD_PROFILE_UNAVAILABLE",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return {
                **result,
                "fields": [{
                    "key": f.key, "label": f.label, "kind": f.kind,
                    "required": f.required, "max_length": f.max_length,
                    "choices": list(f.choices),
                } for f in profile_schema.fields],
            }

        @router.get(
            "/api/v1/domestic/household-intake/my-drafts/{ref}/cultivation-inputs/revisions/{revision}",
        )
        def read_cultivation_input_revision(
            ref: str, revision: int,
            p: Principal = Depends(verified_principal),
        ) -> dict:
            if not profile_allowed(p, ref):
                raise HTTPException(403, detail="HOUSEHOLD_PROFILE_ACCESS_DENIED")
            try:
                result = profile_ledger.read_owned_profile_revision(
                    ref, p, revision,
                )
            except ValueError as exc:
                raise HTTPException(422, detail="INVALID_HOUSEHOLD_PROFILE_REVISION") from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(503, detail="HOUSEHOLD_PROFILE_UNAVAILABLE") from exc
            if result is None:
                raise HTTPException(404, detail="PROFILE_REVISION_NOT_FOUND")
            return result

        if stage_context_authority is not None:
            @router.get(
                "/api/v1/domestic/household-intake/my-drafts/{ref}/stage-observations",
            )
            def read_stage_observations(
                ref: str, p: Principal = Depends(verified_principal),
            ) -> dict:
                if not profile_allowed(p, ref):
                    raise HTTPException(403, detail="HOUSEHOLD_PROFILE_ACCESS_DENIED")
                try:
                    result = profile_ledger.read_owned_stage_observations(
                        ref, p, context_authority=stage_context_authority,
                    )
                except StageObservationConflict as exc:
                    raise HTTPException(
                        409, detail="STAGE_OBSERVATION_CONTEXT_CHANGED",
                    ) from exc
                except (LedgerIntegrityError, sqlite3.Error) as exc:
                    raise HTTPException(
                        503, detail="STAGE_OBSERVATIONS_UNAVAILABLE",
                    ) from exc
                if result is None:
                    raise HTTPException(404, detail="DRAFT_NOT_FOUND")
                return result

            if stage_artifact_store is not None:
                @router.put(
                    "/api/v1/domestic/household-intake/my-drafts/{ref}/"
                    "stage-observations/artifacts/{stage_ref}",
                    status_code=201,
                )
                async def upload_stage_observation_artifact(
                    ref: str, stage_ref: str, request: Request,
                    authorization: str | None = Header(default=None),
                    p: Principal = Depends(verified_principal),
                ) -> dict:
                    if (not isinstance(authorization, str)
                            or not authorization.startswith("Bearer ")):
                        raise HTTPException(
                            401, detail="BEARER_REQUIRED_FOR_MUTATION",
                        )
                    if not profile_allowed(p, ref):
                        raise HTTPException(
                            403, detail="HOUSEHOLD_PROFILE_ACCESS_DENIED",
                        )

                    def required_version_header(name: str) -> int:
                        value = request.headers.get(name, "")
                        if not re.fullmatch(r"[1-9][0-9]{0,8}", value):
                            raise HTTPException(
                                422, detail="INVALID_STAGE_ARTIFACT_CONTEXT",
                            )
                        return int(value)

                    case_version = required_version_header(
                        "x-ronas-case-version",
                    )
                    input_revision = required_version_header(
                        "x-ronas-input-revision",
                    )
                    plan_digest = request.headers.get("x-ronas-plan-digest", "")
                    requirements_digest = request.headers.get(
                        "x-ronas-requirements-digest", "",
                    )
                    try:
                        context = stage_context_authority(ref)
                    except Exception as exc:
                        raise HTTPException(
                            503, detail="STAGE_CONTEXT_UNAVAILABLE",
                        ) from exc
                    if (not isinstance(context, CurrentStageContext)
                            or context.case_ref != ref
                            or context.case_version != case_version
                            or context.input_revision != input_revision
                            or context.plan_digest != plan_digest
                            or not any(
                                item.stage_ref == stage_ref
                                and item.observation_requirements_digest
                                    == requirements_digest
                                for item in context.requirements
                            )):
                        raise HTTPException(
                            409, detail="STAGE_OBSERVATION_CONTEXT_CHANGED",
                        )

                    declared_size = _declared_upload_size(
                        request.headers.get("content-length"),
                    )
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > MAX_ARTIFACT_BYTES:
                            raise HTTPException(
                                413, detail="STAGE_ARTIFACT_TOO_LARGE",
                            )
                        chunks.append(chunk)
                    _check_upload_size(declared_size, size)
                    try:
                        current_context = stage_context_authority(ref)
                    except Exception as exc:
                        raise HTTPException(
                            503, detail="STAGE_CONTEXT_UNAVAILABLE",
                        ) from exc
                    if current_context != context:
                        raise HTTPException(
                            409, detail="STAGE_OBSERVATION_CONTEXT_CHANGED",
                        )
                    try:
                        artifact = stage_artifact_store.put(
                            p.subject, ref + ":" + stage_ref,
                            request.headers.get("content-type", ""),
                            b"".join(chunks),
                        )
                    except ValueError as exc:
                        raise HTTPException(
                            422, detail="INVALID_STAGE_ARTIFACT",
                        ) from exc
                    except StageArtifactStoreError as exc:
                        raise HTTPException(
                            503, detail="STAGE_ARTIFACT_STORE_UNAVAILABLE",
                        ) from exc
                    return {
                        "digest": artifact.digest,
                        "content_type": artifact.content_type,
                        "byte_length": artifact.byte_length,
                        "stored": True,
                    }

                @router.get(
                    "/api/v1/domestic/household-intake/my-drafts/{ref}/"
                    "stage-observations/artifacts/{stage_ref}/{digest}",
                )
                def download_stage_observation_artifact(
                    ref: str, stage_ref: str, digest: str,
                    p: Principal = Depends(verified_principal),
                ) -> Response:
                    if not profile_allowed(p, ref):
                        record_stage_artifact_access(
                            ref, p, stage_ref, digest, permitted=False,
                        )
                        raise HTTPException(
                            403, detail="HOUSEHOLD_PROFILE_ACCESS_DENIED",
                        )
                    try:
                        history = profile_ledger.read_owned_stage_observations(
                            ref, p, context_authority=stage_context_authority,
                        )
                    except StageObservationConflict as exc:
                        raise HTTPException(
                            409, detail="STAGE_OBSERVATION_CONTEXT_CHANGED",
                        ) from exc
                    except (LedgerIntegrityError, sqlite3.Error) as exc:
                        raise HTTPException(
                            503, detail="STAGE_OBSERVATIONS_UNAVAILABLE",
                        ) from exc
                    receipt_exists = bool(history and any(
                        item["stage_ref"] == stage_ref
                        and item["observation_artifact_digest"] == digest
                        for item in history["observations"]
                    ))
                    if not receipt_exists:
                        record_stage_artifact_access(
                            ref, p, stage_ref, digest, permitted=False,
                        )
                        raise HTTPException(
                            404, detail="STAGE_ARTIFACT_NOT_FOUND",
                        )
                    try:
                        stored = stage_artifact_store.get(
                            p.subject, ref + ":" + stage_ref, digest,
                        )
                    except (ValueError, StageArtifactStoreError) as exc:
                        raise HTTPException(
                            503, detail="STAGE_ARTIFACT_STORE_UNAVAILABLE",
                        ) from exc
                    if stored is None:
                        record_stage_artifact_access(
                            ref, p, stage_ref, digest, permitted=False,
                        )
                        raise HTTPException(
                            404, detail="STAGE_ARTIFACT_NOT_FOUND",
                        )
                    if not profile_allowed(p, ref):
                        record_stage_artifact_access(
                            ref, p, stage_ref, digest, permitted=False,
                        )
                        raise HTTPException(
                            404, detail="STAGE_ARTIFACT_NOT_FOUND",
                        )
                    if not record_stage_artifact_access(
                            ref, p, stage_ref, digest, permitted=True):
                        raise HTTPException(
                            404, detail="STAGE_ARTIFACT_NOT_FOUND",
                        )
                    artifact, content = stored
                    return Response(
                        content=content, media_type=artifact.content_type,
                        headers={
                            "Content-Disposition": 'attachment; filename="stage-observation"',
                            "Cache-Control": "private, no-store",
                            "X-Content-Type-Options": "nosniff",
                        },
                    )

            @router.post(
                "/api/v1/domestic/household-intake/my-drafts/{ref}/stage-observations",
                status_code=201,
            )
            def append_stage_observation(
                ref: str, data: HouseholdStageObservationCommand,
                authorization: str | None = Header(default=None),
                p: Principal = Depends(verified_principal),
            ) -> dict:
                if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
                    raise HTTPException(401, detail="BEARER_REQUIRED_FOR_MUTATION")
                if not profile_allowed(p, ref):
                    raise HTTPException(403, detail="HOUSEHOLD_PROFILE_ACCESS_DENIED")
                try:
                    command = StageObservationCommand(
                        action_id=data.action_id,
                        expected_case_version=data.expected_case_version,
                        expected_input_revision=data.expected_input_revision,
                        expected_input_snapshot_digest=data.expected_input_snapshot_digest,
                        expected_plan_digest=data.expected_plan_digest,
                        stage_ref=data.stage_ref,
                        expected_observation_requirements_digest=
                            data.expected_observation_requirements_digest,
                        observed_at=data.observed_at,
                        observation_artifact_digest=data.observation_artifact_digest,
                        corrects_revision=data.corrects_revision or None,
                    )
                    if (stage_artifact_store is not None
                            and not stage_artifact_store.contains(
                                p.subject, ref + ":" + command.stage_ref,
                                command.observation_artifact_digest)):
                        raise HTTPException(422, detail="STAGE_ARTIFACT_NOT_UPLOADED")
                    result = profile_ledger.append_owned_stage_observation(
                        ref, p, command,
                        expected_observation_revision=
                            data.expected_observation_revision,
                        context_authority=stage_context_authority,
                    )
                except StageObservationConflict as exc:
                    raise HTTPException(
                        409, detail="STAGE_OBSERVATION_CONTEXT_CHANGED",
                    ) from exc
                except StageArtifactStoreError as exc:
                    raise HTTPException(
                        503, detail="STAGE_ARTIFACT_STORE_UNAVAILABLE",
                    ) from exc
                except (LedgerIntegrityError, sqlite3.Error) as exc:
                    raise HTTPException(
                        503, detail="STAGE_OBSERVATIONS_UNAVAILABLE",
                    ) from exc
                except ValueError as exc:
                    raise HTTPException(
                        422, detail="INVALID_STAGE_OBSERVATION",
                    ) from exc
                if result is None:
                    raise HTTPException(404, detail="DRAFT_NOT_FOUND")
                return result

        @router.post(
            "/api/v1/domestic/household-intake/my-drafts/{ref}/cultivation-inputs",
            status_code=201,
        )
        def write_cultivation_inputs(
            ref: str, data: HouseholdProfileCorrection,
            authorization: str | None = Header(default=None),
            p: Principal = Depends(verified_principal),
        ) -> dict:
            if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
                raise HTTPException(401, detail="BEARER_REQUIRED_FOR_MUTATION")
            if not profile_allowed(p, ref):
                raise HTTPException(403, detail="HOUSEHOLD_PROFILE_ACCESS_DENIED")
            try:
                result = profile_ledger.append_owned_profile(
                    ref, p, action_id=data.action_id,
                    expected_case_version=data.expected_case_version,
                    expected_revision=data.expected_revision,
                    values=data.values,
                )
            except InputRevisionConflict as exc:
                raise HTTPException(409, detail="HOUSEHOLD_PROFILE_VERSION_CONFLICT") from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(503, detail="HOUSEHOLD_PROFILE_UNAVAILABLE") from exc
            except ValueError as exc:
                raise HTTPException(422, detail="INVALID_HOUSEHOLD_PROFILE") from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result

    return router
