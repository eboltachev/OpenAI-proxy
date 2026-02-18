import unittest

from app.upstream import http_fallback_url_on_ssl_error


class HttpFallbackOnSslErrorTests(unittest.TestCase):
    def test_rewrites_https_to_http_for_ssl_record_layer_failure(self):
        url = "https://localhost:11434/v1/chat/completions?stream=true"
        err = RuntimeError("[SSL] record layer failure (_ssl.c:1010)")

        self.assertEqual(
            http_fallback_url_on_ssl_error(url, err),
            "http://localhost:11434/v1/chat/completions?stream=true",
        )

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
