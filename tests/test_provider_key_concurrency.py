import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import Request

from core.config import provider_key_model_semaphores, provider_key_semaphores
from services import provider as provider_service
from services import proxy as proxy_module
from services.proxy_runtime import internal as internal_runtime
from services.proxy import (
    _get_or_create_user_provider_model_semaphore,
    _get_or_create_provider_key_semaphore,
    _get_provider_key_limit,
    proxy_request,
)


class ProviderKeyConcurrencyTests(unittest.TestCase):
    def setUp(self):
        provider_key_semaphores.clear()
        provider_key_model_semaphores.clear()

    def tearDown(self):
        provider_key_semaphores.clear()
        provider_key_model_semaphores.clear()
        provider_service._key_sticky_map.clear()

    def test_provider_key_limit_is_shared_across_models(self):
        sem_key_a, semaphore_a = _get_or_create_provider_key_semaphore(
            provider_key_id=11,
            provider_name="openai",
            target_limit=2,
        )
        sem_key_b, semaphore_b = _get_or_create_provider_key_semaphore(
            provider_key_id=11,
            provider_name="openai",
            target_limit=2,
        )

        self.assertEqual(sem_key_a, "11:openai")
        self.assertEqual(sem_key_b, "11:openai")
        self.assertIs(semaphore_a, semaphore_b)

        self.assertTrue(asyncio.run(asyncio.wait_for(semaphore_a.acquire(), timeout=0.1)))
        self.assertTrue(asyncio.run(asyncio.wait_for(semaphore_b.acquire(), timeout=0.1)))
        with self.assertRaises(asyncio.TimeoutError):
            asyncio.run(asyncio.wait_for(semaphore_a.acquire(), timeout=0.01))

        semaphore_a.release()
        semaphore_a.release()

    def test_user_provider_model_limit_is_isolated_per_model(self):
        sem_key_a, semaphore_a = _get_or_create_user_provider_model_semaphore(
            api_key_id=1,
            provider_key_id=11,
            provider_model_key="openai/gpt-4o",
            target_limit=1,
        )
        sem_key_b, semaphore_b = _get_or_create_user_provider_model_semaphore(
            api_key_id=1,
            provider_key_id=11,
            provider_model_key="openai/gpt-4.1",
            target_limit=1,
        )

        self.assertEqual(sem_key_a, "user:1:pk:11:model:openai/gpt-4o")
        self.assertEqual(sem_key_b, "user:1:pk:11:model:openai/gpt-4.1")
        self.assertIsNot(semaphore_a, semaphore_b)

        self.assertTrue(asyncio.run(asyncio.wait_for(semaphore_a.acquire(), timeout=0.1)))
        self.assertTrue(asyncio.run(asyncio.wait_for(semaphore_b.acquire(), timeout=0.1)))
        with self.assertRaises(asyncio.TimeoutError):
            asyncio.run(asyncio.wait_for(semaphore_a.acquire(), timeout=0.01))
        with self.assertRaises(asyncio.TimeoutError):
            asyncio.run(asyncio.wait_for(semaphore_b.acquire(), timeout=0.01))

        semaphore_a.release()
        semaphore_b.release()

    def test_provider_key_limit_prefers_key_override(self):
        provider_config = {
            "api_keys": [
                {"id": 11, "api_key": "sk-a", "max_concurrent": 2},
                {"id": 12, "api_key": "sk-b"},
            ],
        }

        self.assertEqual(_get_provider_key_limit(provider_config, 11), 2)
        self.assertEqual(_get_provider_key_limit(provider_config, 12), 3)
        self.assertEqual(_get_provider_key_limit(provider_config, 99), 3)

    def test_admin_config_template_exposes_provider_key_concurrency_input(self):
        template_source = Path("templates/admin/config.html").read_text(encoding="utf-8")

        self.assertIn("new-provider-key-max-concurrent", template_source)
        self.assertIn("k.max_concurrent", template_source)

    def test_disable_provider_key_clears_sticky_key_cache(self):
        provider_service._key_sticky_map[(123, "zhipu")] = (88, 1.0)
        provider_service._key_sticky_map[(123, "openai")] = (99, 1.0)

        asyncio.run(
            provider_service.invalidate_provider_key_sticky_cache(
                provider_name="zhipu",
                provider_key_id=88,
            )
        )

        self.assertNotIn((123, "zhipu"), provider_service._key_sticky_map)
        self.assertIn((123, "openai"), provider_service._key_sticky_map)


class ProxyRuntimeWrapperTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_normal_wrapper_forwards_renamed_semaphores(self):
        provider_key_semaphore = object()
        user_provider_model_semaphore = object()
        response = object()
        runtime_handle = AsyncMock(return_value=response)

        with patch("services.proxy.runtime_handle_normal", new=runtime_handle):
            result = await proxy_module.handle_normal(
                None,
                "https://example.com",
                {},
                b"{}",
                "openai",
                "gpt-test",
                [],
                0,
                {},
                1,
                "127.0.0.1",
                "test",
                0,
                provider_key_semaphore,
                user_provider_model_semaphore,
                "req-1",
            )

        self.assertIs(result, response)
        kwargs = runtime_handle.await_args.kwargs
        self.assertIs(kwargs["provider_key_semaphore"], provider_key_semaphore)
        self.assertIs(
            kwargs["user_provider_model_semaphore"], user_provider_model_semaphore
        )
        self.assertNotIn("semaphore", kwargs)
        self.assertNotIn("api_key_model_semaphore", kwargs)

    async def test_handle_streaming_wrapper_forwards_renamed_semaphores(self):
        provider_key_semaphore = object()
        user_provider_model_semaphore = object()
        response = object()
        runtime_handle = AsyncMock(return_value=response)

        with patch("services.proxy.runtime_handle_streaming", new=runtime_handle):
            result = await proxy_module.handle_streaming(
                "https://example.com",
                {},
                b"{}",
                "openai",
                "gpt-test",
                [],
                0,
                {},
                1,
                "127.0.0.1",
                "test",
                0,
                provider_key_semaphore,
                user_provider_model_semaphore,
                "req-1",
                None,
                None,
            )

        self.assertIs(result, response)
        kwargs = runtime_handle.await_args.kwargs
        self.assertIs(kwargs["provider_key_semaphore"], provider_key_semaphore)
        self.assertIs(
            kwargs["user_provider_model_semaphore"], user_provider_model_semaphore
        )
        self.assertNotIn("semaphore", kwargs)
        self.assertNotIn("api_key_model_semaphore", kwargs)


class InternalProxyConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        provider_key_semaphores.clear()
        provider_key_model_semaphores.clear()

    def tearDown(self):
        provider_key_semaphores.clear()
        provider_key_model_semaphores.clear()

    async def test_internal_user_provider_model_limit_returns_429(self):
        provider_config = {
            "base_url": "https://example.com",
            "protocol": "openai",
            "api_keys": [{"id": 11, "api_key": "sk-test", "max_concurrent": 3}],
            "models": [{"model_name": "gpt-test", "actual_model_name": "gpt-test"}],
        }
        wait_timeouts = []

        async def fake_wait_for(awaitable, timeout):
            awaitable.close()
            wait_timeouts.append(timeout)
            if len(wait_timeouts) == 1:
                return True
            raise asyncio.TimeoutError

        with (
            patch(
                "services.proxy_runtime.internal.ensure_internal_api_key_exists",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "services.proxy_runtime.internal.get_provider_and_model",
                new=AsyncMock(return_value=(provider_config, "gpt-test", "openai")),
            ),
            patch(
                "services.proxy_runtime.internal.pick_api_key",
                return_value=("sk-test", 11),
            ),
            patch("services.proxy_runtime.internal.asyncio.wait_for", new=fake_wait_for),
            patch("services.proxy_runtime.internal.create_request_log", new=AsyncMock(return_value=1)),
            patch("services.proxy_runtime.internal.update_stats", new=Mock()),
            patch("services.proxy_runtime.internal.logger.warning", new=Mock()),
        ):
            result = await internal_runtime.call_internal_model_via_proxy(
                requested_model="openai/gpt-test",
                body_json={"model": "openai/gpt-test", "messages": []},
                api_key_id=1,
                purpose="review",
                client_ip="127.0.0.1",
                user_agent="test",
            )

        self.assertEqual(result["status_code"], 429)
        self.assertIn("already reached max concurrency", result["error"])
        self.assertEqual(len(wait_timeouts), 2)


class ProviderKeyErrorMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_provider_key_error_is_human_readable(self):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/v1/chat/completions",
                "headers": [],
                "query_string": b"",
                "cookies": {},
                "root_path": "",
            }
        )
        request._body = b'{"model":"zhipu/glm-4.5","messages":[]}'

        with (
            patch("services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))),
            patch(
                "services.proxy.get_provider_and_model",
                new=AsyncMock(
                    return_value=(
                        {"base_url": "https://example.com", "api_keys": []},
                        "glm-4.5",
                        "zhipu",
                    )
                ),
            ),
            patch("services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        self.assertEqual(response.status_code, 400)
        body = response.body.decode("utf-8")
        self.assertIn("供应商 'zhipu' 无可用的 API Key", body)
