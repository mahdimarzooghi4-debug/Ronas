"""Encrypted PostgreSQL adapter for private Domestic stage observation artifacts."""
from __future__ import annotations

import hashlib
import hmac
import secrets

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.errors import UniqueViolation

from .stage_observation_artifacts import (
    MAX_ARTIFACT_BYTES, StageArtifact, StageArtifactStoreError,
    _DIGEST, _validated_content_type,
)


class PostgresStageArtifactStore:
    """Private, content-addressed artifact store backed by PostgreSQL BYTEA.

    Artifact bytes are AES-256-GCM encrypted before reaching the database.
    Owner and case references are hashed in storage and included in the AEAD
    associated data. The adapter is opt-in; callers inject it through the
    existing StageArtifactStore interface.
    """

    def __init__(self, dsn: str, encryption_key: bytes, *, connect_timeout: int = 3):
        if not isinstance(dsn, str) or not dsn or len(dsn) > 4096 or "\x00" in dsn:
            raise ValueError("PostgreSQL DSN required")
        if not isinstance(encryption_key, bytes) or len(encryption_key) != 32:
            raise ValueError("stage artifact AES-256 key must contain 32 bytes")
        if type(connect_timeout) is not int or not 1 <= connect_timeout <= 15:
            raise ValueError("bounded connection timeout required")
        self._dsn = dsn
        self._cipher = AESGCM(encryption_key)
        self._scope_key = hmac.new(
            encryption_key, b"ronas:stage-artifact:scope:v1", hashlib.sha256,
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
                    content_type TEXT NOT NULL
                        CHECK (content_type IN
                          ('image/jpeg','image/png','image/webp','application/pdf')),
                    byte_length INTEGER NOT NULL
                        CHECK (byte_length BETWEEN 1 AND 8388608),
                    ciphertext BYTEA NOT NULL
                        CHECK (octet_length(ciphertext) BETWEEN 29 AND 8388636),
                    PRIMARY KEY (owner_hash, case_hash, digest)
                )
            """)

    def _scope(self, owner: str, case_ref: str, digest: str | None = None) -> tuple[str, str]:
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
    def _aad(owner_hash: str, case_hash: str, digest: str) -> bytes:
        return (owner_hash + ":" + case_hash + ":" + digest).encode("ascii")

    def put(self, owner: str, case_ref: str, content_type: str,
            content: bytes) -> StageArtifact:
        if not isinstance(content, bytes) or not 1 <= len(content) <= MAX_ARTIFACT_BYTES:
            raise ValueError("stage artifact size is outside the allowed range")
        media = _validated_content_type(content_type, content)
        owner_hash, case_hash = self._scope(owner, case_ref)
        digest = hashlib.sha256(content).hexdigest()
        nonce = secrets.token_bytes(12)
        ciphertext = nonce + self._cipher.encrypt(
            nonce, content, self._aad(owner_hash, case_hash, digest),
        )
        try:
            with self._connect() as db:
                db.execute("""
                    INSERT INTO ronas_stage_artifact
                      (owner_hash,case_hash,digest,content_type,byte_length,ciphertext)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (owner_hash,case_hash,digest) DO NOTHING
                """, (owner_hash, case_hash, digest, media, len(content), ciphertext))
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
                    SELECT content_type,byte_length,ciphertext
                    FROM ronas_stage_artifact
                    WHERE owner_hash=%s AND case_hash=%s AND digest=%s
                """, (owner_hash, case_hash, digest)).fetchone()
        except psycopg.Error as exc:
            raise StageArtifactStoreError("artifact read failed") from exc
        if row is None:
            return None
        media, length, encrypted = row
        if isinstance(encrypted, memoryview):
            encrypted = encrypted.tobytes()
        if (media not in ("image/jpeg", "image/png", "image/webp", "application/pdf")
                or type(length) is not int or not 1 <= length <= MAX_ARTIFACT_BYTES
                or not isinstance(encrypted, bytes)
                or not 29 <= len(encrypted) <= MAX_ARTIFACT_BYTES + 28):
            raise StageArtifactStoreError("artifact metadata is invalid")
        try:
            content = self._cipher.decrypt(
                encrypted[:12], encrypted[12:],
                self._aad(owner_hash, case_hash, digest),
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

    def contains(self, owner: str, case_ref: str, digest: str) -> bool:
        return self.get(owner, case_ref, digest) is not None
