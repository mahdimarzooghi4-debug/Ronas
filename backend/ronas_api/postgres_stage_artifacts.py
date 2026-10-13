"""Encrypted PostgreSQL adapter for private Domestic stage observation artifacts."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Mapping

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
