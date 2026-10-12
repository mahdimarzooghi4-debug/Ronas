"""Versioned unverified specialist evidence and scope candidates (LOCAL/TEST).

A credential pointer, suggested review scope or Keycloak role is never
professional qualification, conflict clearance, or authority to approve an
individual cultivation plan. This immutable registry has no write API.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from .expert_review_questions_sqlite import TRACKS
from .internal_cultivation_plan_contract import _digest
from .scoped_drafts import _synthetic_ref, _synthetic_subject

VERSION = "ronas.domestic.synthetic-specialist-scope-candidates.v0"
RECORDED = "SPECIALIST_EVIDENCE_CANDIDATE_RECORDED_UNVERIFIED"
WITHHELD = "SPECIALIST_EVIDENCE_CANDIDATE_WITHHELD"
STATES = ("CONFLICT_NOT_ASSESSED", "POTENTIAL_CONFLICT_DECLARED")


@dataclass(frozen=True, slots=True)
class SpecialistScopeEvidenceCandidate:
    subject: str
    case_ref: str
    case_version: int
    evidence_revision: int
    declared_review_tracks: tuple[str, ...]
    qualification_evidence_ref: str
    qualification_evidence_sha256: str
    appointment_evidence_ref: str
    appointment_evidence_sha256: str
    conflict_disclosure_ref: str
    conflict_disclosure_sha256: str
    conflict_declaration_state: str = STATES[0]

    def __post_init__(self) -> None:
        if (not _synthetic_subject(self.subject)
                or not _synthetic_ref(self.case_ref)
                or type(self.case_version) is not int or self.case_version < 1
                or type(self.evidence_revision) is not int
                or self.evidence_revision < 1
                or type(self.declared_review_tracks) is not tuple
                or not self.declared_review_tracks
                or len(set(self.declared_review_tracks)) != len(self.declared_review_tracks)
                or self.declared_review_tracks != tuple(
                    track for track in TRACKS if track in self.declared_review_tracks
                )
                or not all(_synthetic_ref(x) for x in (
                    self.qualification_evidence_ref,
                    self.appointment_evidence_ref, self.conflict_disclosure_ref))
                or not all(_digest(x) for x in (
                    self.qualification_evidence_sha256,
                    self.appointment_evidence_sha256,
                    self.conflict_disclosure_sha256))
                or self.conflict_declaration_state not in STATES):
            raise ValueError("untrusted specialist evidence/scope candidate")


@dataclass(frozen=True, slots=True)
class SpecialistScopeEvidenceEvent:
    action_ref: str
    subject: str
    case_ref: str
    case_version: int
    evidence_revision: int
    operation: str
    candidate: SpecialistScopeEvidenceCandidate | None = None
    reason_ref: str | None = None

    def __post_init__(self):
        if (not _synthetic_ref(self.action_ref)
                or not _synthetic_subject(self.subject)
                or not _synthetic_ref(self.case_ref)
                or type(self.case_version) is not int or self.case_version < 1
                or type(self.evidence_revision) is not int
                or self.evidence_revision < 1
                or self.operation not in (RECORDED, WITHHELD)):
            raise ValueError("invalid synthetic specialist history event")
        if self.operation == RECORDED:
            if (not isinstance(self.candidate, SpecialistScopeEvidenceCandidate)
                    or (self.candidate.subject, self.candidate.case_ref,
                        self.candidate.case_version,
                        self.candidate.evidence_revision) != (
                        self.subject, self.case_ref, self.case_version,
                        self.evidence_revision)
                    or self.reason_ref is not None):
                raise ValueError("specialist record is not exactly version-pinned")
        elif self.candidate is not None or not _synthetic_ref(self.reason_ref):
            raise ValueError("withholding requires a DEMO reason, not evidence")


def _canonical(ev: SpecialistScopeEvidenceEvent) -> tuple:
    p = ev.candidate
    return (ev.action_ref, ev.subject, ev.case_ref, ev.case_version,
            ev.evidence_revision, ev.operation, ev.reason_ref,
            None if p is None else (
                p.declared_review_tracks,
                p.qualification_evidence_ref, p.qualification_evidence_sha256,
                p.appointment_evidence_ref, p.appointment_evidence_sha256,
                p.conflict_disclosure_ref, p.conflict_disclosure_sha256,
                p.conflict_declaration_state,
            ))


@dataclass(frozen=True, slots=True)
class SyntheticSpecialistEvidenceRegistry:
    events: tuple[SpecialistScopeEvidenceEvent, ...] = ()

    def __post_init__(self):
        if type(self.events) is not tuple or any(
                not isinstance(e, SpecialistScopeEvidenceEvent)
                for e in self.events):
            raise ValueError("invalid synthetic specialist evidence history")
        revisions: dict[tuple[str, str], int] = {}
        pinned_versions: dict[tuple[str, str], int] = {}
        current: dict[tuple[str, str], SpecialistScopeEvidenceCandidate | None] = {}
        actions: set[str] = set()
        for event in self.events:
            key = (event.subject, event.case_ref)
            previous = revisions.get(key, 0)
            if (event.action_ref in actions
                    or event.evidence_revision != previous + 1
                    or key in pinned_versions
                    and pinned_versions[key] != event.case_version
                    or event.operation == WITHHELD and (
                        previous == 0 or current.get(key) is None
                    )):
                raise ValueError("stale, conflicting or forged specialist evidence event")
            actions.add(event.action_ref)
            revisions[key] = event.evidence_revision
            pinned_versions[key] = event.case_version
            current[key] = event.candidate

    def with_event(self, event: SpecialistScopeEvidenceEvent
                   ) -> SyntheticSpecialistEvidenceRegistry:
        return SyntheticSpecialistEvidenceRegistry(self.events + (event,))

    def snapshot_at(self, event_ordinal: int) -> SyntheticSpecialistEvidenceRegistry:
        if (type(event_ordinal) is not int or event_ordinal < 0
                or event_ordinal > len(self.events)):
            raise ValueError("untrusted specialist evidence history ordinal")
        return SyntheticSpecialistEvidenceRegistry(self.events[:event_ordinal])

    @property
    def fingerprint(self) -> str:
        return sha256(json.dumps({
            "contract": VERSION,
            "ordered_history": [_canonical(ev) for ev in self.events],
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")).hexdigest()

    def project_assigned_case(
        self, *, subject: str, case_ref: str, case_version: int,
    ) -> dict:
        """Only call AFTER signed role, LIVE case assignment & DB verification.

        Scope declarations here never grant access or permit decisions.
        """
        if (not _synthetic_subject(subject)
                or not _synthetic_ref(case_ref)
                or type(case_version) is not int or case_version < 1):
            raise ValueError("untrusted specialist projection scope")
        key = (subject, case_ref)
        matching = [e for e in self.events
                    if (e.subject, e.case_ref) == key]
        if any(e.case_version != case_version for e in matching):
            raise ValueError("candidate pinned to stale/wrong case version")
        latest = matching[-1] if matching else None
        candidate = latest.candidate if latest else None
        state = (
            "NO_SYNTHETIC_EVIDENCE_CANDIDATE" if latest is None
            else ("CANDIDATE_WITHHELD_NOT_AUTHORIZED"
                  if candidate is None else
                  "EVIDENCE_POINTERS_PRESENT_UNVERIFIED")
        )
        return {
            "contract_version": VERSION,
            "engine": "DOMESTIC",
            "case_ref": case_ref,
            "case_version": case_version,
            "case_state": "DRAFT_ONLY",
            "evidence_state": state,
            "candidate_revision": latest.evidence_revision if latest else None,
            "synthetic_candidate_count": sum(e.operation == RECORDED
                                              for e in matching),
            "synthetic_withholding_count": sum(e.operation == WITHHELD
                                                for e in matching),
            "conflict_declaration_state": (
                candidate.conflict_declaration_state
                if candidate else "CONFLICT_NOT_ASSESSED"
            ),
            "potential_conflict_disclosed": (
                candidate is not None and candidate.conflict_declaration_state
                == "POTENTIAL_CONFLICT_DECLARED"
            ),
            "track_scopes": [{
                "track": track,
                "declared_candidate_scope_present": (
                    candidate is not None
                    and track in candidate.declared_review_tracks
                ),
                "qualified_for_track_verified": False,
                "independent_review_recorded": False,
                "may_decide_cultivation_plan": False,
            } for track in TRACKS],
            "identity_professional_credential_verified": False,
            "appointment_authority_verified": False,
            "conflict_independently_cleared": False,
            "scope_authorized_for_real_review": False,
            "candidate_is_access_grant": False,
            "plan_accepted": False,
            "new_advice_enabled": False,
            "real_data": False,
        }

    def compare(self, from_ordinal: int, to_ordinal: int) -> dict:
        if (type(from_ordinal) is not int or type(to_ordinal) is not int
                or not 0 <= from_ordinal < to_ordinal <= len(self.events)):
            raise ValueError("invalid specialist evidence history comparison")
        previous = self.snapshot_at(from_ordinal)
        current = self.snapshot_at(to_ordinal)
        affected = {(e.subject, e.case_ref) for e in
                    self.events[from_ordinal:to_ordinal]}
        return {
            "contract_version": VERSION,
            "scope": "SYNTHETIC_SPECIALIST_EVIDENCE_POINTER_CHANGES_ONLY",
            "from_ordinal": from_ordinal,
            "to_ordinal": to_ordinal,
            "from_history_fingerprint_sha256": previous.fingerprint,
            "to_history_fingerprint_sha256": current.fingerprint,
            "changed_specialist_case_pair_count": len(affected),
            "added_candidate_event_count": sum(
                e.operation == RECORDED
                for e in self.events[from_ordinal:to_ordinal]
            ),
            "withheld_candidate_event_count": sum(
                e.operation == WITHHELD
                for e in self.events[from_ordinal:to_ordinal]
            ),
            "qualification_verified": False,
            "independent_conflict_clearance_verified": False,
            "operational_review_authorized": False,
            "real_data": False,
        }
