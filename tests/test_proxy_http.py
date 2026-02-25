import asyncio
import json
import os
import types
import unittest

import httpx
from starlette.requests import Request

from app.config import Upstream
from app.proxy_http import _filtered_headers, proxy_http


class _FakeHttpClient:
    def __init__(self, fail_first_ssl: bool = False):
        self.fail_first_ssl = fail_first_ssl
        self.send_calls: list[httpx.Request] = []

    def build_request(self, method, url, headers=None, content=None):
        return httpx.Request(method=method, url=url, headers=headers, content=content)

    async def send(self, request: httpx.Request, stream: bool = True):
        self.send_calls.append(request)
        if self.fail_first_ssl and len(self.send_calls) == 1:
            raise httpx.RequestError("[SSL] record layer failure", request=request)
        return httpx.Response(200, request=request, headers={"content-type": "text/plain"}, content=b"ok")


class _FakeCapsClient:
    async def get(self, url, headers=None):
        req = httpx.Request("GET", url)
        return httpx.Response(404, request=req)


def _make_request(method: str, path: str, headers: dict[str, str] | None = None):
    hdrs = []
    for k, v in (headers or {}).items():
        hdrs.append((k.lower().encode(), v.encode()))
    app = types.SimpleNamespace(state=types.SimpleNamespace())
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": hdrs,
        "app": app,
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    req = Request(scope, receive)
    return req, app


class ProxyHttpFallbackTests(unittest.TestCase):
    def setUp(self):
        self._old_downgrade = os.environ.get("API_ALLOW_SSL_DOWNGRADE")
        self._old_buffer = os.environ.get("API_FALLBACK_BUFFER_BYTES")
        self._old_allow = os.environ.get("API_SSL_DOWNGRADE_ALLOWLIST")
        os.environ["API_ALLOW_SSL_DOWNGRADE"] = "1"
        os.environ["API_FALLBACK_BUFFER_BYTES"] = "1024"
        os.environ["API_SSL_DOWNGRADE_ALLOWLIST"] = "example.test"

    def tearDown(self):
        if self._old_downgrade is None:
            os.environ.pop("API_ALLOW_SSL_DOWNGRADE", None)
        else:
            os.environ["API_ALLOW_SSL_DOWNGRADE"] = self._old_downgrade
        if self._old_buffer is None:
            os.environ.pop("API_FALLBACK_BUFFER_BYTES", None)
        else:
            os.environ["API_FALLBACK_BUFFER_BYTES"] = self._old_buffer
        if self._old_allow is None:
            os.environ.pop("API_SSL_DOWNGRADE_ALLOWLIST", None)
        else:
            os.environ["API_SSL_DOWNGRADE_ALLOWLIST"] = self._old_allow

    def test_post_with_small_buffered_body_retries_over_http(self):
        request, app = _make_request("POST", "/v1/chat/completions", {"content-length": "5"})
        app.state.http_client = _FakeHttpClient(fail_first_ssl=True)
        app.state.caps_client = _FakeCapsClient()
        upstream = Upstream(model="m", base_url="https://example.test", api_key="sekret")

        async def body_iter():
            yield b"hello"

        async def run():
            return await proxy_http(request, upstream, body_iter())

        resp = asyncio.run(run())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(app.state.http_client.send_calls), 2)
        self.assertEqual(str(app.state.http_client.send_calls[1].url), "http://example.test/v1/chat/completions")
        self.assertEqual(app.state.http_client.send_calls[1].content, b"hello")

    def test_post_without_content_length_returns_controlled_error(self):
        request, app = _make_request("POST", "/v1/chat/completions")
        app.state.http_client = _FakeHttpClient(fail_first_ssl=True)
        app.state.caps_client = _FakeCapsClient()
        upstream = Upstream(model="m", base_url="https://example.test", api_key="")

        async def body_iter():
            yield b"hello"

        async def run():
            return await proxy_http(request, upstream, body_iter())

        resp = asyncio.run(run())
        self.assertEqual(resp.status_code, 502)
        payload = json.loads(resp.body)
        self.assertEqual(payload["error"]["code"], "unsafe_ssl_downgrade_retry")

    def test_get_retries_without_body(self):
        request, app = _make_request("GET", "/v1/models")
        app.state.http_client = _FakeHttpClient(fail_first_ssl=True)
        app.state.caps_client = _FakeCapsClient()
        upstream = Upstream(model="m", base_url="https://example.test", api_key="")

        async def empty_iter():
            if False:
                yield b""

        async def run():
            return await proxy_http(request, upstream, empty_iter())

        resp = asyncio.run(run())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(str(app.state.http_client.send_calls[1].url), "http://example.test/v1/models")

    def test_missing_runtime_client_returns_503(self):
        request, app = _make_request("GET", "/v1/models")
        app.state.caps_client = _FakeCapsClient()
        upstream = Upstream(model="m", base_url="https://example.test", api_key="")

        async def empty_iter():
            if False:
                yield b""

        async def run():
            return await proxy_http(request, upstream, empty_iter())

        resp = asyncio.run(run())
        self.assertEqual(resp.status_code, 503)

    def test_filtered_headers_contract(self):
        request, _ = _make_request(
            "POST",
            "/v1/chat/completions",
            {
                "authorization": "Bearer user",
                "connection": "keep-alive",
                "x-custom": "ok",
            },
        )
        upstream = Upstream(model="model-a", base_url="https://example.test", api_key="upstream-key")
        out = _filtered_headers(request, upstream)
        self.assertNotIn("connection", {k.lower() for k in out.keys()})
        self.assertEqual(out["Authorization"], "Bearer upstream-key")
        self.assertEqual(out["X-Proxy-Model"], "model-a")
        self.assertEqual(out["x-custom"], "ok")


if __name__ == "__main__":
    unittest.main()
