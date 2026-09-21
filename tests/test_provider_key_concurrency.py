import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import Request
from fastapi.responses import Response

import app.core.config as config
from app.core.config import (
    provider_key_model_semaphores,
    provider_key_semaphores,
    user_api_key_semaphores,
)
from app.services import provider as provider_service
from app.services import proxy as proxy_module
from app.services.proxy_runtime import internal as internal_runtime
from app.services.proxy_runtime import normal as normal_runtime
from app.services.proxy_runtime import response_handler
from app.services.proxy import (
    _get_or_create_user_provider_model_semaphore,
    _get_or_create_user_api_key_semaphore,
    _get_user_api_key_limit,
    _get_or_create_provider_key_semaphore,
    _get_provider_key_limit,
    proxy_request,
)


class _TrackingSemaphore:
    def __init__(self):
        self.acquire_count = 0
        self.release_count = 0

    async def acquire(self):
        self.acquire_count += 1
        return True

    def release(self):
        self.release_count += 1


class ProviderKeyConcurrencyTests(unittest.TestCase):
    def setUp(self):
        provider_key_semaphores.clear()
        provider_key_model_semaphores.clear()
        user_api_key_semaphores.clear()

    def tearDown(self):
        provider_key_semaphores.clear()
        provider_key_model_semaphores.clear()
        user_api_key_semaphores.clear()
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

    def test_user_api_key_limit_is_shared_across_models_and_providers(self):
        sem_key_a, semaphore_a = _get_or_create_user_api_key_semaphore(
            api_key_id=1,
            target_limit=1,
        )
        sem_key_b, semaphore_b = _get_or_create_user_api_key_semaphore(
            api_key_id=1,
            target_limit=1,
        )

        self.assertEqual(sem_key_a, "user:1")
        self.assertEqual(sem_key_b, "user:1")
        self.assertIs(semaphore_a, semaphore_b)
        self.assertEqual(_get_user_api_key_limit(False), 1)

        self.assertTrue(asyncio.run(asyncio.wait_for(semaphore_a.acquire(), timeout=0.1)))
        with self.assertRaises(asyncio.TimeoutError):
            asyncio.run(asyncio.wait_for(semaphore_a.acquire(), timeout=0.01))

        semaphore_a.release()

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

    def test_provider_key_limit_shrinks_existing_semaphore_with_in_flight_request(self):
        _sem_key, semaphore = _get_or_create_provider_key_semaphore(
            provider_key_id=11,
            provider_name="openai",
            target_limit=3,
        )
        self.assertTrue(asyncio.run(asyncio.wait_for(semaphore.acquire(), timeout=0.1)))

        _sem_key, resized = _get_or_create_provider_key_semaphore(
            provider_key_id=11,
            provider_name="openai",
            target_limit=1,
        )

        self.assertIs(resized, semaphore)
        with self.assertRaises(asyncio.TimeoutError):
            asyncio.run(asyncio.wait_for(resized.acquire(), timeout=0.01))

        semaphore.release()

    def test_pick_api_keys_skips_disabled_keys_and_orders_by_priority(self):
        provider_config = {
            "api_keys": [
                {"id": 11, "api_key": "sk-disabled-high", "priority": 99, "is_active": False},
                {"id": 12, "api_key": "sk-low", "priority": 1},
                {"id": 13, "api_key": "sk-high", "priority": 5},
            ],
        }
        provider_service._key_sticky_map[(123, "zhipu")] = (11, 1.0)

        keys = provider_service.pick_api_keys(
            provider_config, api_key_id=123, provider_name="zhipu"
        )

        self.assertEqual(keys, [("sk-high", 13), ("sk-low", 12)])
        self.assertNotIn(("sk-disabled-high", 11), keys)

    def test_admin_config_template_exposes_provider_key_concurrency_input(self):
        template_source = Path("web/templates/admin/config.html").read_text(encoding="utf-8")

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

        with patch("app.services.proxy.runtime_handle_normal", new=runtime_handle):
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
        user_api_key_semaphore = object()
        response = object()
        runtime_handle = AsyncMock(return_value=response)

        with patch("app.services.proxy.runtime_handle_streaming", new=runtime_handle):
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
                user_api_key_semaphore,
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
        self.assertIs(kwargs["user_api_key_semaphore"], user_api_key_semaphore)
        self.assertNotIn("semaphore", kwargs)
        self.assertNotIn("api_key_model_semaphore", kwargs)


class ProviderKeyHealthEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from app.services import key_health

        key_health.clear_all()

    def tearDown(self):
        from app.services import key_health

        key_health.clear_all()

    async def test_normal_response_records_health_against_provider_key(self):
        from app.services import key_health

        class FakeResponse:
            status_code = 429
            headers = {}
            text = '{"error":{"message":"rate limited"}}'

            def json(self):
                return {"error": {"message": "rate limited"}}

        fake_client = Mock()
        fake_client.post = AsyncMock(return_value=FakeResponse())

        with (
            patch("app.services.proxy_runtime.normal.register_active_request", new=AsyncMock()),
            patch("app.services.proxy_runtime.normal.finish_active_request", new=AsyncMock()),
            patch("app.services.proxy_runtime.normal.create_request_log", new=AsyncMock(return_value=1)),
            patch("app.services.proxy_runtime.normal.update_stats", new=Mock()),
        ):
            await normal_runtime.handle_normal(
                fake_client,
                "https://example.com/chat/completions",
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
                None,
                None,
                "req-1",
                chosen_key_id=99,
            )

        self.assertEqual(key_health.get_events_5m(99)["rate_limited"], 1)
        self.assertEqual(key_health.get_events_5m(1)["rate_limited"], 0)

    async def test_stream_result_records_health_against_provider_key(self):
        from app.services import key_health

        with (
            patch("app.services.proxy_runtime.response_handler.update_request_log", new=AsyncMock(return_value=True)),
            patch("app.services.proxy_runtime.response_handler.update_request_content", new=AsyncMock()),
            patch("app.services.proxy_runtime.response_handler.update_stats", new=Mock()),
            patch("app.services.proxy_runtime.response_handler.record_tokens_second", new=Mock()),
        ):
            await response_handler._record_stream_result(
                "",
                "",
                [],
                "",
                None,
                {},
                "openai",
                "gpt-test",
                1,
                "127.0.0.1",
                "test",
                0,
                0,
                1,
                "success",
                upstream_status_code=200,
                provider_key_id=99,
            )

        self.assertEqual(key_health.get_events_5m(99)["success"], 1)
        self.assertEqual(key_health.get_events_5m(1)["success"], 0)


class InternalProxyConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        provider_key_semaphores.clear()
        provider_key_model_semaphores.clear()
        user_api_key_semaphores.clear()

    def tearDown(self):
        provider_key_semaphores.clear()
        provider_key_model_semaphores.clear()
        user_api_key_semaphores.clear()

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
            if len(wait_timeouts) <= 2:
                return True
            raise asyncio.TimeoutError

        with (
            patch(
                "app.services.proxy_runtime.internal.ensure_internal_api_key_exists",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.services.proxy_runtime.internal.get_provider_and_model",
                new=AsyncMock(return_value=(provider_config, "gpt-test", "openai")),
            ),
            patch(
                "app.services.proxy_runtime.internal.pick_api_key",
                return_value=("sk-test", 11),
            ),
            patch("app.services.proxy_runtime.internal.asyncio.wait_for", new=fake_wait_for),
            patch("app.services.proxy_runtime.internal.create_request_log", new=AsyncMock(return_value=1)),
            patch("app.services.proxy_runtime.internal.update_stats", new=Mock()),
            patch("app.services.proxy_runtime.internal.logger.warning", new=Mock()),
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
        self.assertIn("并发请求已达上限", result["error"])
        self.assertEqual(len(wait_timeouts), 3)


class ProxyGlobalUserConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        provider_key_semaphores.clear()
        provider_key_model_semaphores.clear()
        user_api_key_semaphores.clear()
        self.original_api_keys_cache = dict(config.api_keys_cache)
        config.api_keys_cache.clear()

    def tearDown(self):
        provider_key_semaphores.clear()
        provider_key_model_semaphores.clear()
        user_api_key_semaphores.clear()
        config.api_keys_cache.clear()
        config.api_keys_cache.update(self.original_api_keys_cache)

    async def test_non_bypass_user_global_limit_blocks_third_request(self):
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
        request._body = b'{"model":"openai/gpt-other","messages":[]}'
        config.api_keys_cache["test-key"] = {"id": 1, "bypass_busyness": False, "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000))}
        _, user_semaphore = _get_or_create_user_api_key_semaphore(
            api_key_id=1,
            target_limit=2,
        )
        await user_semaphore.acquire()
        await user_semaphore.acquire()
        provider_config = {
            "base_url": "https://example.com",
            "protocol": "openai",
            "api_keys": [{"id": 11, "api_key": "sk-test", "max_concurrent": 3}],
            "models": [{"model_name": "gpt-other", "actual_model_name": "gpt-other"}],
        }

        with (
            patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))),
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=[(provider_config, "gpt-other", "openai")]),
            ),
            patch(
                "app.services.proxy.pick_api_keys",
                return_value=[("sk-test", 11)],
            ),
            patch("app.services.proxy.create_request_log", new=AsyncMock()),
            patch("app.services.proxy.update_stats", new=Mock()),
            patch("app.services.proxy.USER_PROVIDER_MODEL_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS", 0.01),
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        self.assertEqual(response.status_code, 429)
        body = response.body.decode("utf-8")
        self.assertIn("user_global_concurrency_reached", body)

    async def test_streaming_key_fallback_keeps_global_slot_until_final_response(self):
        config.api_keys_cache["test-key"] = {"id": 1, "bypass_busyness": True, "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000))}
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
        request._body = (
            b'{"model":"openai/gpt-other","messages":[],"stream":true}'
        )
        config.api_keys_cache["test-key"] = {"id": 1, "bypass_busyness": False, "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000))}
        tracking_semaphore = _TrackingSemaphore()
        provider_config = {
            "base_url": "https://example.com",
            "protocol": "openai",
            "api_keys": [
                {"id": 11, "api_key": "sk-one", "max_concurrent": 3},
                {"id": 12, "api_key": "sk-two", "max_concurrent": 3},
            ],
            "models": [{"model_name": "gpt-other", "actual_model_name": "gpt-other"}],
        }
        stream_responses = [
            Response(content=b"{}", status_code=429),
            Response(content=b"{}", status_code=200),
        ]

        async def fake_handle_streaming(*args, **_kwargs):
            provider_key_semaphore = args[12]
            user_provider_model_semaphore = args[13]
            if user_provider_model_semaphore is not None:
                user_provider_model_semaphore.release()
            if provider_key_semaphore is not None:
                provider_key_semaphore.release()
            return stream_responses.pop(0)

        stream_handler = AsyncMock(side_effect=fake_handle_streaming)

        with (
            patch("app.services.proxy.check_model_access", return_value=True),
            patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))),
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=[(provider_config, "gpt-other", "openai")]),
            ),
            patch(
                "app.services.proxy.pick_api_keys",
                return_value=[("sk-one", 11), ("sk-two", 12)],
            ),
            patch(
                "app.services.proxy._get_or_create_user_api_key_semaphore",
                return_value=("user:1", tracking_semaphore),
            ),
            patch("app.services.proxy.handle_streaming", new=stream_handler),
            patch("app.services.proxy.create_request_log", new=AsyncMock(return_value=1)),
            patch("app.services.proxy.update_stats", new=Mock()),
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(stream_handler.await_count, 2)
        self.assertEqual(tracking_semaphore.acquire_count, 1)
        self.assertEqual(tracking_semaphore.release_count, 1)

    async def test_auto_route_falls_back_to_next_provider_when_provider_key_concurrency_full(self):
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
        request._body = b'{"model":"glm-5.1","messages":[]}'
        config.api_keys_cache["test-key"] = {"id": 1, "bypass_busyness": True, "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000))}
        primary_config = {
            "id": 1,
            "base_url": "https://primary.example/v1",
            "protocol": "openai",
            "api_keys": [{"id": 11, "api_key": "sk-primary", "max_concurrent": 1}],
            "models": [{"id": 91, "model_id": 101, "model_name": "glm-5.1", "upstream_model_name": "glm-5.1"}],
        }
        fallback_config = {
            "id": 2,
            "base_url": "https://fallback.example/v1",
            "protocol": "openai",
            "api_keys": [{"id": 12, "api_key": "sk-fallback", "max_concurrent": 1}],
            "models": [{"id": 92, "model_id": 101, "model_name": "glm-5.1", "upstream_model_name": "local_model"}],
        }
        routes = [
            proxy_module.RouteResult(
                provider_config=primary_config,
                provider_name="primary",
                provider_id=1,
                provider_model_id=91,
                model_id=101,
                requested_model="glm-5.1",
                model_name="glm-5.1",
                upstream_model_name="glm-5.1",
                is_forced_provider=False,
            ),
            proxy_module.RouteResult(
                provider_config=fallback_config,
                provider_name="fallback",
                provider_id=2,
                provider_model_id=92,
                model_id=101,
                requested_model="glm-5.1",
                model_name="glm-5.1",
                upstream_model_name="local_model",
                is_forced_provider=False,
            ),
        ]
        wait_results = [asyncio.TimeoutError(), True, True]

        async def fake_wait_for(awaitable, timeout):
            awaitable.close()
            result = wait_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result

        normal_handler = AsyncMock(return_value=Response(content=b"{}", status_code=200))

        with (
            patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))),
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=routes),
            ),
            patch("app.services.proxy.asyncio.wait_for", new=fake_wait_for),
            patch("app.services.proxy.handle_normal", new=normal_handler),
            patch("app.services.proxy.create_request_log", new=AsyncMock()),
            patch("app.services.proxy.update_stats", new=Mock()),
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(normal_handler.await_count, 1)
        self.assertEqual(normal_handler.await_args.args[4], "fallback")

    async def test_concurrency_exhaustion_takes_precedence_over_later_provider_quota_error(self):
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
        request._body = b'{"model":"glm-5.1","messages":[]}'
        config.api_keys_cache["test-key"] = {"id": 1, "bypass_busyness": True, "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000))}
        routes = [
            proxy_module.RouteResult(
                provider_config={
                    "id": 1,
                    "base_url": "https://busy-a.example/v1",
                    "protocol": "openai",
                    "api_keys": [{"id": 11, "api_key": "sk-busy-a", "max_concurrent": 1}],
                    "models": [{"id": 91, "model_id": 101, "model_name": "glm-5.1"}],
                },
                provider_name="busy-a",
                provider_id=1,
                provider_model_id=91,
                model_id=101,
                requested_model="glm-5.1",
                model_name="glm-5.1",
                upstream_model_name="glm-5.1",
                is_forced_provider=False,
            ),
            proxy_module.RouteResult(
                provider_config={
                    "id": 2,
                    "base_url": "https://busy-b.example/v1",
                    "protocol": "openai",
                    "api_keys": [{"id": 12, "api_key": "sk-busy-b", "max_concurrent": 1}],
                    "models": [{"id": 92, "model_id": 101, "model_name": "glm-5.1"}],
                },
                provider_name="busy-b",
                provider_id=2,
                provider_model_id=92,
                model_id=101,
                requested_model="glm-5.1",
                model_name="glm-5.1",
                upstream_model_name="glm-5.1",
                is_forced_provider=False,
            ),
            proxy_module.RouteResult(
                provider_config={
                    "id": 3,
                    "base_url": "https://quota.example/v1",
                    "protocol": "openai",
                    "api_keys": [{"id": 13, "api_key": "sk-quota", "max_concurrent": 1}],
                    "models": [{"id": 93, "model_id": 101, "model_name": "glm-5.1"}],
                },
                provider_name="quota",
                provider_id=3,
                provider_model_id=93,
                model_id=101,
                requested_model="glm-5.1",
                model_name="glm-5.1",
                upstream_model_name="glm-5.1",
                is_forced_provider=False,
            ),
        ]
        wait_results = [asyncio.TimeoutError(), asyncio.TimeoutError(), True, True]

        async def fake_wait_for(awaitable, timeout):
            awaitable.close()
            result = wait_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result

        async def fake_handle_normal(*args, **_kwargs):
            provider_key_semaphore = args[13]
            user_provider_model_semaphore = args[14]
            if user_provider_model_semaphore is not None:
                user_provider_model_semaphore.release()
            if provider_key_semaphore is not None:
                provider_key_semaphore.release()
            return response_handler._openai_error_response(
                "供应商 'quota' 因额度限制已暂停使用，请尝试其他供应商",
                429,
                "rate_limit_error",
                "provider_disabled",
            )

        with (
            patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))),
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=routes),
            ),
            patch("app.services.proxy.asyncio.wait_for", new=fake_wait_for),
            patch("app.services.proxy.handle_normal", new=AsyncMock(side_effect=fake_handle_normal)),
            patch("app.services.proxy.create_request_log", new=AsyncMock()),
            patch("app.services.proxy.update_stats", new=Mock()),
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        body = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 429)
        self.assertIn("provider_key_concurrency_reached", body)
        self.assertNotIn("provider_disabled", body)

    async def test_forced_provider_does_not_fallback_to_next_provider_when_concurrency_full(self):
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
        request._body = b'{"model":"primary/glm-5.1","messages":[]}'
        config.api_keys_cache["test-key"] = {"id": 1, "bypass_busyness": True, "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000))}
        primary_config = {
            "id": 1,
            "base_url": "https://primary.example/v1",
            "protocol": "openai",
            "api_keys": [{"id": 11, "api_key": "sk-primary", "max_concurrent": 1}],
            "models": [{"id": 91, "model_id": 101, "model_name": "glm-5.1", "upstream_model_name": "glm-5.1"}],
        }
        fallback_config = {
            "id": 2,
            "base_url": "https://fallback.example/v1",
            "protocol": "openai",
            "api_keys": [{"id": 12, "api_key": "sk-fallback", "max_concurrent": 1}],
            "models": [{"id": 92, "model_id": 101, "model_name": "glm-5.1", "upstream_model_name": "local_model"}],
        }
        routes = [
            proxy_module.RouteResult(
                provider_config=primary_config,
                provider_name="primary",
                provider_id=1,
                provider_model_id=91,
                model_id=101,
                requested_model="primary/glm-5.1",
                model_name="glm-5.1",
                upstream_model_name="glm-5.1",
                is_forced_provider=True,
            ),
            proxy_module.RouteResult(
                provider_config=fallback_config,
                provider_name="fallback",
                provider_id=2,
                provider_model_id=92,
                model_id=101,
                requested_model="primary/glm-5.1",
                model_name="glm-5.1",
                upstream_model_name="local_model",
                is_forced_provider=False,
            ),
        ]

        async def fake_wait_for(awaitable, timeout):
            awaitable.close()
            raise asyncio.TimeoutError

        normal_handler = AsyncMock(return_value=Response(content=b"{}", status_code=200))

        with (
            patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))),
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=routes),
            ),
            patch("app.services.proxy.asyncio.wait_for", new=fake_wait_for),
            patch("app.services.proxy.handle_normal", new=normal_handler),
            patch("app.services.proxy.create_request_log", new=AsyncMock()),
            patch("app.services.proxy.update_stats", new=Mock()),
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(normal_handler.await_count, 0)
        self.assertIn("provider_key_concurrency_reached", response.body.decode("utf-8"))


class ProviderKeyErrorMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_scoped_provider_key_error_is_model_route_specific(self):
        config.api_keys_cache["test-key"] = {"id": 1, "bypass_busyness": True, "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000))}
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
        request._body = b'{"model":"zhipu/glm-5.1","messages":[]}'
        routes = [
            provider_service.RouteResult(
                provider_config={
                    "base_url": "https://zhipu.example",
                    "api_keys": [
                        {"id": 11, "api_key": "sk-scoped"},
                        {"id": 12, "api_key": "sk-other"},
                    ],
                    "models": [{"model_name": "glm-5.1"}],
                },
                provider_name="zhipu",
                provider_id=1,
                provider_model_id=11,
                model_id=101,
                model_name="glm-5.1",
                upstream_model_name="glm-5.1",
                requested_model="zhipu/glm-5.1",
                is_forced_provider=True,
                provider_key_ids=[11],
            )
        ]

        def fake_health_score(key_id):
            return 0 if key_id == 11 else 100

        with (
            patch("app.services.proxy.check_model_access", return_value=True),
            patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))),
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=routes),
            ),
            patch("app.services.provider.compute_health_score", side_effect=fake_health_score),
            patch("app.services.provider_key_routing.compute_health_score", side_effect=fake_health_score),
            patch("app.services.proxy.create_request_log", new=AsyncMock()),
            patch("app.services.proxy.update_stats", new=Mock()),
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        body = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 429)
        self.assertIn("路由限定的 API Key", body)
        self.assertNotIn("供应商 'zhipu' 当前没有可用的 API Key", body)

    async def test_no_provider_key_error_is_human_readable(self):
        config.api_keys_cache["test-key"] = {"id": 1, "bypass_busyness": True, "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000))}
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
            patch("app.services.proxy.check_model_access", return_value=True),
            patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))),
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(
                    return_value=[(
                        {"base_url": "https://example.com", "api_keys": []},
                        "glm-4.5",
                        "zhipu",
                    )]
                ),
            ),
            patch("app.services.proxy.create_request_log", new=AsyncMock()),
            patch("app.services.proxy.update_stats", new=Mock()),
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        self.assertEqual(response.status_code, 429)
        body = response.body.decode("utf-8")
        self.assertIn("没有可用的 API Key", body)

    async def test_all_candidate_provider_keys_unavailable_does_not_return_model_not_found(self):
        config.api_keys_cache["test-key"] = {"id": 1, "bypass_busyness": True, "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000))}
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
        request._body = b'{"model":"GLM-5.2","messages":[]}'
        routes = [
            provider_service.RouteResult(
                provider_config={
                    "base_url": "https://zhipu.example",
                    "api_keys": [],
                    "models": [{"model_name": "GLM-5.2"}],
                    "disabled_key_reasons": ["智谱 Key 已被禁用"],
                },
                provider_name="zhipu",
                provider_id=1,
                provider_model_id=11,
                model_id=101,
                model_name="GLM-5.2",
                upstream_model_name="GLM-5.2",
                requested_model="GLM-5.2",
            ),
            provider_service.RouteResult(
                provider_config={
                    "base_url": "https://jintou.example",
                    "api_keys": [],
                    "models": [{"model_name": "GLM-5.2"}],
                    "disabled_key_reasons": ["金投 Key 已被禁用"],
                },
                provider_name="jintou",
                provider_id=2,
                provider_model_id=12,
                model_id=101,
                model_name="GLM-5.2",
                upstream_model_name="GLM-5.2",
                requested_model="GLM-5.2",
            ),
        ]

        with (
            patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))),
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=routes),
            ),
            patch("app.services.proxy.create_request_log", new=AsyncMock()),
            patch("app.services.proxy.update_stats", new=Mock()),
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        body = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 429)
        self.assertIn("no_available_api_key", body)
        self.assertIn("智谱 Key 已被禁用", body)
        self.assertNotIn("金投 Key 已被禁用", body)
        self.assertNotIn("model_not_found", body)
        self.assertNotIn("未找到模型", body)

    async def test_all_disabled_provider_keys_reports_highest_priority_key_reason(self):
        config.api_keys_cache["test-key"] = {"id": 1, "bypass_busyness": True, "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000))}
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
        request._body = b'{"model":"GLM-5.2","messages":[]}'
        routes = [
            provider_service.RouteResult(
                provider_config={
                    "base_url": "https://zhipu.example",
                    "api_keys": [],
                    "models": [{"model_name": "GLM-5.2"}],
                    "disabled_key_reasons": ["低优先级 Key 欠费"],
                    "disabled_keys": [
                        {
                            "id": 21,
                            "label": "low",
                            "priority": 10,
                            "disabled_reason": "低优先级 Key 欠费",
                        }
                    ],
                },
                provider_name="zhipu",
                provider_id=1,
                provider_model_id=11,
                model_id=101,
                model_name="GLM-5.2",
                upstream_model_name="GLM-5.2",
                requested_model="GLM-5.2",
            ),
            provider_service.RouteResult(
                provider_config={
                    "base_url": "https://jintou.example",
                    "api_keys": [],
                    "models": [{"model_name": "GLM-5.2"}],
                    "disabled_key_reasons": ["高优先级 Key 已禁用：余额不足"],
                    "disabled_keys": [
                        {
                            "id": 24,
                            "label": "high",
                            "priority": 99,
                            "disabled_reason": "高优先级 Key 已禁用：余额不足",
                        }
                    ],
                },
                provider_name="jintou",
                provider_id=2,
                provider_model_id=12,
                model_id=101,
                model_name="GLM-5.2",
                upstream_model_name="GLM-5.2",
                requested_model="GLM-5.2",
            ),
        ]

        with (
            patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))),
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=routes),
            ),
            patch("app.services.proxy.create_request_log", new=AsyncMock()),
            patch("app.services.proxy.update_stats", new=Mock()),
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        body = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 429)
        self.assertIn("高优先级 Key 已禁用：余额不足", body)
        self.assertNotIn("低优先级 Key 欠费", body)

    async def test_known_model_without_active_provider_does_not_return_model_not_found(self):
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
        request._body = b'{"model":"GLM-5.2","messages":[]}'
        routes = [
            provider_service.RouteResult(
                provider_config=None,
                provider_name="",
                model_id=101,
                requested_model_id=101,
                model_name="GLM-5.2",
                upstream_model_name="GLM-5.2",
                requested_model="GLM-5.2",
            )
        ]

        with (
            patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))),
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=routes),
            ),
            patch("app.services.proxy.create_request_log", new=AsyncMock()),
            patch("app.services.proxy.update_stats", new=Mock()),
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        body = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 503)
        self.assertIn("model_unavailable", body)
        self.assertNotIn("model_not_found", body)
        self.assertNotIn("未找到模型", body)


class RouteFallbackOnServerErrorTests(unittest.IsolatedAsyncioTestCase):
    async def _run_proxy_with_routes(
        self,
        routes,
        handle_normal_side_effect=None,
        handle_streaming_side_effect=None,
    ):
        import contextlib

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
        request._body = b'{"model":"glm-5.1","messages":[]}'
        config.api_keys_cache["test-key"] = {"id": 1, "bypass_busyness": True, "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000))}
        cm_stack = contextlib.ExitStack()
        cm_stack.enter_context(patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))))
        cm_stack.enter_context(patch("app.services.proxy.get_provider_model_candidates", new=AsyncMock(return_value=routes)))
        cm_stack.enter_context(patch("app.services.proxy.create_request_log", new=AsyncMock()))
        cm_stack.enter_context(patch("app.services.proxy.update_stats", new=Mock()))
        cm_stack.enter_context(patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None))
        if handle_normal_side_effect is not None:
            cm_stack.enter_context(patch("app.services.proxy.handle_normal", new=handle_normal_side_effect))
        if handle_streaming_side_effect is not None:
            cm_stack.enter_context(patch("app.services.proxy.handle_streaming", new=handle_streaming_side_effect))
        with cm_stack:
            response = await proxy_request(request, "/chat/completions")
        return response

    def _make_route(self, provider_name, provider_id=1, is_forced=False):
        return proxy_module.RouteResult(
            provider_config={
                "id": provider_id,
                "base_url": f"https://{provider_name}.example/v1",
                "protocol": "openai",
                "api_keys": [{"id": provider_id * 10, "api_key": f"sk-{provider_name}", "max_concurrent": 3}],
                "models": [{"id": provider_id * 10 + 1, "model_id": 101, "model_name": "glm-5.1"}],
            },
            provider_name=provider_name,
            provider_id=provider_id,
            provider_model_id=provider_id * 10 + 1,
            model_id=101,
            requested_model="glm-5.1",
            model_name="glm-5.1",
            upstream_model_name="glm-5.1",
            is_forced_provider=is_forced,
        )

    async def test_500_from_first_provider_falls_back_to_second(self):
        routes = [self._make_route("primary", 1), self._make_route("fallback", 2)]
        responses = [
            Response(content=b'{"error":"server error"}', status_code=500),
            Response(content=b'{"choices":[]}', status_code=200),
        ]

        async def fake_handle_normal(*args, **_kwargs):
            sem = args[13]
            user_sem = args[14]
            if sem is not None:
                sem.release()
            if user_sem is not None:
                user_sem.release()
            return responses.pop(0)

        response = await self._run_proxy_with_routes(
            routes, handle_normal_side_effect=AsyncMock(side_effect=fake_handle_normal)
        )

        self.assertEqual(response.status_code, 200)

    async def test_502_from_first_provider_falls_back_to_second(self):
        routes = [self._make_route("primary", 1), self._make_route("fallback", 2)]
        responses = [
            Response(content=b'{"error":"bad gateway"}', status_code=502),
            Response(content=b'{"choices":[]}', status_code=200),
        ]

        async def fake_handle_normal(*args, **_kwargs):
            sem = args[13]
            user_sem = args[14]
            if sem is not None:
                sem.release()
            if user_sem is not None:
                user_sem.release()
            return responses.pop(0)

        response = await self._run_proxy_with_routes(
            routes, handle_normal_side_effect=AsyncMock(side_effect=fake_handle_normal)
        )

        self.assertEqual(response.status_code, 200)

    async def test_all_providers_return_500_returns_error(self):
        routes = [self._make_route("primary", 1), self._make_route("fallback", 2)]

        async def fake_handle_normal(*args, **_kwargs):
            sem = args[13]
            user_sem = args[14]
            if sem is not None:
                sem.release()
            if user_sem is not None:
                user_sem.release()
            return Response(content=b'{"error":"server error"}', status_code=500)

        response = await self._run_proxy_with_routes(
            routes, handle_normal_side_effect=AsyncMock(side_effect=fake_handle_normal)
        )

        self.assertEqual(response.status_code, 503)
        import json as _json
        body = _json.loads(response.body)
        self.assertEqual(body.get("error", {}).get("code"), "model_unavailable")
        self.assertIn("没有可用的供应商", body.get("error", {}).get("message", ""))

    async def test_network_exception_from_first_provider_falls_back_to_second(self):
        routes = [self._make_route("primary", 1), self._make_route("fallback", 2)]
        call_count = [0]

        async def fake_handle_normal(*args, **_kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("connection refused")
            sem = args[13]
            user_sem = args[14]
            if sem is not None:
                sem.release()
            if user_sem is not None:
                user_sem.release()
            return Response(content=b'{"choices":[]}', status_code=200)

        response = await self._run_proxy_with_routes(
            routes, handle_normal_side_effect=AsyncMock(side_effect=fake_handle_normal)
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(call_count[0], 2)

    async def test_400_from_first_provider_does_not_fall_back(self):
        routes = [self._make_route("primary", 1), self._make_route("fallback", 2)]

        async def fake_handle_normal(*args, **_kwargs):
            sem = args[13]
            user_sem = args[14]
            if sem is not None:
                sem.release()
            if user_sem is not None:
                user_sem.release()
            return Response(content=b'{"error":"bad request"}', status_code=400)

        response = await self._run_proxy_with_routes(
            routes, handle_normal_side_effect=AsyncMock(side_effect=fake_handle_normal)
        )

        self.assertEqual(response.status_code, 400)

    async def test_forced_provider_500_does_not_fall_back(self):
        routes = [
            self._make_route("primary", 1, is_forced=True),
            self._make_route("fallback", 2),
        ]
        call_count = [0]

        async def fake_handle_normal(*args, **_kwargs):
            call_count[0] += 1
            sem = args[13]
            user_sem = args[14]
            if sem is not None:
                sem.release()
            if user_sem is not None:
                user_sem.release()
            return Response(content=b'{"error":"server error"}', status_code=500)

        with patch("app.services.proxy.check_model_access", return_value=True):
            response = await self._run_proxy_with_routes(
                routes, handle_normal_side_effect=AsyncMock(side_effect=fake_handle_normal)
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(call_count[0], 1)

    async def test_stream_500_from_first_provider_falls_back_to_second(self):
        routes = [self._make_route("primary", 1), self._make_route("fallback", 2)]
        responses = [
            Response(content=b'{"error":"server error"}', status_code=503),
            Response(content=b'{"choices":[]}', status_code=200),
        ]
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
        request._body = b'{"model":"glm-5.1","messages":[],"stream":true}'
        config.api_keys_cache["test-key"] = {"id": 1, "bypass_busyness": True, "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000))}

        async def fake_handle_streaming(*args, **_kwargs):
            provider_key_semaphore = args[12]
            user_provider_model_semaphore = args[13]
            if provider_key_semaphore is not None:
                provider_key_semaphore.release()
            if user_provider_model_semaphore is not None:
                user_provider_model_semaphore.release()
            return responses.pop(0)

        with (
            patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))),
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=routes),
            ),
            patch("app.services.proxy.handle_streaming", new=AsyncMock(side_effect=fake_handle_streaming)),
            patch("app.services.proxy.create_request_log", new=AsyncMock(return_value=1)),
            patch("app.services.proxy.update_stats", new=Mock()),
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        self.assertEqual(response.status_code, 200)

    async def test_all_providers_return_429_returns_unified_message(self):
        routes = [self._make_route("primary", 1), self._make_route("fallback", 2)]

        async def fake_handle_normal(*args, **_kwargs):
            sem = args[13]
            user_sem = args[14]
            if sem is not None:
                sem.release()
            if user_sem is not None:
                user_sem.release()
            return Response(content=b'{"error":"rate limited"}', status_code=429)

        response = await self._run_proxy_with_routes(
            routes, handle_normal_side_effect=AsyncMock(side_effect=fake_handle_normal)
        )

        self.assertEqual(response.status_code, 503)
        import json as _json
        body = _json.loads(response.body)
        self.assertEqual(body.get("error", {}).get("code"), "model_unavailable")
        self.assertIn("没有可用的供应商", body.get("error", {}).get("message", ""))

    async def test_all_providers_network_exception_returns_unified_message(self):
        routes = [self._make_route("primary", 1), self._make_route("fallback", 2)]

        async def fake_handle_normal(*args, **_kwargs):
            sem = args[13]
            user_sem = args[14]
            if sem is not None:
                sem.release()
            if user_sem is not None:
                user_sem.release()
            raise ConnectionError("connection refused")

        response = await self._run_proxy_with_routes(
            routes, handle_normal_side_effect=AsyncMock(side_effect=fake_handle_normal)
        )

        self.assertEqual(response.status_code, 503)
        import json as _json
        body = _json.loads(response.body)
        self.assertEqual(body.get("error", {}).get("code"), "model_unavailable")
        self.assertIn("没有可用的供应商", body.get("error", {}).get("message", ""))
