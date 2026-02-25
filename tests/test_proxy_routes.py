import unittest

from app.routers.proxy import PROXY_PATHS


class ProxyRoutesTests(unittest.TestCase):
    def test_images_generations_is_registered_in_proxy_paths(self):
        self.assertIn("/v1/images/generations", PROXY_PATHS)


if __name__ == "__main__":
    unittest.main()
