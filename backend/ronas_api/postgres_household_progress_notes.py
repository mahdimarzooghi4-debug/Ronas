"""Opt-in PostgreSQL encrypted store for private synthetic progress notes.

The adapter deliberately stores only bounded ``DEMO:`` journal text. Current
household authority and case/input lineage are supplied by the existing case
ledger on every call; this table never becomes an ownership or case registry.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.rows import dict_row

from .auth import Principal
from .grant_ledger_sqlite import LedgerIntegrityError
from .household_input_ledger_sqlite import (
    InputRevisionConflict, PROGRESS_CORRECTION_CONTRACT,
    SqliteSyntheticHouseholdInputLedger,
)
from .scoped_drafts import _synthetic_ref, _synthetic_subject


class PostgresHouseholdProgressNoteLedger:
    """Encrypted append-only note journal with live case authority checks."""

    def __init__(self, dsn: str, schema_ref: str, owner_access_authority, context_reader,
                 encryption_key: bytes, scope_key: bytes, *, connect_timeout: int = 3):
        if (not isinstance(dsn, str) or not dsn or len(dsn) > 4096 or "\x00" in dsn
                or not isinstance(schema_ref, str) or not schema_ref or len(schema_ref) > 120
                or not callable(owner_access_authority) or not callable(context_reader)
                or not isinstance(encryption_key, bytes) or len(encryption_key) != 32
                or not isinstance(scope_key, bytes) or len(scope_key) != 32
                or type(connect_timeout) is not int or not 1 <= connect_timeout <= 15):
            raise ValueError("valid PostgreSQL progress journal configuration required")
        self._dsn = dsn
        self._schema_ref = schema_ref
        self._authority = owner_access_authority
        self._context_reader = context_reader
        self._cipher = AESGCM(encryption_key)
        self._scope_key = hmac.new(scope_key, b"ronas:household-progress:scope:v1",
                                   hashlib.sha256).digest()
        self._connect_timeout = connect_timeout
        self._initialize()

    def _connect(self):
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout,
                               application_name="ronas-household-progress",
                               row_factory=dict_row)

    def _initialize(self):
        try:
            with self._connect() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS ronas_domestic_progress_note (
                    action_id TEXT PRIMARY KEY,
                    household_ref TEXT NOT NULL,
                    case_version INTEGER NOT NULL CHECK (case_version > 0),
                    revision INTEGER NOT NULL CHECK (revision > 0),
                    input_revision INTEGER NOT NULL CHECK (input_revision >= 0),
                    corrects_revision INTEGER CHECK (corrects_revision IS NULL OR corrects_revision > 0),
                    owner_hash CHAR(64) NOT NULL,
                    reported_at TEXT NOT NULL,
                    note_ciphertext BYTEA NOT NULL CHECK (octet_length(note_ciphertext) BETWEEN 34 AND 1024),
                    note_digest CHAR(64) NOT NULL,
                    previous_receipt_digest CHAR(64) NOT NULL,
                    receipt_digest CHAR(64) NOT NULL UNIQUE,
                    UNIQUE (household_ref, revision)
                )""")
                db.execute("""CREATE INDEX IF NOT EXISTS ronas_domestic_progress_lookup
                    ON ronas_domestic_progress_note(household_ref, revision)""")
                db.execute("""CREATE TABLE IF NOT EXISTS ronas_domestic_progress_access (
                    household_ref TEXT NOT NULL,
                    event_sequence BIGINT NOT NULL CHECK (event_sequence > 0),
                    owner_hash CHAR(64) NOT NULL,
                    event_kind TEXT NOT NULL CHECK (event_kind IN ('READ','APPEND','REPLAY')),
                    revision INTEGER NOT NULL CHECK (revision >= 0),
                    action_id TEXT NOT NULL,
                    receipt_digest CHAR(64) NOT NULL,
                    occurred_at TEXT NOT NULL,
                    previous_event_digest CHAR(64) NOT NULL,
                    event_digest CHAR(64) NOT NULL,
                    PRIMARY KEY (household_ref, event_sequence)
                )""")
                db.execute("""CREATE OR REPLACE FUNCTION ronas_reject_progress_access_mutation()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'progress access history is immutable'; END;
                    $$""")
                db.execute("""DO $$ BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                        WHERE tgname='ronas_domestic_progress_access_immutable'
                        AND tgrelid='ronas_domestic_progress_access'::regclass
                        AND NOT tgisinternal) THEN
                      CREATE TRIGGER ronas_domestic_progress_access_immutable
                      BEFORE UPDATE OR DELETE ON ronas_domestic_progress_access
                      FOR EACH ROW EXECUTE FUNCTION ronas_reject_progress_access_mutation();
                    END IF;
                    END $$""")
                db.execute("""CREATE OR REPLACE FUNCTION ronas_reject_progress_note_mutation()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'progress note history is immutable'; END;
                    $$""")
                db.execute("""DO $$ BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                        WHERE tgname='ronas_domestic_progress_note_immutable'
                        AND tgrelid='ronas_domestic_progress_note'::regclass
                        AND NOT tgisinternal) THEN
                      CREATE TRIGGER ronas_domestic_progress_note_immutable
                      BEFORE UPDATE OR DELETE ON ronas_domestic_progress_note
                      FOR EACH ROW EXECUTE FUNCTION ronas_reject_progress_note_mutation();
                    END IF;
                    END $$""")
        except psycopg.Error as exc:
            raise LedgerIntegrityError("progress note storage unavailable") from exc

    @staticmethod
    def _hash(value) -> str:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _authorized_context(self, ref: str, principal: Principal):
        if (not isinstance(principal, Principal) or "household" not in principal.roles
                or not _synthetic_ref(ref) or not principal.subject
                or not _synthetic_subject(principal.subject)):
            return None
        try:
            if self._authority(principal, ref, self._schema_ref) is not True:
                return None
            context = self._context_reader(ref, principal)
        except Exception as exc:
            raise LedgerIntegrityError("household authority unavailable") from exc
        if (not isinstance(context, dict) or type(context.get("case_version")) is not int
                or context["case_version"] < 1
                or type(context.get("current_input_revision")) is not int
                or context["current_input_revision"] < 0):
            return None
        return context

    def _owner_hash(self, owner: str) -> str:
        return hmac.new(self._scope_key, owner.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _aad(ref: str, revision: int, owner_hash: str) -> bytes:
        return f"ronas-progress:{ref}:{revision}:{owner_hash}".encode("utf-8")

    def _encrypt(self, ref: str, revision: int, owner_hash: str, note: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(nonce, note.encode("utf-8"),
                                            self._aad(ref, revision, owner_hash))

    def _decrypt(self, row) -> str:
        value = row["note_ciphertext"]
        if isinstance(value, memoryview):
            value = value.tobytes()
        try:
            note = self._cipher.decrypt(value[:12], value[12:], self._aad(
                row["household_ref"], row["revision"], row["owner_hash"].strip(),
            )).decode("utf-8")
        except (InvalidTag, UnicodeDecodeError, TypeError) as exc:
            raise LedgerIntegrityError("progress note ciphertext integrity failure") from exc
        if self._hash(note) != row["note_digest"].strip():
            raise LedgerIntegrityError("progress note digest integrity failure")
        return note

    def _rows(self, db, ref: str):
        return list(db.execute("SELECT * FROM ronas_domestic_progress_note "
                               "WHERE household_ref=%s ORDER BY revision", (ref,)))

    def _verify_access(self, db, ref: str, owner_hash: str):
        rows = list(db.execute("SELECT * FROM ronas_domestic_progress_access "
                               "WHERE household_ref=%s ORDER BY event_sequence", (ref,)))
        note_receipts = {row["revision"]: row["receipt_digest"].strip()
                         for row in db.execute("SELECT revision,receipt_digest "
                                               "FROM ronas_domestic_progress_note "
                                               "WHERE household_ref=%s", (ref,))}
        previous = "0" * 64
        for sequence, row in enumerate(rows, 1):
            revision = row["revision"]
            linked_receipt = note_receipts.get(revision) if revision else "0" * 64
            payload = {
                "ref": ref, "sequence": sequence, "owner_hash": owner_hash,
                "kind": row["event_kind"], "revision": revision,
                "action_id": row["action_id"], "receipt_digest": row["receipt_digest"].strip(),
                "occurred_at": row["occurred_at"], "previous": previous,
            }
            if (row["event_sequence"] != sequence or row["owner_hash"].strip() != owner_hash
                    or row["previous_event_digest"].strip() != previous
                    or row["event_kind"] not in {"READ", "APPEND", "REPLAY"}
                    or linked_receipt != row["receipt_digest"].strip()
                    or row["event_kind"] in {"APPEND", "REPLAY"} and revision < 1
                    or row["event_digest"].strip() != self._hash(payload)):
                raise LedgerIntegrityError("progress access receipt chain failure")
            previous = row["event_digest"].strip()
        return rows

    def _record_access(self, db, ref: str, owner_hash: str, kind: str,
                       revision: int, action_id: str, receipt_digest: str):
        events = self._verify_access(db, ref, owner_hash)
        sequence = len(events) + 1
        previous = events[-1]["event_digest"].strip() if events else "0" * 64
        occurred_at = datetime.now(timezone.utc).isoformat()
        payload = {"ref": ref, "sequence": sequence, "owner_hash": owner_hash,
                   "kind": kind, "revision": revision, "action_id": action_id,
                   "receipt_digest": receipt_digest, "occurred_at": occurred_at,
                   "previous": previous}
        digest = self._hash(payload)
        db.execute("""INSERT INTO ronas_domestic_progress_access
            (household_ref,event_sequence,owner_hash,event_kind,revision,action_id,
             receipt_digest,occurred_at,previous_event_digest,event_digest)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (ref, sequence, owner_hash, kind, revision, action_id, receipt_digest,
             occurred_at, previous, digest))

    def _verify(self, rows, owner_hash: str):
        previous = "0" * 64
        corrected = set()
        notes = []
        for index, row in enumerate(rows, 1):
            note = self._decrypt(row)
            if (row["revision"] != index or row["owner_hash"].strip() != owner_hash
                    or row["previous_receipt_digest"].strip() != previous
                    or row["note_digest"].strip() != self._hash(note)):
                raise LedgerIntegrityError("progress note receipt chain failure")
            receipt = self._hash({
                "action_id": row["action_id"], "ref": row["household_ref"],
                "case_version": row["case_version"], "revision": index,
                "input_revision": row["input_revision"],
                "corrects_revision": row["corrects_revision"],
                "owner_hash": owner_hash, "reported_at": row["reported_at"],
                "note_digest": row["note_digest"].strip(), "previous": previous,
            })
            if receipt != row["receipt_digest"].strip():
                raise LedgerIntegrityError("progress note receipt mismatch")
            if row["corrects_revision"] is not None:
                target = row["corrects_revision"]
                if target >= index or target in corrected:
                    raise LedgerIntegrityError("progress correction chain failure")
                corrected.add(target)
            notes.append((row, note))
            previous = receipt
        return notes

    def read_owned_progress_notes(self, ref: str, principal: Principal) -> dict | None:
        context = self._authorized_context(ref, principal)
        if context is None:
            return None
        owner_hash = self._owner_hash(principal.subject)
        try:
            with self._connect() as db:
                db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (ref,))
                rows = self._verify(self._rows(db, ref), owner_hash)
                self._record_access(db, ref, owner_hash, "READ", len(rows), "", 
                                    rows[-1][0]["receipt_digest"].strip() if rows else "0" * 64)
        except psycopg.Error as exc:
            raise LedgerIntegrityError("progress note storage unavailable") from exc
        corrected = {row["corrects_revision"] for row, _ in rows
                     if row["corrects_revision"] is not None}
        return {
            "contract_version": PROGRESS_CORRECTION_CONTRACT, "engine": "DOMESTIC",
            "ref": ref, "case_version": context["case_version"],
            "current_input_revision": context["current_input_revision"],
            "notes": [{
                "case_version": row["case_version"], "input_revision": row["input_revision"],
                "revision": row["revision"], "reported_at": row["reported_at"],
                "note": note, "corrects_revision": row["corrects_revision"],
                "superseded_by_revision": next((r["revision"] for r, _ in rows
                    if r["corrects_revision"] == row["revision"]), None),
                "is_superseded": row["revision"] in corrected,
                "current_case_version": row["case_version"] == context["case_version"],
                "current_input_context": row["input_revision"] == context["current_input_revision"],
            } for row, note in rows],
            "current_revision": len(rows), "real_data": False,
            "scientific_review": False, "expert_inspection": False, "plan_accepted": False,
        }

    def append_owned_progress_note(self, ref: str, principal: Principal, *, action_id: str,
                                   expected_case_version: int, expected_revision: int,
                                   expected_input_revision: int, corrects_revision: int | None = None,
                                   reported_at: str, note: str) -> dict | None:
        if (not _synthetic_ref(action_id) or type(expected_case_version) is not int
                or expected_case_version < 1 or type(expected_revision) is not int
                or expected_revision < 0 or type(expected_input_revision) is not int
                or expected_input_revision < 0
                or not SqliteSyntheticHouseholdInputLedger._valid_reported_at(reported_at)
                or corrects_revision is not None and (
                    type(corrects_revision) is not int or corrects_revision < 1)
                or not isinstance(note, str) or not note.startswith("DEMO:")
                or not 6 <= len(note) <= 150 or note != note.strip()):
            raise ValueError("invalid synthetic progress note")
        context = self._authorized_context(ref, principal)
        if context is None:
            return None
        if context["case_version"] != expected_case_version:
            raise InputRevisionConflict("stale case version")
        owner_hash = self._owner_hash(principal.subject)
        try:
            with self._connect() as db:
                db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (ref,))
                rows = self._rows(db, ref)
                verified = self._verify(rows, owner_hash)
                self._verify_access(db, ref, owner_hash)
                replay = next((row for row in rows if row["action_id"] == action_id), None)
                if replay is not None:
                    same = (replay["household_ref"] == ref
                            and replay["case_version"] == expected_case_version
                            and replay["revision"] == expected_revision + 1
                            and replay["input_revision"] == expected_input_revision
                            and replay["corrects_revision"] == corrects_revision
                            and replay["reported_at"] == reported_at
                            and self._decrypt(replay) == note)
                    if not same:
                        raise InputRevisionConflict("conflicting progress note replay")
                    self._record_access(db, ref, owner_hash, "REPLAY", replay["revision"],
                                        action_id, replay["receipt_digest"].strip())
                    return {"contract_version": PROGRESS_CORRECTION_CONTRACT,
                            "engine": "DOMESTIC", "ref": ref,
                            "case_version": expected_case_version,
                            "input_revision": expected_input_revision,
                            "corrects_revision": corrects_revision,
                            "revision": expected_revision + 1, "idempotent_replay": True,
                            "real_data": False, "scientific_review": False,
                            "expert_inspection": False, "plan_accepted": False}
                if context["current_input_revision"] != expected_input_revision:
                    raise InputRevisionConflict("stale household input revision")
                if len(rows) != expected_revision:
                    raise InputRevisionConflict("stale progress note revision")
                if corrects_revision is not None and (
                    corrects_revision > expected_revision
                    or not any(r["revision"] == corrects_revision for r, _ in verified)
                    or any(r["corrects_revision"] == corrects_revision for r, _ in verified)
                ):
                    raise InputRevisionConflict("progress correction target unavailable")
                revision = expected_revision + 1
                previous = rows[-1]["receipt_digest"].strip() if rows else "0" * 64
                note_digest = self._hash(note)
                receipt = self._hash({
                    "action_id": action_id, "ref": ref, "case_version": expected_case_version,
                    "revision": revision, "input_revision": expected_input_revision,
                    "corrects_revision": corrects_revision, "owner_hash": owner_hash,
                    "reported_at": reported_at, "note_digest": note_digest,
                    "previous": previous,
                })
                db.execute("""INSERT INTO ronas_domestic_progress_note (
                    action_id,household_ref,case_version,revision,input_revision,
                    corrects_revision,owner_hash,reported_at,note_ciphertext,note_digest,
                    previous_receipt_digest,receipt_digest)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (action_id, ref, expected_case_version, revision, expected_input_revision,
                     corrects_revision, owner_hash, reported_at,
                     self._encrypt(ref, revision, owner_hash, note), note_digest, previous, receipt))
                self._record_access(db, ref, owner_hash, "APPEND", revision, action_id, receipt)
        except psycopg.Error as exc:
            raise LedgerIntegrityError("progress note storage unavailable") from exc
        return {"contract_version": PROGRESS_CORRECTION_CONTRACT, "engine": "DOMESTIC",
                "ref": ref, "case_version": expected_case_version, "revision": revision,
                "input_revision": expected_input_revision, "corrects_revision": corrects_revision,
                "idempotent_replay": False, "real_data": False,
                "scientific_review": False, "expert_inspection": False, "plan_accepted": False}
