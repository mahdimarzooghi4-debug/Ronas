"""PostgreSQL integration tests for encrypted private stage artifacts."""
import hashlib
import os
import secrets
import unittest

import psycopg

from ronas_api.postgres_stage_artifacts import PostgresStageArtifactStore
from ronas_api.stage_observation_artifacts import StageArtifactStoreError

DSN = os.environ.get("RONAS_TEST_POSTGRES_DSN")
PNG = b"\x89PNG\r\n\x1a\n" + b"postgres-stage-artifact-test"


@unittest.skipUnless(DSN, "RONAS_TEST_POSTGRES_DSN is not configured")
class PostgresStageArtifactStoreTests(unittest.TestCase):
    def setUp(self):
        self.owner = "test-owner-" + secrets.token_urlsafe(20)
        self.case = "DEMO-D-" + secrets.token_urlsafe(16)
        self.key = secrets.token_bytes(32)
        self.store = PostgresStageArtifactStore(DSN, self.key)
        self.owner_hash = hashlib.sha256(self.owner.encode()).hexdigest()
        with psycopg.connect(DSN) as db:
            db.execute("DELETE FROM ronas_stage_artifact WHERE owner_hash=%s",
                       (self.owner_hash,))

    def tearDown(self):
        with psycopg.connect(DSN) as db:
            db.execute("DELETE FROM ronas_stage_artifact WHERE owner_hash=%s",
                       (self.owner_hash,))

    def test_encrypted_roundtrip_scoping_and_content_addressed_deduplication(self):
        first = self.store.put(self.owner, self.case + ":stage-1", "image/png", PNG)
        again = self.store.put(self.owner, self.case + ":stage-1", "image/png", PNG)
        self.assertEqual(first, again)
        self.assertEqual(first.digest, hashlib.sha256(PNG).hexdigest())
        self.assertEqual(self.store.get(self.owner, self.case + ":stage-1", first.digest),
                         (first, PNG))
        self.assertTrue(self.store.contains(self.owner, self.case + ":stage-1", first.digest))
        self.assertIsNone(self.store.get("another-owner", self.case + ":stage-1", first.digest))
        self.assertIsNone(self.store.get(self.owner, "another-case:stage-1", first.digest))
        with psycopg.connect(DSN) as db:
            row = db.execute("""
                SELECT owner_hash,case_hash,digest,ciphertext FROM ronas_stage_artifact
                WHERE owner_hash=%s AND digest=%s
            """, (self.owner_hash, first.digest)).fetchone()
        self.assertNotIn(PNG, bytes(row[3]))
        self.assertNotIn(self.owner.encode(), str(row[:3]).encode())

    def test_invalid_media_and_digest_tampering_fail_closed(self):
        with self.assertRaises(ValueError):
            self.store.put(self.owner, self.case, "image/jpeg", PNG)
        artifact = self.store.put(self.owner, self.case, "image/png", PNG)
        owner_hash, case_hash = self.store._scope(self.owner, self.case, artifact.digest)
        with psycopg.connect(DSN) as db:
            db.execute("""
                UPDATE ronas_stage_artifact SET ciphertext=%s
                WHERE owner_hash=%s AND case_hash=%s AND digest=%s
            """, (b"x" * (len(PNG) + 28), owner_hash, case_hash, artifact.digest))
        with self.assertRaises(StageArtifactStoreError):
            self.store.get(self.owner, self.case, artifact.digest)

    def test_scope_and_key_bounds_are_validated(self):
        with self.assertRaises(ValueError):
            PostgresStageArtifactStore(DSN, b"short")
        with self.assertRaises(ValueError):
            self.store.get(self.owner, self.case, "../invalid")


if __name__ == "__main__":
    unittest.main()
