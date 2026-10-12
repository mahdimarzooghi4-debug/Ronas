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
ANSWER_EVENT = "SYNTHETIC_HOUSEHOLD_QUESTION_RESPONSE_RECORDED"
ANSWER_MODE = "SYNTHETIC_HOUSEHOLD_QUESTION_RESPONSE_SHA256:"
ANSWER_VERSION = "ronas.domestic.synthetic-household-question-response.v0"
INSPECTION_EVENT = "SYNTHETIC_EXPERT_RESPONSE_RECEIPT_INSPECTED"
INSPECTION_MODE = "SYNTHETIC_EXPERT_RESPONSE_RECEIPT_SHA256:"
INSPECTION_VERSION = "ronas.domestic.synthetic-response-receipt-inspection.v0"
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
        self._answer_ready = False
        self._inspection_ready = False
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
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS household_question_response (
                    action_id TEXT PRIMARY KEY,
                    ref TEXT NOT NULL,
                    case_version INTEGER NOT NULL,
                    track TEXT NOT NULL,
                    question_revision INTEGER NOT NULL,
                    question_receipt TEXT NOT NULL,
                    input_revision INTEGER NOT NULL,
                    input_digest TEXT NOT NULL,
                    owner_digest TEXT NOT NULL,
                    answer_ref TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL,
                    response_receipt TEXT NOT NULL UNIQUE,
                    audit_sequence INTEGER NOT NULL UNIQUE,
                    UNIQUE(ref,track,question_revision),
                    FOREIGN KEY(audit_sequence) REFERENCES audit_event(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS household_response_no_update
                BEFORE UPDATE ON household_question_response
                BEGIN SELECT RAISE(ABORT, 'household response history immutable'); END;
                CREATE TRIGGER IF NOT EXISTS household_response_no_delete
                BEFORE DELETE ON household_question_response
                BEGIN SELECT RAISE(ABORT, 'household response history immutable'); END;
            """)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS expert_response_receipt_inspection (
                    action_id TEXT PRIMARY KEY,
                    ref TEXT NOT NULL,
                    case_version INTEGER NOT NULL,
                    track TEXT NOT NULL,
                    question_revision INTEGER NOT NULL,
                    question_receipt TEXT NOT NULL,
                    response_receipt TEXT NOT NULL,
                    input_revision INTEGER NOT NULL,
                    input_digest TEXT NOT NULL,
                    science_digest TEXT NOT NULL,
                    proposal_digest TEXT NOT NULL,
                    actor_digest TEXT NOT NULL,
                    inspection_receipt TEXT NOT NULL UNIQUE,
                    audit_sequence INTEGER NOT NULL UNIQUE,
                    UNIQUE(ref,track,question_revision),
                    FOREIGN KEY(audit_sequence) REFERENCES audit_event(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS response_inspection_no_update
                BEFORE UPDATE ON expert_response_receipt_inspection
                BEGIN SELECT RAISE(ABORT, 'inspection history immutable'); END;
                CREATE TRIGGER IF NOT EXISTS response_inspection_no_delete
                BEFORE DELETE ON expert_response_receipt_inspection
                BEGIN SELECT RAISE(ABORT, 'inspection history immutable'); END;
            """)
        self._question_ready = True
        self._answer_ready = True
        self._inspection_ready = True
        with self._transaction() as db:
            self._verify(db)

    def _extended_audit_kinds(self) -> frozenset[str]:
        return super()._extended_audit_kinds() | frozenset({
            EVENT, ANSWER_EVENT, INSPECTION_EVENT,
        })

    @staticmethod
    def _question_digest(data: dict) -> str:
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
            # The question's input must actually be a previously recorded,
            # verified household-owned DEMO revision. Never accept a
            # self-asserted digest/number in a historical review question.
            source_input = db.execute(
                "SELECT manifest_digest,audit_sequence FROM household_input_revision "
                "WHERE ref=? AND revision=?", (ref, input_revision),
            ).fetchone()
            has_profile_history = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='household_profile_revision'",
            ).fetchone() is not None
            if source_input is None and has_profile_history:
                # The profile ledger validates its complete append-only chain
                # after this base question verifier returns. Bind this question
                # to the exact immutable profile revision here.
                source_input = db.execute(
                    "SELECT content_digest,audit_sequence "
                    "FROM household_profile_revision WHERE ref=? AND revision=?",
                    (ref, input_revision),
                ).fetchone()
            if (source_input is None or source_input[0] != input_digest
                    or source_input[1] >= sequence):
                raise LedgerIntegrityError("question input lineage missing or altered")
            if (record is None or case_version != record.version
                    or track not in TRACKS or type(revision) is not int
                    or revision != counts.get(key, 0) + 1
                    or type(input_revision) is not int or input_revision < 1
                    or not all(_synthetic_ref(x) for x in (action, reason, evidence))
                    or not isinstance(actor_hash, str) or not _digest(actor_hash)
                    or not all(_digest(x) for x in (
                        input_digest, science_digest, proposal_digest))
                    or previous != prior.get(key, GENESIS)
                    or receipt != self._question_digest(self._binding_from_row(row))
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
        if self._answer_ready:
            self._verify_household_responses(db)

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
        receipt = self._question_digest(binding)
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

    @staticmethod
    def _answer_binding(row: tuple) -> dict:
        (action, ref, case_version, track, q_revision, q_receipt,
         input_revision, input_digest, owner_digest, answer_ref, evidence_ref,
         response_receipt, audit_sequence) = row
        return {
            "action_id": action, "ref": ref, "engine": "DOMESTIC",
            "case_version": case_version, "track": track,
            "question_revision": q_revision, "question_receipt": q_receipt,
            "input_revision": input_revision, "input_digest": input_digest,
            "owner_digest": owner_digest, "answer_ref": answer_ref,
            "evidence_ref": evidence_ref,
        }

    def _verify_household_responses(self, db: sqlite3.Connection) -> None:
        expected = {}
        for seq, payload in db.execute(
            "SELECT sequence,payload FROM audit_event ORDER BY sequence"
        ):
            event = json.loads(payload)
            mode = event.get("access_mode")
            if (event.get("kind") == ANSWER_EVENT
                    or isinstance(mode, str) and mode.startswith(ANSWER_MODE)):
                expected[seq] = event
        used = set()
        for row in db.execute(
            "SELECT action_id,ref,case_version,track,question_revision,"
            "question_receipt,input_revision,input_digest,owner_digest,"
            "answer_ref,evidence_ref,response_receipt,audit_sequence "
            "FROM household_question_response ORDER BY audit_sequence"
        ):
            (action, ref, version, track, q_revision, q_receipt,
             input_revision, input_digest, owner_hash, answer, evidence,
             receipt, seq) = row
            record = self._catalogue.get(("DOMESTIC", ref))
            question = db.execute(
                "SELECT receipt,input_revision,input_digest,audit_sequence "
                "FROM expert_review_question WHERE ref=? AND track=? "
                "AND revision=?", (ref, track, q_revision),
            ).fetchone()
            inp = db.execute(
                "SELECT manifest_digest,audit_sequence FROM household_input_revision "
                "WHERE ref=? AND revision=?", (ref, input_revision),
            ).fetchone()
            has_profile_history = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='household_profile_revision'",
            ).fetchone() is not None
            if inp is None and has_profile_history:
                inp = db.execute(
                    "SELECT content_digest,audit_sequence "
                    "FROM household_profile_revision WHERE ref=? AND revision=?",
                    (ref, input_revision),
                ).fetchone()
            event = expected.get(seq)
            if (record is None or version != record.version
                    or track != "HOUSEHOLD_INPUT_ADEQUACY"
                    or type(q_revision) is not int or q_revision < 1
                    or type(input_revision) is not int or input_revision < 1
                    or not all(_synthetic_ref(x) for x in (
                        action, answer, evidence))
                    or not all(_digest(x) for x in (
                        q_receipt, input_digest, owner_hash, receipt))
                    or owner_hash != _hash(record.owner_subject)
                    or question is None
                    or question[0] != q_receipt
                    or question[1] != input_revision
                    or question[2] != input_digest
                    or question[3] >= seq
                    or inp is None or inp[0] != input_digest
                    or inp[1] >= question[3]
                    or receipt != self._question_digest(self._answer_binding(row))
                    or event is None or seq in used
                    or event.get("kind") != ANSWER_EVENT
                    or event.get("engine") != "DOMESTIC"
                    or event.get("ref") != ref
                    or event.get("case_version") != version
                    or event.get("actor_digest") != owner_hash
                    or event.get("action_id") != action
                    or event.get("reason_ref") != answer
                    or event.get("target_digest") != _hash(receipt)
                    or event.get("access_mode") != ANSWER_MODE + receipt):
                raise LedgerIntegrityError("household response and audit mismatch")
            used.add(seq)
        if used != set(expected):
            raise LedgerIntegrityError("orphan synthetic household response event")
        if self._inspection_ready:
            self._verify_response_inspections(db)

    def _current_household_question_input(
        self, db: sqlite3.Connection, ref: str, case_version: int,
    ) -> tuple[int, str] | None:
        profile_reader = getattr(
            self, "_profile_snapshot_from_verified_transaction", None,
        )
        if callable(profile_reader):
            return profile_reader(db, ref, case_version)
        return self._input_snapshot_from_verified_transaction(
            db, ref, case_version,
        )

    def append_owned_question_response(
        self, ref: str, principal, *, action_id: str,
        track: str, expected_question_revision: int,
        expected_case_version: int, expected_input_revision: int,
        answer_ref: str, evidence_ref: str,
    ) -> dict | None:
        """Household can answer only its own *input* question, never approve."""
        if (track != "HOUSEHOLD_INPUT_ADEQUACY"
                or not all(_synthetic_ref(x) for x in (
                    action_id, answer_ref, evidence_ref))
                or type(expected_question_revision) is not int
                or expected_question_revision < 1
                or type(expected_case_version) is not int
                or expected_case_version < 1
                or type(expected_input_revision) is not int
                or expected_input_revision < 1):
            raise ValueError("invalid DEMO household response command")
        with self._transaction() as db:
            self._verify(db)
            if not self._owner(ref, principal):
                return None
            record = self._catalogue[("DOMESTIC", ref)]
            if record.version != expected_case_version:
                raise ReviewQuestionConflict("case version differs")
            question = db.execute(
                "SELECT receipt,input_revision,input_digest,audit_sequence "
                "FROM expert_review_question WHERE ref=? AND track=? "
                "AND revision=?", (ref, track, expected_question_revision),
            ).fetchone()
            if question is None:
                raise ReviewQuestionConflict("question not present")
            latest_revision, _ = self._revision(db, ref, track)
            current_input = self._current_household_question_input(
                db, ref, record.version,
            )
            if (latest_revision != expected_question_revision
                    or current_input is None
                    or current_input[0] != expected_input_revision
                    or question[1] != current_input[0]
                    or question[2] != current_input[1]):
                raise ReviewQuestionConflict("stale question or input")
            binding = {
                "action_id": action_id, "ref": ref, "engine": "DOMESTIC",
                "case_version": record.version, "track": track,
                "question_revision": expected_question_revision,
                "question_receipt": question[0],
                "input_revision": current_input[0],
                "input_digest": current_input[1],
                "owner_digest": _hash(principal.subject),
                "answer_ref": answer_ref, "evidence_ref": evidence_ref,
            }
            receipt = self._question_digest(binding)
            prior = db.execute(
                "SELECT action_id,response_receipt FROM household_question_response "
                "WHERE ref=? AND track=? AND question_revision=?",
                (ref, track, expected_question_revision),
            ).fetchone()
            if prior is not None:
                if prior == (action_id, receipt):
                    return self._answer_ack(ref, expected_question_revision, True)
                raise ReviewQuestionConflict("question already answered in DEMO")
            action = db.execute(
                "SELECT response_receipt FROM household_question_response "
                "WHERE action_id=?", (action_id,),
            ).fetchone()
            if action is not None:
                raise ReviewQuestionConflict("response action reused")
            audit = self._append(
                db, kind=ANSWER_EVENT, engine="DOMESTIC", ref=ref,
                actor=principal.subject, target=receipt,
                action_id=action_id, reason_ref=answer_ref,
                mode=ANSWER_MODE + receipt,
            )
            db.execute(
                "INSERT INTO household_question_response VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (action_id, ref, record.version, track,
                 expected_question_revision, question[0], current_input[0],
                 current_input[1], _hash(principal.subject), answer_ref,
                 evidence_ref, receipt, audit.sequence),
            )
            return self._answer_ack(ref, expected_question_revision, False)

    @staticmethod
    def _answer_ack(ref: str, question_revision: int, replay: bool) -> dict:
        return {
            "contract_version": ANSWER_VERSION, "engine": "DOMESTIC",
            "case_ref": ref, "track": "HOUSEHOLD_INPUT_ADEQUACY",
            "question_revision": question_revision,
            "record_state": "SYNTHETIC_RESPONSE_RECEIVED_NOT_REVIEWED",
            "idempotent_replay": replay,
            "purpose_consent_verified": False,
            "household_input_adequacy_verified": False,
            "science_rights_verified": False,
            "qualified_expert_decision_recorded": False,
            "plan_accepted": False, "real_data": False,
        }

    def read_owned_question_responses(self, ref: str, principal) -> dict | None:
        """Owner-only private DE​MO history; no expert approval or real data."""
        with self._transaction() as db:
            self._verify(db)
            if not self._owner(ref, principal):
                return None
            record = self._catalogue[("DOMESTIC", ref)]
            latest = self._current_household_question_input(
                db, ref, record.version,
            )
            questions = list(db.execute(
                "SELECT q.revision,q.input_revision,r.action_id,r.answer_ref,"
                "r.evidence_ref FROM expert_review_question q "
                "LEFT JOIN household_question_response r "
                "ON r.ref=q.ref AND r.track=q.track AND r.question_revision=q.revision "
                "WHERE q.ref=? AND q.track='HOUSEHOLD_INPUT_ADEQUACY' "
                "ORDER BY q.revision", (ref,),
            ))
            has_stage_links = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='expert_stage_question_binding'",
            ).fetchone() is not None
            stage_links = {}
            if has_stage_links:
                stage_links = {
                    revision: {
                        "stage_ref": stage_ref,
                        "stage_observation_revision": observation_revision,
                        "stage_observation_receipt_digest": observation_digest,
                    }
                    for revision, stage_ref, observation_revision, observation_digest
                    in db.execute(
                        "SELECT question_revision,stage_ref,observation_revision,"
                        "observation_receipt_digest FROM "
                        "expert_stage_question_binding WHERE ref=? "
                        "AND track='HOUSEHOLD_INPUT_ADEQUACY'",
                        (ref,),
                    )
                }
            self._append(
                db, kind="READ_ALLOWED", engine="DOMESTIC", ref=ref,
                actor=principal.subject,
                mode="HOUSEHOLD_SYNTHETIC_QUESTION_RESPONSE_HISTORY",
            )
            return {
                "contract_version": ANSWER_VERSION, "engine": "DOMESTIC",
                "case_ref": ref, "case_version": record.version,
                "questions": [
                    {
                        "question_revision": revision,
                        "bound_input_revision": bound_input,
                        "response_state": (
                            "HISTORICAL_RESPONSE_ONLY_NOT_REVIEWED"
                            if action else "MISSING_RESPONSE"
                        ),
                        "response_ref": answer,
                        "evidence_ref": evidence,
                        "is_current_input_version": (
                            latest is not None and bound_input == latest[0]
                        ),
                        **stage_links.get(revision, {
                            "stage_ref": None,
                            "stage_observation_revision": None,
                            "stage_observation_receipt_digest": None,
                        }),
                    }
                    for revision, bound_input, action, answer, evidence
                    in questions
                ],
                "purpose_consent_verified": False,
                "expert_review_recorded": False,
                "plan_accepted": False, "new_advice_enabled": False,
                "real_data": False,
            }

    @staticmethod
    def _inspection_binding(row: tuple) -> dict:
        (action, ref, version, track, qrev, question_receipt, response_receipt,
         input_revision, input_digest, science_digest, proposal_digest,
         actor_digest, receipt, sequence) = row
        return {
            "action_id": action, "ref": ref, "engine": "DOMESTIC",
            "case_version": version, "track": track,
            "question_revision": qrev, "question_receipt": question_receipt,
            "response_receipt": response_receipt,
            "input_revision": input_revision, "input_digest": input_digest,
            "science_digest": science_digest, "proposal_digest": proposal_digest,
            "actor_digest": actor_digest,
        }

    def _verify_response_inspections(self, db: sqlite3.Connection) -> None:
        linked = {}
        for sequence, payload in db.execute(
            "SELECT sequence,payload FROM audit_event ORDER BY sequence"
        ):
            event = json.loads(payload)
            mode = event.get("access_mode")
            if (event.get("kind") == INSPECTION_EVENT
                    or isinstance(mode, str)
                    and mode.startswith(INSPECTION_MODE)):
                linked[sequence] = event
        seen = set()
        for row in db.execute(
            "SELECT action_id,ref,case_version,track,question_revision,"
            "question_receipt,response_receipt,input_revision,input_digest,"
            "science_digest,proposal_digest,actor_digest,inspection_receipt,"
            "audit_sequence FROM expert_response_receipt_inspection "
            "ORDER BY audit_sequence"
        ):
            (action, ref, version, track, qrev, q_receipt, r_receipt,
             irev, idigest, sdigest, pdigest, actor_hash, receipt, sequence) = row
            case = self._catalogue.get(("DOMESTIC", ref))
            q = db.execute(
                "SELECT receipt,input_revision,input_digest,science_digest,"
                "proposal_digest,audit_sequence FROM expert_review_question "
                "WHERE ref=? AND track=? AND revision=?",
                (ref, track, qrev),
            ).fetchone()
            answer = db.execute(
                "SELECT response_receipt,question_receipt,input_revision,"
                "input_digest,audit_sequence FROM household_question_response "
                "WHERE ref=? AND track=? AND question_revision=?",
                (ref, track, qrev),
            ).fetchone()
            event = linked.get(sequence)
            if (case is None or case.version != version
                    or track != "HOUSEHOLD_INPUT_ADEQUACY"
                    or type(qrev) is not int or qrev < 1
                    or type(irev) is not int or irev < 1
                    or not _synthetic_ref(action)
                    or not all(_digest(x) for x in (
                        q_receipt, r_receipt, idigest, sdigest, pdigest,
                        actor_hash, receipt))
                    or q is None or q[:5] != (
                        q_receipt, irev, idigest, sdigest, pdigest)
                    or answer is None
                    or answer[:4] != (r_receipt, q_receipt, irev, idigest)
                    or not q[5] < answer[4] < sequence
                    or receipt != self._question_digest(
                        self._inspection_binding(row))
                    or event is None or sequence in seen
                    or event.get("kind") != INSPECTION_EVENT
                    or event.get("engine") != "DOMESTIC"
                    or event.get("ref") != ref
                    or event.get("case_version") != version
                    or event.get("actor_digest") != actor_hash
                    or event.get("action_id") != action
                    or event.get("reason_ref") != "DEMO-RESPONSE-RECEIPT"
                    or event.get("target_digest") != _hash(receipt)
                    or event.get("access_mode") != INSPECTION_MODE + receipt):
                raise LedgerIntegrityError(
                    "synthetic expert inspection/audit lineage mismatch")
            seen.add(sequence)
        if seen != set(linked):
            raise LedgerIntegrityError("orphan expert response inspection event")

    def _append_verified_response_receipt_inspection(
        self, db: sqlite3.Connection, *, ref: str, case_version: int,
        actor: str, action_id: str, question_revision: int,
        input_revision: int, input_digest: str, science_digest: str,
        proposal_digest: str,
    ) -> dict:
        """Caller must verify role, live case assignment, current source/input."""
        if (not _synthetic_ref(action_id)
                or type(question_revision) is not int or question_revision < 1
                or type(case_version) is not int or case_version < 1
                or type(input_revision) is not int or input_revision < 1
                or not all(_digest(x) for x in (
                    input_digest, science_digest, proposal_digest))):
            raise ValueError("invalid synthetic receipt inspection")
        track = "HOUSEHOLD_INPUT_ADEQUACY"
        q = db.execute(
            "SELECT receipt,input_revision,input_digest,science_digest,"
            "proposal_digest FROM expert_review_question "
            "WHERE ref=? AND track=? AND revision=?",
            (ref, track, question_revision),
        ).fetchone()
        answer = db.execute(
            "SELECT response_receipt FROM household_question_response "
            "WHERE ref=? AND track=? AND question_revision=?",
            (ref, track, question_revision),
        ).fetchone()
        if (q is None or answer is None
                or q != (
                    q[0], input_revision, input_digest,
                    science_digest, proposal_digest)
                or self._revision(db, ref, track)[0] != question_revision):
            raise ReviewQuestionConflict("unanswered/stale question or proposal")
        binding = {
            "action_id": action_id, "ref": ref, "engine": "DOMESTIC",
            "case_version": case_version, "track": track,
            "question_revision": question_revision, "question_receipt": q[0],
            "response_receipt": answer[0], "input_revision": input_revision,
            "input_digest": input_digest, "science_digest": science_digest,
            "proposal_digest": proposal_digest, "actor_digest": _hash(actor),
        }
        receipt = self._question_digest(binding)
        existing = db.execute(
            "SELECT action_id,inspection_receipt "
            "FROM expert_response_receipt_inspection "
            "WHERE ref=? AND track=? AND question_revision=?",
            (ref, track, question_revision),
        ).fetchone()
        if existing is not None:
            if existing == (action_id, receipt):
                return self._inspection_ack(ref, question_revision, True)
            raise ReviewQuestionConflict("receipt inspection already recorded")
        if db.execute(
            "SELECT 1 FROM expert_response_receipt_inspection WHERE action_id=?",
            (action_id,),
        ).fetchone():
            raise ReviewQuestionConflict("inspection action reused")
        audit = self._append(
            db, kind=INSPECTION_EVENT, engine="DOMESTIC", ref=ref,
            actor=actor, target=receipt, action_id=action_id,
            reason_ref="DEMO-RESPONSE-RECEIPT", mode=INSPECTION_MODE + receipt,
        )
        db.execute(
            "INSERT INTO expert_response_receipt_inspection VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (action_id, ref, case_version, track, question_revision,
             q[0], answer[0], input_revision, input_digest, science_digest,
             proposal_digest, _hash(actor), receipt, audit.sequence),
        )
        return self._inspection_ack(ref, question_revision, False)

    @staticmethod
    def _inspection_ack(ref: str, qrev: int, replay: bool) -> dict:
        return {
            "contract_version": INSPECTION_VERSION, "engine": "DOMESTIC",
            "case_ref": ref, "track": "HOUSEHOLD_INPUT_ADEQUACY",
            "question_revision": qrev,
            "state": "SYNTHETIC_RECEIPT_SEEN_NOT_REVIEWED",
            "idempotent_replay": replay,
            "household_input_adequacy_verified": False,
            "source_rights_verified": False,
            "scientific_validity_verified": False,
            "professional_qualification_verified": False,
            "expert_decision_recorded": False,
            "plan_accepted": False, "new_advice_enabled": False,
            "real_data": False,
        }
