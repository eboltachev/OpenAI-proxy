import asyncio
import os
import unittest

from app.main import app, lifespan


class MainSecurityLifecycleTests(unittest.TestCase):
    def setUp(self):
        self._old_required = os.environ.get("API_AUTH_REQUIRED")
        self._old_token = os.environ.get("API_BEARER_TOKEN")

    def tearDown(self):
        if self._old_required is None:
            os.environ.pop("API_AUTH_REQUIRED", None)
        else:
            os.environ["API_AUTH_REQUIRED"] = self._old_required
        if self._old_token is None:
            os.environ.pop("API_BEARER_TOKEN", None)
        else:
            os.environ["API_BEARER_TOKEN"] = self._old_token

    def test_lifespan_fails_fast_when_auth_required_and_token_missing(self):
        os.environ["API_AUTH_REQUIRED"] = "1"
        os.environ["API_BEARER_TOKEN"] = ""

        async def run():
            async with lifespan(app):
                return None

        with self.assertRaises(RuntimeError):
            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
