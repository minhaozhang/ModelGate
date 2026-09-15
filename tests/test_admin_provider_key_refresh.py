import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _fn_body(html: str, name: str) -> str:
    start = html.index("async function " + name)
    brace = html.index("{", start)
    depth = 0
    for i in range(brace, len(html)):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[start : i + 1]
    raise AssertionError("unbalanced braces in " + name)


class ProviderKeyRefreshTests(unittest.TestCase):
    """Key mutations change keys_active, which drives the provider row light
    (renderProviderLight). Handlers must refresh the provider table too."""

    def test_key_mutation_handlers_refresh_provider_table(self):
        html = (ROOT / "web/templates/admin/config.html").read_text(encoding="utf-8")

        for fn in (
            "toggleProviderKey",
            "confirmDisableKey",
            "deleteProviderKey",
            "addProviderKey",
        ):
            body = _fn_body(html, fn)
            self.assertIn("renderProviderKeys(", body, fn)
            self.assertIn("loadProviders()", body, fn)

    def test_provider_light_uses_key_counts(self):
        html = (ROOT / "web/templates/admin/config.html").read_text(encoding="utf-8")
        body = _fn_body(html.replace("function renderProviderLight", "async function renderProviderLight"), "renderProviderLight")

        self.assertIn("keys_total", body)
        self.assertIn("keys_active", body)


if __name__ == "__main__":
    unittest.main()
