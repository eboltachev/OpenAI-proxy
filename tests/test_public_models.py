import os
import unittest

from app.routers.public import _public_models_enabled


class PublicModelsTests(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("API_PUBLIC_MODELS")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("API_PUBLIC_MODELS", None)
        else:
            os.environ["API_PUBLIC_MODELS"] = self._old

    def test_public_models_enabled_by_default(self):
        os.environ.pop("API_PUBLIC_MODELS", None)
        self.assertTrue(_public_models_enabled())


if __name__ == "__main__":
    unittest.main()
