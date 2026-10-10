"""Local encrypted session store: atomic consume, durable reopen and revocation."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import threading
import unittest

from ronas_api.oidc_browser import PendingLogin, BrowserSession
from ronas_api.session_sqlite import SqliteBrowserSessionStore


class SqliteStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "test-identity.db"
        self.key = secrets.token_bytes(32)
        self.clock = [1800000000.0]
        self.make_store = lambda key=None: SqliteBrowserSessionStore(
            self.path, key if key is not None else self.key, now=lambda: self.clock[0]
        )
        self.store = self.make_store()
        self.state = secrets.token_urlsafe(32)
        self.sid = secrets.token_urlsafe(40)

    def pending(self):
        return PendingLogin(self.state, secrets.token_urlsafe(48),
                            secrets.token_urlsafe(32), self.clock[0])

    def session(self):
        return BrowserSession("synthetic-user", frozenset({"domestic_ops"}),
                              "eyJfake.payload.signature", secrets.token_urlsafe(32),
                              int(self.clock[0]) + 120)

    def test_pending_single_use_survives_reopen(self):
        record = self.pending()
        self.store.save_pending(record)
        reopened = self.make_store()
        self.assertEqual(reopened.take_pending(self.state), record)
        self.assertIsNone(self.store.take_pending(self.state))

    def test_atomic_pending_consumption_across_eight_connections(self):
        self.store.save_pending(self.pending())
        barrier = threading.Barrier(8)
        def consume(_):
            another = self.make_store()
            barrier.wait(timeout=5)
            return another.take_pending(self.state)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(consume, range(8)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertIsNone(self.store.take_pending(self.state))

    def test_key_mismatch_does_not_decrypt_plaintext(self):
        self.store.save_pending(self.pending())
        self.store.save_session(self.sid, self.session())
        other = self.make_store(secrets.token_bytes(32))
        self.assertIsNone(other.get_session(self.sid))
        self.assertIsNone(other.take_pending(self.state))

    def test_database_at_rest_contains_no_raw_sensitive_data(self):
        item, active = self.pending(), self.session()
        self.store.save_pending(item)
        self.store.save_session(self.sid, active)
        content = self.path.read_bytes()
        for value in (self.state, self.sid, item.verifier, item.nonce,
                      active.access_token, active.csrf, active.subject):
            self.assertNotIn(value.encode(), content)
        with sqlite3.connect(self.path) as db:
            keys = db.execute("SELECT state_hash FROM pending_login").fetchall()
            ids = db.execute("SELECT sid_hash FROM browser_session").fetchall()
        self.assertEqual(len(keys[0][0]), 64)
        self.assertEqual(len(ids[0][0]), 64)

    def test_reopen_get_and_revoke_are_immediate(self):
        data = self.session()
        self.store.save_session(self.sid, data)
        second = self.make_store()
        self.assertEqual(second.get_session(self.sid), data)
        second.revoke_session(self.sid)
        self.assertIsNone(self.store.get_session(self.sid))
        second.revoke_session(self.sid)

    def test_technical_expiration_deny_and_purge(self):
        self.store.save_session(self.sid, self.session())
        self.store.save_pending(self.pending())
        self.clock[0] += 121
        self.assertIsNone(self.store.get_session(self.sid))
        self.assertEqual(self.store.purge_expired(), (0, 1))
        self.clock[0] += 180
        self.assertIsNone(self.store.take_pending(self.state))
        self.assertEqual(self.store.purge_expired(), (0, 0))

    def test_expired_pending_removed_by_explicit_purge(self):
        self.store.save_pending(self.pending())
        self.clock[0] += 301
        self.assertEqual(self.store.purge_expired(), (1, 0))

    def test_invalid_records_and_replay_refused(self):
        item = self.pending()
        self.store.save_pending(item)
        with self.assertRaises(ValueError):
            self.store.save_pending(item)
        session = self.session()
        self.store.save_session(self.sid, session)
        with self.assertRaises(ValueError):
            self.store.save_session(self.sid, session)
        self.assertIsNone(self.store.take_pending("not-found-reference"))
        self.assertIsNone(self.store.get_session("not-found-reference"))
        self.store.revoke_session("not-found-reference")

    def test_no_future_pending_or_unbounded_session(self):
        with self.assertRaises(ValueError):
            self.store.save_pending(PendingLogin(self.state, "v" * 64,
                                                 "n" * 48, self.clock[0] + 31))
        with self.assertRaises(ValueError):
            self.store.save_session(self.sid, BrowserSession(
                "u", frozenset({"household"}), "token", "csrf",
                int(self.clock[0]) + 1800))
        with self.assertRaises(ValueError):
            self.store.save_session(self.sid, BrowserSession(
                "u", frozenset({"unrecognized-role"}), "token", "csrf",
                int(self.clock[0]) + 60))
        self.assertIsNone(self.store.get_session(self.sid))

    def test_private_file_and_symlink_forbidden(self):
        if os.name != "nt":
            self.assertEqual(self.path.stat().st_mode & 0o077, 0)
            open_path = Path(self.tmp.name) / "world-readable.db"
            open_path.write_bytes(b"")
            open_path.chmod(0o644)
            with self.assertRaises(ValueError):
                SqliteBrowserSessionStore(open_path, self.key)
            alias = Path(self.tmp.name) / "session-link.db"
            alias.symlink_to(self.path)
            with self.assertRaises(ValueError):
                SqliteBrowserSessionStore(alias, self.key)
        with self.assertRaises(ValueError):
            SqliteBrowserSessionStore("relative.db", self.key)
        with self.assertRaises(ValueError):
            SqliteBrowserSessionStore(self.path, b"short")

    def test_corrupt_session_ciphertext_fails_closed(self):
        self.store.save_session(self.sid, self.session())
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE browser_session SET ciphertext=?", (b"tampered",))
            db.commit()
        self.assertIsNone(self.store.get_session(self.sid))

    def test_no_web_app_is_activated_by_store_construct(self):
        from fastapi.testclient import TestClient
        from ronas_api.app import create_app
        client = TestClient(create_app())
        self.assertEqual(client.get("/api/auth/start").status_code, 404)
        self.assertEqual(client.get("/api/auth/session").status_code, 404)
        self.assertEqual(client.get("/readyz").status_code, 503)


if __name__ == "__main__":
    unittest.main()
