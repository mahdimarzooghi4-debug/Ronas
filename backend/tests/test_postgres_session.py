"""PostgreSQL integration coverage for encrypted, multi-worker browser sessions."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import secrets
import time
import unittest

import psycopg

from ronas_api.oidc_browser import BrowserSession, PendingLogin
from ronas_api.postgres_session import PostgresBrowserSessionStore

DSN = os.environ.get("RONAS_TEST_POSTGRES_DSN")


@unittest.skipUnless(DSN, "RONAS_TEST_POSTGRES_DSN is not configured")
class PostgresBrowserSessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.clock = [time.time()]
        self.key = secrets.token_bytes(32)
        self.pending_hashes = []
        self.session_hashes = []
        self.store = PostgresBrowserSessionStore(
            DSN, self.key, now=lambda: self.clock[0],
        )
        # A second independent instance represents another API worker.
        self.peer = PostgresBrowserSessionStore(
            DSN, self.key, now=lambda: self.clock[0],
        )

    def tearDown(self):
        with psycopg.connect(DSN) as db:
            for digest in self.pending_hashes:
                db.execute("DELETE FROM ronas_browser_pending_login WHERE state_hash=%s", (digest,))
            for digest in self.session_hashes:
                db.execute("DELETE FROM ronas_browser_session WHERE sid_hash=%s", (digest,))

    def test_pending_login_is_encrypted_and_consumed_once_across_workers(self):
        state = secrets.token_urlsafe(32)
        item = PendingLogin(
            state, secrets.token_urlsafe(48), secrets.token_urlsafe(32),
            self.clock[0], "/admin",
        )
        self.store.save_pending(item)
        digest = hashlib.sha256(state.encode("ascii")).hexdigest()
        self.pending_hashes.append(digest)
        with psycopg.connect(DSN) as db:
            row = db.execute(
                "SELECT state_hash,ciphertext FROM ronas_browser_pending_login "
                "WHERE state_hash=%s", (digest,),
            ).fetchone()
        self.assertEqual(row[0], digest)
        self.assertNotIn(state.encode(), bytes(row[1]))
        self.assertNotIn(item.verifier.encode(), bytes(row[1]))
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(self.peer.take_pending, [state] * 12))
        self.assertEqual(results.count(item), 1)
        self.assertEqual(results.count(None), 11)

    def test_session_is_shared_encrypted_and_revocable_across_workers(self):
        sid = secrets.token_urlsafe(32)
        session = BrowserSession(
            "synthetic-household-pg", frozenset({"household"}),
            "access-" + secrets.token_urlsafe(24),
            "csrf-" + secrets.token_urlsafe(24),
            int(self.clock[0]) + 600,
            "id-" + secrets.token_urlsafe(24),
            "refresh-" + secrets.token_urlsafe(24),
        )
        self.store.save_session(sid, session)
        self.assertEqual(self.peer.get_session(sid), session)
        digest = hashlib.sha256(sid.encode("ascii")).hexdigest()
        self.session_hashes.append(digest)
        with psycopg.connect(DSN) as db:
            row = db.execute(
                "SELECT sid_hash,ciphertext FROM ronas_browser_session "
                "WHERE sid_hash=%s", (digest,),
            ).fetchone()
        ciphertext = bytes(row[1])
        self.assertEqual(row[0], digest)
        for secret_value in (session.subject, session.access_token, session.csrf, session.id_token, session.refresh_token):
            self.assertNotIn(secret_value.encode(), ciphertext)
        self.peer.revoke_session(sid)
        self.assertIsNone(self.store.get_session(sid))

    def test_duplicate_state_and_session_identifiers_are_rejected(self):
        state = secrets.token_urlsafe(32)
        self.pending_hashes.append(hashlib.sha256(state.encode("ascii")).hexdigest())
        pending = PendingLogin(
            state, secrets.token_urlsafe(48), secrets.token_urlsafe(32),
            self.clock[0], "/",
        )
        self.store.save_pending(pending)
        with self.assertRaisesRegex(ValueError, "duplicate state"):
            self.peer.save_pending(pending)
        sid = secrets.token_urlsafe(32)
        self.session_hashes.append(hashlib.sha256(sid.encode("ascii")).hexdigest())
        session = BrowserSession(
            "synthetic-export-pg", frozenset({"export_ops"}),
            "access-" + secrets.token_urlsafe(24),
            "csrf-" + secrets.token_urlsafe(24),
            int(self.clock[0]) + 600,
        )
        self.store.save_session(sid, session)
        with self.assertRaisesRegex(ValueError, "duplicate session"):
            self.peer.save_session(sid, session)

    def test_expiry_tamper_rejection_and_expired_row_purge(self):
        sid = secrets.token_urlsafe(32)
        self.session_hashes.append(hashlib.sha256(sid.encode("ascii")).hexdigest())
        session = BrowserSession(
            "synthetic-household-expiry", frozenset({"household"}),
            "access-" + secrets.token_urlsafe(24),
            "csrf-" + secrets.token_urlsafe(24),
            int(self.clock[0]) + 900,
        )
        self.store.save_session(sid, session)
        self.clock[0] += 901
        self.assertIsNone(self.peer.get_session(sid))
        self.assertEqual(self.store.purge_expired(), (0, 1))

        corrupt_sid = secrets.token_urlsafe(32)
        self.session_hashes.append(hashlib.sha256(corrupt_sid.encode("ascii")).hexdigest())
        active = BrowserSession(
            "synthetic-household-corrupt", frozenset({"household"}),
            "access-" + secrets.token_urlsafe(24),
            "csrf-" + secrets.token_urlsafe(24),
            int(self.clock[0]) + 600,
        )
        self.store.save_session(corrupt_sid, active)
        digest = hashlib.sha256(corrupt_sid.encode("ascii")).hexdigest()
        with psycopg.connect(DSN) as db:
            db.execute(
                "UPDATE ronas_browser_session SET ciphertext=%s WHERE sid_hash=%s",
                (b"x" * 32, digest),
            )
        self.assertIsNone(self.peer.get_session(corrupt_sid))

        expired_state = secrets.token_urlsafe(32)
        self.pending_hashes.append(hashlib.sha256(expired_state.encode("ascii")).hexdigest())
        self.clock[0] = time.time()
        pending = PendingLogin(
            expired_state, secrets.token_urlsafe(48), secrets.token_urlsafe(32),
            self.clock[0], "/",
        )
        self.store.save_pending(pending)
        self.clock[0] += 301
        self.assertIsNone(self.peer.take_pending(expired_state))
        self.assertEqual(self.store.purge_expired(), (0, 0))

    def test_refresh_lease_is_single_owner_and_atomic_across_workers(self):
        sid = secrets.token_urlsafe(32)
        digest = hashlib.sha256(sid.encode("ascii")).hexdigest()
        self.session_hashes.append(digest)
        before = BrowserSession(
            "synthetic-refresh-user", frozenset({"household"}),
            "access-" + secrets.token_urlsafe(24), "csrf-" + secrets.token_urlsafe(24),
            int(self.clock[0]) + 600, "id-" + secrets.token_urlsafe(24),
            "refresh-" + secrets.token_urlsafe(24),
        )
        self.store.save_session(sid, before)
        lease, other = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        self.assertTrue(self.store.begin_refresh(sid, lease))
        self.assertFalse(self.peer.begin_refresh(sid, other))
        after = BrowserSession(
            before.subject, before.roles, "new-access-" + secrets.token_urlsafe(24),
            "new-csrf-" + secrets.token_urlsafe(24), int(self.clock[0]) + 700,
            before.id_token, "new-refresh-" + secrets.token_urlsafe(24),
        )
        self.assertTrue(self.peer.complete_refresh(sid, lease, after))
        self.assertEqual(self.store.get_session(sid), after)
        self.assertTrue(self.peer.begin_refresh(sid, other))
        self.peer.release_refresh(sid, other)
    def test_invalid_key_and_connection_bounds_fail_before_database_use(self):
        with self.assertRaises(ValueError):
            PostgresBrowserSessionStore(DSN, b"short")
        with self.assertRaises(ValueError):
            PostgresBrowserSessionStore(
                DSN, self.key, connect_timeout=0,
            )


if __name__ == "__main__":
    unittest.main()
