"""Encrypted PostgreSQL store for the existing Keycloak BFF session protocol."""
from __future__ import annotations

import hashlib
import json
import math
import secrets
import time
from typing import Callable

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.errors import UniqueViolation

from .auth import ALL_ROLES
from .oidc_browser import BrowserSession, PendingLogin


class PostgresBrowserSessionStore:
    """Multi-instance BrowserSessionStore; opt-in and never auto-selected."""

    def __init__(
        self, dsn: str, key: bytes, *,
        now: Callable[[], float] = time.time,
        connect_timeout: int = 3,
    ) -> None:
        if not isinstance(dsn, str) or not dsn or len(dsn) > 4096 or "\x00" in dsn:
            raise ValueError("PostgreSQL DSN required")
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("AES-256 session encryption key required")
        if (type(connect_timeout) is not int or not 1 <= connect_timeout <= 15
                or not callable(now)):
            raise ValueError("bounded connection timeout and clock required")
        self._dsn = dsn
        self._cipher = AESGCM(key)
        self._now = now
        self._connect_timeout = connect_timeout
        self._initialize()

    def _connect(self):
        # Never log or expose the DSN, session, or token values.
        return psycopg.connect(
            self._dsn, connect_timeout=self._connect_timeout,
            application_name="ronas-browser-session",
        )

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS ronas_browser_pending_login (
                    state_hash CHAR(64) PRIMARY KEY
                        CHECK (state_hash ~ '^[0-9a-f]{64}$'),
                    ciphertext BYTEA NOT NULL CHECK (octet_length(ciphertext) >= 28),
                    expires_at DOUBLE PRECISION NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS ronas_browser_session (
                    sid_hash CHAR(64) PRIMARY KEY
                        CHECK (sid_hash ~ '^[0-9a-f]{64}$'),
                    ciphertext BYTEA NOT NULL CHECK (octet_length(ciphertext) >= 28),
                    expires_at BIGINT NOT NULL
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS ronas_browser_pending_expiry
                ON ronas_browser_pending_login (expires_at)
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS ronas_browser_session_expiry
                ON ronas_browser_session (expires_at)
            """)

    @staticmethod
    def _digest(value: str) -> str:
        if not isinstance(value, str) or not 20 <= len(value) <= 180 or not value.isascii():
            raise ValueError("invalid opaque state or session reference")
        return hashlib.sha256(value.encode("ascii")).hexdigest()

    def _encrypt(self, area: str, digest: str, data: dict) -> bytes:
        plaintext = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
        if len(plaintext) > 16000:
            raise ValueError("session payload exceeds technical limit")
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(nonce, plaintext, (area + digest).encode("ascii"))

    def _decrypt(self, area: str, digest: str, value: object) -> dict | None:
        if isinstance(value, memoryview):
            value = value.tobytes()
        if not isinstance(value, bytes) or len(value) < 28:
            return None
        try:
            data = json.loads(self._cipher.decrypt(
                value[:12], value[12:], (area + digest).encode("ascii"),
            ))
            return data if isinstance(data, dict) else None
        except (ValueError, KeyError, TypeError, InvalidTag):
            return None

    def save_pending(self, item: PendingLogin) -> None:
        if (not isinstance(item, PendingLogin)
                or type(item.created_at) not in (int, float)
                or not math.isfinite(item.created_at)):
            raise ValueError("invalid pending record")
        digest = self._digest(item.state)
        if not all(isinstance(v, str) and 20 <= len(v) <= 180
                   for v in (item.verifier, item.nonce)):
            raise ValueError("invalid PKCE/nonce")
        if not 0 <= self._now() - item.created_at <= 300:
            raise ValueError("expired or future login start")
        encrypted = self._encrypt("pending:", digest, {
            "state": item.state, "verifier": item.verifier, "nonce": item.nonce,
            "created_at": item.created_at, "return_path": item.return_path,
        })
        try:
            with self._connect() as db:
                db.execute(
                    """INSERT INTO ronas_browser_pending_login
                       (state_hash,ciphertext,expires_at) VALUES (%s,%s,%s)""",
                    (digest, encrypted, item.created_at + 300),
                )
        except UniqueViolation as exc:
            raise ValueError("duplicate state") from exc

    def take_pending(self, state: str) -> PendingLogin | None:
        try:
            digest = self._digest(state)
        except ValueError:
            return None
        # One atomic statement prevents two app workers from consuming one callback.
        with self._connect() as db:
            row = db.execute(
                """DELETE FROM ronas_browser_pending_login WHERE state_hash=%s
                   RETURNING ciphertext,expires_at""", (digest,),
            ).fetchone()
        if (not row or type(row[1]) not in (int, float)
                or not math.isfinite(row[1]) or row[1] <= self._now()):
            return None
        data = self._decrypt("pending:", digest, row[0])
        try:
            if (data is None or set(data) != {
                    "state", "verifier", "nonce", "created_at", "return_path",
            } or data["state"] != state
                    or type(data["created_at"]) not in (int, float)
                    or not math.isfinite(data["created_at"])
                    or row[1] != data["created_at"] + 300):
                return None
            return PendingLogin(**data)
        except (ValueError, TypeError):
            return None

    def save_session(self, sid: str, session: BrowserSession) -> None:
        digest = self._digest(sid)
        if (not isinstance(session, BrowserSession) or type(session.expires_at) is not int
                or not int(self._now()) < session.expires_at <= int(self._now()) + 900
                or not isinstance(session.roles, frozenset) or not session.roles
                or not session.roles.issubset(ALL_ROLES)
                or not all(isinstance(v, str) and v for v in (
                    session.subject, session.access_token, session.csrf,
                ))):
            raise ValueError("invalid browser session")
        encrypted = self._encrypt("session:", digest, {
            "subject": session.subject, "roles": sorted(session.roles),
            "access_token": session.access_token, "csrf": session.csrf,
            "expires_at": session.expires_at,
        })
        try:
            with self._connect() as db:
                db.execute(
                    """INSERT INTO ronas_browser_session
                       (sid_hash,ciphertext,expires_at) VALUES (%s,%s,%s)""",
                    (digest, encrypted, session.expires_at),
                )
        except UniqueViolation as exc:
            raise ValueError("duplicate session") from exc

    def get_session(self, sid: str) -> BrowserSession | None:
        try:
            digest = self._digest(sid)
        except ValueError:
            return None
        with self._connect() as db:
            row = db.execute(
                """SELECT ciphertext,expires_at FROM ronas_browser_session
                   WHERE sid_hash=%s""", (digest,),
            ).fetchone()
        if not row or type(row[1]) is not int or row[1] <= int(self._now()):
            return None
        data = self._decrypt("session:", digest, row[0])
        if data is None or set(data) != {
            "subject", "roles", "access_token", "csrf", "expires_at",
        }:
            return None
        try:
            roles = data["roles"]
            if (not isinstance(roles, list) or not roles
                    or any(role not in ALL_ROLES for role in roles)
                    or len(roles) != len(set(roles))
                    or type(data["expires_at"]) is not int or data["expires_at"] != row[1]
                    or not all(isinstance(data[k], str) for k in (
                        "subject", "access_token", "csrf",
                    ))):
                return None
            return BrowserSession(
                data["subject"], frozenset(roles), data["access_token"],
                data["csrf"], data["expires_at"],
            )
        except (ValueError, TypeError, KeyError):
            return None

    def revoke_session(self, sid: str) -> None:
        try:
            digest = self._digest(sid)
        except ValueError:
            return
        with self._connect() as db:
            db.execute(
                "DELETE FROM ronas_browser_session WHERE sid_hash=%s", (digest,),
            )

    def purge_expired(self) -> tuple[int, int]:
        """Explicit cleanup; scheduling and retention remain caller-owned."""
        with self._connect() as db:
            pending = db.execute(
                "DELETE FROM ronas_browser_pending_login WHERE expires_at <= %s",
                (self._now(),),
            ).rowcount
            sessions = db.execute(
                "DELETE FROM ronas_browser_session WHERE expires_at <= %s",
                (int(self._now()),),
            ).rowcount
            return pending, sessions
