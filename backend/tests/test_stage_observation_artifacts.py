import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ronas_api.auth import Principal
from ronas_api.domestic_stage_observation import CurrentStageContext, StageRequirement
from ronas_api.stage_observation_artifacts import (
    MAX_ARTIFACT_BYTES, PrivateFilesystemStageArtifactStore,
    build_stage_artifact_router,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"test-image-bytes"
D = "a" * 64
PLAN = "b" * 64
REQ = "c" * 64


class StageArtifactStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "objects"
        self.root.mkdir(mode=0o700)
        self.root.chmod(0o700)
        self.store = PrivateFilesystemStageArtifactStore(self.root, b"k" * 32)

    def test_content_is_encrypted_deduplicated_and_scoped_by_owner_and_case(self):
        first = self.store.put("owner-1", "DEMO-D-001", "image/png", PNG)
        again = self.store.put("owner-1", "DEMO-D-001", "image/png", PNG)
        self.assertEqual(first, again)
        self.assertEqual(first.digest, hashlib.sha256(PNG).hexdigest())
        raw_files = [p for p in self.root.rglob("*") if p.is_file()]
        self.assertEqual(len(raw_files), 1)
        self.assertNotIn(PNG, raw_files[0].read_bytes())
        self.assertEqual(self.store.get("owner-1", "DEMO-D-001", first.digest)[1], PNG)
        self.assertIsNone(self.store.get("owner-2", "DEMO-D-001", first.digest))
        self.assertIsNone(self.store.get("owner-1", "DEMO-D-002", first.digest))

    def test_media_signature_and_size_are_checked(self):
        with self.assertRaises(ValueError):
            self.store.put("owner", "DEMO-D-001", "image/jpeg", PNG)
        with self.assertRaises(ValueError):
            self.store.put("owner", "DEMO-D-001", "image/png", b"not a png")
        with self.assertRaises(ValueError):
            self.store.put("owner", "DEMO-D-001", "image/png",
                           PNG + b"x" * MAX_ARTIFACT_BYTES)

    def test_private_directory_and_ciphertext_tampering_fail_closed(self):
        public = Path(self.temp.name) / "public"
        public.mkdir(mode=0o755)
        public.chmod(0o755)
        with self.assertRaises(ValueError):
            PrivateFilesystemStageArtifactStore(public, b"k" * 32)
        artifact = self.store.put("owner", "DEMO-D-001", "image/png", PNG)
        path = next(p for p in self.root.rglob("*") if p.is_file())
        altered = bytearray(path.read_bytes())
        altered[-1] ^= 1
        path.write_bytes(altered)
        with self.assertRaises(Exception):
            self.store.get("owner", "DEMO-D-001", artifact.digest)


class StageArtifactRouterTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.path = Path(root.name) / "artifacts"
        self.path.mkdir(mode=0o700)
        self.path.chmod(0o700)
        store = PrivateFilesystemStageArtifactStore(self.path, b"s" * 32)
        context = CurrentStageContext(
            "DEMO-D-001", 2, 4, D, PLAN,
            (StageRequirement("DEMO-STAGE-01", REQ),),
        )
        self.principal = Principal("owner-1", frozenset({"household"}))
        app = FastAPI()
        app.include_router(build_stage_artifact_router(
            store, lambda: self.principal, "demo-profile-v1",
            lambda principal, ref, schema: (
                principal.subject == "owner-1" and ref == "DEMO-D-001"
                and schema == "demo-profile-v1"
            ),
            lambda ref: context if ref == context.case_ref else None,
        ))
        self.client = TestClient(app)
        self.headers = {
            "Authorization": "Bearer signed-test-token", "Content-Type": "image/png",
            "X-Ronas-Case-Version": "2", "X-Ronas-Input-Revision": "4",
            "X-Ronas-Plan-Digest": PLAN, "X-Ronas-Stage-Ref": "DEMO-STAGE-01",
            "X-Ronas-Requirements-Digest": REQ,
        }
        self.url = "/api/v1/domestic/household-intake/my-drafts/DEMO-D-001/stage-observations/artifacts"

    def test_upload_returns_actual_sha_then_owner_can_download_exact_bytes(self):
        saved = self.client.put(self.url, content=PNG, headers=self.headers)
        self.assertEqual(saved.status_code, 201, saved.text)
        digest = hashlib.sha256(PNG).hexdigest()
        self.assertEqual(saved.json(), {
            "digest": digest, "content_type": "image/png",
            "byte_length": len(PNG), "stored": True,
        })
        downloaded = self.client.get(self.url + "/" + digest,
                                     headers={"Authorization": self.headers["Authorization"]})
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.content, PNG)
        self.assertEqual(downloaded.headers["content-type"], "image/png")
        self.assertIn("attachment", downloaded.headers["content-disposition"])
        self.assertEqual(downloaded.headers["x-content-type-options"], "nosniff")

    def test_upload_requires_bearer_context_and_owner(self):
        no_bearer = dict(self.headers)
        no_bearer.pop("Authorization")
        self.assertEqual(self.client.put(self.url, content=PNG, headers=no_bearer).status_code, 401)
        stale = {**self.headers, "X-Ronas-Plan-Digest": "d" * 64}
        self.assertEqual(self.client.put(self.url, content=PNG, headers=stale).status_code, 409)
        self.principal = Principal("intruder", frozenset({"household"}))
        self.assertEqual(self.client.put(self.url, content=PNG, headers=self.headers).status_code, 404)

    def test_upload_rejects_unsupported_bytes_and_oversized_body(self):
        bad = self.client.put(self.url, content=b"oops", headers=self.headers)
        self.assertEqual(bad.status_code, 422)
        oversized = self.client.put(
            self.url, content=PNG + b"x" * MAX_ARTIFACT_BYTES,
            headers=self.headers,
        )
        self.assertEqual(oversized.status_code, 413)


if __name__ == "__main__":
    unittest.main()
