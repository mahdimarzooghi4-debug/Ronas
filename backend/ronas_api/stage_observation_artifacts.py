"""Private, content-addressed storage for Domestic stage observation files.

The filesystem adapter is for LOCAL/TEST only. Deployments inject an object-store
adapter implementing the same protocol; file bytes never enter the audit ledger.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response

from .auth import Principal
from .domestic_stage_observation import CurrentStageContext

MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_STAGE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_MIME_SIGNATURES = {
    "image/jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "image/png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/webp": lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP",
    "application/pdf": lambda b: b.startswith(b"%PDF-"),
}


class StageArtifactStoreError(RuntimeError):
    """The private artifact adapter could not safely store or read an object."""


@dataclass(frozen=True, slots=True)
class StageArtifact:
    digest: str
    content_type: str
    byte_length: int


class StageArtifactStore(Protocol):
    def put(self, owner: str, case_ref: str, content_type: str,
            content: bytes) -> StageArtifact: ...

    def get(self, owner: str, case_ref: str, digest: str
            ) -> tuple[StageArtifact, bytes] | None:
        # Walk from the configured root using directory descriptors. This avoids
        # following a leaf or namespace symlink if a local directory is replaced
        # after initialization, and binds the read to the checked file descriptor.
        if (not isinstance(owner, str) or not owner or len(owner) > 256
                or not isinstance(case_ref, str) or not case_ref
                or not isinstance(digest, str) or not _DIGEST.fullmatch(digest)):
            raise ValueError("invalid stage artifact scope")
        directory_flag = getattr(os, "O_DIRECTORY", 0)
        nofollow_flag = getattr(os, "O_NOFOLLOW", 0)
        descriptors: list[int] = []
        try:
            root_fd = os.open(self.root, os.O_RDONLY | directory_flag | nofollow_flag)
            descriptors.append(root_fd)
            for directory in (self._namespace(owner), self._namespace(case_ref)):
                try:
                    child_fd = os.open(
                        directory, os.O_RDONLY | directory_flag | nofollow_flag,
                        dir_fd=descriptors[-1],
                    )
                except FileNotFoundError:
                    return None
                info = os.fstat(child_fd)
                if (not stat.S_ISDIR(info.st_mode)
                        or stat.S_IMODE(info.st_mode) & 0o077
                        or (hasattr(os, "getuid") and info.st_uid != os.getuid())):
                    os.close(child_fd)
                    raise StageArtifactStoreError(
                        "artifact directory is not private",
                    )
                descriptors.append(child_fd)
            try:
                fd = os.open(
                    digest, os.O_RDONLY | nofollow_flag,
                    dir_fd=descriptors[-1],
                )
            except FileNotFoundError:
                return None
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode)
                        or stat.S_IMODE(info.st_mode) & 0o077
                        or (hasattr(os, "getuid") and info.st_uid != os.getuid())):
                    raise StageArtifactStoreError("artifact file is not private")
                chunks, size = [], 0
                while True:
                    chunk = os.read(fd, min(64 * 1024, MAX_ARTIFACT_BYTES + 29 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_ARTIFACT_BYTES + 28:
                        raise StageArtifactStoreError("artifact file size is invalid")
                encrypted = b"".join(chunks)
            finally:
                os.close(fd)
            if not 28 <= len(encrypted) <= MAX_ARTIFACT_BYTES + 28:
                raise StageArtifactStoreError("artifact file size is invalid")
            content = self._cipher.decrypt(
                encrypted[:12], encrypted[12:], self._aad(owner, case_ref, digest),
            )
            if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), digest):
                raise StageArtifactStoreError("artifact digest verification failed")
            # Infer media type from authenticated bytes; no mutable sidecar exists.
            media = next((kind for kind, matches in _MIME_SIGNATURES.items()
                          if matches(content)), None)
            if media is None:
                raise StageArtifactStoreError("artifact media signature is invalid")
            return StageArtifact(digest, media, len(content)), content
        except FileNotFoundError:
            return None
        except (OSError, InvalidTag) as exc:
            raise StageArtifactStoreError(
                "artifact read or integrity check failed",
            ) from exc
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
    def contains(self, owner: str, case_ref: str, digest: str) -> bool: ...


def _validated_content_type(content_type: str, content: bytes) -> str:
    if (not isinstance(content_type, str) or content_type not in _MIME_SIGNATURES
            or not _MIME_SIGNATURES[content_type](content)):
        raise ValueError("unsupported or mismatched stage artifact media type")
    return content_type


class PrivateFilesystemStageArtifactStore:
    """Encrypted content-addressed LOCAL/TEST adapter with owner/case isolation."""

    def __init__(self, root: str | Path, encryption_key: bytes):
        self.root = Path(root)
        if not isinstance(encryption_key, bytes) or len(encryption_key) != 32:
            raise ValueError("stage artifact AES-256 key must contain 32 bytes")
        try:
            info = self.root.lstat()
            if (not stat.S_ISDIR(info.st_mode)
                    or stat.S_IMODE(info.st_mode) & 0o077
                    or (hasattr(os, "getuid") and info.st_uid != os.getuid())):
                raise ValueError("artifact root must be an owned private directory")
        except OSError as exc:
            raise ValueError("artifact root must already exist") from exc
        self._cipher = AESGCM(encryption_key)

    @staticmethod
    def _namespace(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _path(self, owner: str, case_ref: str, digest: str) -> Path:
        if (not isinstance(owner, str) or not owner or len(owner) > 256
                or not isinstance(case_ref, str) or not case_ref
                or not isinstance(digest, str) or not _DIGEST.fullmatch(digest)):
            raise ValueError("invalid stage artifact scope")
        return (self.root / self._namespace(owner) / self._namespace(case_ref)
                / digest)

    @staticmethod
    def _aad(owner: str, case_ref: str, digest: str) -> bytes:
        return (hashlib.sha256(owner.encode()).hexdigest() + ":"
                + hashlib.sha256(case_ref.encode()).hexdigest() + ":"
                + digest).encode("ascii")

    def put(self, owner: str, case_ref: str, content_type: str,
            content: bytes) -> StageArtifact:
        if not isinstance(content, bytes) or not 1 <= len(content) <= MAX_ARTIFACT_BYTES:
            raise ValueError("stage artifact size is outside the allowed range")
        content_type = _validated_content_type(content_type, content)
        digest = hashlib.sha256(content).hexdigest()
        path = self._path(owner, case_ref, digest)
        owner_dir = self.root / self._namespace(owner)
        directory = owner_dir / self._namespace(case_ref)
        try:
            owner_dir.mkdir(mode=0o700, exist_ok=True)
            directory.mkdir(mode=0o700, exist_ok=True)
            for parent in (self.root, owner_dir, directory):
                info = parent.lstat()
                if (not stat.S_ISDIR(info.st_mode)
                        or stat.S_IMODE(info.st_mode) & 0o077
                        or (hasattr(os, "getuid") and info.st_uid != os.getuid())):
                    raise StageArtifactStoreError("artifact directory is not private")
            nonce = secrets.token_bytes(12)
            ciphertext = nonce + self._cipher.encrypt(
                nonce, content, self._aad(owner, case_ref, digest),
            )
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                              | getattr(os, "O_NOFOLLOW", 0), 0o600)
            except FileExistsError:
                existing = self.get(owner, case_ref, digest)
                if existing is None or existing[1] != content:
                    raise StageArtifactStoreError("artifact digest collision")
            else:
                with os.fdopen(fd, "wb") as target:
                    target.write(ciphertext)
                    target.flush()
                    os.fsync(target.fileno())
        except (OSError, InvalidTag) as exc:
            if isinstance(exc, StageArtifactStoreError):
                raise
            raise StageArtifactStoreError("artifact write failed") from exc
        return StageArtifact(digest, content_type, len(content))

    def get(self, owner: str, case_ref: str, digest: str
            ) -> tuple[StageArtifact, bytes] | None:
        path = self._path(owner, case_ref, digest)
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                raise StageArtifactStoreError("artifact file is not private")
            encrypted = path.read_bytes()
            if not 28 <= len(encrypted) <= MAX_ARTIFACT_BYTES + 28:
                raise StageArtifactStoreError("artifact file size is invalid")
            content = self._cipher.decrypt(
                encrypted[:12], encrypted[12:], self._aad(owner, case_ref, digest),
            )
            if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), digest):
                raise StageArtifactStoreError("artifact digest verification failed")
            # Store the validated type in a tiny authenticated sidecar-free header:
            # infer from signed bytes, so no mutable metadata can alter serving.
            media = next((kind for kind, matches in _MIME_SIGNATURES.items()
                          if matches(content)), None)
            if media is None:
                raise StageArtifactStoreError("artifact media signature is invalid")
            return StageArtifact(digest, media, len(content)), content
        except FileNotFoundError:
            return None
        except (OSError, InvalidTag) as exc:
            raise StageArtifactStoreError("artifact read or integrity check failed") from exc

    def contains(self, owner: str, case_ref: str, digest: str) -> bool:
        return self.get(owner, case_ref, digest) is not None


def _context_matches(context: CurrentStageContext | None, ref: str,
                     headers: dict[str, str]) -> bool:
    if not isinstance(context, CurrentStageContext) or context.case_ref != ref:
        return False
    try:
        case_version = int(headers["case_version"])
        input_revision = int(headers["input_revision"])
    except (KeyError, TypeError, ValueError):
        return False
    if (case_version != context.case_version or input_revision != context.input_revision
            or headers.get("plan_digest") != context.plan_digest):
        return False
    return any(stage.stage_ref == headers.get("stage_ref")
               and stage.observation_requirements_digest
               == headers.get("requirements_digest")
               for stage in context.requirements)


def build_stage_artifact_router(
    store: StageArtifactStore,
    verified_principal: Callable[..., Principal],
    profile_schema_ref: str,
    profile_access_authority: Callable[[Principal, str, str], bool],
    stage_context_authority: Callable[[str], CurrentStageContext | None],
) -> APIRouter:
    if (not all(callable(value) for value in (
            verified_principal, profile_access_authority, stage_context_authority))
            or not isinstance(profile_schema_ref, str) or not profile_schema_ref
            or not all(callable(getattr(store, name, None))
                       for name in ("put", "get", "contains"))):
        raise ValueError("stage artifact storage requires explicit authorities and adapter")
    router = APIRouter()

    def authorize(p: Principal, ref: str) -> None:
        try:
            allowed = profile_access_authority(p, ref, profile_schema_ref)
        except Exception as exc:
            raise HTTPException(503, detail="HOUSEHOLD_PROFILE_AUTHORITY_UNAVAILABLE") from exc
        if allowed is not True:
            raise HTTPException(404, detail="DRAFT_NOT_FOUND")

    @router.put(
        "/api/v1/domestic/household-intake/my-drafts/{ref}/stage-observations/artifacts",
        status_code=201,
    )
    async def upload_stage_artifact(
        ref: str, request: Request,
        x_ronas_case_version: str | None = Header(default=None),
        x_ronas_input_revision: str | None = Header(default=None),
        x_ronas_plan_digest: str | None = Header(default=None),
        x_ronas_stage_ref: str | None = Header(default=None),
        x_ronas_requirements_digest: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
        p: Principal = Depends(verified_principal),
    ) -> dict:
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            raise HTTPException(401, detail="BEARER_REQUIRED_FOR_MUTATION")
        authorize(p, ref)
        headers = {
            "case_version": x_ronas_case_version or "",
            "input_revision": x_ronas_input_revision or "",
            "plan_digest": x_ronas_plan_digest or "",
            "stage_ref": x_ronas_stage_ref or "",
            "requirements_digest": x_ronas_requirements_digest or "",
        }
        try:
            context = stage_context_authority(ref)
        except Exception as exc:
            raise HTTPException(503, detail="STAGE_CONTEXT_UNAVAILABLE") from exc
        if not _context_matches(context, ref, headers):
            raise HTTPException(409, detail="STAGE_OBSERVATION_CONTEXT_CHANGED")
        declared = request.headers.get("content-length")
        if declared:
            try:
                if int(declared) > MAX_ARTIFACT_BYTES:
                    raise HTTPException(413, detail="STAGE_ARTIFACT_TOO_LARGE")
            except ValueError as exc:
                raise HTTPException(400, detail="INVALID_CONTENT_LENGTH") from exc
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_ARTIFACT_BYTES:
                raise HTTPException(413, detail="STAGE_ARTIFACT_TOO_LARGE")
            chunks.append(chunk)
        content = b"".join(chunks)
        try:
            artifact = store.put(
                p.subject, ref + ":" + headers["stage_ref"],
                request.headers.get("content-type", ""), content,
            )
        except ValueError as exc:
            raise HTTPException(422, detail="INVALID_STAGE_ARTIFACT") from exc
        except StageArtifactStoreError as exc:
            raise HTTPException(503, detail="STAGE_ARTIFACT_STORE_UNAVAILABLE") from exc
        return {"digest": artifact.digest, "content_type": artifact.content_type,
                "byte_length": artifact.byte_length, "stored": True}

    @router.get(
        "/api/v1/domestic/household-intake/my-drafts/{ref}/stage-observations/artifacts/{stage_ref}/{digest}"
    )
    def read_stage_artifact(
        ref: str, stage_ref: str, digest: str,
        p: Principal = Depends(verified_principal),
    ) -> Response:
        authorize(p, ref)
        if not _STAGE_REF.fullmatch(stage_ref) or not _DIGEST.fullmatch(digest):
            raise HTTPException(404, detail="STAGE_ARTIFACT_NOT_FOUND")
        try:
            item = store.get(p.subject, ref + ":" + stage_ref, digest)
        except (ValueError, StageArtifactStoreError) as exc:
            raise HTTPException(503, detail="STAGE_ARTIFACT_STORE_UNAVAILABLE") from exc
        if item is None:
            raise HTTPException(404, detail="STAGE_ARTIFACT_NOT_FOUND")
        artifact, content = item
        return Response(
            content, media_type=artifact.content_type,
            headers={"Cache-Control": "private, no-store",
                     "X-Content-Type-Options": "nosniff",
                     "Content-Disposition": "attachment; filename=stage-observation-"
                     + digest[:16]},
        )

    return router
