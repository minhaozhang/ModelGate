import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import Request

from core.config import provider_key_model_semaphores, provider_key_semaphores
from services import provider as provider_service
from services.proxy import (
    _get_or_create_provider_key_model_semaphore,
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

    def test_provider_key_model_limit_is_isolated_per_model(self):
        sem_key_a, semaphore_a = _get_or_create_provider_key_model_semaphore(
            provider_key_id=11,
            provider_model_key="openai/gpt-4o",
            target_limit=1,
        )
        sem_key_b, semaphore_b = _get_or_create_provider_key_model_semaphore(
            provider_key_id=11,
            provider_model_key="openai/gpt-4.1",
            target_limit=1,
        )

        self.assertEqual(sem_key_a, "11:openai/gpt-4o")
        self.assertEqual(sem_key_b, "11:openai/gpt-4.1")
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
