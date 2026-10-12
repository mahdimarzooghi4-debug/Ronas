"""Canonical LOCAL/TEST Domestic cultivation-preparation display contract.

This is neither an intake schema nor a cultivation-plan readiness decision.
Only *observed*, integrity-checked technical review steps may appear on the
shared household / separately assigned agronomy expert progress timeline.
"""
from __future__ import annotations

CONTRACT_VERSION = "ronas.domestic.preparation-preview.v1"
SLOT_NAMES = ("crop", "growing_area", "water", "soil", "location")
REVIEW_EVENTS = ("TECH_REVIEW_REQUESTED", "TECH_HUMAN_RESPONSE_RECORDED")
REVIEW_STATES = ("UNREQUESTED", "EVIDENCE_REVIEW_REQUESTED", "HUMAN_RESPONSE_RECORDED")


def domestic_preparation_preview(
    *, case_version: int, review_revision: int, technical_review_state: str,
    valid_review_states: tuple[str, ...],
    observed_review_steps: tuple[str, ...] = (),
) -> dict:
    """Expose only real DEMO technical stages, never future or inferred steps.

    The originating ledger independently verifies event/actor/evidence
    lineage. This pure function takes only the redacted names, and returns
    no reviewer identity, source reference, event time or decision text.
    """
    if (type(case_version) is not int or case_version < 1
            or type(review_revision) is not int
            or type(valid_review_states) is not tuple
            or valid_review_states != REVIEW_STATES
            or not 0 <= review_revision < len(REVIEW_STATES)
            or technical_review_state != REVIEW_STATES[review_revision]
            or type(observed_review_steps) is not tuple
            or observed_review_steps != REVIEW_EVENTS[:review_revision]):
        raise ValueError("inconsistent immutable Domestic review snapshot")
    timeline = [
        {"revision": revision, "technical_event": event}
        for revision, event in enumerate(observed_review_steps, start=1)
    ]
    return {
        "contract_version": CONTRACT_VERSION,
        "case_version": case_version,
        "technical_review_state": technical_review_state,
        "review_revision": review_revision,
        "technical_timeline": timeline,
        "timeline_semantics": "OBSERVED_TECHNICAL_STEPS_ONLY",
        "input_state": "NOT_RECORDED_IN_DEMO",
        "cultivation_inputs": {key: None for key in SLOT_NAMES},
        "purpose_consent_verified": False,
        "agronomist_qualification_verified": False,
        "scientific_review_approved": False,
        "plan_state": "NOT_AUTHORED",
        "plan_accepted": False,
        "business_actions_enabled": False,
        "real_data": False,
    }
