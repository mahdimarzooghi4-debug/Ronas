"""Single-transaction three-track synthetic provenance dossier (LOCAL/TEST).

A redacted join of verified owner input, unreviewed source fixture, unexecuted
AI proposal fixture and historical questions. This is never expert review,
source attestation, consent, training permission or an operative plan.
"""
from __future__ import annotations

from .expert_review_questions_sqlite import TRACKS
from .internal_cultivation_plan_contract import (
    InternalCultivationProposal, _digest,
)
from .internal_scientific_basis_contract import CONTRACT_VERSION as SCIENCE_VERSION
from .scoped_drafts import _synthetic_ref

CONTRACT_VERSION = "ronas.domestic.synthetic-expert-provenance-dossier.v0"


def project_expert_provenance_dossier(
    *, case_ref: str, case_version: int,
    current_input: tuple[int, str] | None,
    proposal: InternalCultivationProposal | None,
    science_trace: dict | None,
    evidence_index: dict,
    question_bindings: list[tuple],
) -> dict:
    """Consume *previously* authority-checked inputs, return redacted metadata.

    The service, not this projection, owns the SQL/assignment verification
    and independent current source catalogue lookup. A fixture match never
    attests actual contents or professional competence.
    """
    if (not _synthetic_ref(case_ref)
            or type(case_version) is not int or case_version < 1
            or not isinstance(evidence_index, dict)
            or evidence_index.get("contract_version")
               != "ronas.domestic.synthetic-review-evidence-index.v0"
            or evidence_index.get("engine") != "DOMESTIC"
            or evidence_index.get("case_ref") != case_ref
            or evidence_index.get("case_version") != case_version
            or evidence_index.get("case_state") != "DRAFT_ONLY"
            or type(evidence_index.get("tracks")) is not list
            or len(evidence_index["tracks"]) != len(TRACKS)
            or type(question_bindings) is not list):
        raise ValueError("untrusted case/evidence projection contract")
    if current_input is not None and (
            type(current_input) is not tuple or len(current_input) != 2
            or type(current_input[0]) is not int or current_input[0] < 1
            or not _digest(current_input[1])):
        raise ValueError("untrusted input snapshot")
    if proposal is not None and (
            not isinstance(proposal, InternalCultivationProposal)
            or current_input is None
            or proposal.household_case_ref != case_ref
            or proposal.household_case_version != case_version
            or proposal.household_input_revision != current_input[0]
            or proposal.household_input_snapshot_digest != current_input[1]):
        raise ValueError("untrusted proposed plan input lineage")
    if science_trace is not None and (
            proposal is None or type(science_trace) is not dict
            or science_trace.get("contract_version") != SCIENCE_VERSION
            or science_trace.get("purpose") != "DOMESTIC_CULTIVATION_PLAN"
            or science_trace.get("basis_state") != "PROVENANCE_PINNED_UNVERIFIED"
            or type(science_trace.get("basis_revision")) is not int
            or science_trace["basis_revision"] < 1
            or type(science_trace.get("candidate_source_count")) is not int
            or science_trace["candidate_source_count"] < 1
            or any(science_trace.get(flag) is not False for flag in (
                "scientific_validity_verified", "rights_for_household_plan_verified",
                "rights_for_ai_training_verified",
                "internal_expert_qualification_verified", "plan_review_approved",
                "new_advice_enabled", "business_gate_passed"
            ))):
        raise ValueError("scientific fixture is not an approved decision")

    latest = {}
    counts = {t: 0 for t in TRACKS}
    for row in question_bindings:
        if (type(row) is not tuple or len(row) != 6):
            raise ValueError("untrusted historic question binding shape")
        track, revision, input_rev, input_digest, science_digest, plan_digest = row
        if (track not in counts or type(revision) is not int
                or revision != counts[track] + 1
                or type(input_rev) is not int or input_rev < 1
                or not all(_digest(value) for value in (
                    input_digest, science_digest, plan_digest))):
            raise ValueError("untrusted historic question binding")
        counts[track] += 1
        latest[track] = row
    rows = []
    for track, record in zip(TRACKS, evidence_index["tracks"]):
        if (type(record) is not dict or record.get("track") != track
                or type(record.get("historical_question_count")) is not int
                or record["historical_question_count"] != counts[track]
                or record.get("latest_question_revision") != (
                    latest[track][1] if track in latest else None
                ) or record.get("question_is_independent_specialist_review") is not False
                or record.get("review_decision_recorded") is not False):
            raise ValueError("independent track history mismatch")
        question = latest.get(track)
        bound = bool(
            question is not None and current_input is not None
            and proposal is not None and science_trace is not None
            and question[2] == current_input[0]
            and question[3] == current_input[1]
            and question[4] == proposal.scientific_basis_manifest_digest
            and question[5] == proposal.proposal_content_digest
        )
        rows.append({
            "track": track,
            "historical_question_count": counts[track],
            "latest_question_revision": question[1] if question else None,
            "latest_question_fixture_binding_matches": bound,
            "latest_evidence_marker": record.get("latest_evidence_marker"),
            "household_response_received": record.get(
                "latest_evidence_marker") in (
                    "SYNTHETIC_OWNER_RESPONSE_NOT_REVIEWED",
                    "SYNTHETIC_RECEIPT_SEEN_NOT_REVIEWED",
                ),
            "expert_receipt_sighted_not_reviewed": record.get(
                "latest_evidence_marker") == "SYNTHETIC_RECEIPT_SEEN_NOT_REVIEWED",
            "independent_expert_review_recorded": False,
            "review_outcome": "NOT_REVIEWED",
        })
    return {
        "contract_version": CONTRACT_VERSION,
        "engine": "DOMESTIC",
        "case_ref": case_ref,
        "case_version": case_version,
        "case_state": "DRAFT_ONLY",
        "input": {
            "current_synthetic_revision": (
                current_input[0] if current_input else None
            ),
            "purpose_consent_verified": False,
            "actual_input_adequacy_verified": False,
        },
        "science": {
            "catalogue_fixture_state": (
                "CURRENT_SOURCE_CANDIDATE_POINTERS_UNVERIFIED"
                if science_trace is not None else "NO_CURRENT_CATALOGUE_CHECK"
            ),
            "basis_candidate_revision": (
                science_trace["basis_revision"] if science_trace else None
            ),
            "source_candidate_count": (
                science_trace["candidate_source_count"] if science_trace else 0
            ),
            "actual_source_bytes_attested": False,
            "service_use_rights_verified": False,
            "training_rights_verified": False,
            "scientific_suitability_verified": False,
        },
        "proposal": {
            "fixture_state": (
                "STRUCTURE_ONLY_UNREVIEWED"
                if proposal is not None else "NO_INTERNAL_PROPOSAL_FIXTURE"
            ),
            "synthetic_stage_count": (
                len(proposal.proposed_stages) if proposal else 0
            ),
            "internal_model_execution_attested": False,
            "individual_plan_accepted": False,
        },
        "tracks": rows,
        "qualified_specialist_verified": False,
        "real_review_decision_recorded": False,
        "cultivation_advice_enabled": False,
        "marketplace_enabled": False,
        "real_data": False,
    }
