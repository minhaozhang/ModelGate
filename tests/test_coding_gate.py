import contextlib
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import Request
from fastapi.responses import Response

import app.core.config as config
from app.services import provider as provider_service
from app.services.coding_gate import evaluate_coding_gate
from app.services.proxy import proxy_request


def _route(model_name: str) -> "provider_service.RouteResult":
    return provider_service.RouteResult(
        provider_config={
            "id": 1,
            "name": "primary",
            "protocol": "openai",
            "base_url": "https://primary.example/v1",
            "api_keys": [{"id": 11, "api_key": "sk-a", "max_concurrent": 3}],
            "models": [{"id": 91, "model_id": 101, "model_name": model_name}],
        },
        provider_name="primary",
        provider_id=1,
        provider_model_id=91,
        model_id=101,
        requested_model=model_name,
        model_name=model_name,
        upstream_model_name=model_name,
        is_forced_provider=False,
    )


def _build_request(model_name: str, messages: list, user_agent: str | None = None) -> Request:
    headers = []
    if user_agent is not None:
        headers.append((b"user-agent", user_agent.encode()))
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/chat/completions",
            "headers": headers,
            "query_string": b"",
            "cookies": {},
            "root_url": "",
            "root_path": "",
        }
    )
    request._body = json.dumps({"model": model_name, "messages": messages}).encode()
    return request


class CodingGateUnitTests(unittest.TestCase):
    def setUp(self):
        config.system_settings.pop("coding_gate.min_context_tokens", None)

    def tearDown(self):
        config.system_settings.pop("coding_gate.min_context_tokens", None)

    def _eval(self, *, messages=None, ctx=100, ua="", protocol="openai"):
        return evaluate_coding_gate(
            messages=messages or [],
            context_tokens=ctx,
            user_agent=ua,
            inbound_protocol=protocol,
        )

    def test_codex_endpoint_protocol_passes(self):
        allowed, reason, _ = self._eval(protocol="responses", ua="python-requests/2.31")
        self.assertTrue(allowed)
        self.assertEqual(reason, "coding_endpoint")

    def test_anthropic_endpoint_protocol_passes(self):
        allowed, reason, _ = self._eval(protocol="anthropic", ua="python-requests/2.31")
        self.assertTrue(allowed)
        self.assertEqual(reason, "coding_endpoint")

    def test_coding_tool_user_agents_pass(self):
        for ua in (
            "claude-cli/1.0.34 (external, cli)",
            "codex_cli_rs/0.9.3",
            "opencode/local ai-sdk/provider-utils/4.0.23 runtime/node.js/24",
            "OpenCode/1.2.3",
            "Cursor/0.42",
        ):
            allowed, reason, _ = self._eval(ua=ua)
            self.assertTrue(allowed, ua)
            self.assertEqual(reason, "coding_tool_ua")

    def test_coding_system_prompt_passes(self):
        messages = [
            {"role": "system", "content": "You are Claude Code, Anthropic's official CLI for Claude."},
            {"role": "user", "content": "fix the failing test"},
        ]
        allowed, reason, detail = self._eval(messages=messages, ua="SomeUnknown/1.0", ctx=500)
        self.assertTrue(allowed)
        self.assertEqual(reason, "coding_system_prompt")
        self.assertEqual(detail, "you are claude code")

    def test_bot_system_prompt_rejected_even_with_big_context(self):
        messages = [
            {"role": "system", "content": "你是一个企业知识库助手，请根据检索到的资料回答用户问题。"},
            {"role": "user", "content": "x" * 40000},
        ]
        allowed, reason, _ = self._eval(messages=messages, ua="OpenAI/Python 1.30.1", ctx=20000)
        self.assertFalse(allowed)
        self.assertEqual(reason, "bot_system_prompt")

    def test_llm_judge_eval_prompt_rejected(self):
        # Real-world eval-pipeline prompt (user-reported example).
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a strict path entailment judge. Return only one "
                    "valid JSON object with a numeric score in [0, 1], exactly "
                    "in the format specified below."
                ),
            },
            {"role": "user", "content": "premise: ...\nhypothesis: ..."},
        ]
        # Blocked via system markers even from a non-SDK client...
        allowed, reason, _ = self._eval(messages=messages, ua="curl/8.5.0", ctx=12000)
        self.assertFalse(allowed)
        self.assertEqual(reason, "bot_system_prompt")
        # ...and of course from the usual python SDK client.
        allowed, reason, _ = self._eval(messages=messages, ua="Python-urllib/3.10", ctx=800)
        self.assertFalse(allowed)

    def test_judge_prompt_in_first_user_message_rejected(self):
        # Eval pipelines often ship the whole judge instruction as a single
        # user message with no system role — must still be caught even with
        # an unknown UA and a padded (>10k) context.
        judge_text = (
            "You are a strict path entailment judge. Return only one valid "
            "JSON object with a numeric score in [0, 1], exactly in the form "
            '{"score": <number>}. Judge whether the KG path supports filling '
            "the masked answer. Original question: what was sir isaac "
            "newton's inventions?"
        )
        messages = [
            {"role": "user", "content": judge_text + " padding " * 3000},
        ]
        allowed, reason, _ = self._eval(messages=messages, ua="MyAgent/0.1", ctx=15000)
        self.assertFalse(allowed)
        self.assertEqual(reason, "bot_system_prompt")

        # Small-context variant (<1k, the typical case) via curl.
        messages = [{"role": "user", "content": judge_text}]
        allowed, reason, _ = self._eval(messages=messages, ua="curl/8.5.0", ctx=900)
        self.assertFalse(allowed)

    def test_real_production_judge_split_system_user_rejected(self):
        # Exact production sample (user-reported): judge instruction as the
        # system message, KG task as the user message.
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a strict path entailment judge. Return only one "
                    "valid JSON object with a numeric score in [0, 1], exactly "
                    'in the form {"score": <number>}. Do not output analysis, '
                    "reasoning, explanations, Markdown, code fences, or any "
                    "text before or after the JSON object."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Judge whether the KG path supports filling the masked "
                    "answer.\n"
                    "Original question: what was sir isaac newton's "
                    "inventions?\n"
                    "Masked question: what was sir isaac newton's "
                    "inventions?\n"
                    "Candidate answer: m.01nhc9\n"
                    "Relation path: people.person.profession\n"
                    "Entity path: m.03s9v -> m.0h9c\n"
                    "Score 1.0 means the path strongly entails the answer; "
                    "0.5 means partially plausible; 0.0 means unsupported or "
                    "unrelated.\n"
                    'Hard output requirement: return exactly {"score": '
                    "<number>}. Output only this JSON object. Do not reveal "
                    "or include any thinking, reasoning process, "
                    "explanation, Markdown, or additional text."
                ),
            },
        ]
        # Unknown UA so only the prompt layer can catch it.
        allowed, reason, detail = self._eval(messages=messages, ua="MyEval/1.0", ctx=600)
        self.assertFalse(allowed)
        self.assertEqual(reason, "bot_system_prompt")
        self.assertEqual(detail, "entailment")
        # Standard python pipeline client.
        allowed, _, _ = self._eval(messages=messages, ua="Python-urllib/3.10", ctx=600)
        self.assertFalse(allowed)

    def test_coding_marker_not_scanned_from_user_message(self):
        # A bot whose user message merely QUOTES coding vocabulary must not
        # pass: allow-markers only scan system roles.
        messages = [
            {"role": "system", "content": "你是企业知识库助手"},
            {"role": "user", "content": "用户问：如何配置 coding agent 的系统提示词？"},
        ]
        allowed, reason, _ = self._eval(messages=messages, ua="MyAgent/0.1", ctx=20000)
        self.assertFalse(allowed)
        self.assertEqual(reason, "bot_system_prompt")

    def test_coding_system_marker_beats_judge_wording(self):
        # A coding agent whose prompt happens to mention scoring still passes.
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a coding agent. Grade (打分) the patch you just "
                    "wrote before committing."
                ),
            },
        ]
        allowed, reason, _ = self._eval(messages=messages, ua="python-httpx/0.27", ctx=100)
        self.assertTrue(allowed)
        self.assertEqual(reason, "coding_system_prompt")

    def test_generic_sdk_ua_rejected(self):
        # Calibrated against real production traffic (2026-10-06).
        for ua in (
            "Python-urllib/3.10",
            "python-requests/2.31.0",
            "python-httpx/0.27.0",
            "OpenAI/Python 2.24.0",
            "OpenAI/JS 6.39.1",
            "Go-http-client/2.0",
            "Java/21.0.9",
            "axios/1.6.0",
            "langchain/0.2",
        ):
            allowed, reason, _ = self._eval(ua=ua, ctx=20000)
            self.assertFalse(allowed, ua)
            self.assertEqual(reason, "generic_client_ua", ua)

    def test_production_coding_tool_uas_pass(self):
        # Real production samples of allowed coding tools.
        for ua in (
            "deepseek-harness/0.2.0-rc.2 (+https://github.com/deepseek-ai/deepseek-harness)",
            "opencode/1.18.34 ai-sdk/provider-utils/4.0.23 runtime/node.js/24",
            "opencode/latest/2.0.23/desktop",
            "opencode/1.14.20 ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.11",
        ):
            allowed, reason, _ = self._eval(ua=ua)
            self.assertTrue(allowed, ua)
            self.assertEqual(reason, "coding_tool_ua", ua)

    def test_internal_health_check_purpose_exempt(self):
        from app.services.coding_gate import evaluate_internal_coding_gate

        message = evaluate_internal_coding_gate(
            model="glm-coding",
            purpose="glm-health-check",
            messages=[{"role": "user", "content": "ping"}],
            context_tokens=5,
            user_agent="modelgate/internal-analysis:glm-health-check",
        )
        self.assertIsNone(message)

    def test_internal_chatbot_purpose_blocked(self):
        from app.services.coding_gate import evaluate_internal_coding_gate

        message = evaluate_internal_coding_gate(
            model="glm-coding",
            purpose="report-analysis",
            messages=[
                {"role": "system", "content": "你是企业知识库助手"},
                {"role": "user", "content": "总结一下"},
            ],
            context_tokens=100,
            user_agent="modelgate/internal-analysis:report-analysis",
        )
        self.assertIsNotNone(message)
        self.assertIn("仅面向编程", message)

    def test_small_context_unknown_ua_rejected(self):
        allowed, reason, _ = self._eval(ua="MyMagicClient/1.0", ctx=1500)
        self.assertFalse(allowed)
        self.assertEqual(reason, "below_min_context")

    def test_large_context_unknown_ua_passes_leniently(self):
        allowed, reason, _ = self._eval(ua="MyMagicClient/1.0", ctx=20000)
        self.assertTrue(allowed)
        self.assertEqual(reason, "unclassified_large_context")

    def test_coding_system_prompt_beats_generic_sdk_ua(self):
        messages = [
            {"role": "system", "content": "You are a coding agent embedded in the user's terminal."},
        ]
        allowed, reason, _ = self._eval(messages=messages, ua="python-httpx/0.27", ctx=100)
        self.assertTrue(allowed)
        self.assertEqual(reason, "coding_system_prompt")

    def test_min_context_tokens_setting_override(self):
        config.system_settings["coding_gate.min_context_tokens"] = "50"
        allowed, reason, _ = self._eval(ua="MyMagicClient/1.0", ctx=60)
        self.assertTrue(allowed)
        config.system_settings["coding_gate.min_context_tokens"] = "bogus"
        allowed, reason, _ = self._eval(ua="MyMagicClient/1.0", ctx=60)
        self.assertFalse(allowed)
        self.assertEqual(reason, "below_min_context")


class CodingGateEndToEndTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        config.api_keys_cache.clear()
        from app.core.config import (
            user_api_key_semaphores,
            user_model_semaphores,
            provider_key_semaphores,
            standard_model_semaphores,
        )

        user_api_key_semaphores.clear()
        user_model_semaphores.clear()
        provider_key_semaphores.clear()
        standard_model_semaphores.clear()
        provider_service._model_coding_only_by_name.clear()

    def tearDown(self):
        config.api_keys_cache.clear()
        from app.core.config import (
            user_api_key_semaphores,
            user_model_semaphores,
            provider_key_semaphores,
            standard_model_semaphores,
        )

        user_api_key_semaphores.clear()
        user_model_semaphores.clear()
        provider_key_semaphores.clear()
        standard_model_semaphores.clear()
        provider_service._model_coding_only_by_name.clear()

    def _patch_common(self, stack: contextlib.ExitStack, route):
        stack.enter_context(
            patch(
                "app.services.proxy.validate_api_key",
                new=AsyncMock(return_value=(1, None)),
            )
        )
        stack.enter_context(
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=[route]),
            )
        )
        stack.enter_context(patch("app.services.proxy.create_request_log", new=AsyncMock()))
        stack.enter_context(patch("app.services.proxy.update_stats", new=Mock()))
        stack.enter_context(
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None)
        )

    def _setup_key_cache(self):
        config.api_keys_cache["test-key"] = {
            "id": 1,
            "bypass_busyness": False,
            "max_concurrent": None,
            "allowed_provider_model_ids": list(range(1, 1000)),
            "allowed_model_ids": list(range(1, 1000)),
        }

    async def test_bot_traffic_rejected_with_403(self):
        provider_service._model_coding_only_by_name["gate-model"] = True
        self._setup_key_cache()
        route = _route("gate-model")
        request = _build_request(
            "gate-model",
            messages=[
                {"role": "system", "content": "你是公司的智能客服机器人，请礼貌回答客户咨询。"},
                {"role": "user", "content": "你们的工作时间是什么？"},
            ],
            user_agent="python-requests/2.31.0",
        )
        runtime_normal = AsyncMock(return_value=Response(status_code=200))

        with contextlib.ExitStack() as stack:
            self._patch_common(stack, route)
            stack.enter_context(
                patch("app.services.proxy.runtime_handle_normal", new=runtime_normal)
            )
            response = await proxy_request(request, "/chat/completions")

        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.body)
        self.assertEqual(payload["error"]["code"], "model_coding_only")
        runtime_normal.assert_not_awaited()

    async def test_coding_tool_traffic_passes(self):
        provider_service._model_coding_only_by_name["gate-model"] = True
        self._setup_key_cache()
        route = _route("gate-model")
        request = _build_request(
            "gate-model",
            messages=[
                {"role": "system", "content": "You are a coding agent working in a repository."},
                {"role": "user", "content": "fix the failing test"},
            ],
            user_agent="codex_cli_rs/0.9.3",
        )
        runtime_normal = AsyncMock(return_value=Response(status_code=200))

        with contextlib.ExitStack() as stack:
            self._patch_common(stack, route)
            stack.enter_context(
                patch("app.services.proxy.runtime_handle_normal", new=runtime_normal)
            )
            response = await proxy_request(request, "/chat/completions")

        self.assertEqual(response.status_code, 200)
        runtime_normal.assert_awaited_once()

    async def test_unflagged_model_not_gated(self):
        self._setup_key_cache()
        route = _route("free-model")
        request = _build_request(
            "free-model",
            messages=[
                {"role": "system", "content": "你是公司的智能客服机器人，请礼貌回答客户咨询。"},
            ],
            user_agent="python-requests/2.31.0",
        )
        runtime_normal = AsyncMock(return_value=Response(status_code=200))

        with contextlib.ExitStack() as stack:
            self._patch_common(stack, route)
            stack.enter_context(
                patch("app.services.proxy.runtime_handle_normal", new=runtime_normal)
            )
            response = await proxy_request(request, "/chat/completions")

        self.assertEqual(response.status_code, 200)
        runtime_normal.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
