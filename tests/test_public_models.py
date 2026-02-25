import asyncio
import os
import types
import unittest

from starlette.requests import Request

from app.config import Upstream
from app.routers.public import list_models


class PublicModelsTests(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("API_PUBLIC_MODELS")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("API_PUBLIC_MODELS", None)
        else:
            os.environ["API_PUBLIC_MODELS"] = self._old

    def test_v1_models_available_even_when_api_public_models_disabled(self):
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
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
