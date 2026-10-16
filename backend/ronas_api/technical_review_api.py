"""Opt-in synthetic human-evidence request, response and history adapter.

Not mounted in default runtime. Auth comes exclusively from a trusted
Keycloak-verified app dependency; the ledger additionally authorizes each
case read/request and independently authorizes human responses. No response
records a Business approval.
"""
from collections.abc import Callable
import sqlite3

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from .auth import Principal
from .grant_ledger_sqlite import LedgerIntegrityError
from .human_review_sqlite import (
    RECORDED, REQUESTED, STATES, SqliteSyntheticHumanReviewLedger,
    review_state_for_steps,
)
from .scoped_audit import GrantConflict, GrantNotAuthorized
from .export_research_question import ExportResearchQuestionConflict
from .export_research_evidence import ExportEvidenceReferenceConflict
from .export_research_findings import ExportResearchFindingConflict
from .postgres_export_findings import ExportFindingStorageError
from .export_research_packet import (
    ExportResearchPacketConflict, ExportResearchPacketIntegrityError,
    build_export_research_packet,
)
from .export_source_connector import (
    ExportSourceConnectorRegistry, ExportSourceConnectorUnavailable,
    capture_export_source_reference,
)


class SyntheticExportQuestionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    expected_case_version: StrictInt
    expected_question_revision: StrictInt
    product_ref: StrictStr
    destination_ref: StrictStr


class SyntheticExportEvidenceReferenceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    expected_case_version: StrictInt
    expected_question_revision: StrictInt
    expected_evidence_revision: StrictInt
    evidence_ref: StrictStr
    connector_ref: StrictStr
    source_snapshot_digest: StrictStr


class SyntheticExportFindingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    expected_case_version: StrictInt
    expected_question_revision: StrictInt
    expected_finding_revision: StrictInt
    evidence_revision: StrictInt
    evidence_ref: StrictStr
    note: StrictStr


class SyntheticEvidenceReviewRequestCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    expected_case_version: StrictInt
    expected_review_revision: StrictInt
    request_ref: StrictStr
    evidence_ref: StrictStr


class SyntheticHumanReviewResponseCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: StrictStr
    expected_case_version: StrictInt
    expected_review_revision: StrictInt
    request_ref: StrictStr
    evidence_ref: StrictStr
    decision_ref: StrictStr


def build_technical_review_read_router(
    ledger: SqliteSyntheticHumanReviewLedger,
    verified_principal: Callable[..., Principal],
    export_source_connectors: ExportSourceConnectorRegistry | None = None,
    export_research_finding_ledger=None,
) -> APIRouter:
    """This router is safe only when mounted with real Keycloak verification.

    Do not use a request-generated Principal or a generic AuthConfig.
    The application factory owns strict opt-in and identity wiring.
    """
    if not isinstance(ledger, SqliteSyntheticHumanReviewLedger):
        raise ValueError("an explicit synthetic human review ledger is required")
    if (export_research_finding_ledger is not None and
            getattr(getattr(export_research_finding_ledger, "_workspace_reader", None), "__self__", None) is not ledger):
        raise ValueError("Export finding storage must authorize through the shared case ledger")
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

    def append_review_step(engine: str, ref: str, command: BaseModel,
                           principal: Principal, *, response: bool) -> dict:
        # Mutations require signed Bearer authentication even though browser
        # sessions are also accepted by the read-only BFF pages.
        # This prevents a cookie-only API call from bypassing the BFF's CSRF
        # and Origin protections.
        stage = RECORDED if response else REQUESTED
        try:
            if response:
                saved = ledger.record_human_response(
                    engine=engine, ref=ref, actor=principal,
                    expected_case_version=command.expected_case_version,
                    expected_review_revision=command.expected_review_revision,
                    action_id=command.action_id, request_ref=command.request_ref,
                    evidence_ref=command.evidence_ref,
                    decision_ref=command.decision_ref,
                )
            else:
                saved = ledger.request_evidence_review(
                    engine=engine, ref=ref, actor=principal,
                    expected_case_version=command.expected_case_version,
                    expected_review_revision=command.expected_review_revision,
                    action_id=command.action_id, request_ref=command.request_ref,
                    evidence_ref=command.evidence_ref,
                )
        except GrantNotAuthorized as exc:
            raise HTTPException(404, detail="DRAFT_NOT_FOUND") from exc
        except GrantConflict as exc:
            raise HTTPException(409, detail="TECHNICAL_REVIEW_CHANGED") from exc
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(
                503, detail="TECHNICAL_REVIEW_UNAVAILABLE",
            ) from exc
        except ValueError as exc:
            raise HTTPException(422, detail="INVALID_TECHNICAL_REVIEW_COMMAND") from exc
        return {
            "engine": saved.engine,
            "ref": saved.ref,
            "case_version": command.expected_case_version,
            "case_status": "DRAFT_ONLY",
            "review_revision": saved.revision,
            "technical_review_state": review_state_for_steps(saved.revision),
            "stage": stage,
            "request_ref": saved.request_ref,
            "evidence_ref": saved.evidence_ref,
            "decision_ref": saved.decision_ref,
            "business_approval": False,
            "plan_accepted": False,
            "advice_enabled": False,
        }

    def require_bearer(authorization: str | None) -> None:
        if (not isinstance(authorization, str)
                or not authorization.startswith("Bearer ")
                or not authorization[7:]):
            raise HTTPException(401, detail="BEARER_REQUIRED")

    def request_handler(engine: str):
        def endpoint(
            ref: str, command: SyntheticEvidenceReviewRequestCommand,
            authorization: str | None = Header(default=None),
            p: Principal = Depends(verified_principal),
        ) -> dict:
            require_bearer(authorization)
            return append_review_step(engine, ref, command, p, response=False)
        return endpoint

    def response_handler(engine: str):
        def endpoint(
            ref: str, command: SyntheticHumanReviewResponseCommand,
            authorization: str | None = Header(default=None),
            p: Principal = Depends(verified_principal),
        ) -> dict:
            require_bearer(authorization)
            return append_review_step(engine, ref, command, p, response=True)
        return endpoint

    for engine, path in (
        ("DOMESTIC", "/api/v1/admin/domestic/household-intake/drafts/{ref}"),
        ("EXPORT", "/api/v1/admin/export/research/drafts/{ref}"),
    ):
        router.add_api_route(
            path + "/technical-review/requests", request_handler(engine),
            methods=["POST"], status_code=201,
        )
        router.add_api_route(
            path + "/technical-review/human-responses", response_handler(engine),
            methods=["POST"], status_code=201,
        )

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

    @router.post(
        "/api/v1/admin/export/research/drafts/{ref}/evidence-references",
        status_code=201,
    )
    def record_export_evidence_reference(
        ref: str, command: SyntheticExportEvidenceReferenceCommand,
        authorization: str | None = Header(default=None),
        p: Principal = Depends(verified_principal),
    ) -> dict:
        if (not isinstance(authorization, str)
                or not authorization.startswith("Bearer ")):
            raise HTTPException(401, detail="BEARER_REQUIRED")
        try:
            result = ledger.record_export_evidence_reference(
                ref, p,
                expected_case_version=command.expected_case_version,
                expected_question_revision=command.expected_question_revision,
                expected_evidence_revision=command.expected_evidence_revision,
                action_id=command.action_id,
                evidence_ref=command.evidence_ref,
                connector_ref=command.connector_ref,
                source_snapshot_digest=command.source_snapshot_digest,
            )
        except ExportEvidenceReferenceConflict as exc:
            raise HTTPException(
                409, detail="EXPORT_EVIDENCE_REFERENCE_CHANGED",
            ) from exc
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(
                503, detail="TECHNICAL_REVIEW_UNAVAILABLE",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                422, detail="INVALID_EXPORT_EVIDENCE_REFERENCE",
            ) from exc
        if result is None:
            raise HTTPException(404, detail="DRAFT_NOT_FOUND")
        return result

    if export_source_connectors is not None:
        if not isinstance(export_source_connectors, ExportSourceConnectorRegistry):
            raise ValueError("explicit Export connector registry required")

        class SyntheticExportConnectorCaptureCommand(BaseModel):
            model_config = ConfigDict(extra="forbid", strict=True)
            action_id: StrictStr
            expected_case_version: StrictInt
            expected_question_revision: StrictInt
            expected_evidence_revision: StrictInt
            connector_ref: StrictStr

        @router.post(
            "/api/v1/admin/export/research/drafts/{ref}/evidence-references/capture",
            status_code=201,
        )
        def capture_export_source(
            ref: str, command: SyntheticExportConnectorCaptureCommand,
            authorization: str | None = Header(default=None),
            p: Principal = Depends(verified_principal),
        ) -> dict:
            if (not isinstance(authorization, str)
                    or not authorization.startswith("Bearer ")):
                raise HTTPException(401, detail="BEARER_REQUIRED")
            try:
                result = capture_export_source_reference(
                    ledger, export_source_connectors, ref, p,
                    expected_case_version=command.expected_case_version,
                    expected_question_revision=command.expected_question_revision,
                    expected_evidence_revision=command.expected_evidence_revision,
                    action_id=command.action_id,
                    connector_ref=command.connector_ref,
                )
            except ExportEvidenceReferenceConflict as exc:
                raise HTTPException(
                    409, detail="EXPORT_EVIDENCE_REFERENCE_CHANGED",
                ) from exc
            except ExportSourceConnectorUnavailable as exc:
                raise HTTPException(
                    503, detail="EXPORT_SOURCE_CONNECTOR_UNAVAILABLE",
                ) from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="TECHNICAL_REVIEW_UNAVAILABLE",
                ) from exc
            except ValueError as exc:
                raise HTTPException(
                    422, detail="INVALID_EXPORT_SOURCE_CONNECTOR",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return result

    @router.post(
        "/api/v1/admin/export/research/drafts/{ref}/findings",
        status_code=201,
    )
    def append_export_finding(
        ref: str, command: SyntheticExportFindingCommand,
        authorization: str | None = Header(default=None),
        p: Principal = Depends(verified_principal),
    ) -> dict:
        require_bearer(authorization)
        try:
            finding_ledger = export_research_finding_ledger or ledger
            result = finding_ledger.record_export_research_finding(
                ref, p, expected_case_version=command.expected_case_version,
                expected_question_revision=command.expected_question_revision,
                expected_finding_revision=command.expected_finding_revision,
                evidence_revision=command.evidence_revision,
                action_id=command.action_id, evidence_ref=command.evidence_ref,
                note=command.note,
            )
        except ExportResearchFindingConflict as exc:
            raise HTTPException(
                409, detail="EXPORT_RESEARCH_FINDING_CHANGED",
            ) from exc
        except (LedgerIntegrityError, sqlite3.Error) as exc:
            raise HTTPException(
                503, detail="TECHNICAL_REVIEW_UNAVAILABLE",
            ) from exc
        except ExportFindingStorageError as exc:
            raise HTTPException(503, detail="TECHNICAL_REVIEW_UNAVAILABLE") from exc
        except ValueError as exc:
            raise HTTPException(422, detail="INVALID_EXPORT_RESEARCH_FINDING") from exc
        if result is None:
            raise HTTPException(404, detail="DRAFT_NOT_FOUND")
        return result

    if export_research_finding_ledger is not None:
        @router.get("/api/v1/admin/export/research/drafts/{ref}/findings")
        def read_export_findings(
            ref: str, p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                result = export_research_finding_ledger.read_history(ref, p)
            except ExportFindingStorageError as exc:
                raise HTTPException(
                    503, detail="TECHNICAL_REVIEW_UNAVAILABLE",
                ) from exc
            if result is None:
                # Keep unknown and unauthorized cases indistinguishable.
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return {"engine": "EXPORT", "ref": ref, "items": result,
                    "draft_only": True, "report_approved": False}

        @router.get("/api/v1/admin/export/research/drafts/{ref}/research-packet")
        def read_export_research_packet(
            ref: str, p: Principal = Depends(verified_principal),
        ) -> dict:
            try:
                before = ledger.read_export_research_workspace(ref, p)
                findings = export_research_finding_ledger.read_history(ref, p)
                after = ledger.read_export_research_workspace(ref, p)
                if before is None or findings is None or after is None:
                    raise HTTPException(404, detail="DRAFT_NOT_FOUND")
                return build_export_research_packet(before, findings, after)
            except HTTPException:
                raise
            except ExportResearchPacketConflict as exc:
                raise HTTPException(409, detail="EXPORT_RESEARCH_CONTEXT_CHANGED") from exc
            except ExportResearchPacketIntegrityError as exc:
                raise HTTPException(503, detail="TECHNICAL_REVIEW_UNAVAILABLE") from exc
            except (LedgerIntegrityError, sqlite3.Error, ExportFindingStorageError) as exc:
                raise HTTPException(503, detail="TECHNICAL_REVIEW_UNAVAILABLE") from exc

    return router
