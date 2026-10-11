"""Redacted three-track synthetic evidence index, never a review decision.

Only called on ledger-verified, currently case-assigned LOCAL/TEST reads.
Input revision matching is structural and does NOT attest scientific source
rights, actual input sufficiency, specialist qualifications or plan validity.
"""
from __future__ import annotations

from .expert_review_questions_sqlite import TRACKS
from .scoped_drafts import _synthetic_ref

CONTRACT_VERSION = "ronas.domestic.synthetic-review-evidence-index.v0"
NO_QUESTION = "NO_SYNTHETIC_QUESTION"
QUESTION_ONLY = "QUESTION_RECORDED_NOT_REVIEWED"
OWNER_RESPONSE = "SYNTHETIC_OWNER_RESPONSE_NOT_REVIEWED"
RECEIPT_SEEN = "SYNTHETIC_RECEIPT_SEEN_NOT_REVIEWED"


def project_synthetic_review_evidence_index(
    *, case_ref: str, case_version: int, input_revision: int | None,
    questions: list[tuple], responses: set[tuple], inspections: set[tuple],
) -> dict:
    """Index verified receipt *presence*, not note contents or approval.

    questions: previously verified (track, revision, input_revision, reason_ref,
    evidence_ref). No source/household-private refs, hash or actor is returned.
    """
    if (not _synthetic_ref(case_ref)
            or type(case_version) is not int or case_version < 1
            or input_revision is not None
            and (type(input_revision) is not int or input_revision < 1)
            or type(questions) is not list or type(responses) is not set
            or type(inspections) is not set):
        raise ValueError("invalid synthetic evidence index scope")

    by_track: dict[str, list[tuple[int, int]]] = {t: [] for t in TRACKS}
    known: set[tuple[str, int]] = set()
    for row in questions:
        if (type(row) is not tuple or len(row) != 5):
            raise ValueError("unexpected question history shape")
        track, revision, bound_input, reason_ref, evidence_ref = row
        if (track not in by_track
                or type(revision) is not int
                or revision != len(by_track[track]) + 1
                or type(bound_input) is not int or bound_input < 1
                or not _synthetic_ref(reason_ref)
                or not _synthetic_ref(evidence_ref)):
            raise ValueError("untrusted question evidence lineage")
        key = (track, revision)
        known.add(key)
        by_track[track].append((revision, bound_input))

    for name, keys in (("response", responses), ("inspection", inspections)):
        for key in keys:
            if (type(key) is not tuple or len(key) != 2
                    or key not in known or key[0] != TRACKS[0]
                    or type(key[1]) is not int):
                raise ValueError("invalid " + name + " evidence link")
    if not inspections.issubset(responses):
        raise ValueError("inspection without recorded owner response")

    tracks = []
    for track in TRACKS:
        history = by_track[track]
        latest = history[-1] if history else None
        key = (track, latest[0]) if latest else None
        seen = key in inspections if key else False
        answered = key in responses if key else False
        marker = (NO_QUESTION if key is None
                  else RECEIPT_SEEN if seen
                  else OWNER_RESPONSE if answered
                  else QUESTION_ONLY)
        tracks.append({
            "track": track,
            "historical_question_count": len(history),
            "historical_owner_response_count": sum(
                (track, revision) in responses for revision, _ in history
            ),
            "historical_receipt_sighting_count": sum(
                (track, revision) in inspections for revision, _ in history
            ),
            "latest_question_revision": latest[0] if latest else None,
            "latest_bound_input_revision": latest[1] if latest else None,
            "latest_question_matches_current_input_revision": (
                latest is not None and input_revision is not None
                and latest[1] == input_revision
            ),
            "latest_evidence_marker": marker,
            "source_lineage_current_verified": False,
            "question_is_independent_specialist_review": False,
            "review_decision_recorded": False,
        })

    return {
        "contract_version": CONTRACT_VERSION,
        "engine": "DOMESTIC",
        "case_ref": case_ref,
        "case_version": case_version,
        "case_state": "DRAFT_ONLY",
        "index_scope": "HISTORICAL_SYNTHETIC_EVIDENCE_ONLY",
        "tracks": tracks,
        "professional_qualification_verified": False,
        "purpose_consent_verified": False,
        "scientific_basis_and_rights_verified": False,
        "actual_input_adequacy_verified": False,
        "independent_specialist_review_recorded": False,
        "plan_accepted": False,
        "new_advice_enabled": False,
        "real_data": False,
    }
