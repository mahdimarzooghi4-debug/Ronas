"""Redacted, immutable-history synthetic binding drift view, LOCAL/TEST.

Never an operational plan eligibility, source licence, training permission,
qualified specialist decision, or authority to reuse any historical evidence.
"""
from __future__ import annotations

from .expert_review_questions_sqlite import TRACKS
from .internal_cultivation_plan_contract import InternalCultivationProposal, _digest
from .scoped_drafts import _synthetic_ref

VERSION = "ronas.domestic.synthetic-review-binding-drift.v0"
SOURCE_STATES = frozenset({
    "NO_SEPARATE_SOURCE_CATALOGUE",
    "SOURCE_CANDIDATE_POINTERS_MATCH_UNVERIFIED",
    "SOURCE_CANDIDATE_POINTERS_CHANGED",
})


def project_synthetic_review_binding_drift(
    *, case_ref: str, case_version: int,
    current_input: tuple[int, str] | None,
    current_proposal: InternalCultivationProposal | None,
    source_pointer_state: str, question_bindings: list[tuple],
    responses: set[tuple], inspections: set[tuple],
) -> dict:
    """Diagnose structural drift in historical synthetic question bindings.

    All inputs must come from an already-verified, case-assigned ledger
    transaction and a separate current source-catalogue callback where present.
    """
    if (not _synthetic_ref(case_ref)
            or type(case_version) is not int or case_version < 1
            or source_pointer_state not in SOURCE_STATES
            or type(question_bindings) is not list
            or type(responses) is not set or type(inspections) is not set):
        raise ValueError("invalid historical drift scope")
    if current_input is not None and (
            type(current_input) is not tuple or len(current_input) != 2
            or type(current_input[0]) is not int or current_input[0] < 1
            or not _digest(current_input[1])):
        raise ValueError("invalid current input snapshot")
    if current_proposal is not None and (
            not isinstance(current_proposal, InternalCultivationProposal)
            or current_proposal.household_case_ref != case_ref
            or current_proposal.household_case_version != case_version):
        raise ValueError("untrusted synthetic proposal")
    if (source_pointer_state != "NO_SEPARATE_SOURCE_CATALOGUE"
            and current_proposal is None):
        raise ValueError("source catalogue cannot validate missing proposal")

    by_track: dict[str, list[tuple]] = {t: [] for t in TRACKS}
    keys: set[tuple[str, int]] = set()
    for row in question_bindings:
        if type(row) is not tuple or len(row) != 6:
            raise ValueError("malformed verified historical binding")
        track, rev, input_rev, input_hash, science_hash, plan_hash = row
        if (track not in by_track or type(rev) is not int
                or rev != len(by_track[track]) + 1
                or type(input_rev) is not int or input_rev < 1
                or not all(_digest(x) for x in (
                    input_hash, science_hash, plan_hash))):
            raise ValueError("unexpected question revision or lineage")
        keys.add((track, rev))
        by_track[track].append(row)
    for links in (responses, inspections):
        for key in links:
            if (type(key) is not tuple or len(key) != 2
                    or key not in keys or key[0] != TRACKS[0]
                    or type(key[1]) is not int):
                raise ValueError("orphan or non-owner response/receipt")
    if not inspections.issubset(responses):
        raise ValueError("receipt sighting without owner response")

    proposal_input_matches = (
        current_proposal is not None and current_input is not None
        and current_proposal.household_input_revision == current_input[0]
        and current_proposal.household_input_snapshot_digest == current_input[1]
    )
    result_tracks = []
    for track in TRACKS:
        history = by_track[track]
        entries = []
        for item in history:
            _, rev, input_rev, input_hash, science_hash, plan_hash = item
            input_matches = (
                current_input is not None and input_rev == current_input[0]
                and input_hash == current_input[1]
            )
            proposal_matches = (
                current_proposal is not None
                and science_hash == current_proposal.scientific_basis_manifest_digest
                and plan_hash == current_proposal.proposal_content_digest
            )
            if current_input is None:
                context = "NO_CURRENT_SYNTHETIC_OWNER_INPUT"
            elif not input_matches:
                context = "HOUSEHOLD_INPUT_REVISION_OR_FINGERPRINT_CHANGED"
            elif current_proposal is None:
                context = "NO_CURRENT_SYNTHETIC_PROPOSAL_FIXTURE"
            elif not proposal_input_matches:
                context = "CURRENT_PROPOSAL_BOUND_TO_DIFFERENT_INPUT"
            elif not proposal_matches:
                context = "PROPOSAL_OR_SCIENCE_MANIFEST_CHANGED"
            elif source_pointer_state == "SOURCE_CANDIDATE_POINTERS_CHANGED":
                context = "SCIENTIFIC_SOURCE_CANDIDATE_POINTERS_CHANGED"
            elif source_pointer_state == "NO_SEPARATE_SOURCE_CATALOGUE":
                context = "SCIENTIFIC_CATALOGUE_NOT_CHECKED"
            else:
                context = "STRUCTURAL_FIXTURE_MATCH_ONLY_UNREVIEWED"
            key = (track, rev)
            entries.append({
                "question_revision": rev,
                "bound_input_revision": input_rev,
                "superseded_by_newer_question": rev != history[-1][1],
                "historical_owner_response_received": key in responses,
                "historical_receipt_sighted_not_reviewed": key in inspections,
                "structural_context": context,
                "eligible_for_operational_reuse": False,
                "independent_specialist_review_recorded": False,
            })
        result_tracks.append({
            "track": track,
            "historical_question_count": len(history),
            "questions": entries,
            "review_outcome": "NOT_REVIEWED",
        })
    return {
        "contract_version": VERSION,
        "engine": "DOMESTIC", "case_ref": case_ref,
        "case_version": case_version, "case_state": "DRAFT_ONLY",
        "scope": "HISTORICAL_SYNTHETIC_EVIDENCE_DIAGNOSTICS_ONLY",
        "current_synthetic_owner_input_revision": (
            current_input[0] if current_input else None
        ),
        "source_candidate_pointer_state": source_pointer_state,
        "tracks": result_tracks,
        "purpose_consent_verified": False,
        "rights_for_service_verified": False,
        "rights_for_training_verified": False,
        "scientific_validity_verified": False,
        "qualified_specialist_verified": False,
        "independent_plan_decision_recorded": False,
        "plan_accepted": False,
        "new_advice_enabled": False,
        "real_data": False,
    }
