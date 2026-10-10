"""Encrypted, transactional SQLite adapter for LOCAL/TEST BFF session validation.

No production backend is selected. This is a multi-connection single-host
reference adapter, not a distributed session service, and is never mounted
by the default app. All secrets (PKCE, access JWT, CSRF) are encrypted at rest.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import time
from typing import Callable, Iterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .auth import ALL_ROLES
from .oidc_browser import BrowserSession, PendingLogin


class SqliteBrowserSessionStore:
    """Single-host, encrypted, explicit-opt-in persistence for synthetic tests."""

    def __init__(self, path: Path | str, key: bytes, *, now: Callable[[], float] = time.time):
        self.path = Path(path)
        if not self.path.is_absolute() or str(self.path) == ":memory:" or self.path.is_symlink():
            raise ValueError("a regular absolute local database file is required")
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("ephemeral AES-256 key required from caller")
        self._cipher = AESGCM(key)
        self._now = now
        if not self.path.parent.is_dir():
            raise ValueError("parent directory must exist")
        try:
            descriptor = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if self.path.is_symlink():
                raise ValueError("symlink database forbidden") from None
        else:
            os.close(descriptor)
        info = self.path.stat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("session database must be a private regular file")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise ValueError("session database owner mismatch")
        with self._db() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""CREATE TABLE IF NOT EXISTS pending_login (
                state_hash TEXT PRIMARY KEY, ciphertext BLOB NOT NULL,
                expires_at REAL NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS browser_session (
                sid_hash TEXT PRIMARY KEY, ciphertext BLOB NOT NULL,
                expires_at INTEGER NOT NULL
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS pending_expiry ON pending_login(expires_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS session_expiry ON browser_session(expires_at)")

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("PRAGMA secure_delete=ON")
            db.execute("PRAGMA temp_store=MEMORY")
            yield db
        finally:
            db.close()

    @staticmethod
    def _digest(key: str) -> str:
        if not isinstance(key, str) or not 20 <= len(key) <= 180 or not key.isascii():
            raise ValueError("invalid opaque state or session reference")
        return hashlib.sha256(key.encode("ascii")).hexdigest()

    def _encrypt(self, area: str, digest: str, data: dict) -> bytes:
        plaintext = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(plaintext) > 16000:
            raise ValueError("session payload exceeds technical limit")
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(nonce, plaintext, (area + digest).encode("ascii"))

    def _decrypt(self, area: str, digest: str, blob: bytes) -> dict | None:
        try:
            data = json.loads(self._cipher.decrypt(
                blob[:12], blob[12:], (area + digest).encode("ascii")
            ))
            return data if isinstance(data, dict) else None
        except (ValueError, KeyError, TypeError):
            return None

    def save_pending(self, item: PendingLogin) -> None:
        if not isinstance(item, PendingLogin) or not isinstance(item.created_at, (int, float)):
            raise ValueError("invalid pending record")
        digest = self._digest(item.state)
        if not all(isinstance(x, str) and 20 <= len(x) <= 180 for x in (item.verifier, item.nonce)):
            raise ValueError("invalid PKCE/nonce")
        if not 0 <= self._now() - item.created_at <= 300:
            raise ValueError("expired or future login start")
        ciphertext = self._encrypt("pending:", digest, {
            "state": item.state, "verifier": item.verifier,
            "nonce": item.nonce, "created_at": item.created_at,
        })
        with self._db() as db:
            try:
                db.execute("INSERT INTO pending_login VALUES (?, ?, ?)",
                           (digest, ciphertext, item.created_at + 300))
            except sqlite3.IntegrityError as exc:
                raise ValueError("duplicate state") from exc

    def take_pending(self, state: str) -> PendingLogin | None:
        try:
            digest = self._digest(state)
        except ValueError:
            return None
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT ciphertext, expires_at FROM pending_login WHERE state_hash=?",
                                 (digest,)).fetchone()
                if row:
                    db.execute("DELETE FROM pending_login WHERE state_hash=?", (digest,))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        if not row or row[1] <= self._now():
            return None
        data = self._decrypt("pending:", digest, row[0])
        try:
            if data is None or set(data) != {"state", "verifier", "nonce", "created_at"} or data["state"] != state:
                return None
            return PendingLogin(**data)
        except (ValueError, TypeError):
            return None

    def save_session(self, sid: str, session: BrowserSession) -> None:
        digest = self._digest(sid)
        if (not isinstance(session, BrowserSession)
                or not isinstance(session.expires_at, int)
                or not int(self._now()) < session.expires_at <= int(self._now()) + 900
                or not isinstance(session.roles, frozenset)
                or not session.roles or not session.roles.issubset(ALL_ROLES)
                or not all(isinstance(x, str) and x for x in (
                    session.subject, session.access_token, session.csrf
                ))):
            raise ValueError("invalid browser session")
        ciphertext = self._encrypt("session:", digest, {
            "subject": session.subject, "roles": sorted(session.roles),
            "access_token": session.access_token, "csrf": session.csrf,
            "expires_at": session.expires_at,
        })
        with self._db() as db:
            try:
                db.execute("INSERT INTO browser_session VALUES (?, ?, ?)",
                           (digest, ciphertext, session.expires_at))
            except sqlite3.IntegrityError as exc:
                raise ValueError("duplicate session") from exc

    def get_session(self, sid: str) -> BrowserSession | None:
        try:
            digest = self._digest(sid)
        except ValueError:
            return None
        with self._db() as db:
            row = db.execute(
                "SELECT ciphertext, expires_at FROM browser_session WHERE sid_hash=?", (digest,)
            ).fetchone()
        if not row or row[1] <= int(self._now()):
            return None
        data = self._decrypt("session:", digest, row[0])
        if data is None or set(data) != {"subject", "roles", "access_token", "csrf", "expires_at"}:
            return None
        try:
            roles = data["roles"]
            if (not isinstance(roles, list) or not roles or any(r not in ALL_ROLES for r in roles)
                    or len(roles) != len(set(roles)) or type(data["expires_at"]) is not int
                    or data["expires_at"] != row[1]
                    or not all(isinstance(data[k], str) for k in ("subject", "access_token", "csrf"))):
                return None
            return BrowserSession(data["subject"], frozenset(roles),
                                  data["access_token"], data["csrf"], data["expires_at"])
        except (ValueError, TypeError, KeyError):
            return None

    def revoke_session(self, sid: str) -> None:
        try:
            digest = self._digest(sid)
        except ValueError:
            return
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("DELETE FROM browser_session WHERE sid_hash=?", (digest,))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    def purge_expired(self) -> tuple[int, int]:
        """Operator-invoked local maintenance; not a production retention rule."""
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                pending = db.execute("DELETE FROM pending_login WHERE expires_at <= ?",
                                     (self._now(),)).rowcount
                sessions = db.execute("DELETE FROM browser_session WHERE expires_at <= ?",
                                      (int(self._now()),)).rowcount
                db.execute("COMMIT")
                return pending, sessions
            except Exception:
                db.execute("ROLLBACK")
                raise
