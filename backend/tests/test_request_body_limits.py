"""Household profile body bounds run before request parsing."""
import asyncio
import unittest

from ronas_api.request_body_limits import HouseholdProfileBodyLimitMiddleware


PATH = "/api/v1/domestic/household-intake/my-drafts/DEMO-D-1/cultivation-inputs"


class HouseholdProfileBodyLimitTests(unittest.TestCase):
    def run_asgi(self, *, scope, messages):
        calls = {"app": 0, "body": bytearray()}
        sent = []
        queue = list(messages)

        async def receive():
            if queue:
                return queue.pop(0)
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        async def app(_scope, downstream_receive, send):
            calls["app"] += 1
            while True:
                message = await downstream_receive()
                if message["type"] != "http.request":
                    break
                calls["body"].extend(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        asyncio.run(HouseholdProfileBodyLimitMiddleware(app)(scope, receive, send))
        return calls, sent

    def test_chunked_oversized_profile_body_is_rejected_before_downstream(self):
        scope = {"type": "http", "method": "POST", "path": PATH, "headers": []}
        calls, sent = self.run_asgi(scope=scope, messages=[
            {"type": "http.request", "body": b"a" * 2048, "more_body": True},
            {"type": "http.request", "body": b"b" * 2049, "more_body": True},
        ])
        self.assertEqual(calls["app"], 0)
        self.assertEqual(sent[0]["status"], 413)
        self.assertIn((b"cache-control", b"no-store"), sent[0]["headers"])

    def test_oversized_content_length_is_rejected_without_reading_body(self):
        scope = {
            "type": "http", "method": "POST", "path": PATH,
            "headers": [(b"content-length", b"4097")],
        }
        calls, sent = self.run_asgi(scope=scope, messages=[])
        self.assertEqual(calls["app"], 0)
        self.assertEqual(sent[0]["status"], 413)

    def test_unrelated_route_and_method_are_not_body_limited(self):
        for scope in (
            {"type": "http", "method": "POST", "path": "/api/v1/export/research", "headers": []},
            {"type": "http", "method": "GET", "path": PATH, "headers": []},
        ):
            with self.subTest(method=scope["method"], path=scope["path"]):
                calls, sent = self.run_asgi(scope=scope, messages=[
                    {"type": "http.request", "body": b"x" * 8192,
                     "more_body": False},
                ])
                self.assertEqual(calls["app"], 1)
                self.assertEqual(calls["body"], b"x" * 8192)
                self.assertEqual(sent[0]["status"], 200)

    def test_body_at_limit_is_replayed_unchanged(self):
        body = b"x" * 4096
        scope = {"type": "http", "method": "POST", "path": PATH, "headers": []}
        calls, sent = self.run_asgi(scope=scope, messages=[
            {"type": "http.request", "body": body[:2048], "more_body": True},
            {"type": "http.request", "body": body[2048:], "more_body": False},
        ])
        self.assertEqual(calls["app"], 1)
        self.assertEqual(calls["body"], body)
        self.assertEqual(sent[0]["status"], 200)


if __name__ == "__main__":
    unittest.main()
