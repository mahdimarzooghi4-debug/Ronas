"""LOCAL/TEST household-owned input-manifest revision journal.

This is NOT actual input collection or a consent receipt. It stores only
synthetic SHA-shaped manifest identifiers. Business D1 consent fields,
real science, collected crop data, AI execution and Production are absent.
Shares the exact immutable local review/audit ledger; no parallel case store.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from .auth import Principal
from .grant_ledger_sqlite import GENESIS, LedgerIntegrityError, _hash, _json
from .human_review_sqlite import SqliteSyntheticHumanReviewLedger
from .internal_cultivation_plan_contract import _digest
from .scoped_drafts import _synthetic_ref, _synthetic_subject

EVENT_KIND = "SYNTHETIC_INPUT_MANIFEST_REVISION_RECORDED"
MODE = "HOUSEHOLD_INPUT_MANIFEST_REVISION_SHA256:"
CONTRACT_VERSION = "ronas.domestic.synthetic-household-input-revisions.v0"
PROGRESS_EVENT = "SYNTHETIC_HOUSEHOLD_PROGRESS_NOTE_RECORDED"
PROGRESS_MODE = "HOUSEHOLD_PROGRESS_NOTE_SHA256:"
PROGRESS_CONTRACT = "ronas.domestic.synthetic-household-progress-notes.v0"


class InputRevisionConflict(ValueError):
    """An outdated or conflicting local DEMO manifest revision command."""


class SqliteSyntheticHouseholdInputLedger(SqliteSyntheticHumanReviewLedger):
    """Offline/test append-only input receipt extension of the SAME case ledger."""

    def __init__(self, *args, **kwargs):
        self._input_ready = False
        super().__init__(*args, **kwargs)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS household_input_revision (
                    action_id TEXT PRIMARY KEY,
                    ref TEXT NOT NULL,
                    case_version INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    owner_digest TEXT NOT NULL,
                    manifest_digest TEXT NOT NULL,
                    previous_receipt_digest TEXT NOT NULL,
                    receipt_digest TEXT NOT NULL UNIQUE,
                    audit_sequence INTEGER NOT NULL UNIQUE,
                    UNIQUE(ref, revision),
                    FOREIGN KEY(audit_sequence) REFERENCES audit_event(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS input_no_update
                BEFORE UPDATE ON household_input_revision
                BEGIN SELECT RAISE(ABORT, 'synthetic input history immutable'); END;
                CREATE TRIGGER IF NOT EXISTS input_no_delete
                BEFORE DELETE ON household_input_revision
                BEGIN SELECT RAISE(ABORT, 'synthetic input history immutable'); END;
                CREATE TABLE IF NOT EXISTS household_progress_note (
                    action_id TEXT PRIMARY KEY, ref TEXT NOT NULL,
                    case_version INTEGER NOT NULL, revision INTEGER NOT NULL,
                    owner_digest TEXT NOT NULL, reported_at TEXT NOT NULL,
                    note TEXT NOT NULL, previous_receipt_digest TEXT NOT NULL,
                    receipt_digest TEXT NOT NULL UNIQUE, audit_sequence INTEGER NOT NULL UNIQUE,
                    UNIQUE(ref, revision),
                    FOREIGN KEY(audit_sequence) REFERENCES audit_event(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS progress_note_no_update
                BEFORE UPDATE ON household_progress_note
                BEGIN SELECT RAISE(ABORT, 'synthetic progress history immutable'); END;
                CREATE TRIGGER IF NOT EXISTS progress_note_no_delete
                BEFORE DELETE ON household_progress_note
                BEGIN SELECT RAISE(ABORT, 'synthetic progress history immutable'); END;
            """)
        self._input_ready = True
        with self._transaction() as db:
            self._verify(db)

    def _extended_audit_kinds(self) -> frozenset[str]:
        # Preserve all *independently verified* parent review/Export audit
        # events. Replacing rather than extending this set caused a shared
        # Domestic + Export ledger to reject valid Export question events.
        return super()._extended_audit_kinds() | frozenset({EVENT_KIND, PROGRESS_EVENT})

    @staticmethod
    def _binding(action: str, ref: str, case_version: int, revision: int,
                 owner_digest: str, manifest_digest: str,
                 previous_receipt_digest: str) -> str:
        return _hash(_json({
            "action_id": action, "engine": "DOMESTIC", "ref": ref,
            "case_version": case_version, "revision": revision,
            "owner_digest": owner_digest, "manifest_digest": manifest_digest,
            "previous_receipt_digest": previous_receipt_digest,
        }))

    def _verify(self, db: sqlite3.Connection) -> None:
        super()._verify(db)
        if not self._input_ready:
            return
        linked = {}
        for sequence, payload in db.execute(
            "SELECT sequence,payload FROM audit_event ORDER BY sequence"
        ):
            event = json.loads(payload)
            mode = event.get("access_mode")
            # Pair both sides of this event contract: an unexpected event
            # kind *or* a forged revision mode must never escape the ledger's
            # append-only table verifier merely because its mode was changed.
            if (event.get("kind") == EVENT_KIND
                    or isinstance(mode, str) and mode.startswith(MODE)):
                linked[sequence] = event
        used = set()
        previous: dict[str, str] = {}
        counts: dict[str, int] = {}
        for row in db.execute(
            "SELECT action_id,ref,case_version,revision,owner_digest,"
            "manifest_digest,previous_receipt_digest,receipt_digest,audit_sequence "
            "FROM household_input_revision ORDER BY audit_sequence"
        ):
            (action, ref, case_version, revision, actor_hash, manifest,
             prior, receipt, sequence) = row
            record = self._catalogue.get(("DOMESTIC", ref))
            expected_prior = previous.get(ref, GENESIS)
            expected_revision = counts.get(ref, 0) + 1
            event = linked.get(sequence)
            if (record is None or not _synthetic_ref(action)
                    or type(case_version) is not int
                    or case_version != record.version
                    or type(revision) is not int
                    or revision != expected_revision
                    or actor_hash != _hash(record.owner_subject)
                    or not _digest(manifest)
                    or prior != expected_prior
                    or receipt != self._binding(
                        action, ref, case_version, revision, actor_hash,
                        manifest, prior,
                    ) or event is None
                    or event.get("kind") != EVENT_KIND
                    or event.get("engine") != "DOMESTIC"
                    or event.get("ref") != ref
                    or event.get("case_version") != case_version
                    or event.get("action_id") != action
                    or event.get("actor_digest") != actor_hash
                    or event.get("target_digest") != _hash(receipt)
                    or event.get("access_mode") != MODE + receipt):
                raise LedgerIntegrityError("synthetic input receipt/audit mismatch")
            if sequence in used:
                raise LedgerIntegrityError("duplicate input receipt audit")
            used.add(sequence)
            previous[ref] = receipt
            counts[ref] = revision
        if used != set(linked):
            raise LedgerIntegrityError("orphaned synthetic input audit event")
        self._verify_progress_notes(db)

    @staticmethod
    def _progress_binding(action: str, ref: str, case_version: int,
                          revision: int, owner_digest: str,
                          reported_at: str, note: str, prior: str) -> str:
        return _hash(_json({
            "action_id": action, "engine": "DOMESTIC", "ref": ref,
            "case_version": case_version, "revision": revision,
            "owner_digest": owner_digest, "reported_at": reported_at,
            "note_digest": _hash(note), "previous_receipt_digest": prior,
        }))

    @staticmethod
    def _valid_reported_at(value: str) -> bool:
        if not isinstance(value, str) or len(value) > 40:
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed.tzinfo is not None and parsed.utcoffset() is not None

    def _verify_progress_notes(self, db: sqlite3.Connection) -> None:
        linked = {}
        for sequence, payload in db.execute(
            "SELECT sequence,payload FROM audit_event ORDER BY sequence"
        ):
            event = json.loads(payload)
            mode = event.get("access_mode")
            if (event.get("kind") == PROGRESS_EVENT
                    or isinstance(mode, str) and mode.startswith(PROGRESS_MODE)):
                linked[sequence] = event
        used = set()
        previous: dict[str, str] = {}
        counts: dict[str, int] = {}
        for row in db.execute(
            "SELECT action_id,ref,case_version,revision,owner_digest,reported_at,"
            "note,previous_receipt_digest,receipt_digest,audit_sequence "
            "FROM household_progress_note ORDER BY audit_sequence"
        ):
            action, ref, version, revision, owner_hash, reported_at, note, prior, receipt, seq = row
            record = self._catalogue.get(("DOMESTIC", ref))
            expected_revision = counts.get(ref, 0) + 1
            expected_prior = previous.get(ref, GENESIS)
            event = linked.get(seq)
            if (record is None or not _synthetic_ref(action)
                    or type(version) is not int or not 1 <= version <= record.version
                    or type(revision) is not int or revision != expected_revision
                    or owner_hash != _hash(record.owner_subject)
                    or not self._valid_reported_at(reported_at)
                    or not isinstance(note, str) or not note.startswith("DEMO:")
                    or len(note) > 150 or prior != expected_prior
                    or receipt != self._progress_binding(
                        action, ref, version, revision, owner_hash,
                        reported_at, note, prior)
                    or event is None or event.get("kind") != PROGRESS_EVENT
                    or event.get("engine") != "DOMESTIC"
                    or event.get("ref") != ref or event.get("case_version") != version
                    or event.get("action_id") != action
                    or event.get("actor_digest") != owner_hash
                    or event.get("target_digest") != _hash(receipt)
                    or event.get("access_mode") != PROGRESS_MODE + receipt):
                raise LedgerIntegrityError("synthetic progress note/audit mismatch")
            if seq in used:
                raise LedgerIntegrityError("duplicate progress note audit")
            used.add(seq)
            previous[ref] = receipt
            counts[ref] = revision
        if used != set(linked):
            raise LedgerIntegrityError("orphaned synthetic progress audit event")

    def read_owned_progress_notes(self, ref: str, principal: Principal) -> dict | None:
        with self._transaction() as db:
            self._verify(db)
            if not self._owner(ref, principal):
                return None
            record = self._catalogue[("DOMESTIC", ref)]
            rows = list(db.execute(
                "SELECT revision,reported_at,note FROM household_progress_note "
                "WHERE ref=? ORDER BY revision", (ref,),
            ))
            self._append(db, kind="READ_ALLOWED", engine="DOMESTIC", ref=ref,
                         actor=principal.subject, mode="HOUSEHOLD_PROGRESS_NOTE_HISTORY")
            return {
                "contract_version": PROGRESS_CONTRACT, "engine": "DOMESTIC",
                "ref": ref, "case_version": record.version,
                "notes": [{"revision": r, "reported_at": ts, "note": text}
                          for r, ts, text in rows],
                "current_revision": rows[-1][0] if rows else 0,
                "real_data": False, "scientific_review": False,
                "expert_inspection": False, "plan_accepted": False,
            }

    def append_owned_progress_note(
        self, ref: str, principal: Principal, *, action_id: str,
        expected_case_version: int, expected_revision: int,
        reported_at: str, note: str,
    ) -> dict | None:
        if (not _synthetic_ref(action_id) or type(expected_case_version) is not int
                or expected_case_version < 1 or type(expected_revision) is not int
                or expected_revision < 0 or not self._valid_reported_at(reported_at)
                or not isinstance(note, str) or not note.startswith("DEMO:")
                or not 6 <= len(note) <= 150 or note != note.strip()):
            raise ValueError("invalid synthetic progress note")
        with self._transaction() as db:
            self._verify(db)
            if not self._owner(ref, principal):
                return None
            record = self._catalogue[("DOMESTIC", ref)]
            if record.version != expected_case_version:
                raise InputRevisionConflict("stale case version")
            owner_hash = _hash(principal.subject)
            prior_action = db.execute(
                "SELECT ref,case_version,revision,owner_digest,reported_at,note "
                "FROM household_progress_note WHERE action_id=?", (action_id,),
            ).fetchone()
            expected = (ref, expected_case_version, expected_revision + 1,
                        owner_hash, reported_at, note)
            if prior_action is not None:
                if prior_action == expected:
                    return {"contract_version": PROGRESS_CONTRACT, "engine": "DOMESTIC",
                            "ref": ref, "case_version": expected_case_version,
                            "revision": expected_revision + 1, "idempotent_replay": True,
                            "real_data": False, "scientific_review": False,
                            "expert_inspection": False, "plan_accepted": False}
                raise InputRevisionConflict("conflicting progress note replay")
            latest = db.execute(
                "SELECT revision,receipt_digest FROM household_progress_note "
                "WHERE ref=? ORDER BY revision DESC LIMIT 1", (ref,),
            ).fetchone()
            current = latest[0] if latest else 0
            if current != expected_revision:
                raise InputRevisionConflict("stale progress note revision")
            revision = current + 1
            prior = latest[1] if latest else GENESIS
            receipt = self._progress_binding(action_id, ref, record.version, revision,
                owner_hash, reported_at, note, prior)
            audit = self._append(db, kind=PROGRESS_EVENT, engine="DOMESTIC", ref=ref,
                actor=principal.subject, target=receipt, action_id=action_id,
                mode=PROGRESS_MODE + receipt)
            db.execute(
                "INSERT INTO household_progress_note "
                "(action_id,ref,case_version,revision,owner_digest,reported_at,note,"
                "previous_receipt_digest,receipt_digest,audit_sequence) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (action_id, ref, record.version, revision, owner_hash, reported_at,
                 note, prior, receipt, audit.sequence),
            )
            return {"contract_version": PROGRESS_CONTRACT, "engine": "DOMESTIC",
                    "ref": ref, "case_version": record.version, "revision": revision,
                    "idempotent_replay": False, "real_data": False,
                    "scientific_review": False, "expert_inspection": False,
                    "plan_accepted": False}

    def _owner(self, ref: str, principal: Principal) -> bool:
        record = self._catalogue.get(("DOMESTIC", ref))
        return (record is not None and _synthetic_ref(ref)
                and isinstance(principal, Principal)
                and _synthetic_subject(principal.subject)
                and "household" in principal.roles
                and principal.subject == record.owner_subject)

    @staticmethod
    def _rows(db: sqlite3.Connection, ref: str) -> list[tuple]:
        return list(db.execute(
            "SELECT revision,manifest_digest,receipt_digest,action_id "
            "FROM household_input_revision WHERE ref=? ORDER BY revision",
            (ref,),
        ))

    def read_owned_input_revisions(
        self, ref: str, principal: Principal,
    ) -> dict | None:
        with self._transaction() as db:
            self._verify(db)
            if not self._owner(ref, principal):
                return None
            record = self._catalogue[("DOMESTIC", ref)]
            history = self._rows(db, ref)
            self._append(
                db, kind="READ_ALLOWED", engine="DOMESTIC", ref=ref,
                actor=principal.subject, mode="HOUSEHOLD_INPUT_REVISION_HISTORY",
            )
            return {
                "contract_version": CONTRACT_VERSION,
                "engine": "DOMESTIC", "ref": ref,
                "case_version": record.version,
                "input_revisions": [x[0] for x in history],
                "current_input_revision": history[-1][0] if history else None,
                "input_state": "SYNTHETIC_MANIFEST_ONLY" if history
                               else "NOT_RECORDED_IN_DEMO",
                "purpose_consent_verified": False,
                "science_validated": False,
                "ai_training_authorized": False,
                "plan_accepted": False, "real_data": False,
            }

    def append_owned_input_manifest(
        self, ref: str, principal: Principal, *,
        action_id: str, expected_case_version: int, expected_input_revision: int,
        synthetic_manifest_digest: str,
    ) -> dict | None:
        """Durable synthetic digest-only correction; zero household data bytes.

        Caller must be a previously signature-verified Principal. Test-only
        methods do not establish legal consent or actual input provenance.
        """
        if (not _synthetic_ref(action_id)
                or type(expected_case_version) is not int
                or expected_case_version < 1
                or type(expected_input_revision) is not int
                or expected_input_revision < 0
                or not _digest(synthetic_manifest_digest)):
            raise ValueError("invalid synthetic input revision command")
        with self._transaction() as db:
            self._verify(db)
            if not self._owner(ref, principal):
                return None
            record = self._catalogue[("DOMESTIC", ref)]
            if record.version != expected_case_version:
                raise InputRevisionConflict("stale case version")
            prior_action = db.execute(
                "SELECT ref,case_version,revision,owner_digest,manifest_digest "
                "FROM household_input_revision WHERE action_id=?", (action_id,),
            ).fetchone()
            if prior_action is not None:
                if prior_action == (
                    ref, expected_case_version, expected_input_revision + 1,
                    _hash(principal.subject), synthetic_manifest_digest,
                ):
                    return self._receipt(ref, record.version,
                                         expected_input_revision + 1, replay=True)
                raise InputRevisionConflict("conflicting synthetic action replay")
            previous = db.execute(
                "SELECT revision,manifest_digest,receipt_digest "
                "FROM household_input_revision WHERE ref=? "
                "ORDER BY revision DESC LIMIT 1", (ref,),
            ).fetchone()
            current = previous[0] if previous else 0
            if current != expected_input_revision:
                raise InputRevisionConflict("stale synthetic input revision")
            if previous is not None and previous[1] == synthetic_manifest_digest:
                raise InputRevisionConflict("unchanged synthetic manifest")
            next_rev = current + 1
            actor_hash = _hash(principal.subject)
            prior_receipt = previous[2] if previous else GENESIS
            receipt = self._binding(
                action_id, ref, record.version, next_rev, actor_hash,
                synthetic_manifest_digest, prior_receipt,
            )
            audit = self._append(
                db, kind=EVENT_KIND, engine="DOMESTIC", ref=ref,
                actor=principal.subject, target=receipt, action_id=action_id,
                mode=MODE + receipt,
            )
            db.execute(
                "INSERT INTO household_input_revision "
                "(action_id,ref,case_version,revision,owner_digest,"
                "manifest_digest,previous_receipt_digest,receipt_digest,audit_sequence) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (action_id, ref, record.version, next_rev, actor_hash,
                 synthetic_manifest_digest, prior_receipt, receipt, audit.sequence),
            )
            return self._receipt(ref, record.version, next_rev, replay=False)

    @staticmethod
    def _receipt(ref: str, case_version: int, revision: int, *,
                 replay: bool) -> dict:
        return {
            "contract_version": CONTRACT_VERSION,
            "engine": "DOMESTIC", "ref": ref, "case_version": case_version,
            "input_revision": revision,
            "input_state": "SYNTHETIC_MANIFEST_ONLY",
            "idempotent_replay": replay,
            "purpose_consent_verified": False,
            "science_validated": False,
            "ai_training_authorized": False,
            "plan_accepted": False, "real_data": False,
        }

    def _input_snapshot_from_verified_transaction(
        self, db: sqlite3.Connection, ref: str, version: int,
    ) -> tuple[int, str] | None:
        """Only while an exact shared-ledger transaction has verified integrity.

        Never open another connection from the assigned specialist read:
        BEGIN IMMEDIATE is already held and a nested writer would deadlock.
        """
        record = self._catalogue.get(("DOMESTIC", ref))
        if record is None or record.version != version:
            return None
        row = db.execute(
            "SELECT revision,manifest_digest FROM household_input_revision "
            "WHERE ref=? ORDER BY revision DESC LIMIT 1", (ref,),
        ).fetchone()
        return (row[0], row[1]) if row else None

    def internal_input_snapshot(self, ref: str, version: int) -> tuple[int, str] | None:
        """Internal-only independent digest source; do not serve by HTTP."""
        with self._transaction() as db:
            self._verify(db)
            record = self._catalogue.get(("DOMESTIC", ref))
            if record is None or record.version != version:
                return None
            row = db.execute(
                "SELECT revision,manifest_digest FROM household_input_revision "
                "WHERE ref=? ORDER BY revision DESC LIMIT 1", (ref,),
            ).fetchone()
            return (row[0], row[1]) if row else None
