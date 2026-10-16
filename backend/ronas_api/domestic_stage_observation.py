"""Schema-bound Domestic stage observation receipt contract (LOCAL/TEST).

This module records only a reference to an observation artifact. It does not
interpret observations, evaluate requirements, mark cultivation stages done,
or authorize advice. All stage identifiers and requirement digests are supplied
by the current proposal authority; no agronomic schema is invented here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re

from .internal_cultivation_plan_contract import _digest
from .scoped_drafts import _synthetic_ref

CONTRACT_VERSION = "ronas.domestic.stage-observation-receipt.v0"
_ACTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")


class StageObservationConflict(ValueError):
    """The submitted observation no longer matches the current case context."""


@dataclass(frozen=True, slots=True)
class StageRequirement:
    """Opaque binding to externally supplied stage and observation requirements."""

    stage_ref: str
    observation_requirements_digest: str

    def __post_init__(self) -> None:
        if (not _synthetic_ref(self.stage_ref)
                or not _digest(self.observation_requirements_digest)):
            raise ValueError("invalid injected stage requirement")


@dataclass(frozen=True, slots=True)
class CurrentStageContext:
    """One current, independently resolved Domestic plan/input snapshot."""

    case_ref: str
    case_version: int
    input_revision: int
    input_snapshot_digest: str
    plan_digest: str
    requirements: tuple[StageRequirement, ...]

    def __post_init__(self) -> None:
        if (not _synthetic_ref(self.case_ref)
                or type(self.case_version) is not int or self.case_version < 1
                or type(self.input_revision) is not int or self.input_revision < 1
                or not _digest(self.input_snapshot_digest)
                or not _digest(self.plan_digest)
                or type(self.requirements) is not tuple
                or not self.requirements
                or any(not isinstance(x, StageRequirement) for x in self.requirements)
                or len({x.stage_ref for x in self.requirements}) != len(self.requirements)):
            raise ValueError("invalid current Domestic stage context")


@dataclass(frozen=True, slots=True)
class StageObservationCommand:
    """A household-reported artifact reference, never an interpreted result."""

    action_id: str
    expected_case_version: int
    expected_input_revision: int
    expected_input_snapshot_digest: str
    expected_plan_digest: str
    stage_ref: str
    expected_observation_requirements_digest: str
    observed_at: str
    observation_artifact_digest: str
    corrects_revision: int | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.action_id, str) or not _ACTION.fullmatch(self.action_id)
                or type(self.expected_case_version) is not int
                or self.expected_case_version < 1
                or type(self.expected_input_revision) is not int
                or self.expected_input_revision < 1
                or not _digest(self.expected_input_snapshot_digest)
                or not _digest(self.expected_plan_digest)
                or not _synthetic_ref(self.stage_ref)
                or not _digest(self.expected_observation_requirements_digest)
                or not _aware_timestamp(self.observed_at)
                or not _digest(self.observation_artifact_digest)
                or self.corrects_revision is not None
                   and (type(self.corrects_revision) is not int
                        or self.corrects_revision < 1)):
            raise ValueError("invalid stage observation receipt command")


@dataclass(frozen=True, slots=True)
class StageObservationReceipt:
    """Immutable lineage receipt; status is deliberately not stage completion."""

    contract_version: str
    case_ref: str
    case_version: int
    input_revision: int
    input_snapshot_digest: str
    plan_digest: str
    stage_ref: str
    observation_requirements_digest: str
    observed_at: str
    observation_artifact_digest: str
    revision: int
    previous_receipt_digest: str
    receipt_digest: str
    corrects_revision: int | None = None
    status: str = "OBSERVATION_REFERENCE_RECORDED"
    stage_completed: bool = False
    scientific_review_approved: bool = False
    advice_enabled: bool = False
    real_data: bool = False


def _aware_timestamp(value: str) -> bool:
    if not isinstance(value, str) or len(value) > 40:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def record_stage_observation(
    command: StageObservationCommand, *, current: CurrentStageContext,
    revision: int, previous_receipt_digest: str | None = None,
) -> StageObservationReceipt:
    """Validate exact current lineage and return a deterministic receipt.

    Persistence, owner authorization, and append-only audit are supplied by the
    caller's existing transactional ledger. Call this inside that transaction.
    """
    if not isinstance(command, StageObservationCommand) or not isinstance(
            current, CurrentStageContext):
        raise ValueError("trusted command and current stage context required")
    if (type(revision) is not int or revision < 1
            or previous_receipt_digest is not None
               and not _digest(previous_receipt_digest)):
        raise ValueError("invalid observation journal position")
    if (command.expected_case_version != current.case_version
            or command.expected_input_revision != current.input_revision
            or command.expected_input_snapshot_digest != current.input_snapshot_digest
            or command.expected_plan_digest != current.plan_digest):
        raise StageObservationConflict("case, input, or plan context changed")
    stage = next(
        (x for x in current.requirements if x.stage_ref == command.stage_ref), None,
    )
    if (stage is None or stage.observation_requirements_digest
            != command.expected_observation_requirements_digest):
        raise StageObservationConflict("stage requirements changed")
    prior = previous_receipt_digest or ("0" * 64)
    body = {
        "contract_version": CONTRACT_VERSION,
        "action_id": command.action_id,
        "case_ref": current.case_ref,
        "case_version": current.case_version,
        "input_revision": current.input_revision,
        "input_snapshot_digest": current.input_snapshot_digest,
        "plan_digest": current.plan_digest,
        "stage_ref": stage.stage_ref,
        "observation_requirements_digest":
            stage.observation_requirements_digest,
        "observed_at": command.observed_at,
        "observation_artifact_digest": command.observation_artifact_digest,
        "revision": revision,
        "previous_receipt_digest": prior,
    }
    if command.corrects_revision is not None:
        body["corrects_revision"] = command.corrects_revision
    digest = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    return StageObservationReceipt(
        contract_version=CONTRACT_VERSION,
        case_ref=current.case_ref,
        case_version=current.case_version,
        input_revision=current.input_revision,
        input_snapshot_digest=current.input_snapshot_digest,
        plan_digest=current.plan_digest,
        stage_ref=stage.stage_ref,
        observation_requirements_digest=stage.observation_requirements_digest,
        observed_at=command.observed_at,
        observation_artifact_digest=command.observation_artifact_digest,
        revision=revision,
        previous_receipt_digest=prior,
        receipt_digest=digest,
        corrects_revision=command.corrects_revision,
    )


def receipt_is_current(
    receipt: StageObservationReceipt, current: CurrentStageContext,
) -> bool:
    """Compare receipt lineage to current authority without rewriting history."""
    if not isinstance(receipt, StageObservationReceipt) or not isinstance(
            current, CurrentStageContext):
        return False
    requirement = next(
        (x for x in current.requirements if x.stage_ref == receipt.stage_ref), None,
    )
    return bool(
        receipt.case_ref == current.case_ref
        and receipt.case_version == current.case_version
        and receipt.input_revision == current.input_revision
        and receipt.input_snapshot_digest == current.input_snapshot_digest
        and receipt.plan_digest == current.plan_digest
        and requirement is not None
        and receipt.observation_requirements_digest
            == requirement.observation_requirements_digest
    )
