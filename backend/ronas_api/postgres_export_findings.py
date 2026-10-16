"""LOCAL/TEST PostgreSQL journal for encrypted Export research draft notes."""
from __future__ import annotations

import hashlib
import json
import secrets

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.rows import dict_row

from .auth import Principal
from .export_research_findings import (
    ExportResearchFindingConflict, finding_binding, finding_digest,
)
from .scoped_drafts import _synthetic_ref


class ExportFindingStorageError(RuntimeError):
    """Storage or integrity failure; callers must fail closed."""


class PostgresExportResearchFindingLedger:
    """Encrypted append-only journal, authorized against the live case ledger."""

    def __init__(self, dsn: str, workspace_reader, encryption_key: bytes, *,
                 connect_timeout: int = 3):
        if (not isinstance(dsn, str) or not dsn or len(dsn) > 4096 or "\x00" in dsn
                or not callable(workspace_reader)
                or not isinstance(encryption_key, bytes) or len(encryption_key) != 32
                or type(connect_timeout) is not int or not 1 <= connect_timeout <= 15):
            raise ValueError("PostgreSQL workspace reader and private key required")
        self._dsn = dsn
        self._workspace_reader = workspace_reader
        self._cipher = AESGCM(encryption_key)
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
                    note_digest CHAR(64) NOT NULL CHECK (note_digest ~ '^[0-9a-f]{64}$'),
                    previous_digest CHAR(64) NOT NULL CHECK (previous_digest ~ '^[0-9a-f]{64}$'),
                    receipt_digest CHAR(64) NOT NULL UNIQUE CHECK (receipt_digest ~ '^[0-9a-f]{64}$'),
                    UNIQUE(ref, question_revision, revision)
                )""")
                db.execute("""CREATE OR REPLACE FUNCTION ronas_reject_export_finding_mutation()
                    RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                    RAISE EXCEPTION 'Export research finding history is immutable'; END; $$""")
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
                    nonce = secrets.token_bytes(12)
                    aad = (ref + ":" + str(expected_question_revision) + ":" + str(current + 1)).encode()
                    ciphertext = nonce + self._cipher.encrypt(nonce, note.encode(), aad)
                    row = db.execute("""INSERT INTO ronas_export_research_finding
                        (action_id,ref,case_version,question_revision,evidence_revision,revision,
                        actor_digest,evidence_ref,source_ref,connector_ref,source_snapshot_digest,
                        note_ciphertext,note_digest,previous_digest,receipt_digest)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                        (action_id,ref,expected_case_version,expected_question_revision,evidence_revision,
                         current+1,actor,evidence_ref,ev.get("source_ref", ""),ev.get("connector_ref", ""),
                         ev.get("source_snapshot_digest", "0"*64),ciphertext,note_digest,previous,receipt)).fetchone()
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
            result = []
            previous_by_question = {}
            for row in rows:
                qrev = row["question_revision"]
                previous = previous_by_question.get(qrev, "0" * 64)
                binding = finding_binding(action_id=row["action_id"], ref=ref,
                    case_version=row["case_version"], question_revision=qrev,
                    evidence_revision=row["evidence_revision"], revision=row["revision"],
                    actor_digest=row["actor_digest"].strip(), evidence_ref=row["evidence_ref"],
                    note_digest=row["note_digest"].strip(), previous_digest=previous)
                binding.update(source_ref=row["source_ref"], connector_ref=row["connector_ref"],
                               source_snapshot_digest=row["source_snapshot_digest"].strip())
                if (row["previous_digest"].strip() != previous
                        or finding_digest(binding) != row["receipt_digest"].strip()):
                    raise ExportFindingStorageError("Export finding history integrity failure")
                previous_by_question[qrev] = row["receipt_digest"].strip()
                result.append(self._project(row, rows, workspace))
            return result
        except ExportFindingStorageError:
            raise
        except psycopg.Error as exc:
            raise ExportFindingStorageError("Export finding storage unavailable") from exc

    def _project(self, row, rows, workspace):
        aad = (row["ref"] + ":" + str(row["question_revision"]) + ":" + str(row["revision"])).encode()
        try:
            note = self._cipher.decrypt(bytes(row["note_ciphertext"][:12]),
                                       bytes(row["note_ciphertext"])[12:], aad).decode()
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise ExportFindingStorageError("Export finding note integrity failure") from exc
        if hashlib.sha256(note.encode("utf-8")).hexdigest() != row["note_digest"].strip():
            raise ExportFindingStorageError("Export finding note digest failure")
        current_question = (workspace.get("local_test_draft_question") or {}).get("question_revision")
        evidence = next((e for e in workspace.get("local_test_evidence_references", [])
                         if e.get("evidence_revision") == row["evidence_revision"]
                         and e.get("evidence_ref") == row["evidence_ref"]), None)
        return {"question_revision": row["question_revision"], "evidence_revision": row["evidence_revision"],
            "revision": row["revision"], "evidence_ref": row["evidence_ref"],
            "source_ref": row["source_ref"], "connector_ref": row["connector_ref"],
            "source_snapshot_digest": row["source_snapshot_digest"].strip(), "note": note,
            "question_binding": "CURRENT" if row["question_revision"] == current_question else "HISTORICAL",
            "evidence_binding": "CURRENT" if evidence is not None else "HISTORICAL",
            "draft_only": True, "report_approved": False}
