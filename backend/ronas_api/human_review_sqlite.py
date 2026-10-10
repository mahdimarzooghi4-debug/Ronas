"""Persistent technical review evidence ONLY, never a Business case decision.

This opt-in, LOCAL/TEST SQLite subclass stores a two-step *technical*
human-evidence review workflow next to the existing transactional grant
ledger. It NEVER changes ScopedDraft.status (DRAFT_ONLY), issues agronomy
advice, accepts licensed Export sources, or authorizes production records.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from typing import Callable, Iterable

from .auth import Principal
from .grant_ledger_sqlite import (
    LedgerIntegrityError, SqliteSyntheticGrantLedger, _hash, _json,
)
from .scoped_audit import GrantConflict, GrantNotAuthorized
from .scoped_drafts import ScopedDraft, _OP_ROLE, _synthetic_ref, _synthetic_subject

REQUESTED = "TECH_REVIEW_REQUESTED"
RECORDED = "TECH_HUMAN_RESPONSE_RECORDED"
STATES = ("UNREQUESTED", "EVIDENCE_REVIEW_REQUESTED", "HUMAN_RESPONSE_RECORDED")


def _review_binding(*, action: str, engine: str, ref: str, revision: int,
                    stage: str, actor_digest: str, request_ref: str,
                    evidence_ref: str, decision_ref: str | None,
                    command_digest: str) -> str:
    # Bound into the append-only audit event itself so changes to either
    # the request, response reference or evidence are detected on reopen.
    return _json({
        "action": action, "engine": engine, "ref": ref, "revision": revision,
        "stage": stage, "actor_digest": actor_digest,
        "request_ref": request_ref, "evidence_ref": evidence_ref,
        "decision_ref": decision_ref, "command_digest": command_digest,
    })


@dataclass(frozen=True, slots=True)
class TechnicalReviewStep:
    engine: str
    ref: str
    revision: int
    stage: str
    action_id: str
    actor_digest: str
    request_ref: str
    evidence_ref: str
    decision_ref: str | None
    audit_sequence: int


class SqliteSyntheticHumanReviewLedger(SqliteSyntheticGrantLedger):
    """One synthetic request + one independently authorized human reference.

    This is not the formal D1 agronomy or E0 source-rights approval workflow.
    No public HTTP decision/transition endpoints are defined.
    """

    def __init__(self, path, records: Iterable[ScopedDraft], *,
                 trusted_revoke_authorizer: Callable[[str, str, str], bool],
                 trusted_human_review_authorizer: Callable[[str, str, str], bool],
                 previous_versions: Iterable[ScopedDraft] = ()):
        if not callable(trusted_human_review_authorizer):
            raise ValueError("explicit independent human-review authority required")
        self._human_authorizer = trusted_human_review_authorizer
        self._review_ready = False
        super().__init__(
            path, records, previous_versions=previous_versions,
            trusted_revoke_authorizer=trusted_revoke_authorizer,
        )
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS technical_review_step (
                    action_id TEXT PRIMARY KEY,
                    engine TEXT NOT NULL,
                    ref TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    actor_digest TEXT NOT NULL,
                    request_ref TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL,
                    decision_ref TEXT,
                    command_digest TEXT NOT NULL,
                    audit_sequence INTEGER NOT NULL UNIQUE,
                    UNIQUE(engine, ref, revision),
                    FOREIGN KEY(audit_sequence) REFERENCES audit_event(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS review_no_update
                BEFORE UPDATE ON technical_review_step
                BEGIN SELECT RAISE(ABORT, 'review history is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS review_no_delete
                BEFORE DELETE ON technical_review_step
                BEGIN SELECT RAISE(ABORT, 'review history is immutable'); END;
            """)
        self._review_ready = True
        with self._transaction() as db:
            self._verify(db)

    def _verify(self, db: sqlite3.Connection) -> None:
        super()._verify(db)
        if not self._review_ready:
            return
        expected_events = {
            int(seq): json.loads(payload)
            for seq, payload in db.execute(
                "SELECT sequence, payload FROM audit_event"
            )
            if json.loads(payload).get("kind") in (REQUESTED, RECORDED)
        }
        linked: set[int] = set()
        by_case: dict[tuple[str, str], list[TechnicalReviewStep]] = {}
        seen_requests: set[str] = set()
        for row in db.execute(
            "SELECT action_id, engine, ref, revision, stage, actor_digest, "
            "request_ref, evidence_ref, decision_ref, command_digest, audit_sequence "
            "FROM technical_review_step ORDER BY audit_sequence"
        ):
            (action, engine, ref, revision, stage, actor_digest,
             request_ref, evidence_ref, decision_ref, command_digest, sequence) = row
            audit = expected_events.get(sequence)
            if (audit is None or sequence in linked
                    or (engine, ref) not in self._catalogue
                    or type(revision) is not int or revision not in (1, 2)
                    or stage not in (REQUESTED, RECORDED)
                    or not all(_synthetic_ref(x) for x in
                               (action, request_ref, evidence_ref))
                    or decision_ref is not None and not _synthetic_ref(decision_ref)
                    or not isinstance(actor_digest, str) or len(actor_digest) != 64
                    or not isinstance(command_digest, str) or len(command_digest) != 64
                    or audit.get("kind") != stage or audit.get("engine") != engine
                    or audit.get("ref") != ref or audit.get("action_id") != action
                    or audit.get("actor_digest") != actor_digest
                    or audit.get("reason_ref") != evidence_ref
                    or audit.get("target_digest") != _hash(_review_binding(
                        action=action, engine=engine, ref=ref, revision=revision,
                        stage=stage, actor_digest=actor_digest,
                        request_ref=request_ref, evidence_ref=evidence_ref,
                        decision_ref=decision_ref, command_digest=command_digest,
                    ))
                    or audit.get("case_version") != self._catalogue[(engine, ref)].version
                    or audit.get("access_mode") != "TECHNICAL_ONLY"):
                raise LedgerIntegrityError("review/audit record mismatch")
            linked.add(sequence)
            step = TechnicalReviewStep(engine, ref, revision, stage, action,
                                       actor_digest, request_ref, evidence_ref,
                                       decision_ref, sequence)
            by_case.setdefault((engine, ref), []).append(step)
            if stage == REQUESTED:
                if decision_ref is not None or request_ref in seen_requests:
                    raise LedgerIntegrityError("invalid technical review request")
                seen_requests.add(request_ref)
            elif decision_ref is None:
                raise LedgerIntegrityError("human response needs external decision ref")
        if linked != set(expected_events):
            raise LedgerIntegrityError("unpaired review audit event")
        for steps in by_case.values():
            if len(steps) > 2:
                raise LedgerIntegrityError("review cycle cannot be repeated")
            if steps[0].stage != REQUESTED or steps[0].revision != 1:
                raise LedgerIntegrityError("human response without request")
            if len(steps) == 2:
                if (steps[1].stage != RECORDED or steps[1].revision != 2
                        or steps[1].request_ref != steps[0].request_ref
                        or steps[1].actor_digest == steps[0].actor_digest):
                    raise LedgerIntegrityError("inconsistent human response lineage")

    def _active_operator(self, db, engine: str, ref: str, principal: Principal) -> bool:
        if (not isinstance(principal, Principal)
                or not _synthetic_subject(principal.subject)
                or engine not in _OP_ROLE
                or _OP_ROLE[engine] not in principal.roles):
            return False
        record = self._catalogue.get((engine, ref))
        if (record is None or not any(g.subject == principal.subject
                                    and g.role == _OP_ROLE[engine]
                                    for g in record.grants)):
            return False
        revoked = db.execute(
            "SELECT 1 FROM grant_revocation WHERE engine=? AND ref=? "
            "AND subject_digest=? AND role=?",
            (engine, ref, _hash(principal.subject), _OP_ROLE[engine]),
        ).fetchone()
        return revoked is None

    def _steps(self, db, engine: str, ref: str) -> list[TechnicalReviewStep]:
        return [
            TechnicalReviewStep(*row)
            for row in db.execute(
                "SELECT engine, ref, revision, stage, action_id, actor_digest, "
                "request_ref, evidence_ref, decision_ref, audit_sequence "
                "FROM technical_review_step WHERE engine=? AND ref=? ORDER BY revision",
                (engine, ref),
            )
        ]

    def review_state(self, engine: str, ref: str) -> dict | None:
        with self._transaction() as db:
            self._verify(db)
            if (engine, ref) not in self._catalogue:
                return None
            steps = self._steps(db, engine, ref)
            return {
                "engine": engine, "ref": ref,
                "case_version": self._catalogue[(engine, ref)].version,
                "case_status": "DRAFT_ONLY",
                "review_revision": len(steps),
                "technical_review_state": STATES[len(steps)],
            }

    def review_history(self, engine: str, ref: str) -> tuple[TechnicalReviewStep, ...]:
        with self._transaction() as db:
            self._verify(db)
            return tuple(self._steps(db, engine, ref))

    def read_review_for_operator(self, engine: str, ref: str,
                                 principal: Principal) -> dict | None:
        """Audit an exact-case, currently authorized technical-history read.

        This opt-in, internal-only facade expects a principal independently
        verified by the Keycloak authentication boundary. It does not verify
        JWT signatures itself, and must not be wired to an unauthenticated
        route. An unrelated role, unassigned operator or revoked grant cannot
        read request/evidence/note references, even with a previously signed
        token. Unknown records are indistinguishable from denied records to
        callers; they cannot create audit events against nonexistent cases.
        """
        with self._transaction() as db:
            self._verify(db)
            if ((engine, ref) not in self._catalogue
                    or not isinstance(principal, Principal)
                    or not _synthetic_subject(principal.subject)):
                return None
            allowed = self._active_operator(db, engine, ref, principal)
            # The decision and append are in the same BEGIN IMMEDIATE
            # transaction, preventing a concurrent grant revocation from
            # racing between the permission check and the read.
            if allowed:
                steps = self._steps(db, engine, ref)
                result = {
                    "engine": engine,
                    "ref": ref,
                    "case_version": self._catalogue[(engine, ref)].version,
                    "case_status": "DRAFT_ONLY",
                    "review_revision": len(steps),
                    "technical_review_state": STATES[len(steps)],
                    "history": tuple({
                        "revision": step.revision,
                        "stage": step.stage,
                        "request_ref": step.request_ref,
                        "evidence_ref": step.evidence_ref,
                        "decision_ref": step.decision_ref,
                        "audit_sequence": step.audit_sequence,
                    } for step in steps),
                }
            else:
                result = None
            self._append(
                db, kind="READ_ALLOWED" if allowed else "READ_DENIED",
                engine=engine, ref=ref, actor=principal.subject,
                mode="TECHNICAL_REVIEW_HISTORY",
            )
            return result

    def _apply(self, *, stage: str, engine: str, ref: str, actor: Principal,
               expected_case_version: int, expected_review_revision: int,
               action_id: str, request_ref: str, evidence_ref: str,
               decision_ref: str | None) -> TechnicalReviewStep:
        if (engine not in _OP_ROLE or not _synthetic_ref(ref)
                or not _synthetic_ref(action_id) or not _synthetic_ref(request_ref)
                or not _synthetic_ref(evidence_ref)
                or stage not in (REQUESTED, RECORDED)
                or stage == REQUESTED and decision_ref is not None
                or stage == RECORDED and not _synthetic_ref(decision_ref)
                or type(expected_case_version) is not int
                or type(expected_review_revision) is not int
                or expected_review_revision != (0 if stage == REQUESTED else 1)):
            raise ValueError("invalid synthetic human-evidence command")
        if not isinstance(actor, Principal) or not _synthetic_subject(actor.subject):
            raise GrantNotAuthorized("a verified synthetic principal is necessary")
        with self._transaction() as db:
            self._verify(db)
            record = self._catalogue.get((engine, ref))
            if (record is None or record.version != expected_case_version
                    or not self._active_operator(db, engine, ref, actor)):
                raise GrantNotAuthorized("signed case-specific role and current version required")
            if stage == RECORDED:
                try:
                    permitted = self._human_authorizer(actor.subject, engine, ref)
                except Exception as exc:
                    raise GrantNotAuthorized("independent human authorizer failed") from exc
                if permitted is not True:
                    raise GrantNotAuthorized("independent human authorization required")
            data = {
                "stage": stage, "engine": engine, "ref": ref, "actor": actor.subject,
                "case_version": expected_case_version,
                "review_revision": expected_review_revision,
                "action_id": action_id, "request_ref": request_ref,
                "evidence_ref": evidence_ref, "decision_ref": decision_ref,
            }
            command_digest = _hash(_json(data))
            replay = db.execute(
                "SELECT command_digest FROM technical_review_step WHERE action_id=?",
                (action_id,),
            ).fetchone()
            if replay is not None:
                if replay[0] != command_digest:
                    raise GrantConflict("changed human-evidence action replay")
                return next(step for step in self._steps(db, engine, ref)
                            if step.action_id == action_id)
            steps = self._steps(db, engine, ref)
            if len(steps) != expected_review_revision:
                raise GrantConflict("stale technical review revision")
            if stage == RECORDED and (
                len(steps) != 1 or steps[0].request_ref != request_ref
                or steps[0].actor_digest == _hash(actor.subject)
            ):
                raise GrantConflict("human response lacks independent matching request")
            if stage == REQUESTED and steps:
                raise GrantConflict("review already requested")
            event = self._append(
                db, kind=stage, engine=engine, ref=ref, actor=actor.subject,
                action_id=action_id, reason_ref=evidence_ref,
                target=_review_binding(
                    action=action_id, engine=engine, ref=ref,
                    revision=expected_review_revision + 1, stage=stage,
                    actor_digest=_hash(actor.subject), request_ref=request_ref,
                    evidence_ref=evidence_ref, decision_ref=decision_ref,
                    command_digest=command_digest,
                ), mode="TECHNICAL_ONLY",
            )
            db.execute(
                "INSERT INTO technical_review_step VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (action_id, engine, ref, expected_review_revision + 1, stage,
                 _hash(actor.subject), request_ref, evidence_ref, decision_ref,
                 command_digest, event.sequence),
            )
            return TechnicalReviewStep(
                engine, ref, expected_review_revision + 1, stage, action_id,
                _hash(actor.subject), request_ref, evidence_ref,
                decision_ref, event.sequence,
            )

    def request_evidence_review(self, *, engine: str, ref: str, actor: Principal,
                                expected_case_version: int,
                                expected_review_revision: int, action_id: str,
                                request_ref: str, evidence_ref: str) -> TechnicalReviewStep:
        return self._apply(
            stage=REQUESTED, engine=engine, ref=ref, actor=actor,
            expected_case_version=expected_case_version,
            expected_review_revision=expected_review_revision,
            action_id=action_id, request_ref=request_ref,
            evidence_ref=evidence_ref, decision_ref=None,
        )

    def record_human_response(self, *, engine: str, ref: str, actor: Principal,
                              expected_case_version: int,
                              expected_review_revision: int,
                              action_id: str, request_ref: str,
                              evidence_ref: str, decision_ref: str) -> TechnicalReviewStep:
        return self._apply(
            stage=RECORDED, engine=engine, ref=ref, actor=actor,
            expected_case_version=expected_case_version,
            expected_review_revision=expected_review_revision,
            action_id=action_id, request_ref=request_ref,
            evidence_ref=evidence_ref, decision_ref=decision_ref,
        )
