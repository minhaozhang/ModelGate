import unittest
from app.routes.providers import ProviderCreate, ProviderUpdate


class ProviderUrlStripTests(unittest.TestCase):
    def test_create_strips_whitespace(self):
        data = ProviderCreate(
            name="jintou",
            base_url="  https://token.naitg.cn/v1/chat/completions  ",
        )
        self.assertEqual(data.base_url, "https://token.naitg.cn/v1/chat/completions")

    def test_update_strips_whitespace(self):
        data = ProviderUpdate(base_url=" https://example.com/v1 ")
        self.assertEqual(data.base_url, "https://example.com/v1")

    def test_update_none_passthrough(self):
        self.assertIsNone(ProviderUpdate(base_url=None).base_url)


if __name__ == "__main__":
    unittest.main()
