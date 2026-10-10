"""CORE-E0-A: bounded source-linked market research DRAFTS ONLY.

A linked citation is not scientific verification or republication permission.
No customer, agreement, actual trade, pricing, customs or money movement.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Sequence


def _nonblank(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class ResearchSource:
    """A declared source with rights caveat; no automatic rights clearance."""

    reference: str
    title: str
    retrieved_on: date
    rights_caveat: str

    def __post_init__(self) -> None:
        for name in ("reference", "title", "rights_caveat"):
            _nonblank(getattr(self, name), name)
        if not isinstance(self.retrieved_on, date):
            raise ValueError("retrieved_on must be a date")


@dataclass(frozen=True, slots=True)
class ResearchFinding:
    """Researcher-provided statement with source and uncertainty."""

    statement: str
    source_ref: str
    limitation: str

    def __post_init__(self) -> None:
        for name in ("statement", "source_ref", "limitation"):
            _nonblank(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class ResearchDraft:
    """Not a verified opportunity, buyer, order, permission or contract."""

    product: str
    destination: str
    research_question: str
    sources: tuple[ResearchSource, ...]
    findings: tuple[ResearchFinding, ...]
    status: str = field(default="DRAFT_ONLY", init=False)
    engine: str = field(default="EXPORT", init=False)


def build_research_draft(
    *,
    product: str,
    destination: str,
    research_question: str,
    sources: Sequence[ResearchSource],
    findings: Sequence[ResearchFinding],
) -> ResearchDraft:
    """Require explicit research scope and provenance; infer no missing facts."""
    for name, value in (
        ("product", product),
        ("destination", destination),
        ("research_question", research_question),
    ):
        _nonblank(value, name)
    if not isinstance(sources, (tuple, list)) or not sources:
        raise ValueError("at least one source is required")
    if not all(isinstance(source, ResearchSource) for source in sources):
        raise ValueError("invalid research source")
    refs = [source.reference.strip() for source in sources]
    if len(set(refs)) != len(refs):
        raise ValueError("duplicate source references")
    if not isinstance(findings, (tuple, list)):
        raise ValueError("findings must be a sequence")
    if not all(isinstance(item, ResearchFinding) for item in findings):
        raise ValueError("invalid finding")
    if any(item.source_ref.strip() not in refs for item in findings):
        raise ValueError("every finding requires a listed source reference")
    return ResearchDraft(
        product=product.strip(),
        destination=destination.strip(),
        research_question=research_question.strip(),
        sources=tuple(sources),
        findings=tuple(findings),
    )
