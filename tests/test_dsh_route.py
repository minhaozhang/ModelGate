import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import dsh


class DshPatchYmlTests(unittest.TestCase):
    CTX = {
        "base_url": "https://gw.example/modelgate/v1",
        "models": ["glm-5", "glm-5-air"],
        "display_names": {},
        "default_model": "glm-5",
        "api_key": "sk-test",
    }

    def test_patch_yml_shape(self):
        yml = dsh.build_dsh_patch_yml(self.CTX)
        self.assertIn("- name: '@deepseek-ai/dsh-llm-pi-ai'", yml)
        self.assertIn("modelgate:", yml)
        self.assertIn("apiKeyEnv: MODELGATE_API_KEY", yml)
        self.assertIn("api: openai-completions", yml)
        self.assertIn('baseURL: "https://gw.example/modelgate/v1"', yml)
        self.assertIn("supportsDeveloperRole: false", yml)
        self.assertIn("maxTokensField: max_tokens", yml)
        self.assertIn("- id: glm-5", yml)
        self.assertIn("- id: glm-5-air", yml)
        # The API key itself never enters the YAML.
        self.assertNotIn("sk-test", yml)

    def test_patch_yml_empty_models_placeholder(self):
        yml = dsh.build_dsh_patch_yml({**self.CTX, "models": []})
        self.assertIn("- id: model-not-found", yml)

    def test_setup_markdown_mentions_both_options(self):
        ctx = dict(self.CTX)
        md = dsh.build_dsh_setup_markdown(ctx, "sk-test")
        self.assertIn("Custom model API", md)
        self.assertIn("Fetch available models", md)
        self.assertIn("cordis.patch.yml", md)
        self.assertIn("MODELGATE_API_KEY", md)
        self.assertIn("- `glm-5`", md)


class DshEndpointTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(dsh.router)
        self.client = TestClient(app)

    def _fake_ctx(self):
        ctx = {
            "base_url": "http://testserver/v1",
            "models": ["glm-5"],
            "display_names": {},
            "default_model": "glm-5",
            "api_key": "sk-test",
        }

        async def fake_ctx(request, api_key=None, api_key_id=None):
            return ctx

        return fake_ctx

    def test_config_requires_key(self):
        resp = self.client.get("/dsh/config")
        self.assertEqual(resp.status_code, 400)

    def test_patch_yml_requires_key(self):
        resp = self.client.get("/dsh/cordis.patch.yml")
        self.assertEqual(resp.status_code, 400)

    def test_setup_md_requires_key(self):
        resp = self.client.get("/dsh/setup.md")
        self.assertEqual(resp.status_code, 400)

    def test_patch_yml_endpoint(self):
        from unittest.mock import patch

        with patch.object(dsh, "build_codex_context", self._fake_ctx()):
            resp = self.client.get("/dsh/cordis.patch.yml?api_key=sk-test")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("dsh-llm-pi-ai", resp.text)
        self.assertIn("http://testserver/v1", resp.text)


if __name__ == "__main__":
    unittest.main()
