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
from .export_research_question import (
    RECORDED as EXPORT_QUESTION_RECORDED, ExportResearchQuestionConflict,
    question_binding, question_digest, question_preview, valid_question_refs,
)
from .export_research_evidence import (
    RECORDED as EXPORT_EVIDENCE_RECORDED, ExportEvidenceReferenceConflict,
    evidence_binding, evidence_digest, evidence_preview, valid_evidence_refs,
    valid_snapshot_digest,
)
from .domestic_preparation_preview import domestic_preparation_preview
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
                CREATE TABLE IF NOT EXISTS export_research_question_draft (
                    action_id TEXT PRIMARY KEY,
                    ref TEXT NOT NULL, case_version INTEGER NOT NULL,
                    revision INTEGER NOT NULL, actor_digest TEXT NOT NULL,
                    source_ref TEXT NOT NULL, product_ref TEXT NOT NULL,
                    destination_ref TEXT NOT NULL, command_digest TEXT NOT NULL,
                    audit_sequence INTEGER NOT NULL UNIQUE,
                    UNIQUE(ref, revision),
                    FOREIGN KEY(audit_sequence) REFERENCES audit_event(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS export_question_no_update
                BEFORE UPDATE ON export_research_question_draft
                BEGIN SELECT RAISE(ABORT, 'question history immutable'); END;
                CREATE TRIGGER IF NOT EXISTS export_question_no_delete
                BEFORE DELETE ON export_research_question_draft
                BEGIN SELECT RAISE(ABORT, 'question history immutable'); END;
                CREATE TABLE IF NOT EXISTS export_research_evidence_reference (
                    action_id TEXT PRIMARY KEY,
                    ref TEXT NOT NULL, case_version INTEGER NOT NULL,
                    question_revision INTEGER NOT NULL, revision INTEGER NOT NULL,
                    actor_digest TEXT NOT NULL, source_ref TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL, connector_ref TEXT NOT NULL,
                    source_snapshot_digest TEXT NOT NULL,
                    command_digest TEXT NOT NULL, audit_sequence INTEGER NOT NULL UNIQUE,
                    UNIQUE(ref, question_revision, revision),
                    FOREIGN KEY(audit_sequence) REFERENCES audit_event(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS export_evidence_no_update
                BEFORE UPDATE ON export_research_evidence_reference
                BEGIN SELECT RAISE(ABORT, 'evidence reference history immutable'); END;
                CREATE TRIGGER IF NOT EXISTS export_evidence_no_delete
                BEFORE DELETE ON export_research_evidence_reference
                BEGIN SELECT RAISE(ABORT, 'evidence reference history immutable'); END;
            """)
        self._review_ready = True
        with self._transaction() as db:
            self._verify(db)

    def _extended_audit_kinds(self) -> frozenset[str]:
        return super()._extended_audit_kinds() | frozenset({
            EXPORT_QUESTION_RECORDED, EXPORT_EVIDENCE_RECORDED,
        })

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

        question_triggers = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='export_research_question_draft'"
        )}
        if question_triggers != {
            "export_question_no_update", "export_question_no_delete",
        }:
            raise LedgerIntegrityError("Export question immutable triggers missing")
        expected_questions = {
            int(seq): json.loads(payload)
            for seq, payload in db.execute(
                "SELECT sequence,payload FROM audit_event"
            )
            if json.loads(payload).get("kind") == EXPORT_QUESTION_RECORDED
        }
        paired_questions = set()
        question_revisions = {}
        for row in db.execute(
            "SELECT action_id,ref,case_version,revision,actor_digest,"
            "source_ref,product_ref,destination_ref,command_digest,"
            "audit_sequence FROM export_research_question_draft "
            "ORDER BY audit_sequence"
        ):
            (action, ref, case_version, revision, actor_digest, source_ref,
             product_ref, destination_ref, digest, sequence) = row
            record = self._catalogue.get(("EXPORT", ref))
            event = expected_questions.get(sequence)
            try:
                binding = question_binding(
                    action_id=action, ref=ref, case_version=case_version,
                    revision=revision, actor_digest=actor_digest,
                    source_ref=source_ref, product_ref=product_ref,
                    destination_ref=destination_ref,
                )
            except (ValueError, TypeError) as exc:
                raise LedgerIntegrityError("invalid Export question row") from exc
            prior = question_revisions.get(ref, 0)
            if (record is None or record.version != case_version
                    or source_ref != record.source_ref
                    or revision != prior + 1
                    or event is None or sequence in paired_questions
                    or question_digest(binding) != digest
                    or event.get("kind") != EXPORT_QUESTION_RECORDED
                    or event.get("engine") != "EXPORT"
                    or event.get("ref") != ref
                    or event.get("case_version") != case_version
                    or event.get("action_id") != action
                    or event.get("actor_digest") != actor_digest
                    or event.get("reason_ref") != source_ref
                    or event.get("target_digest") != digest
                    or event.get("access_mode") != "LOCAL_TEST_QUESTION_DRAFT"):
                raise LedgerIntegrityError(
                    "Export question/audit/source/version mismatch"
                )
            question_revisions[ref] = revision
            paired_questions.add(sequence)
        if paired_questions != set(expected_questions):
            raise LedgerIntegrityError("orphan Export question audit event")

        evidence_triggers = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='export_research_evidence_reference'"
        )}
        if evidence_triggers != {
            "export_evidence_no_update", "export_evidence_no_delete",
        }:
            raise LedgerIntegrityError("Export evidence immutable triggers missing")
        expected_evidence = {
            int(seq): json.loads(payload)
            for seq, payload in db.execute(
                "SELECT sequence,payload FROM audit_event"
            )
            if json.loads(payload).get("kind") == EXPORT_EVIDENCE_RECORDED
        }
        paired_evidence: set[int] = set()
        evidence_revisions: dict[tuple[str, int], int] = {}
        for row in db.execute(
            "SELECT action_id,ref,case_version,question_revision,revision,"
            "actor_digest,source_ref,evidence_ref,connector_ref,"
            "source_snapshot_digest,command_digest,audit_sequence "
            "FROM export_research_evidence_reference ORDER BY audit_sequence"
        ):
            (action, ref, case_version, question_revision, revision,
             actor_digest, source_ref, evidence_ref, connector_ref,
             snapshot_digest, digest, sequence) = row
            record = self._catalogue.get(("EXPORT", ref))
            question = db.execute(
                "SELECT case_version,source_ref FROM export_research_question_draft "
                "WHERE ref=? AND revision=?", (ref, question_revision),
            ).fetchone()
            event = expected_evidence.get(sequence)
            prior = evidence_revisions.get((ref, question_revision), 0)
            try:
                binding = evidence_binding(
                    action_id=action, ref=ref, case_version=case_version,
                    question_revision=question_revision, revision=revision,
                    actor_digest=actor_digest, source_ref=source_ref,
                    evidence_ref=evidence_ref, connector_ref=connector_ref,
                    snapshot_digest=snapshot_digest,
                )
            except (ValueError, TypeError) as exc:
                raise LedgerIntegrityError("invalid Export evidence reference") from exc
            if (record is None or case_version != record.version
                    or question is None or question[0] != case_version
                    or question[1] != source_ref or revision != prior + 1
                    or event is None or sequence in paired_evidence
                    or evidence_digest(binding) != digest
                    or event.get("kind") != EXPORT_EVIDENCE_RECORDED
                    or event.get("engine") != "EXPORT" or event.get("ref") != ref
                    or event.get("case_version") != case_version
                    or event.get("action_id") != action
                    or event.get("actor_digest") != actor_digest
                    or event.get("reason_ref") != evidence_ref
                    or event.get("target_digest") != digest
                    or event.get("access_mode") != "EXPORT_EVIDENCE_REFERENCE_DRAFT"):
                raise LedgerIntegrityError(
                    "Export evidence/question/audit binding mismatch"
                )
            evidence_revisions[(ref, question_revision)] = revision
            paired_evidence.add(sequence)
        if paired_evidence != set(expected_evidence):
            raise LedgerIntegrityError("orphan Export evidence audit event")

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

    def list_owned_domestic_progress(
        self, principal: Principal, *, after_ref: str | None = None,
        limit: int = 20, technical_state: str = "ALL",
    ) -> dict:
        """One verified, audited snapshot of an owner's observed DEMO progress.

        This read-only projection uses the identical ledger transaction for
        exact immutable ownership, per-case technical history and per-row
        audit. It must never expose reviewer identities or evidence references
        and cannot imply Business acceptance from a technical human response.
        """
        if (type(limit) is not int or not 1 <= limit <= 50
                or after_ref is not None and not _synthetic_ref(after_ref)
                or technical_state not in ("ALL", *STATES)):
            raise ValueError("invalid synthetic progress list query")
        with self._transaction() as db:
            self._verify(db)
            items: list[dict] = []
            next_cursor = None
            if (isinstance(principal, Principal)
                    and _synthetic_subject(principal.subject)
                    and "household" in principal.roles):
                owned = [
                    ref for (engine, ref), record in sorted(self._catalogue.items())
                    if engine == "DOMESTIC"
                    and record.owner_subject == principal.subject
                    and (after_ref is None or ref > after_ref)
                ]
                matching: list[tuple[str, list[TechnicalReviewStep]]] = []
                for ref in owned:
                    steps = self._steps(db, "DOMESTIC", ref)
                    if (technical_state == "ALL"
                            or STATES[len(steps)] == technical_state):
                        matching.append((ref, steps))
                for ref, steps in matching[:limit]:
                    record = self._catalogue[("DOMESTIC", ref)]
                    item = record.public_view()
                    item.update({
                        "review_revision": len(steps),
                        "technical_review_state": STATES[len(steps)],
                    })
                    items.append(item)
                    # Disclosure and event insertion are in one transaction:
                    # if any audit append fails, the entire page fails.
                    self._append(
                        db, kind="READ_ALLOWED", engine="DOMESTIC",
                        ref=ref, actor=principal.subject,
                        mode="HOUSEHOLD_PROGRESS_WORKLIST",
                    )
                if len(matching) > limit:
                    next_cursor = items[-1]["ref"]
            return {
                "engine": "DOMESTIC",
                "technical_state_filter": technical_state,
                "items": items,
                "next_cursor": next_cursor,
            }

    def read_owned_domestic_status(self, ref: str,
                                   principal: Principal) -> dict | None:
        """Expose minimal observed technical progress to the exact owner.

        This internal facade requires a *previously Keycloak-verified*
        principal; a Python Principal alone is never authentication.
        Request/evidence/decision refs, reviewer IDs and audit internals
        remain private to the independently authorized operator view.
        """
        with self._transaction() as db:
            self._verify(db)
            record = self._catalogue.get(("DOMESTIC", ref))
            if (record is None or not _synthetic_ref(ref)
                    or not isinstance(principal, Principal)
                    or not _synthetic_subject(principal.subject)):
                return None
            allowed = (
                "household" in principal.roles
                and principal.subject == record.owner_subject
            )
            if allowed:
                steps = self._steps(db, "DOMESTIC", ref)
                result = record.public_view()
                result.update({
                    "review_revision": len(steps),
                    "technical_review_state": STATES[len(steps)],
                    "cultivation_preparation": domestic_preparation_preview(
                        case_version=record.version,
                        review_revision=len(steps),
                        technical_review_state=STATES[len(steps)],
                        valid_review_states=STATES,
                        observed_review_steps=tuple(
                            step.stage for step in steps
                        ),
                    ),
                })
            else:
                result = None
            # Audited in the SAME transaction as the owner decision.
            self._append(
                db, kind="READ_ALLOWED" if allowed else "READ_DENIED",
                engine="DOMESTIC", ref=ref, actor=principal.subject,
                mode="HOUSEHOLD_TECHNICAL_STATUS",
            )
            return result

    def list_export_research_cases(
        self, principal: Principal, *, technical_state: str = "ALL",
        after_ref: str | None = None, limit: int = 20,
    ) -> dict:
        """One audited, exact-grant Export research queue for LOCAL/TEST.

        The filter is *technical review state*, never an inferred research
        result, research readiness, Business approval, buyer or trade state.
        Apply current grants and the requested filter BEFORE pagination.
        Unknown and unassigned cases never influence cursor or counts.
        """
        choices = frozenset({"ALL", *STATES})
        if (technical_state not in choices
                or type(limit) is not int or not 1 <= limit <= 50
                or after_ref is not None and not _synthetic_ref(after_ref)):
            raise ValueError("invalid synthetic Export research queue query")
        with self._transaction() as db:
            self._verify(db)
            selected: list[tuple[str, int, str, int]] = []
            if (isinstance(principal, Principal)
                    and _synthetic_subject(principal.subject)
                    and "export_ops" in principal.roles):
                for (engine, ref), record in sorted(self._catalogue.items()):
                    if (engine != "EXPORT"
                            or after_ref is not None and ref <= after_ref
                            or not self._active_operator(db, "EXPORT", ref, principal)):
                        continue
                    steps = self._steps(db, "EXPORT", ref)
                    observed = STATES[len(steps)]
                    if technical_state == "ALL" or observed == technical_state:
                        selected.append((ref, record.version, observed, len(steps)))
            items = []
            for ref, version, state, revision in selected[:limit]:
                items.append({
                    "ref": ref, "engine": "EXPORT",
                    "case_version": version,
                    "case_status": "DRAFT_ONLY",
                    "technical_review_state": state,
                    "review_revision": revision,
                    "research_question_defined": False,
                    "source_rights_verified": False,
                    "research_report_approved": False,
                    "business_actions_enabled": False,
                })
                self._append(
                    db, kind="READ_ALLOWED", engine="EXPORT", ref=ref,
                    actor=principal.subject, mode="EXPORT_RESEARCH_CASE_QUEUE",
                )
            return {
                "engine": "EXPORT",
                "technical_state_filter": technical_state,
                "items": items,
                "next_cursor": items[-1]["ref"] if len(selected) > limit else None,
            }

    def _current_export_question(self, db, ref: str) -> dict | None:
        row = db.execute(
            "SELECT revision,source_ref,product_ref,destination_ref "
            "FROM export_research_question_draft WHERE ref=? "
            "ORDER BY revision DESC LIMIT 1", (ref,),
        ).fetchone()
        if row is None:
            return None
        record = self._catalogue[("EXPORT", ref)]
        return question_preview(
            ref=ref, case_version=record.version, revision=row[0],
            source_ref=row[1], product_ref=row[2], destination_ref=row[3],
        )

    def _export_question_history(self, db, ref: str) -> list[dict]:
        """Already verified append-only DEMO question revisions, no audit internals.

        This must be called ONLY from the same grant-checked and integrity-
        verified transaction as the authorized Export workspace read.
        """
        rows = list(db.execute(
            "SELECT revision,product_ref,destination_ref "
            "FROM export_research_question_draft WHERE ref=? "
            "ORDER BY revision", (ref,),
        ))
        if any(row[0] != position for position, row in enumerate(rows, 1)):
            raise LedgerIntegrityError("Export draft revision history mismatch")
        latest = rows[-1][0] if rows else None
        return [
            {
                "question_revision": revision,
                "product_ref": product,
                "destination_ref": destination,
                "is_current": revision == latest,
                "question_state": "UNVERIFIED_LOCAL_TEST_DRAFT",
            }
            for revision, product, destination in rows
        ]

    def record_export_research_question(
        self, ref: str, principal: Principal, *,
        expected_case_version: int, expected_question_revision: int,
        action_id: str, product_ref: str, destination_ref: str,
    ) -> dict | None:
        """One versioned DEMO question and audit event in existing case DB."""
        if not _synthetic_ref(ref):
            return None
        if (type(expected_case_version) is not int
                or type(expected_question_revision) is not int
                or expected_question_revision < 0
                or not _synthetic_ref(action_id)
                or not valid_question_refs(product_ref, destination_ref)):
            raise ValueError("invalid DEMO export question command")
        with self._transaction() as db:
            self._verify(db)
            record = self._catalogue.get(("EXPORT", ref))
            if (record is None
                    or not self._active_operator(db, "EXPORT", ref, principal)):
                return None
            if record.version != expected_case_version:
                raise ExportResearchQuestionConflict("stale Export case version")
            current = db.execute(
                "SELECT COALESCE(MAX(revision),0) "
                "FROM export_research_question_draft WHERE ref=?", (ref,),
            ).fetchone()[0]
            replay = db.execute(
                "SELECT ref,case_version,revision,actor_digest,source_ref,"
                "product_ref,destination_ref FROM export_research_question_draft "
                "WHERE action_id=?", (action_id,),
            ).fetchone()
            if replay is not None:
                if (replay != (
                        ref, record.version, expected_question_revision + 1,
                        _hash(principal.subject), record.source_ref,
                        product_ref, destination_ref,
                    ) or current != replay[2]):
                    raise ExportResearchQuestionConflict(
                        "stale or conflicting question action"
                    )
                return self._current_export_question(db, ref)
            if expected_question_revision != current:
                raise ExportResearchQuestionConflict("stale question revision")
            revision = current + 1
            binding = question_binding(
                action_id=action_id, ref=ref, case_version=record.version,
                revision=revision, actor_digest=_hash(principal.subject),
                source_ref=record.source_ref, product_ref=product_ref,
                destination_ref=destination_ref,
            )
            digest = question_digest(binding)
            event = self._append(
                db, kind=EXPORT_QUESTION_RECORDED, engine="EXPORT",
                ref=ref, actor=principal.subject, action_id=action_id,
                reason_ref=record.source_ref,
                target=_json(binding), mode="LOCAL_TEST_QUESTION_DRAFT",
            )
            db.execute(
                "INSERT INTO export_research_question_draft "
                "(action_id,ref,case_version,revision,actor_digest,source_ref,"
                "product_ref,destination_ref,command_digest,audit_sequence) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (action_id, ref, record.version, revision,
                 _hash(principal.subject), record.source_ref, product_ref,
                 destination_ref, digest, event.sequence),
            )
            self._verify(db)
            return self._current_export_question(db, ref)

    def _export_evidence_reference_history(
        self, db: sqlite3.Connection, ref: str, current_question_revision: int,
    ) -> list[dict]:
        rows = db.execute(
            "SELECT case_version,question_revision,revision,source_ref,"
            "evidence_ref,connector_ref,source_snapshot_digest "
            "FROM export_research_evidence_reference WHERE ref=? "
            "ORDER BY question_revision,revision", (ref,),
        )
        return [
            evidence_preview(
                ref=ref, case_version=row[0], question_revision=row[1],
                revision=row[2], source_ref=row[3], evidence_ref=row[4],
                connector_ref=row[5], snapshot_digest=row[6],
                current_question=row[1] == current_question_revision,
            )
            for row in rows
        ]

    def replay_export_evidence_capture(
        self, ref: str, principal: Principal, *,
        expected_case_version: int, expected_question_revision: int,
        expected_evidence_revision: int, action_id: str, connector_ref: str,
    ) -> tuple[bool, dict | None]:
        """Resolve a committed capture retry before fetching external bytes."""
        if (not _synthetic_ref(ref)
                or type(expected_case_version) is not int
                or type(expected_question_revision) is not int
                or expected_question_revision < 1
                or type(expected_evidence_revision) is not int
                or expected_evidence_revision < 0
                or not _synthetic_ref(action_id)
                or not _synthetic_ref(connector_ref)
                or not connector_ref.startswith("DEMO-CONNECTOR-")):
            raise ValueError("invalid DEMO Export capture retry")
        with self._transaction() as db:
            self._verify(db)
            record = self._catalogue.get(("EXPORT", ref))
            if (record is None
                    or not self._active_operator(db, "EXPORT", ref, principal)):
                return True, None
            if record.version != expected_case_version:
                raise ExportEvidenceReferenceConflict("stale Export case version")
            question = self._current_export_question(db, ref)
            if (question is None
                    or question["question_revision"] != expected_question_revision):
                raise ExportEvidenceReferenceConflict("stale Export question revision")
            replay = db.execute(
                "SELECT ref,case_version,question_revision,revision,actor_digest,"
                "source_ref,connector_ref FROM export_research_evidence_reference "
                "WHERE action_id=?", (action_id,),
            ).fetchone()
            if replay is None:
                return False, None
            current = db.execute(
                "SELECT COALESCE(MAX(revision),0) "
                "FROM export_research_evidence_reference "
                "WHERE ref=? AND question_revision=?",
                (ref, expected_question_revision),
            ).fetchone()[0]
            if (replay != (
                    ref, record.version, expected_question_revision,
                    expected_evidence_revision + 1, _hash(principal.subject),
                    record.source_ref, connector_ref,
                ) or current != replay[3]):
                raise ExportEvidenceReferenceConflict(
                    "stale or conflicting evidence-capture action",
                )
            history = self._export_evidence_reference_history(
                db, ref, expected_question_revision,
            )
            return True, history[-1]

    def record_export_evidence_reference(
        self, ref: str, principal: Principal, *,
        expected_case_version: int, expected_question_revision: int,
        expected_evidence_revision: int, action_id: str, evidence_ref: str,
        connector_ref: str, source_snapshot_digest: str,
    ) -> dict | None:
        """Append an opaque connector fingerprint to the exact current DEMO question."""
        if (not _synthetic_ref(ref)
                or type(expected_case_version) is not int
                or type(expected_question_revision) is not int
                or expected_question_revision < 1
                or type(expected_evidence_revision) is not int
                or expected_evidence_revision < 0
                or not _synthetic_ref(action_id)
                or not valid_evidence_refs(evidence_ref, connector_ref)
                or not valid_snapshot_digest(source_snapshot_digest)):
            raise ValueError("invalid DEMO Export evidence-reference command")
        with self._transaction() as db:
            self._verify(db)
            record = self._catalogue.get(("EXPORT", ref))
            if (record is None
                    or not self._active_operator(db, "EXPORT", ref, principal)):
                return None
            if record.version != expected_case_version:
                raise ExportEvidenceReferenceConflict("stale Export case version")
            question = self._current_export_question(db, ref)
            if (question is None
                    or question["question_revision"] != expected_question_revision):
                raise ExportEvidenceReferenceConflict("stale Export question revision")
            current = db.execute(
                "SELECT COALESCE(MAX(revision),0) "
                "FROM export_research_evidence_reference "
                "WHERE ref=? AND question_revision=?",
                (ref, expected_question_revision),
            ).fetchone()[0]
            actor_digest = _hash(principal.subject)
            replay = db.execute(
                "SELECT ref,case_version,question_revision,revision,actor_digest,"
                "source_ref,evidence_ref,connector_ref,source_snapshot_digest "
                "FROM export_research_evidence_reference WHERE action_id=?",
                (action_id,),
            ).fetchone()
            if replay is not None:
                if (replay != (
                        ref, record.version, expected_question_revision,
                        expected_evidence_revision + 1, actor_digest,
                        record.source_ref, evidence_ref, connector_ref,
                        source_snapshot_digest,
                    ) or current != replay[3]):
                    raise ExportEvidenceReferenceConflict(
                        "stale or conflicting evidence-reference action"
                    )
                history = self._export_evidence_reference_history(
                    db, ref, expected_question_revision,
                )
                return history[-1]
            if expected_evidence_revision != current:
                raise ExportEvidenceReferenceConflict("stale evidence revision")
            revision = current + 1
            binding = evidence_binding(
                action_id=action_id, ref=ref, case_version=record.version,
                question_revision=expected_question_revision, revision=revision,
                actor_digest=actor_digest, source_ref=record.source_ref,
                evidence_ref=evidence_ref, connector_ref=connector_ref,
                snapshot_digest=source_snapshot_digest,
            )
            digest = evidence_digest(binding)
            event = self._append(
                db, kind=EXPORT_EVIDENCE_RECORDED, engine="EXPORT",
                ref=ref, actor=principal.subject, action_id=action_id,
                reason_ref=evidence_ref, target=_json(binding),
                mode="EXPORT_EVIDENCE_REFERENCE_DRAFT",
            )
            db.execute(
                "INSERT INTO export_research_evidence_reference "
                "(action_id,ref,case_version,question_revision,revision,"
                "actor_digest,source_ref,evidence_ref,connector_ref,"
                "source_snapshot_digest,command_digest,audit_sequence) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (action_id, ref, record.version, expected_question_revision,
                 revision, actor_digest, record.source_ref, evidence_ref,
                 connector_ref, source_snapshot_digest, digest, event.sequence),
            )
            self._verify(db)
            return self._export_evidence_reference_history(
                db, ref, expected_question_revision,
            )[-1]

    def read_export_research_workspace(
        self, ref: str, principal: Principal,
    ) -> dict | None:
        """One audited, grant-scoped EXPORT research DEMO snapshot.

        This is not a real market study or a report decision. An immutable
        synthetic source *reference* is not evidence of permission to use it.
        Product, destination, HS, findings and an actual buyer are UNKNOWN,
        never inferred from the reference or a technical human response.
        """
        if not _synthetic_ref(ref):
            return None
        with self._transaction() as db:
            self._verify(db)
            record = self._catalogue.get(("EXPORT", ref))
            if (record is None or not isinstance(principal, Principal)
                    or not _synthetic_subject(principal.subject)):
                return None
            allowed = self._active_operator(db, "EXPORT", ref, principal)
            if allowed:
                steps = self._steps(db, "EXPORT", ref)
                versions = tuple(row[0] for row in db.execute(
                    "SELECT version FROM case_history "
                    "WHERE engine='EXPORT' AND ref=? ORDER BY version", (ref,),
                ))
                if (versions != self._histories[("EXPORT", ref)]
                        or not versions or versions[-1] != record.version):
                    raise LedgerIntegrityError("synthetic Export version drift")
                result = {
                    "ref": ref,
                    "engine": "EXPORT",
                    "case_version": record.version,
                    "known_versions": list(versions),
                    "case_status": "DRAFT_ONLY",
                    "source": "SYNTHETIC_ONLY",
                    "source_ref": record.source_ref,
                    "research_question": {
                        "product": None,
                        "destination": None,
                        "hs_code": None,
                    },
                    "study_findings": None,
                    # Explicit DEMO question does not turn any original
                    # verified market fields into known research results.
                    "local_test_draft_question": (
                        self._current_export_question(db, ref)
                    ),
                    "local_test_question_history": (
                        self._export_question_history(db, ref)
                    ),
                    "local_test_evidence_references": (
                        self._export_evidence_reference_history(
                            db, ref,
                            (self._current_export_question(db, ref) or {})
                            .get("question_revision", 0),
                        )
                    ),
                    "review_revision": len(steps),
                    "technical_review_state": STATES[len(steps)],
                    "technical_review_steps": [
                        {"revision": step.revision, "stage": step.stage}
                        for step in steps
                    ],
                    "source_rights_verified": False,
                    "research_report_approved": False,
                    "buyer_verified": False,
                    "contracted": False,
                    "real_data": False,
                    "business_actions_enabled": False,
                }
            else:
                result = None
            # The active grant, full-historical verification, redacted view
            # and append-only read audit are one serialized transaction.
            self._append(
                db, kind="READ_ALLOWED" if allowed else "READ_DENIED",
                engine="EXPORT", ref=ref, actor=principal.subject,
                mode="EXPORT_RESEARCH_WORKSPACE",
            )
            return result

    def read_export_research_version_history(
        self, ref: str, principal: Principal,
    ) -> dict | None:
        """Current-grant Export DEMO version lineage, without inferred edits.

        Only immutable preseeded version numbers are returned; no times,
        source content, historic grant claims, reviewer or market findings.
        """
        if not _synthetic_ref(ref):
            return None
        with self._transaction() as db:
            self._verify(db)
            record = self._catalogue.get(("EXPORT", ref))
            if (record is None or not isinstance(principal, Principal)
                    or not _synthetic_subject(principal.subject)):
                return None
            allowed = self._active_operator(db, "EXPORT", ref, principal)
            if allowed:
                versions = tuple(row[0] for row in db.execute(
                    "SELECT version FROM case_history "
                    "WHERE engine='EXPORT' AND ref=? ORDER BY version",
                    (ref,),
                ))
                if (versions != self._histories[("EXPORT", ref)]
                        or not versions or versions[-1] != record.version):
                    raise LedgerIntegrityError("Export case history drift")
                result = {
                    "ref": ref,
                    "engine": "EXPORT",
                    "case_version": record.version,
                    "case_status": "DRAFT_ONLY",
                    "source": "SYNTHETIC_ONLY",
                    "history_source": "PRESEEDED_IMMUTABLE_FIXTURES",
                    "version_numbers": list(versions),
                    "versions": [
                        {
                            "version": version,
                            "is_current": version == record.version,
                            "case_status": "DRAFT_ONLY",
                        }
                        for version in versions
                    ],
                    "source_rights_verified": False,
                    "research_report_approved": False,
                    "buyer_verified": False,
                    "contracted": False,
                    "real_data": False,
                    "business_actions_enabled": False,
                }
            else:
                result = None
            self._append(
                db, kind="READ_ALLOWED" if allowed else "READ_DENIED",
                engine="EXPORT", ref=ref, actor=principal.subject,
                mode="EXPORT_RESEARCH_VERSION_HISTORY",
            )
            return result

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

    def list_technical_review_worklist(
        self, engine: str, principal: Principal, *,
        after_ref: str | None = None, limit: int = 20,
    ) -> dict:
        """Bounded, exact-grant filtered technical queue for an operator.

        Only current grants on immutable DEMO case seeds are considered.
        A single SQLite transaction verifies, selects, and audits every
        disclosed item. Keyset pagination walks *authorized* refs only;
        unrelated refs, counts, evidence and human-note contents never
        enter the response. This does not create a Business work queue,
        assessment or authorization to decide a case.
        """
        if (engine not in _OP_ROLE or type(limit) is not int
                or not 1 <= limit <= 50
                or after_ref is not None and not _synthetic_ref(after_ref)):
            raise ValueError("invalid synthetic worklist query")
        with self._transaction() as db:
            self._verify(db)
            items: list[dict] = []
            if (isinstance(principal, Principal)
                    and _synthetic_subject(principal.subject)
                    and _OP_ROLE[engine] in principal.roles):
                visible = [
                    ref for candidate_engine, ref in sorted(self._catalogue)
                    if candidate_engine == engine
                    and (after_ref is None or ref > after_ref)
                    and self._active_operator(db, engine, ref, principal)
                ]
                page = visible[:limit]
                for ref in page:
                    steps = self._steps(db, engine, ref)
                    items.append({
                        "ref": ref,
                        "engine": engine,
                        "case_version": self._catalogue[(engine, ref)].version,
                        "case_status": "DRAFT_ONLY",
                        "review_revision": len(steps),
                        "technical_review_state": STATES[len(steps)],
                    })
                    # Audit only disclosed items, not hidden/other-engine
                    # cases. If any append fails the entire page fails.
                    self._append(
                        db, kind="READ_ALLOWED", engine=engine,
                        ref=ref, actor=principal.subject,
                        mode="TECHNICAL_REVIEW_WORKLIST",
                    )
                next_cursor = page[-1] if len(visible) > limit else None
            else:
                next_cursor = None
            return {
                "engine": engine,
                "items": items,
                "next_cursor": next_cursor,
            }

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
