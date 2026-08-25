import unittest

import tomllib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import codex


class CodexTomlTests(unittest.TestCase):
    def test_build_codex_toml(self):
        toml = codex.build_codex_toml("https://gw.example/modelgate/v1", "glm-5", "sk-test")
        parsed = tomllib.loads(toml)
        self.assertEqual(parsed["model"], "glm-5")
        self.assertEqual(parsed["model_provider"], "modelgate")
        self.assertEqual(parsed["preferred_auth_method"], "apikey")
        self.assertEqual(parsed["forced_login_method"], "api")
        self.assertEqual(parsed["model_reasoning_effort"], "high")
        self.assertEqual(parsed["model_catalog_json"], "~/.codex/models.json")
        provider = parsed["model_providers"]["modelgate"]
        self.assertEqual(provider["name"], "ModelGate")
        self.assertEqual(provider["base_url"], "https://gw.example/modelgate/v1")
        self.assertEqual(provider["wire_api"], "responses")
        self.assertEqual(provider["experimental_bearer_token"], "sk-test")

    def test_merge_into_empty(self):
        merged, removed = codex.merge_codex_toml(
            "", "https://gw.example/v1", "glm-5", "sk-test"
        )
        self.assertEqual(removed, [])
        parsed = tomllib.loads(merged)
        self.assertEqual(parsed["model"], "glm-5")
        self.assertEqual(parsed["model_providers"]["modelgate"]["wire_api"], "responses")

    def test_merge_preserves_foreign_sections_and_comments(self):
        existing = """# my codex config
model = "gpt-5"
model_provider = "openai"

[projects."my-project"]
trust_level = "trusted"

[mcp_servers.foo]
command = "npx"

[model_providers.modelgate]
name = "Old"
base_url = "https://old.example/"
"""
        merged, removed = codex.merge_codex_toml(
            existing, "https://gw.example/v1", "glm-5", "sk-test"
        )
        parsed = tomllib.loads(merged)
        self.assertEqual(parsed["model"], "glm-5")
        self.assertEqual(parsed["model_provider"], "modelgate")
        self.assertEqual(parsed["projects"]["my-project"]["trust_level"], "trusted")
        self.assertEqual(parsed["mcp_servers"]["foo"]["command"], "npx")
        self.assertEqual(
            parsed["model_providers"]["modelgate"]["base_url"], "https://gw.example/v1"
        )
        self.assertIn("# my codex config", merged)
        self.assertEqual(
            sorted(removed),
            sorted(['model = "gpt-5"', 'model_provider = "openai"',
                    "[model_providers.modelgate]", 'name = "Old"',
                    'base_url = "https://old.example/"']),
        )

    def test_merge_rejects_invalid_toml(self):
        with self.assertRaises(ValueError):
            codex.merge_codex_toml("not [valid toml", "https://gw/v1", "m", "sk-t")

    def test_managed_keys_after_first_section_kept(self):
        # A managed key inside a section (not top level) must NOT be touched.
        existing = """[profiles.fast]
model = "gpt-5-mini"
"""
        merged, _removed = codex.merge_codex_toml(
            existing, "https://gw/v1", "glm-5", "sk-t"
        )
        parsed = tomllib.loads(merged)
        self.assertEqual(parsed["profiles"]["fast"]["model"], "gpt-5-mini")
        self.assertEqual(parsed["model"], "glm-5")


class CodexCatalogTests(unittest.TestCase):
    def test_model_entry_text_model(self):
        entry = codex._codex_model_entry(
            "glm-5",
            {
                "name": "GLM-5",
                "modalities": {"input": ["text"], "output": ["text"]},
                "limit": {"context": 204800, "output": 131072},
                "variants": {"high": {}, "max": {}},
            },
        )
        self.assertEqual(entry["slug"], "glm-5")
        self.assertEqual(entry["display_name"], "GLM-5")
        self.assertEqual(entry["input_modalities"], ["text"])
        self.assertFalse(entry["supports_image_detail_original"])
        self.assertEqual(entry["context_window"], 204800)
        self.assertEqual(entry["default_reasoning_level"], "high")
        self.assertEqual(
            [lvl["effort"] for lvl in entry["supported_reasoning_levels"]],
            ["high", "max"],
        )
        self.assertNotIn("instructions_template", entry)

    def test_model_entry_vision_no_reasoning(self):
        entry = codex._codex_model_entry(
            "glm-4v",
            {
                "name": "GLM-4V",
                "modalities": {"input": ["text", "image"], "output": ["text"]},
                "limit": {"context": 128000, "output": 8192},
                "variants": {},
            },
        )
        self.assertEqual(entry["input_modalities"], ["text", "image"])
        self.assertTrue(entry["supports_image_detail_original"])
        self.assertNotIn("supported_reasoning_levels", entry)

    def test_catalog_sorted(self):
        catalog = codex.build_codex_models_catalog(
            {
                "zeta": {"name": "Zeta", "limit": {"context": 1, "output": 1}},
                "alpha": {"name": "Alpha", "limit": {"context": 1, "output": 1}},
            }
        )
        self.assertEqual(
            [m["slug"] for m in catalog["models"]], ["alpha", "zeta"]
        )


class _Ctx:
    def __init__(self, ctx):
        self._ctx = ctx

    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return False


class CodexEndpointTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(codex.router)
        self.client = TestClient(app)

    def test_config_requires_key(self):
        resp = self.client.get("/codex/config")
        self.assertEqual(resp.status_code, 400)

    def test_models_json_requires_key(self):
        resp = self.client.get("/codex/models.json")
        self.assertEqual(resp.status_code, 400)

    def test_setup_md_requires_key(self):
        resp = self.client.get("/codex/setup.md")
        self.assertEqual(resp.status_code, 400)

    def test_setup_file_requires_key(self):
        resp = self.client.post("/codex/setup-file")
        self.assertEqual(resp.status_code, 400)

    def test_scripts_render_without_key(self):
        resp = self.client.get("/codex/setup.ps1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("/codex/setup-file", resp.text)
        resp = self.client.get("/codex/setup.sh")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("codex/setup-file", resp.text)
        self.assertIn("MODELGATE_API_KEY", resp.text)

    def test_setup_file_merges_and_returns_models_header(self):
        ctx = {
            "base_url": "http://testserver/v1",
            "models": ["glm-5", "glm-5-air"],
            "display_names": {"glm-5": "GLM-5"},
            "default_model": "glm-5",
            "api_key": "sk-test",
        }

        async def fake_ctx(request, api_key=None, api_key_id=None):
            return ctx

        from unittest.mock import patch

        with patch.object(codex, "build_codex_context", fake_ctx):
            resp = self.client.post(
                "/codex/setup-file?api_key=sk-test",
                content=b'[mcp_servers.foo]\ncommand = "npx"\n',
            )
        self.assertEqual(resp.status_code, 200)
        parsed = tomllib.loads(resp.text)
        self.assertEqual(parsed["model"], "glm-5")
        self.assertEqual(parsed["mcp_servers"]["foo"]["command"], "npx")
        self.assertEqual(
            parsed["model_providers"]["modelgate"]["experimental_bearer_token"],
            "sk-test",
        )
        self.assertIn("glm-5", resp.headers["X-Models"])

    def test_setup_file_invalid_toml_422(self):
        ctx = {
            "base_url": "http://testserver/v1",
            "models": ["glm-5"],
            "display_names": {},
            "default_model": "glm-5",
            "api_key": "sk-test",
        }

        async def fake_ctx(request, api_key=None, api_key_id=None):
            return ctx

        from unittest.mock import patch

        with patch.object(codex, "build_codex_context", fake_ctx):
            resp = self.client.post(
                "/codex/setup-file?api_key=sk-test", content=b"broken [ ["
            )
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
