"""Atomic synthetic specialist review-context dossier composition (LOCAL/TEST).

Composes independently validated, redacted structural projections. Caller
must have verified the signed identity, LIVE assignment, entire SQLite audit
ledger, input/proposal/source and specialist candidate authority once.
"""
from __future__ import annotations

from hashlib import sha256
import json

from .expert_review_questions_sqlite import TRACKS
from .internal_expert_evidence_comparison import VERSION as TIMELINE_VERSION
from .internal_expert_review_handoff import VERSION as HANDOFF_VERSION
from .internal_specialist_scope_change_impact import VERSION as IMPACT_VERSION
from .scoped_drafts import _synthetic_ref

VERSION = "ronas.domestic.synthetic-specialist-review-context.v0"


class SyntheticContextFingerprintConflict(ValueError):
    """Current read-only context changed relative to a prior fingerprint."""


def enforce_synthetic_context_precondition(
    *, current_fingerprint: str, expected_fingerprint: str | None,
) -> None:
    """Synthetic optimistic stale-read check, not authorization."""
    from hmac import compare_digest
    def valid(value):
        return (isinstance(value, str) and len(value) == 64
                and all(c in "0123456789abcdef" for c in value))
    if not valid(current_fingerprint):
        raise ValueError("invalid current synthetic context identity")
    if expected_fingerprint is None:
        return
    if not valid(expected_fingerprint):
        raise ValueError("invalid expected synthetic context identity")
    if not compare_digest(current_fingerprint, expected_fingerprint):
        raise SyntheticContextFingerprintConflict(
            "synthetic context changed since caller observed it"
        )



def project_synthetic_specialist_review_context(
    *, case_ref: str, case_version: int,
    handoff: dict, evidence_timeline: dict, specialist_impact: dict,
) -> dict:
    """Reconcile three results from SAME verified, live-assigned transaction.

    This is a structural overview, NEVER readiness, scientific/legal/professional
    validation, replay authority, signed attestation or an approval decision.
    """
    if not _synthetic_ref(case_ref) or type(case_version) is not int or case_version < 1:
        raise ValueError("untrusted case scope")
    sources = (
        (handoff, HANDOFF_VERSION),
        (evidence_timeline, TIMELINE_VERSION),
        (specialist_impact, IMPACT_VERSION),
    )
    for data, version in sources:
        if (type(data) is not dict
                or data.get("contract_version") != version
                or data.get("engine") != "DOMESTIC"
                or data.get("case_ref") != case_ref
                or data.get("case_version") != case_version
                or data.get("case_state") != "DRAFT_ONLY"):
            raise ValueError("cross-domain projection/version mismatch")
    if (handoff.get("snapshot_kind")
            != "EPHEMERAL_SYNTHETIC_STRUCTURAL_CONTEXT"
            or handoff.get("fingerprint_is_independent_attestation") is not False
            or handoff.get("fingerprint_is_persisted_or_signed") is not False
            or specialist_impact.get("comparison_scope")
               != "ONE_CASE_ONE_SPECIALIST_UNVERIFIED_EVIDENCE_ONLY"
            or evidence_timeline.get("evidence_boundary_kind")
               != "CASE_LOCAL_SYNTHETIC_MUTATION_ORDINAL"
            or evidence_timeline.get("global_audit_sequence_exposed") is not False):
        raise ValueError("incompatible non-authorizing projection semantics")
    for data, keys in (
        (handoff, (
            "qualified_specialist_verified", "purpose_consent_verified",
            "scientific_suitability_verified", "service_use_rights_verified",
            "training_rights_verified", "model_execution_verified",
            "independent_decision_recorded", "plan_accepted",
            "new_advice_enabled", "real_data",
        )),
        (specialist_impact, (
            "current_candidate_matches_authority",
            "professional_qualification_verified",
            "appointment_authority_verified",
            "conflict_independently_cleared",
            "scope_authorized_for_real_review",
            "independent_specialist_decision_recorded",
            "candidate_is_access_grant", "plan_accepted",
            "new_advice_enabled", "real_data",
        )),
        (evidence_timeline, (
            "historical_science_catalogue_reconstructible",
            "historical_ai_proposal_reconstructible",
            "plan_accepted", "real_data",
        )),
    ):
        if any(data.get(key) is not False for key in keys):
            raise ValueError("false elevation of authority in review context")

    handoff_tracks = handoff.get("tracks")
    impact_tracks = specialist_impact.get("declared_track_scope_changes")
    if (type(handoff_tracks) is not list or type(impact_tracks) is not list
            or len(handoff_tracks) != len(TRACKS)
            or len(impact_tracks) != len(TRACKS)):
        raise ValueError("missing independent review tracks")
    for track, h, scope in zip(TRACKS, handoff_tracks, impact_tracks):
        if (type(h) is not dict or type(scope) is not dict
                or h.get("track") != track
                or scope.get("track") != track
                or h.get("review_outcome") != "NOT_REVIEWED"
                or h.get("independent_specialist_review_recorded") is not False
                or scope.get("qualified_for_track_verified") is not False
                or scope.get("may_decide_cultivation_plan") is not False):
            raise ValueError("track cannot be inferred as independently reviewed")
    revision = handoff.get("current_input_revision")
    if (revision is not None and (type(revision) is not int or revision < 1)):
        raise ValueError("invalid current input revision")
    evidence_revisions = evidence_timeline.get("revisions")
    n = evidence_timeline.get("latest_evidence_revision")
    if (type(n) is not int or n < 0
            or type(evidence_revisions) is not list
            or len(evidence_revisions) != n):
        raise ValueError("historical evidence count mismatch")
    input_revisions = [
        e.get("subject_revision")
        for e in evidence_revisions
        if type(e) is dict and e.get("event_kind") == "HOUSEHOLD_INPUT_REVISION"
    ]
    if (input_revisions[-1] if input_revisions else None) != revision:
        raise ValueError("current input and immutable input history disagree")
    for entry in evidence_revisions:
        if (type(entry) is not dict
                or entry.get("independent_specialist_review_recorded") is not False):
            raise ValueError("historical evidence is not a review approval")

    for key in ("context_fingerprint_sha256",):
        if (not isinstance(handoff.get(key), str)
                or len(handoff[key]) != 64
                or any(c not in "0123456789abcdef" for c in handoff[key])):
            raise ValueError("invalid synthetic handoff identity")
    for key in ("observed_scope_fingerprint_sha256",
                "current_scope_fingerprint_sha256"):
        value = specialist_impact.get(key)
        if (not isinstance(value, str) or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)):
            raise ValueError("invalid scoped candidate identity")
    if (type(specialist_impact.get("current_evidence_revision")) is not int
            or type(specialist_impact.get("observed_evidence_revision")) is not int
            or specialist_impact["current_evidence_revision"] <
               specialist_impact["observed_evidence_revision"]):
        raise ValueError("invalid specialist candidate revision")

    canonical = {
        "version": VERSION, "case": ("DOMESTIC", case_ref, case_version),
        "handoff": handoff["context_fingerprint_sha256"],
        "case_evidence_revision": n,
        "specialist_current": specialist_impact[
            "current_scope_fingerprint_sha256"
        ],
        "specialist_observed": specialist_impact[
            "observed_scope_fingerprint_sha256"
        ],
    }
    checksum = sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")).hexdigest()

    return {
        "contract_version": VERSION,
        "engine": "DOMESTIC",
        "case_ref": case_ref,
        "case_version": case_version,
        "case_state": "DRAFT_ONLY",
        "snapshot_kind": "SINGLE_AUTHORIZED_LOCAL_TEST_STRUCTURAL_READ",
        "synthetic_context_fingerprint_sha256": checksum,
        "fingerprint_is_signature_or_approval": False,
        "household_input": {
            "current_revision": revision,
            "case_local_immutable_evidence_event_count": n,
            "purpose_consent_verified": False,
            "adequacy_independently_verified": False,
        },
        "scientific_source": {
            "current_candidate_pointer_state": handoff[
                "source_candidate_pointer_state"
            ],
            "historical_catalogue_reconstructed": False,
            "actual_source_material_attested": False,
            "service_use_rights_verified": False,
            "training_rights_verified": False,
            "scientific_suitability_verified": False,
        },
        "internal_ai_proposal": {
            "current_fixture_state": handoff["proposal_fixture_state"],
            "historical_proposal_reconstructed": False,
            "model_execution_attested": False,
            "cultivation_plan_approved": False,
        },
        "specialist_evidence": {
            "observed_revision": specialist_impact["observed_evidence_revision"],
            "current_revision": specialist_impact["current_evidence_revision"],
            "structural_relationship": specialist_impact["structural_relationship"],
            "current_candidate_state": specialist_impact["current_candidate_state"],
            "current_conflict_diagnostic": specialist_impact[
                "current_conflict_diagnostic"
            ],
            "scope_candidate_withheld_since_observed": (
                specialist_impact["candidate_withheld_since_observed_count"] > 0
            ),
            "independent_professional_qualification_verified": False,
            "appointment_verified": False,
            "conflict_independently_cleared": False,
            "operational_decision_authority": False,
        },
        "tracks": [{
            "track": track,
            "historical_question_count": h["historical_question_count"],
            "latest_question_revision": h["latest_question_revision"],
            "historical_owner_response_count": h[
                "historical_response_receipt_count"
            ],
            "historical_receipt_sighting_count": h[
                "historical_sighting_receipt_count"
            ],
            "latest_question_fixture_binding_matches": h[
                "latest_question_fixture_binding_matches"
            ],
            "current_declared_scope_candidate_present": scope[
                "current_candidate_scope_declared"
            ],
            "candidate_scope_declaration_changed": scope[
                "scope_declaration_changed"
            ],
            "review_outcome": "NOT_REVIEWED",
            "independent_review_recorded": False,
            "eligible_for_operational_reuse": False,
        } for track, h, scope in zip(TRACKS, handoff_tracks, impact_tracks)],
        "real_specialist_decision_recorded": False,
        "plan_accepted": False,
        "new_cultivation_advice_enabled": False,
        "commercial_actions_enabled": False,
        "real_data": False,
    }
