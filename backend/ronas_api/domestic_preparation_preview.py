"""Canonical LOCAL/TEST Domestic cultivation-preparation *display* contract.

This is not an intake schema, criteria to author a cultivation plan, consent,
professional eligibility or a recommendation. All slots are intentionally
unknown because the seeded cases contain NO agricultural inputs. The same
minimal projection is safe for independently authorized household owners and
synthetic assigned agronomy experts; neither can see the other party's identity.
"""
from __future__ import annotations

CONTRACT_VERSION = "ronas.domestic.preparation-preview.v1"
SLOT_NAMES = ("crop", "growing_area", "water", "soil", "location")


def domestic_preparation_preview(
    *, case_version: int, review_revision: int, technical_review_state: str,
    valid_review_states: tuple[str, ...],
) -> dict:
    """Only represent missing DEMO slots; never calculate plan readiness."""
    if (type(case_version) is not int or case_version < 1
            or type(review_revision) is not int
            or not isinstance(valid_review_states, tuple)
            or not 0 <= review_revision < len(valid_review_states)
            or technical_review_state != valid_review_states[review_revision]):
        raise ValueError("inconsistent immutable Domestic review snapshot")
    return {
        "contract_version": CONTRACT_VERSION,
        "case_version": case_version,
        "technical_review_state": technical_review_state,
        "review_revision": review_revision,
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
