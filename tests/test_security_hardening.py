import asyncio
import os
import types
import unittest

from starlette.requests import Request

from app.config import Upstream
from app.middleware import BearerAuthMiddleware
from app.proxy_http import proxy_http
from app.routers.public import list_models
from app.upstream import http_fallback_url_on_ssl_error


class SecurityHardeningTests(unittest.TestCase):
    def setUp(self):
        self._old = {k: os.environ.get(k) for k in [
            "API_AUTH_REQUIRED",
            "API_BEARER_TOKEN",
            "API_ALLOW_SSL_DOWNGRADE",
            "API_SSL_DOWNGRADE_ALLOWLIST",
            "API_PUBLIC_MODELS",
        ]}

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_auth_required_blocks_when_token_missing(self):
        os.environ["API_AUTH_REQUIRED"] = "1"
        os.environ["API_BEARER_TOKEN"] = ""

        called = {"app": False}

        async def app(scope, receive, send):
            called["app"] = True

        mw = BearerAuthMiddleware(app)
        scope = {"type": "http", "method": "GET", "path": "/v1/chat/completions", "headers": []}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent = []

        async def send(msg):
            sent.append(msg)

        asyncio.run(mw(scope, receive, send))
        self.assertFalse(called["app"])
        self.assertTrue(any(m.get("status") == 401 for m in sent if isinstance(m, dict)))

    def test_ssl_downgrade_disallowed_for_external_host_without_allowlist(self):
        os.environ["API_ALLOW_SSL_DOWNGRADE"] = "1"
        os.environ["API_SSL_DOWNGRADE_ALLOWLIST"] = ""
        err = RuntimeError("[SSL] record layer failure")
        self.assertIsNone(http_fallback_url_on_ssl_error("https://example.com/v1/chat/completions", err))

    def test_ssl_downgrade_allowed_for_explicit_allowlist_host(self):
        os.environ["API_ALLOW_SSL_DOWNGRADE"] = "1"
        os.environ["API_SSL_DOWNGRADE_ALLOWLIST"] = "example.com"
        err = RuntimeError("[SSL] record layer failure")
        self.assertEqual(
            http_fallback_url_on_ssl_error("https://example.com/v1/chat/completions", err),
            "http://example.com/v1/chat/completions",
        )

    def test_public_models_disabled_returns_not_found(self):
        os.environ["API_PUBLIC_MODELS"] = "0"

        app = types.SimpleNamespace(state=types.SimpleNamespace(config_provider=types.SimpleNamespace(get=lambda: {"m": Upstream("m", "http://u", "")})))
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/v1/models",
            "query_string": b"",
            "headers": [],
            "app": app,
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        req = Request(scope, receive)
        resp = asyncio.run(list_models(req))
        self.assertEqual(resp.status_code, 404)

    def test_runtime_client_missing_is_503(self):
        os.environ["API_ALLOW_SSL_DOWNGRADE"] = "1"
        app = types.SimpleNamespace(state=types.SimpleNamespace(caps_client=None, http_client=None))
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/v1/models",
            "query_string": b"",
            "headers": [],
            "app": app,
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        req = Request(scope, receive)

        async def empty_iter():
            if False:
                yield b""

        resp = asyncio.run(proxy_http(req, Upstream("m", "https://example.com", ""), empty_iter()))
        self.assertEqual(resp.status_code, 503)


if __name__ == "__main__":
    unittest.main()
