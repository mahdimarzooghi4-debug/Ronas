"""Encrypted PostgreSQL adapter for private Domestic stage observation artifacts."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Mapping
from datetime import datetime, timezone

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .stage_observation_artifacts import (
    MAX_ARTIFACT_BYTES, StageArtifact, StageArtifactStoreError,
    _DIGEST, _validated_content_type,
)

_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_ROTATION_BATCH = 500


class PostgresStageArtifactStore:
    """Private encrypted artifact store with bounded encryption-key rotation."""

    def __init__(
        self, dsn: str, encryption_key: bytes | None = None, *,
        connect_timeout: int = 3, keyring: Mapping[str, bytes] | None = None,
        active_key_id: str = "default", scope_key: bytes | None = None,
    ):
        if not isinstance(dsn, str) or not dsn or len(dsn) > 4096 or "\x00" in dsn:
            raise ValueError("PostgreSQL DSN required")
        if type(connect_timeout) is not int or not 1 <= connect_timeout <= 15:
            raise ValueError("bounded connection timeout required")
        if not isinstance(active_key_id, str) or not _KEY_ID.fullmatch(active_key_id):
            raise ValueError("valid active encryption key id required")
        if keyring is None:
            if not isinstance(encryption_key, bytes) or len(encryption_key) != 32:
                raise ValueError("stage artifact AES-256 key must contain 32 bytes")
            keys = {active_key_id: encryption_key}
            scope_material = encryption_key if scope_key is None else scope_key
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
            scope_material = scope_key
        if not isinstance(scope_material, bytes) or len(scope_material) != 32:
            raise ValueError("stable scope HMAC key must contain 32 bytes")
        self._dsn = dsn
        self._keys = {key_id: AESGCM(key) for key_id, key in keys.items()}
        self._active_key_id = active_key_id
        self._scope_key = hmac.new(
            scope_material, b"ronas:stage-artifact:scope:v1", hashlib.sha256,
        ).digest()
        self._connect_timeout = connect_timeout
        self._initialize()

    def _connect(self):
        return psycopg.connect(
            self._dsn, connect_timeout=self._connect_timeout,
            application_name="ronas-stage-artifact",
        )

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS ronas_stage_artifact (
                    owner_hash CHAR(64) NOT NULL
                        CHECK (owner_hash ~ '^[0-9a-f]{64}$'),
                    case_hash CHAR(64) NOT NULL
                        CHECK (case_hash ~ '^[0-9a-f]{64}$'),
                    digest CHAR(64) NOT NULL
                        CHECK (digest ~ '^[0-9a-f]{64}$'),
                    content_type TEXT NOT NULL CHECK (content_type IN
                        ('image/jpeg','image/png','image/webp','application/pdf')),
                    byte_length INTEGER NOT NULL
                        CHECK (byte_length BETWEEN 1 AND 8388608),
                    ciphertext BYTEA NOT NULL
                        CHECK (octet_length(ciphertext) BETWEEN 29 AND 8388636),
                    encryption_key_id TEXT NOT NULL DEFAULT 'default',
                    PRIMARY KEY (owner_hash, case_hash, digest)
                )
            """)
            db.execute("""
                ALTER TABLE ronas_stage_artifact
                ADD COLUMN IF NOT EXISTS encryption_key_id TEXT NOT NULL DEFAULT 'default'
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS ronas_stage_artifact_key_rotation
                ON ronas_stage_artifact (encryption_key_id, owner_hash, case_hash, digest)
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS ronas_stage_artifact_access_event (
                    owner_hash CHAR(64) NOT NULL,
                    case_hash CHAR(64) NOT NULL,
                    event_sequence BIGINT NOT NULL CHECK (event_sequence > 0),
                    stage_hash CHAR(64) NOT NULL,
                    artifact_digest_hash CHAR(64) NOT NULL,
                    decision TEXT NOT NULL CHECK (decision IN ('READ_ALLOWED','READ_DENIED')),
                    occurred_at TEXT NOT NULL,
                    previous_event_digest CHAR(64) NOT NULL,
                    event_digest CHAR(64) NOT NULL,
                    PRIMARY KEY (owner_hash,case_hash,event_sequence)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS ronas_stage_artifact_access_head (
                    owner_hash CHAR(64) NOT NULL,
                    case_hash CHAR(64) NOT NULL,
                    event_sequence BIGINT NOT NULL CHECK (event_sequence >= 0),
                    event_digest CHAR(64) NOT NULL,
                    PRIMARY KEY (owner_hash,case_hash)
                )
            """)
            db.execute("""
                CREATE OR REPLACE FUNCTION ronas_reject_stage_artifact_access_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $
                BEGIN RAISE EXCEPTION 'stage artifact access history is immutable'; END;
                $
            """)
            db.execute("""
                DO $ BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                        WHERE tgname='ronas_stage_artifact_access_immutable'
                        AND tgrelid='ronas_stage_artifact_access_event'::regclass
                        AND NOT tgisinternal) THEN
                      CREATE TRIGGER ronas_stage_artifact_access_immutable
                      BEFORE UPDATE OR DELETE ON ronas_stage_artifact_access_event
                      FOR EACH ROW EXECUTE FUNCTION ronas_reject_stage_artifact_access_mutation();
                    END IF;
                END $
            """)

    def _scope(self, owner: str, case_ref: str,
               digest: str | None = None) -> tuple[str, str]:
        if (not isinstance(owner, str) or not owner or len(owner) > 256
                or not isinstance(case_ref, str) or not case_ref or len(case_ref) > 256
                or "\x00" in owner or "\x00" in case_ref
                or digest is not None
                   and (not isinstance(digest, str) or not _DIGEST.fullmatch(digest))):
            raise ValueError("invalid stage artifact scope")
        owner_hash = hmac.new(
            self._scope_key, b"owner\x00" + owner.encode("utf-8"), hashlib.sha256,
        ).hexdigest()
        case_hash = hmac.new(
            self._scope_key, b"case\x00" + case_ref.encode("utf-8"), hashlib.sha256,
        ).hexdigest()
        return owner_hash, case_hash

    @staticmethod
    def _aad(owner_hash: str, case_hash: str, digest: str, key_id: str) -> bytes:
        if key_id == "default":
            return (owner_hash + ":" + case_hash + ":" + digest).encode("ascii")
        return (owner_hash + ":" + case_hash + ":" + digest + ":" + key_id).encode("ascii")

    def _encrypt(self, owner_hash: str, case_hash: str, digest: str,
                 content: bytes, key_id: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._keys[key_id].encrypt(
            nonce, content, self._aad(owner_hash, case_hash, digest, key_id),
        )

    def _decrypt(self, owner_hash: str, case_hash: str, digest: str, key_id: str,
                 encrypted: object, length: object, media: object) -> tuple[StageArtifact, bytes]:
        cipher = self._keys.get(key_id) if isinstance(key_id, str) else None
        if cipher is None:
            raise StageArtifactStoreError("artifact encryption key is unavailable")
        if isinstance(encrypted, memoryview):
            encrypted = encrypted.tobytes()
        if (media not in ("image/jpeg", "image/png", "image/webp", "application/pdf")
                or type(length) is not int or not 1 <= length <= MAX_ARTIFACT_BYTES
                or not isinstance(encrypted, bytes)
                or not 29 <= len(encrypted) <= MAX_ARTIFACT_BYTES + 28):
            raise StageArtifactStoreError("artifact metadata is invalid")
        try:
            content = cipher.decrypt(
                encrypted[:12], encrypted[12:],
                self._aad(owner_hash, case_hash, digest, key_id),
            )
        except InvalidTag as exc:
            raise StageArtifactStoreError("artifact authentication failed") from exc
        if (len(content) != length
                or not hmac.compare_digest(hashlib.sha256(content).hexdigest(), digest)):
            raise StageArtifactStoreError("artifact integrity check failed")
        try:
            checked_media = _validated_content_type(media, content)
        except ValueError as exc:
            raise StageArtifactStoreError("artifact media signature is invalid") from exc
        return StageArtifact(digest, checked_media, length), content

    def put(self, owner: str, case_ref: str, content_type: str,
            content: bytes) -> StageArtifact:
        if not isinstance(content, bytes) or not 1 <= len(content) <= MAX_ARTIFACT_BYTES:
            raise ValueError("stage artifact size is outside the allowed range")
        media = _validated_content_type(content_type, content)
        owner_hash, case_hash = self._scope(owner, case_ref)
        digest = hashlib.sha256(content).hexdigest()
        ciphertext = self._encrypt(
            owner_hash, case_hash, digest, content, self._active_key_id,
        )
        try:
            with self._connect() as db:
                db.execute("""
                    INSERT INTO ronas_stage_artifact
                      (owner_hash,case_hash,digest,content_type,byte_length,ciphertext,encryption_key_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (owner_hash,case_hash,digest) DO NOTHING
                """, (owner_hash, case_hash, digest, media, len(content),
                      ciphertext, self._active_key_id))
        except psycopg.Error as exc:
            raise StageArtifactStoreError("artifact write failed") from exc
        existing = self.get(owner, case_ref, digest)
        if existing is None or not hmac.compare_digest(existing[1], content):
            raise StageArtifactStoreError("artifact digest collision or write failure")
        return existing[0]

    def get(self, owner: str, case_ref: str, digest: str
            ) -> tuple[StageArtifact, bytes] | None:
        owner_hash, case_hash = self._scope(owner, case_ref, digest)
        try:
            with self._connect() as db:
                row = db.execute("""
                    SELECT content_type,byte_length,ciphertext,encryption_key_id
                    FROM ronas_stage_artifact
                    WHERE owner_hash=%s AND case_hash=%s AND digest=%s
                """, (owner_hash, case_hash, digest)).fetchone()
        except psycopg.Error as exc:
            raise StageArtifactStoreError("artifact read failed") from exc
        if row is None:
            return None
        media, length, encrypted, key_id = row
        return self._decrypt(
            owner_hash, case_hash, digest, key_id, encrypted, length, media,
        )

    def contains(self, owner: str, case_ref: str, digest: str) -> bool:
        return self.get(owner, case_ref, digest) is not None

    @staticmethod
    def _audit_hash(payload: dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _audit_scope_hash(self, label: bytes, value: str) -> str:
        return hmac.new(
            self._scope_key, label + b"\x00" + value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _verify_access_events(self, db, owner_hash: str, case_hash: str):
        rows = db.execute("""
            SELECT event_sequence,stage_hash,artifact_digest_hash,decision,
                   occurred_at,previous_event_digest,event_digest
            FROM ronas_stage_artifact_access_event
            WHERE owner_hash=%s AND case_hash=%s ORDER BY event_sequence
        """, (owner_hash, case_hash)).fetchall()
        previous = "0" * 64
        checked = []
        for sequence, stage_hash, artifact_hash, decision, occurred_at, prior, digest in rows:
            payload = {
                "owner_hash": owner_hash, "case_hash": case_hash,
                "event_sequence": sequence, "stage_hash": stage_hash.strip(),
                "artifact_digest_hash": artifact_hash.strip(),
                "decision": decision, "occurred_at": occurred_at,
                "previous_event_digest": previous,
            }
            expected = self._audit_hash(payload)
            if (sequence != len(checked) + 1
                    or decision not in {"READ_ALLOWED", "READ_DENIED"}
                    or prior.strip() != previous or digest.strip() != expected):
                raise StageArtifactStoreError("artifact access audit chain failure")
            previous = digest.strip()
            checked.append({
                "event_sequence": sequence, "stage_hash": stage_hash.strip(),
                "artifact_digest_hash": artifact_hash.strip(),
                "decision": decision, "occurred_at": occurred_at,
                "previous_event_digest": prior.strip(),
                "event_digest": digest.strip(),
            })
        head = db.execute("""
            SELECT event_sequence,event_digest FROM ronas_stage_artifact_access_head
            WHERE owner_hash=%s AND case_hash=%s
        """, (owner_hash, case_hash)).fetchone()
        expected_head = (len(checked), previous)
        actual_head = (0, "0" * 64) if head is None else (head[0], head[1].strip())
        if actual_head != expected_head:
            raise StageArtifactStoreError("artifact access audit head mismatch")
        return checked

    def record_access(
        self, owner: str, case_ref: str, stage_ref: str, digest: str, *,
        permitted: bool,
    ) -> bool:
        """Persist a redacted, append-only access decision shared by BFF workers."""
        if (not isinstance(stage_ref, str) or not 1 <= len(stage_ref) <= 128
                or "\x00" in stage_ref or type(permitted) is not bool):
            raise ValueError("invalid stage artifact access audit")
        owner_hash, case_hash = self._scope(owner, case_ref + ":" + stage_ref, digest)
        stage_hash = self._audit_scope_hash(b"stage", stage_ref)
        artifact_hash = self._audit_scope_hash(b"artifact-digest", digest)
        decision = "READ_ALLOWED" if permitted else "READ_DENIED"
        try:
            with self._connect() as db:
                db.execute("""
                    INSERT INTO ronas_stage_artifact_access_head
                      (owner_hash,case_hash,event_sequence,event_digest)
                    VALUES (%s,%s,0,%s) ON CONFLICT (owner_hash,case_hash) DO NOTHING
                """, (owner_hash, case_hash, "0" * 64))
                head = db.execute("""
                    SELECT event_sequence,event_digest
                    FROM ronas_stage_artifact_access_head
                    WHERE owner_hash=%s AND case_hash=%s FOR UPDATE
                """, (owner_hash, case_hash)).fetchone()
                events = self._verify_access_events(db, owner_hash, case_hash)
                sequence, previous = head[0], head[1].strip()
                if sequence != len(events) or previous != (
                        events[-1]["event_digest"] if events else "0" * 64):
                    raise StageArtifactStoreError("artifact access audit head is inconsistent")
                occurred_at = datetime.now(timezone.utc).isoformat()
                payload = {
                    "owner_hash": owner_hash, "case_hash": case_hash,
                    "event_sequence": sequence + 1, "stage_hash": stage_hash,
                    "artifact_digest_hash": artifact_hash,
                    "decision": decision, "occurred_at": occurred_at,
                    "previous_event_digest": previous,
                }
                event_digest = self._audit_hash(payload)
                db.execute("""
                    INSERT INTO ronas_stage_artifact_access_event
                      (owner_hash,case_hash,event_sequence,stage_hash,
                       artifact_digest_hash,decision,occurred_at,
                       previous_event_digest,event_digest)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (owner_hash, case_hash, sequence + 1, stage_hash,
                      artifact_hash, decision, occurred_at, previous, event_digest))
                db.execute("""
                    UPDATE ronas_stage_artifact_access_head
                    SET event_sequence=%s,event_digest=%s
                    WHERE owner_hash=%s AND case_hash=%s
                """, (sequence + 1, event_digest, owner_hash, case_hash))
        except StageArtifactStoreError:
            raise
        except psycopg.Error as exc:
            raise StageArtifactStoreError("artifact access audit write failed") from exc
        return permitted

    def _access_events_for_scope(
        self, owner: str, case_ref: str, stage_ref: str, digest: str,
    ):
        """Private integrity-checked view for integration tests and diagnostics."""
        owner_hash, case_hash = self._scope(owner, case_ref + ":" + stage_ref, digest)
        try:
            with self._connect() as db:
                return self._verify_access_events(db, owner_hash, case_hash)
        except StageArtifactStoreError:
            raise
        except psycopg.Error as exc:
            raise StageArtifactStoreError("artifact access audit read failed") from exc

    def rotate_batch(self, limit: int = 100) -> int:
        """Atomically re-encrypt up to limit rows; safe for concurrent workers."""
        if type(limit) is not int or not 1 <= limit <= _MAX_ROTATION_BATCH:
            raise ValueError("rotation batch must be between 1 and 500")
        changed = 0
        try:
            with self._connect() as db:
                rows = db.execute("""
                    SELECT owner_hash,case_hash,digest,content_type,byte_length,ciphertext,encryption_key_id
                    FROM ronas_stage_artifact
                    WHERE encryption_key_id <> %s
                    ORDER BY owner_hash,case_hash,digest
                    LIMIT %s FOR UPDATE SKIP LOCKED
                """, (self._active_key_id, limit)).fetchall()
                for owner_hash, case_hash, digest, media, length, encrypted, old_key_id in rows:
                    _, content = self._decrypt(
                        owner_hash, case_hash, digest, old_key_id,
                        encrypted, length, media,
                    )
                    replacement = self._encrypt(
                        owner_hash, case_hash, digest, content, self._active_key_id,
                    )
                    result = db.execute("""
                        UPDATE ronas_stage_artifact
                        SET ciphertext=%s,encryption_key_id=%s
                        WHERE owner_hash=%s AND case_hash=%s AND digest=%s
                          AND encryption_key_id=%s
                    """, (replacement, self._active_key_id,
                          owner_hash, case_hash, digest, old_key_id))
                    if result.rowcount != 1:
                        raise StageArtifactStoreError("artifact rotation lost its row lock")
                    changed += 1
        except psycopg.Error as exc:
            raise StageArtifactStoreError("artifact key rotation failed") from exc
        return changed
