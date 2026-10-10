"""Corrupted SQLite cells and concurrent recovery, LOCAL/TEST ONLY.

No operational identity provider, real accounts or business decisions are used.
Tests exercise the reference store's fail-closed behavior after reopening.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import math
import secrets
import sqlite3
import tempfile
from threading import Barrier
import unittest

from ronas_api.oidc_browser import BrowserSession, PendingLogin
from ronas_api.session_sqlite import SqliteBrowserSessionStore


class CorruptAndConcurrentSessionRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "sessions.db"
        self.key = secrets.token_bytes(32)
        self.time = [1800000000.0]
        self.store = self.reopen()
        self.sid = secrets.token_urlsafe(40)
        self.state = secrets.token_urlsafe(32)

    def reopen(self):
        return SqliteBrowserSessionStore(
            self.path, self.key, now=lambda: self.time[0]
        )

    def session(self, *, name="synthetic-holder", ttl=120):
        return BrowserSession(
            name, frozenset({"domestic_ops"}), "synthetic-test-jwt",
            secrets.token_urlsafe(32), int(self.time[0]) + ttl,
        )

    def pending(self):
        return PendingLogin(
            self.state, secrets.token_urlsafe(48),
            secrets.token_urlsafe(32), self.time[0],
        )

    def mutate(self, table, key_column, key, column, value):
        # Intentional direct local file corruption to simulate damaged media;
        # not a claim to defeat an adversary able to rewrite all DB contents.
        with sqlite3.connect(self.path) as db:
            db.execute(
                f"UPDATE {table} SET {column}=? WHERE {key_column}=?",
                (value, key),
            )

    def session_digest(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT sid_hash FROM browser_session").fetchone()[0]

    def state_digest(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT state_hash FROM pending_login").fetchone()[0]

    def test_nonblob_session_cells_rejected_on_live_and_reopened_store(self):
        self.store.save_session(self.sid, self.session())
        key = self.session_digest()
        with sqlite3.connect(self.path) as db:
            valid = db.execute(
                "SELECT ciphertext FROM browser_session"
            ).fetchone()[0]
        for broken in ("not-bytes", 137, 0.5, b"", b"too-short"):
            with self.subTest(value=repr(broken)):
                self.mutate("browser_session", "sid_hash", key, "ciphertext", broken)
                self.assertIsNone(self.store.get_session(self.sid))
                self.assertIsNone(self.reopen().get_session(self.sid))
                self.mutate("browser_session", "sid_hash", key, "ciphertext", valid)
        self.assertEqual(self.reopen().get_session(self.sid).subject,
                         "synthetic-holder")

    def test_nonblob_pending_cells_fail_closed_and_are_consumed_once(self):
        for broken in ("not-bytes", 137, 0.5, b"tiny"):
            with self.subTest(value=repr(broken)):
                self.state = secrets.token_urlsafe(32)
                self.store.save_pending(self.pending())
                key = self.store._digest(self.state)
                self.mutate("pending_login", "state_hash", key, "ciphertext", broken)
                self.assertIsNone(self.reopen().take_pending(self.state))
                self.assertIsNone(self.store.take_pending(self.state))
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM pending_login"
            ).fetchone()[0], 0)

    def test_untrusted_session_expiry_column_fails_closed(self):
        self.store.save_session(self.sid, self.session())
        key = self.session_digest()
        for bad in ("tomorrow", math.inf,
                    int(self.time[0]) + 9000, self.time[0] + 90.5):
            with self.subTest(value=str(bad)):
                self.mutate("browser_session", "sid_hash", key, "expires_at", bad)
                self.assertIsNone(self.reopen().get_session(self.sid))

    def test_untrusted_pending_expiry_column_cannot_extend_login(self):
        for bad in ("forever", math.inf,
                    self.time[0] + 1200, self.time[0] + 299):
            with self.subTest(value=str(bad)):
                self.state = secrets.token_urlsafe(32)
                self.store.save_pending(self.pending())
                key = self.store._digest(self.state)
                self.mutate("pending_login", "state_hash", key, "expires_at", bad)
                self.assertIsNone(self.reopen().take_pending(self.state))
                self.assertIsNone(self.store.take_pending(self.state))

    def test_ciphertext_swap_between_two_sessions_cannot_grant_access(self):
        sid2 = secrets.token_urlsafe(40)
        original1 = self.session(name="synthetic-owner-one")
        original2 = self.session(name="synthetic-owner-two")
        self.store.save_session(self.sid, original1)
        self.store.save_session(sid2, original2)
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT sid_hash, ciphertext FROM browser_session"
            ).fetchall()
            self.assertEqual(len(rows), 2)
            db.execute("UPDATE browser_session SET ciphertext=? WHERE sid_hash=?",
                       (rows[0][1], rows[1][0]))
            db.execute("UPDATE browser_session SET ciphertext=? WHERE sid_hash=?",
                       (rows[1][1], rows[0][0]))
        self.assertIsNone(self.reopen().get_session(self.sid))
        self.assertIsNone(self.reopen().get_session(sid2))

    def test_pending_expiration_is_enforced_after_database_reopen(self):
        pending = self.pending()
        self.store.save_pending(pending)
        self.assertEqual(self.reopen().take_pending(self.state), pending)
        self.assertIsNone(self.store.take_pending(self.state))
        self.state = secrets.token_urlsafe(32)
        self.store.save_pending(self.pending())
        self.time[0] += 301
        self.assertIsNone(self.reopen().take_pending(self.state))
        self.assertIsNone(self.store.take_pending(self.state))

    def test_invalid_pending_nan_infinite_or_bool_creation_rejected(self):
        for invalid in (math.nan, math.inf, -math.inf, True):
            with self.subTest(value=str(invalid)):
                with self.assertRaises(ValueError):
                    self.store.save_pending(PendingLogin(
                        secrets.token_urlsafe(32), secrets.token_urlsafe(48),
                        secrets.token_urlsafe(32), invalid,
                    ))
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM pending_login").fetchone()[0], 0)

    def test_invalid_boolean_session_expiry_cannot_be_persisted(self):
        with self.assertRaises(ValueError):
            self.store.save_session(self.sid, BrowserSession(
                "synthetic-owner", frozenset({"domestic_ops"}),
                "synthetic-token", secrets.token_urlsafe(32), True,
            ))
        self.assertIsNone(self.store.get_session(self.sid))

    def test_revocation_rollback_preserves_then_removes_session(self):
        item = self.session()
        self.store.save_session(self.sid, item)
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER block_revoke BEFORE DELETE ON browser_session
                BEGIN SELECT RAISE(ABORT, 'injected delete failure'); END
            """)
        with self.assertRaises(sqlite3.DatabaseError):
            self.reopen().revoke_session(self.sid)
        self.assertEqual(self.store.get_session(self.sid), item)
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER block_revoke")
        self.reopen().revoke_session(self.sid)
        self.assertIsNone(self.store.get_session(self.sid))
        self.assertIsNone(self.reopen().get_session(self.sid))

    def test_concurrent_reopen_read_revoke_and_purge_cannot_resurrect(self):
        self.store.save_session(self.sid, self.session())
        barrier = Barrier(12)

        def read(_):
            connection = self.reopen()
            barrier.wait(timeout=12)
            return connection.get_session(self.sid)

        def revoke():
            connection = self.reopen()
            barrier.wait(timeout=12)
            connection.revoke_session(self.sid)
            return "revoked"

        def purge():
            connection = self.reopen()
            barrier.wait(timeout=12)
            return connection.purge_expired()

        with ThreadPoolExecutor(max_workers=12) as workers:
            futures = [workers.submit(read, n) for n in range(10)]
            futures.extend([workers.submit(revoke), workers.submit(purge)])
            outcomes = [future.result() for future in futures]
        self.assertEqual(outcomes[10], "revoked")
        self.assertEqual(outcomes[11], (0, 0))
        self.assertTrue(all(v is None or isinstance(v, BrowserSession)
                            for v in outcomes[:10]))
        self.assertIsNone(self.reopen().get_session(self.sid))
        self.assertIsNone(self.store.get_session(self.sid))

    def test_sqlite_wal_checkpoint_and_reopen_preserves_only_valid_state(self):
        item = self.session()
        self.store.save_session(self.sid, item)
        second_sid = secrets.token_urlsafe(40)
        self.store.save_session(second_sid, self.session(name="synthetic-second"))
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.execute(
                "UPDATE browser_session SET ciphertext=? WHERE sid_hash=?",
                (b"corrupted", self.store._digest(second_sid)),
            )
            db.commit()
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.assertEqual(self.reopen().get_session(self.sid), item)
        self.assertIsNone(self.reopen().get_session(second_sid))
        self.reopen().revoke_session(self.sid)
        self.assertIsNone(self.reopen().get_session(self.sid))


if __name__ == "__main__":
    unittest.main()
