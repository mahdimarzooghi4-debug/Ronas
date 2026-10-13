"""PostgreSQL integration tests for encrypted private stage artifacts."""
import hashlib
import os
import secrets
import unittest

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ronas_api.auth import Principal
from ronas_api.domestic_stage_observation import CurrentStageContext, StageRequirement
from ronas_api.postgres_stage_artifacts import PostgresStageArtifactStore
from ronas_api.stage_observation_artifacts import (
    StageArtifactStoreError, build_stage_artifact_router,
)

DSN = os.environ.get("RONAS_TEST_POSTGRES_DSN")
PNG = b"\x89PNG\r\n\x1a\n" + b"postgres-stage-artifact-test"


@unittest.skipUnless(DSN, "RONAS_TEST_POSTGRES_DSN is not configured")
class PostgresStageArtifactStoreTests(unittest.TestCase):
    def setUp(self):
        self.owner = "test-owner-" + secrets.token_urlsafe(20)
        self.case = "DEMO-D-" + secrets.token_urlsafe(16)
        self.key = secrets.token_bytes(32)
        self.store = PostgresStageArtifactStore(DSN, self.key)
        self.owner_hash = self.store._scope(self.owner, self.case)[0]
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


    def test_authenticated_http_upload_and_download_use_existing_store_protocol(self):
        owner = "synthetic-household-001"
        case_ref = "DEMO-D-001"
        case_version, input_revision = 2, 3
        input_digest, plan_digest, requirements_digest = "a" * 64, "b" * 64, "c" * 64
        stage_ref = "DEMO-STAGE-01"
        context = CurrentStageContext(
            case_ref, case_version, input_revision, input_digest, plan_digest,
            (StageRequirement(stage_ref, requirements_digest),),
        )
        app = FastAPI()
        app.include_router(build_stage_artifact_router(
            self.store,
            lambda: Principal(owner, frozenset({"household"})),
            "schema-v1",
            lambda principal, ref, schema: (
                principal.subject == owner and ref == case_ref and schema == "schema-v1"
            ),
            lambda ref: context if ref == case_ref else None,
        ))
        client = TestClient(app)
        headers = {
            "Authorization": "Bearer test-only",
            "Content-Type": "image/png",
            "X-Ronas-Case-Version": str(case_version),
            "X-Ronas-Input-Revision": str(input_revision),
            "X-Ronas-Plan-Digest": plan_digest,
            "X-Ronas-Stage-Ref": stage_ref,
            "X-Ronas-Requirements-Digest": requirements_digest,
        }
        upload = client.put(
            f"/api/v1/domestic/household-intake/my-drafts/{case_ref}/stage-observations/artifacts",
            content=PNG, headers=headers,
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        self.assertEqual(upload.json()["byte_length"], len(PNG))
        digest = upload.json()["digest"]
        download = client.get(
            f"/api/v1/domestic/household-intake/my-drafts/{case_ref}/stage-observations/artifacts/{stage_ref}/{digest}"
        )
        self.assertEqual(download.status_code, 200, download.text)
        self.assertEqual(download.content, PNG)
        self.assertEqual(download.headers["x-content-type-options"], "nosniff")
        self.assertIn("no-store", download.headers["cache-control"])

        stale = dict(headers)
        stale["X-Ronas-Input-Revision"] = str(input_revision + 1)
        conflict = client.put(
            f"/api/v1/domestic/household-intake/my-drafts/{case_ref}/stage-observations/artifacts",
            content=PNG, headers=stale,
        )
        self.assertEqual(conflict.status_code, 409)

    def test_scope_hashes_are_keyed_and_domain_separated(self):
        owner_hash, case_hash = self.store._scope(self.owner, self.case)
        self.assertNotEqual(owner_hash, hashlib.sha256(self.owner.encode()).hexdigest())
        self.assertNotEqual(case_hash, hashlib.sha256(self.case.encode()).hexdigest())
        self.assertNotEqual(
            self.store._scope("same-value", "different")[0],
            self.store._scope("different", "same-value")[1],
        )

    def test_scope_and_key_bounds_are_validated(self):
        with self.assertRaises(ValueError):
            PostgresStageArtifactStore(DSN, b"short")
        with self.assertRaises(ValueError):
            self.store.get(self.owner, self.case, "../invalid")


    def test_key_rotation_preserves_reads_and_reencrypts_rows_in_bounded_batches(self):
        first = self.store.put(self.owner, self.case + ":one", "image/png", PNG)
        second = self.store.put(
            self.owner, self.case + ":two", "image/png", PNG + b"-second",
        )
        new_key = secrets.token_bytes(32)
        rotated = PostgresStageArtifactStore(
            DSN, keyring={"default": self.key, "rotation-2026-10": new_key},
            active_key_id="rotation-2026-10", scope_key=self.key,
        )
        self.assertEqual(rotated.get(self.owner, self.case + ":one", first.digest), (first, PNG))
        self.assertEqual(rotated.rotate_batch(limit=1), 1)
        self.assertEqual(rotated.rotate_batch(limit=1), 1)
        self.assertEqual(rotated.rotate_batch(limit=1), 0)
        with psycopg.connect(DSN) as db:
            ids = db.execute("""
                SELECT DISTINCT encryption_key_id FROM ronas_stage_artifact
                WHERE owner_hash=%s
            """, (self.owner_hash,)).fetchall()
        self.assertEqual(ids, [("rotation-2026-10",)])
        self.assertEqual(rotated.get(self.owner, self.case + ":two", second.digest),
                         (second, PNG + b"-second"))

    def test_two_workers_can_rotate_without_double_processing(self):
        one = self.store.put(self.owner, self.case + ":one", "image/png", PNG)
        two = self.store.put(self.owner, self.case + ":two", "image/png", PNG + b"-two")
        new_key = secrets.token_bytes(32)
        config = dict(
            keyring={"default": self.key, "rotation-2026-10": new_key},
            active_key_id="rotation-2026-10", scope_key=self.key,
        )
        first_worker = PostgresStageArtifactStore(DSN, **config)
        second_worker = PostgresStageArtifactStore(DSN, **config)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda worker: worker.rotate_batch(1),
                                    (first_worker, second_worker)))
        self.assertEqual(sum(results), 2)
        self.assertEqual(first_worker.get(self.owner, self.case + ":one", one.digest),
                         (one, PNG))
        self.assertEqual(second_worker.get(self.owner, self.case + ":two", two.digest),
                         (two, PNG + b"-two"))

    def test_rotation_requires_old_keys_and_bounds_batch_size(self):
        artifact = self.store.put(self.owner, self.case, "image/png", PNG)
        new_key = secrets.token_bytes(32)
        missing_old = PostgresStageArtifactStore(
            DSN, keyring={"new": new_key}, active_key_id="new", scope_key=self.key,
        )
        with self.assertRaises(StageArtifactStoreError):
            missing_old.get(self.owner, self.case, artifact.digest)
        with self.assertRaises(ValueError):
            missing_old.rotate_batch(0)
        with self.assertRaises(ValueError):
            missing_old.rotate_batch(501)


if __name__ == "__main__":
    unittest.main()
