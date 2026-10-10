"""Synthetic, explicitly assigned agronomy case preview for the shared user UI.

There is no certified agronomist registry, real consent, cultivation inputs,
expert decision or authorized cultivation plan. This adapter is LOCAL/TEST
only, and must be mounted only with the *identical* Keycloak-scoped review
ledger. Signed agronomy_expert role alone cannot select a household case.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .auth import Principal
from .grant_ledger_sqlite import LedgerIntegrityError
from .human_review_sqlite import SqliteSyntheticHumanReviewLedger, STATES
from .scoped_drafts import _synthetic_ref, _synthetic_subject


@dataclass(frozen=True, slots=True)
class SyntheticAgronomyAssignment:
    ref: str
    subject: str
    case_version: int

    def __post_init__(self) -> None:
        if (not _synthetic_ref(self.ref)
                or not _synthetic_subject(self.subject)
                or type(self.case_version) is not int or self.case_version < 1):
            raise ValueError("invalid explicit synthetic expert assignment")


class SyntheticAgronomyWorkspace:
    """Separate role+case authorization, without reusing domestic_ops grants."""

    def __init__(
        self, ledger: SqliteSyntheticHumanReviewLedger,
        assignments: Iterable[SyntheticAgronomyAssignment], *,
        trusted_assignment_active: Callable[[str, str, int], bool],
    ) -> None:
        if (not isinstance(ledger, SqliteSyntheticHumanReviewLedger)
                or not callable(trusted_assignment_active)):
            raise ValueError("explicit ledger and live assignment authority required")
        bound: dict[tuple[str, str], SyntheticAgronomyAssignment] = {}
        for assignment in assignments:
            if not isinstance(assignment, SyntheticAgronomyAssignment):
                raise ValueError("unexpected agronomy assignment type")
            record = ledger._catalogue.get(("DOMESTIC", assignment.ref))
            if record is None or record.version != assignment.case_version:
                raise ValueError("assignment must pin an exact DOMESTIC case/version")
            key = assignment.subject, assignment.ref
            if key in bound:
                raise ValueError("duplicate agronomy case assignment")
            bound[key] = assignment
        self.ledger = ledger
        self._assignments = bound
        self._live_authority = trusted_assignment_active

    @staticmethod
    def _actor(principal: Principal) -> str | None:
        if (not isinstance(principal, Principal)
                or not _synthetic_subject(principal.subject)
                or "agronomy_expert" not in principal.roles):
            return None
        return principal.subject

    def _allowed(self, subject: str, ref: str, version: int) -> bool:
        assignment = self._assignments.get((subject, ref))
        if assignment is None or assignment.case_version != version:
            return False
        try:
            # This is NOT a real professional-qualification authority. It is
            # only current, explicit LOCAL/TEST case access permission.
            return self._live_authority(subject, ref, version) is True
        except Exception as exc:
            raise LedgerIntegrityError("agronomy assignment authority unavailable") from exc

    def _preview(self, db, ref: str) -> dict:
        record = self.ledger._catalogue[("DOMESTIC", ref)]
        versions = tuple(row[0] for row in db.execute(
            "SELECT version FROM case_history "
            "WHERE engine='DOMESTIC' AND ref=? ORDER BY version", (ref,),
        ))
        if (versions != self.ledger._histories[("DOMESTIC", ref)]
                or not versions or versions[-1] != record.version):
            raise LedgerIntegrityError("agronomy case history mismatch")
        steps = self.ledger._steps(db, "DOMESTIC", ref)
        return {
            "ref": ref,
            "engine": "DOMESTIC",
            "case_version": record.version,
            "known_versions": list(versions),
            "case_status": "DRAFT_ONLY",
            "source": "SYNTHETIC_ONLY",
            "review_revision": len(steps),
            "technical_review_state": STATES[len(steps)],
            "technical_review_steps": [
                {"revision": item.revision, "stage": item.stage}
                for item in steps
            ],
            "cultivation_inputs": {
                "crop": None, "growing_area": None, "water": None,
                "soil": None, "location": None,
            },
            "plan_state": "NOT_AUTHORED",
            "agronomist_qualification_verified": False,
            "purpose_consent_verified": False,
            "scientific_review_approved": False,
            "plan_accepted": False,
            "real_data": False,
            "business_actions_enabled": False,
        }

    def read_assigned_case(self, ref: str, principal: Principal) -> dict | None:
        if not _synthetic_ref(ref):
            return None
        with self.ledger._transaction() as db:
            self.ledger._verify(db)
            record = self.ledger._catalogue.get(("DOMESTIC", ref))
            subject = self._actor(principal)
            if record is None or subject is None:
                return None
            allowed = self._allowed(subject, ref, record.version)
            result = self._preview(db, ref) if allowed else None
            self.ledger._append(
                db, kind="READ_ALLOWED" if allowed else "READ_DENIED",
                engine="DOMESTIC", ref=ref, actor=subject,
                mode="AGRONOMY_ASSIGNED_CASE",
            )
            return result

    def list_assigned_cases(
        self, principal: Principal, *, after_ref: str | None = None,
        limit: int = 20,
    ) -> dict:
        if (type(limit) is not int or not 1 <= limit <= 50
                or after_ref is not None and not _synthetic_ref(after_ref)):
            raise ValueError("invalid synthetic agronomy list request")
        with self.ledger._transaction() as db:
            self.ledger._verify(db)
            subject = self._actor(principal)
            refs = []
            if subject is not None:
                for actor, ref in sorted(self._assignments):
                    if actor != subject or after_ref is not None and ref <= after_ref:
                        continue
                    record = self.ledger._catalogue.get(("DOMESTIC", ref))
                    if (record is None
                            or not self._allowed(subject, ref, record.version)):
                        continue
                    refs.append(ref)
            selected = refs[:limit]
            items = []
            for ref in selected:
                data = self._preview(db, ref)
                items.append({
                    "ref": ref, "engine": "DOMESTIC",
                    "case_version": data["case_version"],
                    "case_status": "DRAFT_ONLY",
                    "technical_review_state": data["technical_review_state"],
                    "plan_state": "NOT_AUTHORED",
                    "agronomist_qualification_verified": False,
                    "plan_accepted": False,
                })
                self.ledger._append(
                    db, kind="READ_ALLOWED", engine="DOMESTIC", ref=ref,
                    actor=subject, mode="AGRONOMY_ASSIGNED_WORKLIST",
                )
            return {
                "engine": "DOMESTIC",
                "items": items,
                "next_cursor": selected[-1] if len(refs) > limit else None,
            }
