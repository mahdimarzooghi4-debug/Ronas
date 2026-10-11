"""LOCAL/TEST case-scoped drift of unverified specialist evidence candidates.

Only compares immutable DEMO pointer revisions. Neither time-based expiry,
Keycloak role, nor a candidate document proves professional authority.
"""
from __future__ import annotations

from hashlib import sha256
import json

from .expert_review_questions_sqlite import TRACKS
from .internal_specialist_scope_contract import (
    SyntheticSpecialistEvidenceRegistry, RECORDED, WITHHELD, _canonical,
)
from .scoped_drafts import _synthetic_ref, _synthetic_subject

VERSION = "ronas.domestic.synthetic-specialist-scope-change-impact.v0"


class SpecialistEvidenceRevisionConflict(ValueError):
    """The requested case-local specialist evidence revision does not exist."""


def project_assigned_specialist_scope_change_impact(
    *, registry: SyntheticSpecialistEvidenceRegistry,
    subject: str, case_ref: str, case_version: int,
    observed_revision: int,
) -> dict:
    """Compare one specialist/case's historic candidate against current.

    Caller must FIRST verify signed identity, exact LIVE case assignment and
    existing shared audit ledger; no historical role or appointment is granted.
    """
    if (not isinstance(registry, SyntheticSpecialistEvidenceRegistry)
            or not _synthetic_subject(subject)
            or not _synthetic_ref(case_ref)
            or type(case_version) is not int or case_version < 1):
        raise ValueError("untrusted synthetic specialist scope")
    # The registry's own case-version checks must always remain authoritative.
    current_diagnostic = registry.project_assigned_case(
        subject=subject, case_ref=case_ref, case_version=case_version,
    )
    history = tuple(e for e in registry.events
                    if e.subject == subject and e.case_ref == case_ref)
    if (type(observed_revision) is not int
            or not 0 <= observed_revision <= len(history)):
        raise SpecialistEvidenceRevisionConflict(
            "invalid case-local specialist evidence revision"
        )

    def frame(boundary: int) -> dict:
        included = history[:boundary]
        last = included[-1] if included else None
        candidate = last.candidate if last else None
        canonical = {
            "contract": VERSION,
            "scope": ("DOMESTIC", subject, case_ref, case_version),
            "history": [_canonical(e) for e in included],
        }
        digest = sha256(json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("ascii")).hexdigest()
        return {
            "revision": boundary,
            "candidate": candidate,
            "fingerprint": digest,
            "state": (
                "NO_CANDIDATE_RECORDED" if last is None
                else ("CANDIDATE_WITHHELD" if candidate is None
                      else "POINTERS_PRESENT_UNVERIFIED")
            ),
        }

    before = frame(observed_revision)
    now = frame(len(history))
    a, b = before["candidate"], now["candidate"]

    def changed(*fields: str) -> bool:
        return (tuple(getattr(a, field) for field in fields) if a else None) != (
            tuple(getattr(b, field) for field in fields) if b else None
        )

    def conflict_state(candidate) -> str:
        if candidate is None:
            return "NO_CURRENT_CANDIDATE_CONFLICT_UNKNOWN"
        if candidate.conflict_declaration_state == "POTENTIAL_CONFLICT_DECLARED":
            return "POTENTIAL_CONFLICT_DISCLOSED_UNRESOLVED"
        return "CONFLICT_NOT_INDEPENDENTLY_ASSESSED"

    if now["state"] == "CANDIDATE_WITHHELD":
        relationship = "CURRENT_CANDIDATE_WITHHELD_NO_REUSE"
    elif now["state"] == "NO_CANDIDATE_RECORDED":
        relationship = "NO_SPECIALIST_EVIDENCE_CANDIDATE"
    elif observed_revision != len(history):
        relationship = "CANDIDATE_EVIDENCE_REVISED_UNVERIFIED"
    else:
        relationship = "UNCHANGED_STRUCTURAL_CANDIDATE_UNVERIFIED"

    revised_events = history[observed_revision:]
    return {
        "contract_version": VERSION,
        "engine": "DOMESTIC",
        "case_ref": case_ref, "case_version": case_version,
        "case_state": "DRAFT_ONLY",
        "comparison_scope": "ONE_CASE_ONE_SPECIALIST_UNVERIFIED_EVIDENCE_ONLY",
        "observed_evidence_revision": before["revision"],
        "current_evidence_revision": now["revision"],
        "observed_scope_fingerprint_sha256": before["fingerprint"],
        "current_scope_fingerprint_sha256": now["fingerprint"],
        "observed_candidate_state": before["state"],
        "current_candidate_state": now["state"],
        "structural_relationship": relationship,
        "version_changed": observed_revision != len(history),
        "candidate_recorded_since_observed_count": sum(
            e.operation == RECORDED for e in revised_events
        ),
        "candidate_withheld_since_observed_count": sum(
            e.operation == WITHHELD for e in revised_events
        ),
        "qualification_evidence_pointer_changed": changed(
            "qualification_evidence_ref", "qualification_evidence_sha256",
        ),
        "appointment_evidence_pointer_changed": changed(
            "appointment_evidence_ref", "appointment_evidence_sha256",
        ),
        "conflict_disclosure_pointer_changed": changed(
            "conflict_disclosure_ref", "conflict_disclosure_sha256",
        ),
        "conflict_declaration_changed": changed(
            "conflict_declaration_state",
        ),
        "observed_conflict_diagnostic": conflict_state(a),
        "current_conflict_diagnostic": conflict_state(b),
        "declared_track_scope_changes": [{
            "track": track,
            "observed_candidate_scope_declared": bool(
                a is not None and track in a.declared_review_tracks
            ),
            "current_candidate_scope_declared": bool(
                b is not None and track in b.declared_review_tracks
            ),
            "scope_declaration_changed": (
                bool(a is not None and track in a.declared_review_tracks)
                != bool(b is not None and track in b.declared_review_tracks)
            ),
            "qualified_for_track_verified": False,
            "may_decide_cultivation_plan": False,
        } for track in TRACKS],
        "current_live_case_access_was_checked": True,
        "historical_case_access_reconstructed": False,
        "current_candidate_matches_authority": False,
        "professional_qualification_verified": False,
        "appointment_authority_verified": False,
        "conflict_independently_cleared": False,
        "scope_authorized_for_real_review": False,
        "independent_specialist_decision_recorded": False,
        "candidate_is_access_grant": False,
        "plan_accepted": False,
        "new_advice_enabled": False,
        "real_data": False,
    }
