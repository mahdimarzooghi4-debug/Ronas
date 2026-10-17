"""Small bounded request bodies for sensitive JSON write routes."""
from __future__ import annotations

import re


_PROFILE_PATH = re.compile(
    r"^/api/v1/domestic/household-intake/my-drafts/[^/]+/cultivation-inputs$"
)
_MAX_PROFILE_BODY = 4096
_REJECT_BODY = b'{"detail":"HOUSEHOLD_PROFILE_REQUEST_TOO_LARGE"}'


class HouseholdProfileBodyLimitMiddleware:
    """Cap profile JSON before framework parsing or model validation."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope.get("type") != "http" or scope.get("method") != "POST"
                or not _PROFILE_PATH.fullmatch(scope.get("path", ""))):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", ())}
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                declared_length = int(declared)
            except ValueError:
                declared_length = -1
            if declared_length > _MAX_PROFILE_BODY:
                await self._reject(send)
                return

        chunks = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunks.extend(message.get("body", b""))
            if len(chunks) > _MAX_PROFILE_BODY:
                await self._reject(send)
                return
            if not message.get("more_body", False):
                break

        body = bytes(chunks)
        replayed = False

        async def replay_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(send):
        await send({
            "type": "http.response.start", "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_REJECT_BODY)).encode("ascii")),
                (b"cache-control", b"no-store"),
                (b"x-content-type-options", b"nosniff"),
            ],
        })
        await send({"type": "http.response.body", "body": _REJECT_BODY})
