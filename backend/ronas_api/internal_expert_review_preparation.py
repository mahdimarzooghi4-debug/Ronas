"""Three independent, non-authorizing expert review tracks — LOCAL/TEST.

A projection of an already authorized, ledger-verified assigned case read.
Not an agronomist decision, a consent check, or a real scientific evaluator.
No suggested input requirements, science thresholds, approval states or new
business transitions. RON-DEC-015..021, D1-SCI-01 remain controlling.
"""
from __future__ import annotations

from .scoped_drafts import _synthetic_ref

CONTRACT_VERSION = "ronas.domestic.internal-expert-review-preparation.v0"
NO_PROPOSAL = "NO_INTERNAL_PROPOSAL_FIXTURE"
STRUCTURAL = "STRUCTURE_ONLY_UNREVIEWED"
SCIENCE_STATES = ("SCIENTIFIC_SOURCE_UNVERIFIED", "PROVENANCE_PINNED_UNVERIFIED")
TECHNICAL_STATES = (
    "UNREQUESTED", "EVIDENCE_REVIEW_REQUESTED", "HUMAN_RESPONSE_RECORDED",
)


def project_expert_review_preparation(assigned_read: dict) -> dict:
    """Split data, source and proposal review into non-promotable work tracks.

    The caller MUST obtain assigned_read via the same audit-verified
    role + currently assigned per-case workspace read. This module does
    not authenticate actors or establish rights independently.
    """
    if not isinstance(assigned_read, dict):
        raise ValueError("untrusted expert review preparation read")
    if (assigned_read.get("contract_version") !=
            "ronas.domestic.internal-proposal-handoff.v0"
            or assigned_read.get("engine") != "DOMESTIC"
            or not _synthetic_ref(assigned_read.get("case_ref"))
            or type(assigned_read.get("case_version")) is not int
            or assigned_read["case_version"] < 1
            or assigned_read.get("plan_state") != "NOT_AUTHORED"
            or assigned_read.get("technical_review_state") not in TECHNICAL_STATES
            or any(assigned_read.get(k) is not False for k in (
                "expert_qualification_verified", "scientific_review_approved",
                "plan_accepted", "advice_enabled", "real_data",
            ))):
        raise ValueError("unreviewed case state or plan contract changed")
    status = assigned_read.get("proposal_status")
    if status not in (NO_PROPOSAL, STRUCTURAL):
        raise ValueError("unsupported proposal review state")
    if status == NO_PROPOSAL:
        if ("proposed_stage_refs" in assigned_read
                or "input_revision" in assigned_read
                or "scientific_basis_state" in assigned_read
                or assigned_read.get("input_state") != "NOT_RECORDED_IN_DEMO"
                or assigned_read.get("cultivation_inputs") != {
                    "crop": None, "growing_area": None, "water": None,
                    "soil": None, "location": None,
                }):
            raise ValueError("absent proposal cannot carry plan/input evidence")
        input_marker = "NO_SYNTHETIC_INPUT_BINDING"
        science_marker = "NO_PROPOSAL_SCIENCE_BINDING"
        proposal_marker = NO_PROPOSAL
        stage_count = 0
    else:
        stages = assigned_read.get("proposed_stage_refs")
        if (type(assigned_read.get("input_revision")) is not int
                or assigned_read["input_revision"] < 1
                or assigned_read.get("input_state") != "NOT_RECORDED_IN_DEMO"
                or assigned_read.get("scientific_basis_state") not in SCIENCE_STATES
                or type(stages) is not list or not stages
                or any(not _synthetic_ref(s) for s in stages)
                or len(stages) != len(set(stages))
                or "cultivation_inputs" in assigned_read):
            raise ValueError("invalid input/science or stage review lineage")
        input_marker = "SYNTHETIC_INPUT_REVISION_BOUND_NOT_VALIDATED"
        science_marker = assigned_read["scientific_basis_state"]
        proposal_marker = STRUCTURAL
        stage_count = len(stages)
    return {
        "contract_version": CONTRACT_VERSION,
        "engine": "DOMESTIC",
        "case_ref": assigned_read["case_ref"],
        "case_version": assigned_read["case_version"],
        "case_status": "DRAFT_ONLY",
        "technical_case_tracking": assigned_read["technical_review_state"],
        "technical_tracking_is_expert_approval": False,
        "tracks": [
            {
                "track": "HOUSEHOLD_INPUT_ADEQUACY",
                "observed_structure": input_marker,
                "required_fields_approved": False,
                "real_purpose_consent_verified": False,
                "actual_household_input_verified": False,
                "independent_specialist_review_recorded": False,
                "review_outcome": "NOT_REVIEWED",
            },
            {
                "track": "SCIENTIFIC_BASIS_AND_USE_RIGHTS",
                "observed_structure": science_marker,
                "source_retrieval_attested": False,
                "rights_for_service_verified": False,
                "rights_for_training_verified": False,
                "scientific_relevance_review_recorded": False,
                "review_outcome": "NOT_REVIEWED",
            },
            {
                "track": "INDIVIDUAL_CULTIVATION_PROPOSAL",
                "observed_structure": proposal_marker,
                "synthetic_stage_reference_count": stage_count,
                "internal_model_execution_attested": False,
                "independent_plan_review_recorded": False,
                "review_outcome": "NOT_REVIEWED",
            },
        ],
        "qualified_reviewer_identity_verified": False,
        "current_expert_assignment_is_qualification": False,
        "combined_review_status": "NOT_AUTHORIZED_FOR_DECISION",
        "actual_cultivation_plan_exists": False,
        "plan_accepted": False,
        "stages_activated": False,
        "new_advice_enabled": False,
        "marketplace_enabled": False,
        "real_data": False,
    }
