import json
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import claude


class ClaudeSettingsTests(unittest.TestCase):
    CTX = {
        "base_url": "https://gw.example/modelgate/v1",
        "models": ["glm-5", "glm-5-air"],
        "display_names": {},
        "default_model": "glm-5",
        "api_key": "sk-test",
    }

    def test_env_block_strips_v1_suffix(self):
        env = claude._claude_env_block(self.CTX, "sk-test")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://gw.example/modelgate")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "sk-test")
        self.assertEqual(env["ANTHROPIC_MODEL"], "glm-5")

    def test_build_claude_settings(self):
        parsed = claude.build_claude_settings(self.CTX, "sk-test")
        self.assertEqual(list(parsed.keys()), ["env"])
        self.assertEqual(parsed["env"]["ANTHROPIC_AUTH_TOKEN"], "sk-test")

    def test_merge_preserves_foreign_keys_and_env_vars(self):
        existing = json.dumps(
            {
                "permissions": {"allow": ["Bash(npm test)"]},
                "env": {"ANTHROPIC_API_KEY": "old", "CUSTOM_VAR": "keepme"},
                "model": "sonnet",
            }
        )
        merged = json.loads(claude.merge_claude_settings(existing, self.CTX, "sk-test"))
        self.assertEqual(merged["permissions"]["allow"], ["Bash(npm test)"])
        self.assertEqual(merged["model"], "sonnet")
        self.assertEqual(merged["env"]["ANTHROPIC_API_KEY"], "old")
        self.assertEqual(merged["env"]["CUSTOM_VAR"], "keepme")
        self.assertEqual(merged["env"]["ANTHROPIC_BASE_URL"], "https://gw.example/modelgate")
        self.assertEqual(merged["env"]["ANTHROPIC_AUTH_TOKEN"], "sk-test")
        self.assertEqual(merged["env"]["ANTHROPIC_MODEL"], "glm-5")

    def test_merge_into_empty(self):
        merged = json.loads(claude.merge_claude_settings("", self.CTX, "sk-test"))
        self.assertEqual(merged["env"]["ANTHROPIC_AUTH_TOKEN"], "sk-test")

    def test_merge_invalid_json_raises_value_error(self):
        with self.assertRaises(ValueError):
            claude.merge_claude_settings("not json", self.CTX, "sk-test")

    def test_merge_non_object_root_raises_value_error(self):
        with self.assertRaises(ValueError):
            claude.merge_claude_settings("[1,2]", self.CTX, "sk-test")


class ClaudeEndpointTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(claude.router)
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
        resp = self.client.get("/claude/config")
        self.assertEqual(resp.status_code, 400)

    def test_settings_json_requires_key(self):
        resp = self.client.get("/claude/settings.json")
        self.assertEqual(resp.status_code, 400)

    def test_setup_md_requires_key(self):
        resp = self.client.get("/claude/setup.md")
        self.assertEqual(resp.status_code, 400)

    def test_setup_file_requires_key(self):
        resp = self.client.post("/claude/setup-file")
        self.assertEqual(resp.status_code, 400)

    def test_scripts_render_without_key(self):
        resp = self.client.get("/claude/setup.ps1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("/claude/setup-file", resp.text)
        resp = self.client.get("/claude/setup.sh")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("claude/setup-file", resp.text)
        self.assertIn("MODELGATE_API_KEY", resp.text)

    def test_setup_file_merges_and_returns_models_header(self):
        from unittest.mock import patch

        existing = json.dumps({"permissions": {"allow": []}, "env": {"X": "y"}})
        with patch.object(claude, "build_codex_context", self._fake_ctx()):
            resp = self.client.post(
                "/claude/setup-file?api_key=sk-test", content=existing.encode()
            )
        self.assertEqual(resp.status_code, 200)
        parsed = json.loads(resp.text)
        self.assertEqual(parsed["permissions"], {"allow": []})
        self.assertEqual(parsed["env"]["X"], "y")
        self.assertEqual(parsed["env"]["ANTHROPIC_BASE_URL"], "http://testserver")
        self.assertEqual(parsed["env"]["ANTHROPIC_AUTH_TOKEN"], "sk-test")
        self.assertEqual(parsed["env"]["ANTHROPIC_MODEL"], "glm-5")
        self.assertIn("glm-5", resp.headers["X-Models"])

    def test_setup_file_invalid_json_422(self):
        from unittest.mock import patch

        with patch.object(claude, "build_codex_context", self._fake_ctx()):
            resp = self.client.post(
                "/claude/setup-file?api_key=sk-test", content=b"not json"
            )
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
