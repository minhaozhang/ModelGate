import json
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import pi


class PiModelsJsonTests(unittest.TestCase):
    def test_build_pi_models_json(self):
        ctx = {
            "base_url": "https://gw.example/modelgate/v1",
            "models": ["glm-5", "glm-5-air"],
        }
        parsed = pi.build_pi_models_json(ctx, "sk-test")
        provider = parsed["providers"]["modelgate"]
        self.assertEqual(provider["baseUrl"], "https://gw.example/modelgate/v1")
        self.assertEqual(provider["api"], "openai-completions")
        self.assertEqual(provider["apiKey"], "sk-test")
        self.assertEqual([m["id"] for m in provider["models"]], ["glm-5", "glm-5-air"])

    def test_merge_into_empty(self):
        ctx = {
            "base_url": "https://gw.example/v1",
            "models": ["glm-5"],
        }
        merged = pi.merge_pi_models_json("", ctx, "sk-test")
        parsed = json.loads(merged)
        self.assertEqual(parsed["providers"]["modelgate"]["apiKey"], "sk-test")

    def test_merge_preserves_foreign_providers_and_top_level_keys(self):
        existing = json.dumps(
            {
                "providers": {
                    "other": {
                        "baseUrl": "http://x/v1",
                        "api": "openai-completions",
                        "apiKey": "k",
                        "models": [{"id": "m"}],
                    },
                    "modelgate": {"baseUrl": "http://old", "apiKey": "old"},
                },
                "otherTopLevel": 1,
            }
        )
        ctx = {
            "base_url": "https://gw.example/v1",
            "models": ["glm-5"],
        }
        merged = pi.merge_pi_models_json(existing, ctx, "sk-test")
        parsed = json.loads(merged)
        self.assertEqual(parsed["otherTopLevel"], 1)
        self.assertEqual(parsed["providers"]["other"]["apiKey"], "k")
        self.assertEqual(parsed["providers"]["other"]["models"], [{"id": "m"}])
        self.assertEqual(parsed["providers"]["modelgate"]["baseUrl"], "https://gw.example/v1")
        self.assertEqual(parsed["providers"]["modelgate"]["apiKey"], "sk-test")

    def test_merge_invalid_json_raises_value_error(self):
        ctx = {"base_url": "https://gw.example/v1", "models": ["glm-5"]}
        with self.assertRaises(ValueError):
            pi.merge_pi_models_json("not json", ctx, "sk-test")


class PiEndpointTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(pi.router)
        self.client = TestClient(app)

    def _fake_ctx(self):
        ctx = {
            "base_url": "http://testserver/v1",
            "models": ["glm-5", "glm-5-air"],
            "display_names": {"glm-5": "GLM-5"},
            "default_model": "glm-5",
            "api_key": "sk-test",
        }

        async def fake_ctx(request, api_key=None, api_key_id=None):
            return ctx

        return fake_ctx

    def test_config_requires_key(self):
        resp = self.client.get("/pi/config")
        self.assertEqual(resp.status_code, 400)

    def test_models_json_requires_key(self):
        resp = self.client.get("/pi/models.json")
        self.assertEqual(resp.status_code, 400)

    def test_setup_md_requires_key(self):
        resp = self.client.get("/pi/setup.md")
        self.assertEqual(resp.status_code, 400)

    def test_setup_file_requires_key(self):
        resp = self.client.post("/pi/setup-file")
        self.assertEqual(resp.status_code, 400)

    def test_scripts_render_without_key(self):
        resp = self.client.get("/pi/setup.ps1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("/pi/setup-file", resp.text)
        resp = self.client.get("/pi/setup.sh")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("pi/setup-file", resp.text)
        self.assertIn("MODELGATE_API_KEY", resp.text)

    def test_setup_file_merges_and_returns_models_header(self):
        from unittest.mock import patch

        existing = json.dumps(
            {
                "providers": {
                    "other": {"baseUrl": "http://x/v1", "apiKey": "k", "models": []}
                }
            }
        )
        with patch.object(pi, "build_codex_context", self._fake_ctx()):
            resp = self.client.post(
                "/pi/setup-file?api_key=sk-test", content=existing.encode()
            )
        self.assertEqual(resp.status_code, 200)
        parsed = json.loads(resp.text)
        provider = parsed["providers"]["modelgate"]
        self.assertEqual(provider["api"], "openai-completions")
        self.assertEqual(provider["apiKey"], "sk-test")
        self.assertEqual([m["id"] for m in provider["models"]], ["glm-5", "glm-5-air"])
        self.assertEqual(parsed["providers"]["other"]["apiKey"], "k")
        self.assertIn("glm-5", resp.headers["X-Models"])

    def test_setup_file_invalid_json_422(self):
        from unittest.mock import patch

        with patch.object(pi, "build_codex_context", self._fake_ctx()):
            resp = self.client.post(
                "/pi/setup-file?api_key=sk-test", content=b"not json"
            )
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
