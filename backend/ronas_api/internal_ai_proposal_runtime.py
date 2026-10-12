"""Internal-model adapter boundary for synthetic LOCAL/TEST proposal runs.

The runtime accepts an injected Ronas-internal model adapter and pins its
structural output to an explicit synthetic case/input/source context. It never
creates crop instructions, verifies rights or scientific truth, trains weights,
or accepts/promotes a proposal. Production composition is deliberately absent.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
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
        domestic_case = (
            _synthetic_ref(self.case_ref)
            and self.case_ref.startswith(("DEMO-D", "DEMO-H"))
        )
        if (self.engine != "DOMESTIC" or not domestic_case
                or type(self.case_version) is not int or self.case_version < 1
                or type(self.input_revision) is not int or self.input_revision < 1
                or not _digest(self.input_snapshot_digest)
                or not _digest(self.scientific_basis_manifest_digest)
                or not _digest(self.model_artifact_digest)
                or not _synthetic_ref(self.run_ref)):
            raise ValueError("invalid synthetic proposal runtime context")


@dataclass(frozen=True, slots=True)
class ProposalRuntimeBasis:
    """Current non-household source/model basis supplied by an independent port."""

    case_ref: str
    case_version: int
    scientific_basis_manifest_digest: str
    model_artifact_digest: str

    def __post_init__(self) -> None:
        if (not _synthetic_ref(self.case_ref)
                or not self.case_ref.startswith(("DEMO-D", "DEMO-H"))
                or type(self.case_version) is not int or self.case_version < 1
                or not _digest(self.scientific_basis_manifest_digest)
                or not _digest(self.model_artifact_digest)):
            raise ValueError("invalid synthetic proposal runtime basis")


class ProposalRuntimeBasisAuthority(Protocol):
    def read_current_basis(
        self, case_ref: str, run_ref: str,
    ) -> ProposalRuntimeBasis | None: ...


class ProposalInputLineageSource(Protocol):
    def internal_proposal_lineage(
        self, case_ref: str,
    ) -> tuple[int, int, str] | None: ...


class ProfileBackedProposalContextAuthority:
    """Join current synthetic case/source basis with the owner profile digest.

    The source/model basis port and profile ledger are read independently on
    every checkpoint. Profile contents never leave the ledger; only version and
    canonical digest enter the internal runtime context.
    """

    def __init__(
        self, profile_lineage: ProposalInputLineageSource,
        basis_authority: ProposalRuntimeBasisAuthority,
    ):
        if (not callable(getattr(profile_lineage, "internal_proposal_lineage", None))
                or not callable(getattr(basis_authority, "read_current_basis", None))):
            raise ValueError("profile lineage and current basis authorities required")
        self._profile_lineage = profile_lineage
        self._basis_authority = basis_authority

    def read_current_context(
        self, case_ref: str, run_ref: str,
    ) -> ProposalRuntimeContext | None:
        basis = self._basis_authority.read_current_basis(case_ref, run_ref)
        lineage = self._profile_lineage.internal_proposal_lineage(case_ref)
        if (not isinstance(basis, ProposalRuntimeBasis)
                or basis.case_ref != case_ref or lineage is None
                or type(lineage) is not tuple or len(lineage) != 3):
            return None
        case_version, input_revision, snapshot_digest = lineage
        if basis.case_version != case_version:
            return None
        try:
            return ProposalRuntimeContext(
                case_ref=case_ref, case_version=case_version,
                input_revision=input_revision,
                input_snapshot_digest=snapshot_digest,
                scientific_basis_manifest_digest=
                    basis.scientific_basis_manifest_digest,
                model_artifact_digest=basis.model_artifact_digest,
                run_ref=run_ref,
            )
        except (TypeError, ValueError):
            return None


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


def candidate_structure_digest(
    model_artifact_digest: str, stages: tuple[CandidateStage, ...],
) -> str:
    """Hash the exact ordered structural output emitted by the adapter.

    The digest binds the model artifact and every stage reference/digest. It
    contains no household text, agronomic advice, approval, or inferred science.
    """
    if (not _digest(model_artifact_digest) or type(stages) is not tuple
            or not stages or any(not isinstance(stage, CandidateStage)
                                 for stage in stages)):
        raise ValueError("invalid candidate structure")
    body = {
        "contract": "ronas.domestic.internal-ai-candidate-structure.v0",
        "model_artifact_digest": model_artifact_digest,
        "stages": [{
            "ref": stage.ref,
            "instructions_digest": stage.instructions_digest,
            "observation_requirements_digest":
                stage.observation_requirements_digest,
        } for stage in stages],
    }
    # Validate all fields before hashing. This gives malformed values the same
    # fail-closed behavior as the proposal envelope.
    for stage in stages:
        ProposedCultivationStage(
            stage.ref, stage.instructions_digest,
            stage.observation_requirements_digest,
        )
    encoded = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


class InternalModelAdapter(Protocol):
    """Adapter port for a Ronas-owned, internally hosted model runtime."""

    def generate(self, context: ProposalRuntimeContext) -> CandidateOutput: ...


class ProposalRuntimeUnavailable(RuntimeError):
    """A model adapter or independent runtime authority was unavailable."""


class ProposalRuntimeStale(ProposalRuntimeUnavailable):
    """The pinned Domestic context changed while the model was running."""


class ProposalContextAuthority(Protocol):
    """Independent current-state source; never trust the run request itself."""

    def read_current_context(
        self, case_ref: str, run_ref: str,
    ) -> ProposalRuntimeContext | None: ...


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
        computed_content_digest = candidate_structure_digest(
            output.model_artifact_digest, output.stages,
        )
    except (TypeError, ValueError) as exc:
        raise ProposalRuntimeUnavailable("internal model output shape rejected") from exc
    if not hmac.compare_digest(output.proposal_content_digest,
                               computed_content_digest):
        raise ProposalRuntimeUnavailable("internal model content digest mismatch")
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
            proposal_content_digest=computed_content_digest,
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
        "proposal_content_digest": computed_content_digest,
        "stage_refs": [stage.ref for stage in stages],
        "runtime_status": "LOCAL_TEST_STRUCTURE_ONLY",
    }
    encoded = json.dumps(receipt_body, sort_keys=True, separators=(",", ":")).encode()
    return ProposalRuntimeResult(
        proposal=proposal, structural_record=structural,
        runtime_receipt_digest=hashlib.sha256(encoded).hexdigest(),
    )



def run_current_synthetic_internal_proposal(
    case_ref: str, run_ref: str, authority: ProposalContextAuthority,
    adapter: InternalModelAdapter,
) -> ProposalRuntimeResult:
    """Run only if the same independent context is current before and after.

    A model may take long enough for a household correction or scientific-source
    revision to arrive. The caller supplies identifiers only; the authority
    independently constructs the context twice. Any difference discards the
    generated proposal before it can be handed to a consumer.
    """
    domestic_case = (
        isinstance(case_ref, str) and _synthetic_ref(case_ref)
        and case_ref.startswith(("DEMO-D", "DEMO-H"))
    )
    if (not domestic_case or not _synthetic_ref(run_ref)
            or not callable(getattr(authority, "read_current_context", None))):
        raise ValueError("synthetic Domestic context authority required")

    def current() -> ProposalRuntimeContext:
        try:
            context = authority.read_current_context(case_ref, run_ref)
        except Exception as exc:
            raise ProposalRuntimeUnavailable(
                "proposal context authority unavailable",
            ) from exc
        if (not isinstance(context, ProposalRuntimeContext)
                or context.case_ref != case_ref or context.run_ref != run_ref):
            raise ProposalRuntimeStale("current proposal context unavailable")
        return context

    before = current()
    result = run_synthetic_internal_proposal(before, adapter)
    after = current()
    if after != before:
        raise ProposalRuntimeStale("proposal context changed during model run")
    return result
