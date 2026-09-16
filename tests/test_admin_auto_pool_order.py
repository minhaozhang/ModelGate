import unittest
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "web" / "templates" / "admin" / "config.html"
HTML = CONFIG.read_text(encoding="utf-8")


class AutoPoolOrderTests(unittest.TestCase):
    def test_pool_ids_preserve_array_order_not_object_keys(self):
        self.assertNotIn("Object.keys(poolMap)", HTML)
        self.assertIn(
            "poolConfig.filter(i => i && i.id).map(i => Number(i.id))",
            HTML,
        )

    def test_load_path_keeps_pool_config(self):
        self.assertIn("pool_config: data.pool_config || []", HTML)


if __name__ == "__main__":
    unittest.main()
