"""Append-only synthetic *questions*, not expert findings or approvals.

This LOCAL/TEST ledger extends the exact auditable household case/input
repository. A question captures immutable DEMO refs to missing evidence for
one of three independent review tracks. All question content is external;
no real household data, consent, professional decision or crop is collected.
"""
from __future__ import annotations

import json
import sqlite3

from .grant_ledger_sqlite import GENESIS, LedgerIntegrityError, _hash, _json
from .household_input_ledger_sqlite import SqliteSyntheticHouseholdInputLedger
from .internal_cultivation_plan_contract import _digest
from .scoped_drafts import _synthetic_ref

EVENT = "SYNTHETIC_EXPERT_REVIEW_QUESTION_RECORDED"
MODE = "SYNTHETIC_EXPERT_REVIEW_QUESTION_SHA256:"
TRACKS = (
    "HOUSEHOLD_INPUT_ADEQUACY",
    "SCIENTIFIC_BASIS_AND_USE_RIGHTS",
    "INDIVIDUAL_CULTIVATION_PROPOSAL",
)
VERSION = "ronas.domestic.synthetic-expert-review-questions.v0"


class ReviewQuestionConflict(ValueError):
    """Changed case/input/evidence context or concurrent local question."""


class SqliteSyntheticExpertQuestionLedger(SqliteSyntheticHouseholdInputLedger):
    """Append-only note history on the *same* audited LOCAL/TEST SQLite DB."""

    def __init__(self, *args, **kwargs):
        self._question_ready = False
        super().__init__(*args, **kwargs)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS expert_review_question (
                    action_id TEXT PRIMARY KEY,
                    ref TEXT NOT NULL,
                    case_version INTEGER NOT NULL,
                    track TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    actor_digest TEXT NOT NULL,
                    input_revision INTEGER NOT NULL,
                    input_digest TEXT NOT NULL,
                    science_digest TEXT NOT NULL,
                    proposal_digest TEXT NOT NULL,
                    reason_ref TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL,
                    previous_receipt TEXT NOT NULL,
                    receipt TEXT NOT NULL UNIQUE,
                    audit_sequence INTEGER NOT NULL UNIQUE,
                    UNIQUE(ref, track, revision),
                    FOREIGN KEY(audit_sequence) REFERENCES audit_event(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS expert_question_no_update
                BEFORE UPDATE ON expert_review_question
                BEGIN SELECT RAISE(ABORT, 'expert question history immutable'); END;
                CREATE TRIGGER IF NOT EXISTS expert_question_no_delete
                BEFORE DELETE ON expert_review_question
                BEGIN SELECT RAISE(ABORT, 'expert question history immutable'); END;
            """)
        self._question_ready = True
        with self._transaction() as db:
            self._verify(db)

    def _extended_audit_kinds(self) -> frozenset[str]:
        return super()._extended_audit_kinds() | frozenset({EVENT})

    @staticmethod
    def _receipt(data: dict) -> str:
        return _hash(_json(data))

    @staticmethod
    def _binding_from_row(row: tuple) -> dict:
        (action, ref, case_version, track, revision, actor_hash, input_revision,
         input_digest, science_digest, proposal_digest, reason_ref, evidence_ref,
         previous_receipt, receipt, audit_sequence) = row
        return {
            "action_id": action, "ref": ref, "engine": "DOMESTIC",
            "case_version": case_version, "track": track, "revision": revision,
            "actor_digest": actor_hash, "input_revision": input_revision,
            "input_digest": input_digest, "science_digest": science_digest,
            "proposal_digest": proposal_digest, "reason_ref": reason_ref,
            "evidence_ref": evidence_ref, "previous_receipt": previous_receipt,
        }

    def _verify(self, db: sqlite3.Connection) -> None:
        super()._verify(db)
        if not self._question_ready:
            return
        event_map = {}
        for sequence, payload in db.execute(
            "SELECT sequence,payload FROM audit_event ORDER BY sequence"
        ):
            event = json.loads(payload)
            mode = event.get("access_mode")
            if (event.get("kind") == EVENT
                    or isinstance(mode, str) and mode.startswith(MODE)):
                event_map[sequence] = event
        paired = set()
        prior: dict[tuple[str, str], str] = {}
        counts: dict[tuple[str, str], int] = {}
        for row in db.execute(
            "SELECT action_id,ref,case_version,track,revision,actor_digest,"
            "input_revision,input_digest,science_digest,proposal_digest,"
            "reason_ref,evidence_ref,previous_receipt,receipt,audit_sequence "
            "FROM expert_review_question ORDER BY audit_sequence"
        ):
            (action, ref, case_version, track, revision, actor_hash, input_revision,
             input_digest, science_digest, proposal_digest, reason, evidence,
             previous, receipt, sequence) = row
            key = (ref, track)
            record = self._catalogue.get(("DOMESTIC", ref))
            linked = event_map.get(sequence)
            if (record is None or case_version != record.version
                    or track not in TRACKS or type(revision) is not int
                    or revision != counts.get(key, 0) + 1
                    or type(input_revision) is not int or input_revision < 1
                    or not all(_synthetic_ref(x) for x in (action, reason, evidence))
                    or not isinstance(actor_hash, str) or not _digest(actor_hash)
                    or not all(_digest(x) for x in (
                        input_digest, science_digest, proposal_digest))
                    or previous != prior.get(key, GENESIS)
                    or receipt != self._receipt(self._binding_from_row(row))
                    or linked is None or sequence in paired
                    or linked.get("kind") != EVENT
                    or linked.get("engine") != "DOMESTIC"
                    or linked.get("ref") != ref
                    or linked.get("case_version") != case_version
                    or linked.get("actor_digest") != actor_hash
                    or linked.get("action_id") != action
                    or linked.get("reason_ref") != reason
                    or linked.get("target_digest") != _hash(receipt)
                    or linked.get("access_mode") != MODE + receipt):
                raise LedgerIntegrityError("expert question and audit disagree")
            paired.add(sequence)
            counts[key] = revision
            prior[key] = receipt
        if paired != set(event_map):
            raise LedgerIntegrityError("orphan synthetic expert-question audit")

    @staticmethod
    def _history(db: sqlite3.Connection, ref: str) -> list[tuple]:
        return list(db.execute(
            "SELECT track,revision,input_revision,reason_ref,evidence_ref "
            "FROM expert_review_question WHERE ref=? ORDER BY audit_sequence",
            (ref,),
        ))

    @staticmethod
    def _revision(db: sqlite3.Connection, ref: str, track: str) -> tuple[int, str]:
        row = db.execute(
            "SELECT revision,receipt FROM expert_review_question "
            "WHERE ref=? AND track=? ORDER BY revision DESC LIMIT 1",
            (ref, track),
        ).fetchone()
        return (row[0], row[1]) if row else (0, GENESIS)

    def _append_verified_question(
        self, db: sqlite3.Connection, *, ref: str, case_version: int,
        actor: str, track: str, action_id: str, expected_revision: int,
        input_revision: int, input_digest: str, science_digest: str,
        proposal_digest: str, reason_ref: str, evidence_ref: str,
    ) -> dict:
        """Caller owns same transaction, integrity+role+case+live-lineage checks."""
        if (track not in TRACKS or not all(
                _synthetic_ref(x) for x in (action_id, reason_ref, evidence_ref)
            ) or type(expected_revision) is not int or expected_revision < 0
                or type(case_version) is not int or case_version < 1
                or type(input_revision) is not int or input_revision < 1
                or not all(_digest(x) for x in (
                    input_digest, science_digest, proposal_digest))):
            raise ValueError("invalid synthetic review question")
        actor_hash = _hash(actor)
        same = db.execute(
            "SELECT ref,case_version,track,revision,actor_digest,"
            "input_revision,input_digest,science_digest,proposal_digest,"
            "reason_ref,evidence_ref FROM expert_review_question "
            "WHERE action_id=?", (action_id,),
        ).fetchone()
        if same is not None:
            expected = (
                ref, case_version, track, expected_revision + 1, actor_hash,
                input_revision, input_digest, science_digest, proposal_digest,
                reason_ref, evidence_ref,
            )
            if same == expected:
                return self._ack(ref, track, expected_revision + 1, True)
            raise ReviewQuestionConflict("conflicting question action replay")
        current, prior = self._revision(db, ref, track)
        if current != expected_revision:
            raise ReviewQuestionConflict("stale question track revision")
        next_revision = current + 1
        binding = {
            "action_id": action_id, "ref": ref, "engine": "DOMESTIC",
            "case_version": case_version, "track": track, "revision": next_revision,
            "actor_digest": actor_hash, "input_revision": input_revision,
            "input_digest": input_digest, "science_digest": science_digest,
            "proposal_digest": proposal_digest, "reason_ref": reason_ref,
            "evidence_ref": evidence_ref, "previous_receipt": prior,
        }
        receipt = self._receipt(binding)
        audit = self._append(
            db, kind=EVENT, engine="DOMESTIC", ref=ref,
            actor=actor, target=receipt, action_id=action_id,
            reason_ref=reason_ref, mode=MODE + receipt,
        )
        db.execute(
            "INSERT INTO expert_review_question VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (action_id, ref, case_version, track, next_revision, actor_hash,
             input_revision, input_digest, science_digest, proposal_digest,
             reason_ref, evidence_ref, prior, receipt, audit.sequence),
        )
        return self._ack(ref, track, next_revision, False)

    @staticmethod
    def _ack(ref: str, track: str, revision: int, replay: bool) -> dict:
        return {
            "contract_version": VERSION, "engine": "DOMESTIC",
            "case_ref": ref, "track": track, "question_revision": revision,
            "record_state": "SYNTHETIC_QUESTION_ONLY_NOT_REVIEWED",
            "idempotent_replay": replay,
            "professional_qualification_verified": False,
            "data_adequacy_approved": False,
            "science_rights_approved": False,
            "plan_approved": False, "real_data": False,
        }
