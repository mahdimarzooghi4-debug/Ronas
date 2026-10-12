"""Internal-model adapter boundary for synthetic LOCAL/TEST proposal runs.

The runtime accepts an injected Ronas-internal model adapter and pins its
structural output to an explicit synthetic case/input/source context. It never
creates crop instructions, verifies rights or scientific truth, trains weights,
or accepts/promotes a proposal. Production composition is deliberately absent.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Protocol

from .internal_cultivation_plan_contract import (
    InternalCultivationProposal, ProposedCultivationStage, _digest,
    inspect_proposal_structure,
)
from .scoped_drafts import _synthetic_ref


@dataclass(frozen=True, slots=True)
class ProposalRuntimeContext:
    case_ref: str
    case_version: int
    input_revision: int
    input_snapshot_digest: str
    scientific_basis_manifest_digest: str
    model_artifact_digest: str
    run_ref: str
    engine: str = "DOMESTIC"

    def __post_init__(self) -> None:
        if (self.engine != "DOMESTIC" or not _synthetic_ref(self.case_ref)
                or type(self.case_version) is not int or self.case_version < 1
                or type(self.input_revision) is not int or self.input_revision < 1
                or not _digest(self.input_snapshot_digest)
                or not _digest(self.scientific_basis_manifest_digest)
                or not _digest(self.model_artifact_digest)
                or not _synthetic_ref(self.run_ref)):
            raise ValueError("invalid synthetic proposal runtime context")


@dataclass(frozen=True, slots=True)
class CandidateStage:
    ref: str
    instructions_digest: str
    observation_requirements_digest: str


@dataclass(frozen=True, slots=True)
class CandidateOutput:
    model_artifact_digest: str
    proposal_content_digest: str
    stages: tuple[CandidateStage, ...]


class InternalModelAdapter(Protocol):
    """Adapter port for a Ronas-owned, internally hosted model runtime."""

    def generate(self, context: ProposalRuntimeContext) -> CandidateOutput: ...


class ProposalRuntimeUnavailable(RuntimeError):
    """The injected internal model adapter failed or returned an invalid shape."""


@dataclass(frozen=True, slots=True)
class ProposalRuntimeResult:
    proposal: InternalCultivationProposal
    structural_record: dict
    runtime_receipt_digest: str


def run_synthetic_internal_proposal(
    context: ProposalRuntimeContext, adapter: InternalModelAdapter,
) -> ProposalRuntimeResult:
    """Invoke an injected internal adapter and return structure-only evidence.

    The context intentionally contains identifiers/digests, not household text.
    This method can exercise adapter integration using synthetic fixtures; it
    is not a production inference API and it grants no authority to the result.
    """
    if not isinstance(context, ProposalRuntimeContext) or not callable(
        getattr(adapter, "generate", None)
    ):
        raise ValueError("explicit runtime context and model adapter required")
    try:
        output = adapter.generate(context)
    except Exception as exc:
        raise ProposalRuntimeUnavailable("internal model adapter unavailable") from exc
    if (not isinstance(output, CandidateOutput)
            or output.model_artifact_digest != context.model_artifact_digest
            or not _digest(output.proposal_content_digest)
            or type(output.stages) is not tuple or not output.stages
            or any(not isinstance(stage, CandidateStage) for stage in output.stages)):
        raise ProposalRuntimeUnavailable("internal model output shape rejected")
    try:
        stages = tuple(ProposedCultivationStage(
            stage.ref, stage.instructions_digest,
            stage.observation_requirements_digest,
        ) for stage in output.stages)
        proposal = InternalCultivationProposal(
            household_case_ref=context.case_ref,
            household_case_version=context.case_version,
            household_input_revision=context.input_revision,
            household_input_snapshot_digest=context.input_snapshot_digest,
            scientific_basis_manifest_digest=context.scientific_basis_manifest_digest,
            internal_model_artifact_digest=output.model_artifact_digest,
            internal_run_ref=context.run_ref,
            proposal_content_digest=output.proposal_content_digest,
            proposed_stages=stages,
        )
        structural = inspect_proposal_structure(
            proposal, expected_case_engine=context.engine,
            expected_case_ref=context.case_ref,
            expected_case_version=context.case_version,
            expected_input_revision=context.input_revision,
            expected_input_snapshot_digest=context.input_snapshot_digest,
        )
    except (TypeError, ValueError) as exc:
        raise ProposalRuntimeUnavailable("internal model output lineage rejected") from exc
    receipt_body = {
        "contract": "ronas.domestic.internal-model-runtime-receipt.v0",
        "case_ref": context.case_ref,
        "case_version": context.case_version,
        "input_revision": context.input_revision,
        "input_snapshot_digest": context.input_snapshot_digest,
        "scientific_basis_manifest_digest": context.scientific_basis_manifest_digest,
        "model_artifact_digest": output.model_artifact_digest,
        "run_ref": context.run_ref,
        "proposal_content_digest": output.proposal_content_digest,
        "stage_refs": [stage.ref for stage in stages],
        "runtime_status": "LOCAL_TEST_STRUCTURE_ONLY",
    }
    encoded = json.dumps(receipt_body, sort_keys=True, separators=(",", ":")).encode()
    return ProposalRuntimeResult(
        proposal=proposal, structural_record=structural,
        runtime_receipt_digest=hashlib.sha256(encoded).hexdigest(),
    )
