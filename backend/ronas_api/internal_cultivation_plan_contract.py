"""LOCAL/TEST structural envelope for RONAS-INTERNAL AI cultivation proposals.

A structurally valid *proposal* is NEVER an agronomically valid plan.
This module neither calls a model nor produces agronomy instructions and is
NOT the approved operational D1 lifecycle or a production endpoint. Binding:
RON-DEC-015..021 and the Ronas-internal delivery direction RON-DEC-033.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .scoped_drafts import _synthetic_ref

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
CONTRACT_VERSION = "ronas.domestic.internal-plan-proposal-structure.v0"


def _digest(value: str) -> bool:
    return isinstance(value, str) and SHA256_HEX.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class ProposedCultivationStage:
    """Stage reference and commitments only; no science or timing fabricated."""

    ref: str
    instructions_digest: str
    observation_requirements_digest: str

    def __post_init__(self) -> None:
        if (not _synthetic_ref(self.ref)
                or not _digest(self.instructions_digest)
                or not _digest(self.observation_requirements_digest)):
            raise ValueError("invalid synthetic internal cultivation stage lineage")


@dataclass(frozen=True, slots=True)
class InternalCultivationProposal:
    """One structurally pinned, never-accepted internal AI proposal envelope."""

    household_case_ref: str
    household_case_version: int
    household_input_revision: int
    household_input_snapshot_digest: str
    scientific_basis_manifest_digest: str
    internal_model_artifact_digest: str
    internal_run_ref: str
    proposal_content_digest: str
    proposed_stages: tuple[ProposedCultivationStage, ...]
    origin: str = "RONAS_INTERNAL_AI"

    def __post_init__(self) -> None:
        if (not _synthetic_ref(self.household_case_ref)
                or type(self.household_case_version) is not int
                or self.household_case_version < 1
                or type(self.household_input_revision) is not int
                or self.household_input_revision < 1
                or not _synthetic_ref(self.internal_run_ref)
                or self.origin != "RONAS_INTERNAL_AI"
                or not all(_digest(x) for x in (
                    self.household_input_snapshot_digest,
                    self.scientific_basis_manifest_digest,
                    self.internal_model_artifact_digest,
                    self.proposal_content_digest,
                ))
                or type(self.proposed_stages) is not tuple
                or not self.proposed_stages
                or any(not isinstance(stage, ProposedCultivationStage)
                       for stage in self.proposed_stages)
                or len({stage.ref for stage in self.proposed_stages})
                       != len(self.proposed_stages)):
            raise ValueError("invalid or unbound synthetic internal AI proposal")


def inspect_proposal_structure(
    proposal: InternalCultivationProposal, *, expected_case_engine: str,
    expected_case_ref: str, expected_case_version: int, expected_input_revision: int,
    expected_input_snapshot_digest: str,
) -> dict:
    """An immutable offline trace for tests, never a science/consent/approval gate.

    Expected lineage MUST come from a separate case/input authority in a
    future approved implementation; caller-provided digests here are not
    trusted consent, expert qualification, approved science, or model attestation.
    """
    if (not isinstance(proposal, InternalCultivationProposal)
            or expected_case_engine != "DOMESTIC"
            or not _synthetic_ref(expected_case_ref)
            or type(expected_case_version) is not int
            or type(expected_input_revision) is not int
            or expected_case_version < 1
            or expected_input_revision < 1
            or not _digest(expected_input_snapshot_digest)
            or proposal.household_case_ref != expected_case_ref
            or proposal.household_case_version != expected_case_version
            or proposal.household_input_revision != expected_input_revision
            or proposal.household_input_snapshot_digest
               != expected_input_snapshot_digest):
        raise ValueError("stale or unverified internal plan proposal lineage")
    return {
        "contract_version": CONTRACT_VERSION,
        "engine": "DOMESTIC",
        "case_ref": proposal.household_case_ref,
        "case_version": proposal.household_case_version,
        "household_input_revision": proposal.household_input_revision,
        "household_input_snapshot_digest": proposal.household_input_snapshot_digest,
        "scientific_basis_manifest_digest":
            proposal.scientific_basis_manifest_digest,
        "internal_model_artifact_digest":
            proposal.internal_model_artifact_digest,
        "internal_run_ref": proposal.internal_run_ref,
        "proposal_content_digest": proposal.proposal_content_digest,
        "proposal_origin": proposal.origin,
        "proposed_stage_refs": [stage.ref for stage in proposal.proposed_stages],
        "proposal_status": "STRUCTURE_ONLY_UNREVIEWED",
        "business_plan_state": "NOT_ACCEPTED",
        "expert_qualification_verified": False,
        "expert_plan_approved": False,
        "scientific_basis_verified": False,
        "informed_household_consent_verified": False,
        "model_attestation_verified": False,
        "supervision_stages_activated": False,
        "new_cultivation_advice_enabled": False,
        "commercial_actions_enabled": False,
        "real_data": False,
    }
