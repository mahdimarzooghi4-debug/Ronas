"""LOCAL/TEST PostgreSQL journal for encrypted Export research draft notes."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Mapping

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.rows import dict_row

from .auth import Principal
from .export_research_findings import (
    ExportResearchFindingConflict, finding_binding, finding_digest,
)
from .scoped_drafts import _synthetic_ref

_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_ROTATION_BATCH = 500


class ExportFindingStorageError(RuntimeError):
    """Storage or integrity failure; callers must fail closed."""


class PostgresExportResearchFindingLedger:
    """Encrypted append-only journal, authorized against the live case ledger."""

    def __init__(self, dsn: str, workspace_reader, encryption_key: bytes | None = None, *,
                 keyring: Mapping[str, bytes] | None = None,
                 active_key_id: str = "default", connect_timeout: int = 3):
        if (not isinstance(dsn, str) or not dsn or len(dsn) > 4096 or "\x00" in dsn
                or not callable(workspace_reader)
                or type(connect_timeout) is not int or not 1 <= connect_timeout <= 15):
            raise ValueError("PostgreSQL workspace reader and private key required")
        if not isinstance(active_key_id, str) or not _KEY_ID.fullmatch(active_key_id):
            raise ValueError("valid active encryption key id required")
        if keyring is None:
            if not isinstance(encryption_key, bytes) or len(encryption_key) != 32:
                raise ValueError("Export finding AES-256 key must contain 32 bytes")
            keys = {active_key_id: encryption_key}
        else:
            if encryption_key is not None or not isinstance(keyring, Mapping) or not keyring:
                raise ValueError("provide either one key or a non-empty keyring")
            keys = dict(keyring)
            if any(not isinstance(k, str) or not _KEY_ID.fullmatch(k)
                   or not isinstance(v, bytes) or len(v) != 32
                   for k, v in keys.items()):
                raise ValueError("keyring ids and AES-256 keys are invalid")
            if active_key_id not in keys:
                raise ValueError("active encryption key is absent from keyring")
        self._dsn = dsn
        self._workspace_reader = workspace_reader
        self._ciphers = {key_id: AESGCM(key) for key_id, key in keys.items()}
        self._active_key_id = active_key_id
        self._connect_timeout = connect_timeout
        self._initialize()

    def _connect(self):
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout,
                               application_name="ronas-export-research-findings",
                               row_factory=dict_row)

    def _initialize(self):
        try:
            with self._connect() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS ronas_export_research_finding (
                    action_id TEXT PRIMARY KEY,
                    ref TEXT NOT NULL,
                    case_version INTEGER NOT NULL CHECK (case_version > 0),
                    question_revision INTEGER NOT NULL CHECK (question_revision > 0),
                    evidence_revision INTEGER NOT NULL CHECK (evidence_revision > 0),
                    revision INTEGER NOT NULL CHECK (revision > 0),
                    actor_digest CHAR(64) NOT NULL CHECK (actor_digest ~ '^[0-9a-f]{64}$'),
                    evidence_ref TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    connector_ref TEXT NOT NULL,
                    source_snapshot_digest CHAR(64) NOT NULL CHECK (source_snapshot_digest ~ '^[0-9a-f]{64}$'),
                    note_ciphertext BYTEA NOT NULL CHECK (octet_length(note_ciphertext) >= 28),
                    encryption_key_id TEXT NOT NULL DEFAULT 'default',
                    note_digest CHAR(64) NOT NULL CHECK (note_digest ~ '^[0-9a-f]{64}$'),
                    previous_digest CHAR(64) NOT NULL CHECK (previous_digest ~ '^[0-9a-f]{64}$'),
                    receipt_digest CHAR(64) NOT NULL UNIQUE CHECK (receipt_digest ~ '^[0-9a-f]{64}$'),
                    UNIQUE(ref, question_revision, revision)
                )""")
                db.execute("""ALTER TABLE ronas_export_research_finding
                    ADD COLUMN IF NOT EXISTS encryption_key_id TEXT NOT NULL DEFAULT 'default'""")
                db.execute("""CREATE INDEX IF NOT EXISTS ronas_export_finding_key_rotation
                    ON ronas_export_research_finding
                    (encryption_key_id, ref, question_revision, revision)""")
                db.execute("""CREATE OR REPLACE FUNCTION ronas_reject_export_finding_mutation()
                    RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION 'Export research finding history is immutable';
                    END IF;
                    IF (to_jsonb(NEW) - 'note_ciphertext' - 'encryption_key_id')
                       IS DISTINCT FROM
                       (to_jsonb(OLD) - 'note_ciphertext' - 'encryption_key_id') THEN
                        RAISE EXCEPTION 'Export research finding history is immutable';
                    END IF;
                    RETURN NEW; END; $$""")
                db.execute("""DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger
                    WHERE tgname='ronas_export_finding_no_update_delete'
                    AND tgrelid='ronas_export_research_finding'::regclass AND NOT tgisinternal)
                    THEN CREATE TRIGGER ronas_export_finding_no_update_delete
                    BEFORE UPDATE OR DELETE ON ronas_export_research_finding
                    FOR EACH ROW EXECUTE FUNCTION ronas_reject_export_finding_mutation();
                    END IF; END $$""")
        except psycopg.Error as exc:
            raise ExportFindingStorageError("Export finding storage unavailable") from exc

    def _workspace(self, ref, principal):
        try:
            return self._workspace_reader(ref, principal)
        except Exception as exc:
            raise ExportFindingStorageError("Export case authorization unavailable") from exc

    def record_export_research_finding(self, ref: str, principal: Principal, *,
            expected_case_version: int, expected_question_revision: int,
            expected_finding_revision: int, evidence_revision: int,
            action_id: str, evidence_ref: str, note: str) -> dict | None:
        if (not _synthetic_ref(ref) or not isinstance(principal, Principal)
                or type(expected_case_version) is not int or type(expected_question_revision) is not int
                or expected_question_revision < 1 or type(expected_finding_revision) is not int
                or expected_finding_revision < 0 or type(evidence_revision) is not int
                or evidence_revision < 1 or not _synthetic_ref(action_id)
                or not _synthetic_ref(evidence_ref) or not evidence_ref.startswith("DEMO-EVIDENCE-")
                or not isinstance(note, str) or not note.startswith("DEMO:")
                or note != note.strip() or not 8 <= len(note) <= 2000):
            raise ValueError("invalid DEMO Export finding command")
        workspace = self._workspace(ref, principal)
        if workspace is None:
            return None
        question = workspace.get("local_test_draft_question") or {}
        evidence = next((e for e in workspace.get("local_test_evidence_references", [])
                         if e.get("evidence_revision") == evidence_revision
                         and e.get("evidence_ref") == evidence_ref), None)
        if (workspace.get("case_version") != expected_case_version
                or question.get("question_revision") != expected_question_revision
                or evidence is None):
            raise ExportResearchFindingConflict("stale Export case, question, or evidence")
        actor = hashlib.sha256(principal.subject.encode("utf-8")).hexdigest()
        note_digest = hashlib.sha256(note.encode("utf-8")).hexdigest()
        try:
            with self._connect() as db:
                db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                           ("ronas-export-finding-action:" + action_id,))
                db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                           ("ronas-export-finding:" + ref + ":" + str(expected_question_revision),))
                # Authorization and current question/evidence are rechecked under the append lock.
                workspace = self._workspace(ref, principal)
                if workspace is None:
                    return None
                q = workspace.get("local_test_draft_question") or {}
                ev = next((e for e in workspace.get("local_test_evidence_references", [])
                           if e.get("evidence_revision") == evidence_revision
                           and e.get("evidence_ref") == evidence_ref), None)
                if (workspace.get("case_version") != expected_case_version
                        or q.get("question_revision") != expected_question_revision or ev is None):
                    raise ExportResearchFindingConflict("Export context changed")
                rows = db.execute("SELECT * FROM ronas_export_research_finding WHERE ref=%s AND question_revision=%s ORDER BY revision",
                                  (ref, expected_question_revision)).fetchall()
                self._verify_chain(ref, rows)
                current = rows[-1]["revision"] if rows else 0
                previous = rows[-1]["receipt_digest"] if rows else "0" * 64
                replay = db.execute("SELECT * FROM ronas_export_research_finding WHERE action_id=%s",
                                    (action_id,)).fetchone()
                expected_revision = expected_finding_revision + 1
                if replay:
                    if (replay["ref"] != ref or replay["case_version"] != expected_case_version
                            or replay["question_revision"] != expected_question_revision
                            or replay["evidence_revision"] != evidence_revision
                            or replay["revision"] != expected_revision
                            or replay["actor_digest"].strip() != actor or replay["evidence_ref"] != evidence_ref
                            or replay["source_ref"] != ev["source_ref"]
                            or replay["connector_ref"] != ev["connector_ref"]
                            or replay["source_snapshot_digest"].strip() != ev["source_snapshot_digest"]
                            or replay["note_digest"].strip() != note_digest or current != expected_revision):
                        raise ExportResearchFindingConflict("conflicting finding replay")
                    row = replay
                else:
                    if current != expected_finding_revision:
                        raise ExportResearchFindingConflict("stale finding revision")
                    binding = finding_binding(action_id=action_id, ref=ref,
                        case_version=expected_case_version, question_revision=expected_question_revision,
                        evidence_revision=evidence_revision, revision=current + 1,
                        actor_digest=actor, evidence_ref=evidence_ref, note_digest=note_digest,
                        previous_digest=previous)
                    binding.update(source_ref=ev["source_ref"], connector_ref=ev["connector_ref"],
                                   source_snapshot_digest=ev["source_snapshot_digest"])
                    receipt = finding_digest(binding)
                    ciphertext = self._encrypt_note(
                        ref, expected_question_revision, current + 1, note.encode(),
                        self._active_key_id,
                    )
                    row = db.execute("""INSERT INTO ronas_export_research_finding
                        (action_id,ref,case_version,question_revision,evidence_revision,revision,
                        actor_digest,evidence_ref,source_ref,connector_ref,source_snapshot_digest,
                        note_ciphertext,encryption_key_id,note_digest,previous_digest,receipt_digest)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                        (action_id,ref,expected_case_version,expected_question_revision,evidence_revision,
                         current+1,actor,evidence_ref,ev.get("source_ref", ""),ev.get("connector_ref", ""),
                         ev.get("source_snapshot_digest", "0"*64),ciphertext,self._active_key_id,
                         note_digest,previous,receipt)).fetchone()
                latest = self._workspace(ref, principal)
                latest_question = (latest or {}).get("local_test_draft_question") or {}
                latest_evidence = next((e for e in (latest or {}).get("local_test_evidence_references", [])
                                        if e.get("evidence_revision") == evidence_revision
                                        and e.get("evidence_ref") == evidence_ref), None)
                if (latest is None or latest.get("case_version") != expected_case_version
                        or latest_question.get("question_revision") != expected_question_revision
                        or latest_evidence is None
                        or latest_evidence.get("source_snapshot_digest") != ev.get("source_snapshot_digest")):
                    raise ExportResearchFindingConflict("Export context changed during append")
                return self._project(row, rows, workspace)
        except ExportResearchFindingConflict:
            raise
        except ExportFindingStorageError:
            raise
        except psycopg.Error as exc:
            raise ExportFindingStorageError("Export finding storage unavailable") from exc

    def read_history(self, ref: str, principal: Principal) -> list[dict] | None:
        workspace = self._workspace(ref, principal)
        if workspace is None:
            return None
        try:
            with self._connect() as db:
                rows = db.execute("SELECT * FROM ronas_export_research_finding WHERE ref=%s ORDER BY question_revision,revision",
                                  (ref,)).fetchall()
            self._verify_chain(ref, rows)
            result = []
            for row in rows:
                result.append(self._project(row, rows, workspace))
            return result
        except ExportFindingStorageError:
            raise
        except psycopg.Error as exc:
            raise ExportFindingStorageError("Export finding storage unavailable") from exc

    def _project(self, row, rows, workspace):
        note = self._decrypt_note(row)
        current_question = (workspace.get("local_test_draft_question") or {}).get("question_revision")
        evidence_rows = workspace.get("local_test_evidence_references", [])
        current_evidence_revision = max(
            (e.get("evidence_revision", 0) for e in evidence_rows), default=0,
        )
        evidence_is_current = (
            row["question_revision"] == current_question
            and any(e.get("evidence_revision") == row["evidence_revision"]
                    and e.get("evidence_ref") == row["evidence_ref"]
                    and e.get("evidence_revision") == current_evidence_revision
                    for e in evidence_rows)
        )
        return {"question_revision": row["question_revision"], "evidence_revision": row["evidence_revision"],
            "revision": row["revision"], "evidence_ref": row["evidence_ref"],
            "source_ref": row["source_ref"], "connector_ref": row["connector_ref"],
            "source_snapshot_digest": row["source_snapshot_digest"].strip(), "note": note,
            "question_binding": "CURRENT" if row["question_revision"] == current_question else "HISTORICAL",
            "evidence_binding": "CURRENT" if evidence_is_current else "HISTORICAL",
            "draft_only": True, "report_approved": False}

    @staticmethod
    def _aad(ref: str, question_revision: int, revision: int, key_id: str) -> bytes:
        # Preserve original v1 AAD for rows written before key ids existed.
        suffix = "" if key_id == "default" else ":" + key_id
        return (ref + ":" + str(question_revision) + ":" + str(revision)
                + suffix).encode("utf-8")

    def _encrypt_note(self, ref: str, question_revision: int, revision: int,
                      note: bytes, key_id: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._ciphers[key_id].encrypt(
            nonce, note, self._aad(ref, question_revision, revision, key_id),
        )

    def _decrypt_note(self, row) -> str:
        key_id = row.get("encryption_key_id", "default")
        cipher = self._ciphers.get(key_id) if isinstance(key_id, str) else None
        encrypted = row.get("note_ciphertext")
        if cipher is None or not isinstance(encrypted, (bytes, memoryview)):
            raise ExportFindingStorageError("Export finding encryption key is unavailable")
        encrypted = bytes(encrypted)
        if len(encrypted) < 28:
            raise ExportFindingStorageError("Export finding ciphertext is invalid")
        try:
            note = cipher.decrypt(
                encrypted[:12], encrypted[12:],
                self._aad(row["ref"], row["question_revision"], row["revision"], key_id),
            ).decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise ExportFindingStorageError("Export finding note integrity failure") from exc
        if hashlib.sha256(note.encode("utf-8")).hexdigest() != row["note_digest"].strip():
            raise ExportFindingStorageError("Export finding note digest failure")
        return note

    def rotate_batch(self, limit: int = 100) -> int:
        """Atomically re-encrypt at most limit rows; safe for concurrent workers."""
        if type(limit) is not int or not 1 <= limit <= _MAX_ROTATION_BATCH:
            raise ValueError("rotation batch must be between 1 and 500")
        changed = 0
        try:
            with self._connect() as db:
                rows = db.execute("""SELECT * FROM ronas_export_research_finding
                    WHERE encryption_key_id <> %s
                    ORDER BY ref,question_revision,revision
                    LIMIT %s FOR UPDATE SKIP LOCKED""",
                    (self._active_key_id, limit)).fetchall()
                for row in rows:
                    note = self._decrypt_note(row)
                    replacement = self._encrypt_note(
                        row["ref"], row["question_revision"], row["revision"],
                        note.encode("utf-8"), self._active_key_id,
                    )
                    result = db.execute("""UPDATE ronas_export_research_finding
                        SET note_ciphertext=%s,encryption_key_id=%s
                        WHERE action_id=%s AND encryption_key_id=%s""",
                        (replacement, self._active_key_id, row["action_id"],
                         row["encryption_key_id"]))
                    if result.rowcount != 1:
                        raise ExportFindingStorageError("finding rotation lost its row lock")
                    changed += 1
        except ExportFindingStorageError:
            raise
        except psycopg.Error as exc:
            raise ExportFindingStorageError("Export finding key rotation failed") from exc
        return changed

    def _verify_chain(self, ref, rows):
        previous_by_question = {}
        revision_by_question = {}
        for row in rows:
            qrev = row["question_revision"]
            previous = previous_by_question.get(qrev, "0" * 64)
            expected_revision = revision_by_question.get(qrev, 0) + 1
            binding = finding_binding(action_id=row["action_id"], ref=ref,
                case_version=row["case_version"], question_revision=qrev,
                evidence_revision=row["evidence_revision"], revision=row["revision"],
                actor_digest=row["actor_digest"].strip(), evidence_ref=row["evidence_ref"],
                note_digest=row["note_digest"].strip(), previous_digest=previous)
            binding.update(source_ref=row["source_ref"], connector_ref=row["connector_ref"],
                           source_snapshot_digest=row["source_snapshot_digest"].strip())
            if (row["revision"] != expected_revision
                    or row["previous_digest"].strip() != previous
                    or finding_digest(binding) != row["receipt_digest"].strip()):
                raise ExportFindingStorageError("Export finding history integrity failure")
            previous_by_question[qrev] = row["receipt_digest"].strip()
            revision_by_question[qrev] = row["revision"]
