import asyncio
import os
import unittest

from app.middleware import BearerAuthMiddleware


class BearerAuthWebSocketTests(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("API_BEARER_TOKEN")
        os.environ["API_BEARER_TOKEN"] = "token123"

    def tearDown(self):
        if self._old is None:
            os.environ.pop("API_BEARER_TOKEN", None)
        else:
            os.environ["API_BEARER_TOKEN"] = self._old

    def test_websocket_unauthorized_returns_4401(self):
        called = {"app": False}

        async def app(scope, receive, send):
            called["app"] = True

        mw = BearerAuthMiddleware(app)
        scope = {
            "type": "websocket",
            "path": "/v1/realtime",
            "headers": [],
        }
        sent = []

        async def receive():
            return {"type": "websocket.connect"}

        async def send(msg):
            sent.append(msg)

        asyncio.run(mw(scope, receive, send))
        self.assertFalse(called["app"])
        self.assertEqual(sent[0]["type"], "websocket.close")
        self.assertEqual(sent[0]["code"], 4401)

    def test_websocket_authorized_passes_through(self):
        called = {"app": False}

        async def app(scope, receive, send):
            called["app"] = True

        mw = BearerAuthMiddleware(app)
        scope = {
            "type": "websocket",
            "path": "/v1/realtime",
            "headers": [(b"authorization", b"Bearer token123")],
        }

        async def receive():
            return {"type": "websocket.connect"}

        async def send(msg):
            return None

        asyncio.run(mw(scope, receive, send))
        self.assertTrue(called["app"])


if __name__ == "__main__":
    unittest.main()
