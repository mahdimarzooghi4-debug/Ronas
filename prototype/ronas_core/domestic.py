"""CORE-D1-A: pure draft validation; never operational household onboarding.

No persistence, identity verification, eligibility, crop planning or training.
The caller must use synthetic data until real Business/legal gates are passed.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

DRAFT_PURPOSE = "CULTIVATION_CONTEXT_INTAKE"


def _nonblank(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class ConsentEvidence:
    """Caller-declared consent reference, not independently authenticated proof."""

    subject_ref: str
    receipt_ref: str
    purpose: str
    explicitly_granted: bool
    captured_at: datetime

    def __post_init__(self) -> None:
        for name in ("subject_ref", "receipt_ref", "purpose"):
            _nonblank(getattr(self, name), name)
        if not isinstance(self.captured_at, datetime) or self.captured_at.tzinfo is None:
            raise ValueError("captured_at requires timezone-aware datetime")
        if self.captured_at.utcoffset() is None:
            raise ValueError("captured_at requires valid timezone offset")
        if type(self.explicitly_granted) is not bool:
            raise ValueError("explicitly_granted must be a boolean")


@dataclass(frozen=True, slots=True)
class DeclaredFact:
    """Synthetic caller-declared fact; not an expert-validated assertion."""

    field_name: str
    value: str
    source_ref: str

    def __post_init__(self) -> None:
        for name in ("field_name", "value", "source_ref"):
            _nonblank(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class HouseholdIntakeDraft:
    """In-memory review-only output; not an accepted household record."""

    subject_ref: str
    consent_ref: str
    facts: tuple[DeclaredFact, ...]
    status: str = field(default="DRAFT_ONLY", init=False)
    engine: str = field(default="DOMESTIC", init=False)


def build_household_intake_draft(
    consent: ConsentEvidence, facts: Sequence[DeclaredFact]
) -> HouseholdIntakeDraft:
    """Fail closed on absent purpose-specific consent or ambiguous declarations.

    This function cannot authenticate consent, determine required fields, create
    or approve a crop plan, grant sale eligibility or retain any records.
    """
    if not isinstance(consent, ConsentEvidence):
        raise ValueError("consent evidence is required")
    if consent.purpose != DRAFT_PURPOSE or consent.explicitly_granted is not True:
        raise ValueError("explicit consent for cultivation intake is required")
    if not isinstance(facts, (tuple, list)) or not facts:
        raise ValueError("at least one declared fact is required")
    if not all(isinstance(fact, DeclaredFact) for fact in facts):
        raise ValueError("facts must be caller-declared facts")
    names = [fact.field_name.strip() for fact in facts]
    if len(set(names)) != len(names):
        raise ValueError("duplicate field names are ambiguous")
    return HouseholdIntakeDraft(
        subject_ref=consent.subject_ref,
        consent_ref=consent.receipt_ref,
        facts=tuple(facts),
    )
