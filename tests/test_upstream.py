import os
import unittest

from app.upstream import http_fallback_url_on_ssl_error


class HttpFallbackOnSslErrorTests(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("PROXY_ALLOW_SSL_DOWNGRADE")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("PROXY_ALLOW_SSL_DOWNGRADE", None)
        else:
            os.environ["PROXY_ALLOW_SSL_DOWNGRADE"] = self._old

    def test_rewrites_https_to_http_for_ssl_record_layer_failure(self):
        url = "https://localhost:11434/v1/chat/completions?stream=true"
        err = RuntimeError("[SSL] record layer failure (_ssl.c:1010)")

        os.environ["PROXY_ALLOW_SSL_DOWNGRADE"] = "1"

        self.assertEqual(
            http_fallback_url_on_ssl_error(url, err),
            "http://localhost:11434/v1/chat/completions?stream=true",
        )


    def test_returns_none_when_ssl_downgrade_is_disabled(self):
        os.environ["PROXY_ALLOW_SSL_DOWNGRADE"] = "0"
        url = "https://localhost:11434/v1/chat/completions"
        err = RuntimeError("[SSL] record layer failure (_ssl.c:1010)")

        self.assertIsNone(http_fallback_url_on_ssl_error(url, err))

    def test_returns_none_for_non_https_url(self):
        url = "http://localhost:11434/v1/chat/completions"
        err = RuntimeError("[SSL] record layer failure (_ssl.c:1010)")

        self.assertIsNone(http_fallback_url_on_ssl_error(url, err))

    def test_returns_none_for_non_ssl_error(self):
        url = "https://localhost:11434/v1/chat/completions"
        err = RuntimeError("connection refused")

        self.assertIsNone(http_fallback_url_on_ssl_error(url, err))


if __name__ == "__main__":
    unittest.main()
