"""Tests for outbound provider adapters' error translation.

Focus: context-overflow signature preservation so downstream agents
(Codex via /v1/responses, Claude Code via /v1/messages, opencode via
/v1/chat/completions) can still trigger auto-compaction after protocol
conversion.
"""
import unittest

from app.services.proxy_runtime.adapters.anthropic import AnthropicAdapter
from app.services.proxy_runtime.adapters.openai import OpenAIAdapter


class AnthropicAdapterErrorTests(unittest.TestCase):
    def setUp(self):
        self.adapter = AnthropicAdapter()

    def test_overflow_prompt_too_long_gets_context_code(self):
        raw = {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "prompt is too long: 200000 tokens > 128000 maximum",
            },
        }
        out = self.adapter.transform_error_response(raw, 400)
        self.assertEqual(out["error"]["code"], "context_length_exceeded")
        self.assertEqual(out["error"]["type"], "invalid_request_error")
        self.assertIn("prompt is too long", out["error"]["message"])

    def test_overflow_context_limit_wording_gets_context_code(self):
        raw = {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "input length and `max_tokens` exceed context limit: 250000 tokens + 32000 tokens > 256000 maximum tokens",
            },
        }
        out = self.adapter.transform_error_response(raw, 400)
        self.assertEqual(out["error"]["code"], "context_length_exceeded")

    def test_non_overflow_400_keeps_status_code(self):
        raw = {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "tools: Field required",
            },
        }
        out = self.adapter.transform_error_response(raw, 400)
        self.assertEqual(out["error"]["code"], "400")

    def test_non_400_overflow_wording_keeps_status_code(self):
        raw = {
            "type": "error",
            "error": {
                "type": "api_error",
                "message": "internal error mentioning context length",
            },
        }
        out = self.adapter.transform_error_response(raw, 500)
        self.assertEqual(out["error"]["code"], "500")

    def test_non_dict_error_keeps_status_code(self):
        out = self.adapter.transform_error_response({"unexpected": "shape"}, 502)
        self.assertEqual(out["error"]["code"], "502")
        self.assertEqual(out["error"]["type"], "api_error")


class OpenAIAdapterErrorTests(unittest.TestCase):
    def test_error_passthrough_preserves_code(self):
        raw = {
            "error": {
                "message": "This model's maximum context length is 128000 tokens.",
                "type": "invalid_request_error",
                "code": "context_length_exceeded",
            }
        }
        out = OpenAIAdapter().transform_error_response(raw, 400)
        self.assertEqual(out, raw)


if __name__ == "__main__":
    unittest.main()
