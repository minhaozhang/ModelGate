import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import Request
from pydantic import ValidationError

import app.core.config as config
from app.core.config import standard_model_semaphores, user_api_key_semaphores
from app.services import provider as provider_service
from app.services import proxy as proxy_module
from app.services.provider import get_cached_model_max_concurrent
from app.services.proxy import proxy_request
from app.services.proxy_runtime import (
    acquire_scoped_semaphore,
    _get_or_create_standard_model_semaphore,
    _get_provider_key_limit,
)


class ProviderKeyLimitZeroSemanticsTests(unittest.TestCase):
    def test_none_defaults_to_three(self):
        provider_config = {"api_keys": [{"id": 11, "api_key": "sk-a"}]}
        self.assertEqual(_get_provider_key_limit(provider_config, 11), 3)

    def test_missing_key_id_defaults_to_three(self):
        self.assertEqual(_get_provider_key_limit({"api_keys": []}, 99), 3)

    def test_explicit_zero_is_zero(self):
        provider_config = {"api_keys": [{"id": 11, "api_key": "sk-a", "max_concurrent": 0}]}
        self.assertEqual(_get_provider_key_limit(provider_config, 11), 0)

    def test_negative_treated_as_default(self):
        provider_config = {"api_keys": [{"id": 11, "api_key": "sk-a", "max_concurrent": -5}]}
        self.assertEqual(_get_provider_key_limit(provider_config, 11), 3)

    def test_positive_value_passthrough(self):
        provider_config = {"api_keys": [{"id": 11, "api_key": "sk-a", "max_concurrent": 7}]}
        self.assertEqual(_get_provider_key_limit(provider_config, 11), 7)

    def test_string_value_parsed(self):
        provider_config = {"api_keys": [{"id": 11, "api_key": "sk-a", "max_concurrent": "4"}]}
        self.assertEqual(_get_provider_key_limit(provider_config, 11), 4)


class StandardModelSemaphoreTests(unittest.TestCase):
    def setUp(self):
        standard_model_semaphores.clear()

    def tearDown(self):
        standard_model_semaphores.clear()

    def test_same_model_reuses_semaphore(self):
        key_a, sem_a = _get_or_create_standard_model_semaphore("glm-6.6", 2)
        key_b, sem_b = _get_or_create_standard_model_semaphore("glm-6.6", 2)
        self.assertEqual(key_a, "stdmodel:glm-6.6")
        self.assertIs(sem_a, sem_b)

    def test_different_models_are_isolated(self):
        _, sem_a = _get_or_create_standard_model_semaphore("glm-6.6", 2)
        _, sem_b = _get_or_create_standard_model_semaphore("glm-7", 2)
        self.assertIsNot(sem_a, sem_b)

    def test_negative_target_floored_to_zero(self):
        _, sem = _get_or_create_standard_model_semaphore("glm-6.6", -3)
        self.assertEqual(getattr(sem, "_modelgate_scoped_limit"), 0)

    async def _check_zero_fast_fail(self):
        _, sem = _get_or_create_standard_model_semaphore("stopped-model", 0)
        start = asyncio.get_running_loop().time()
        with self.assertRaises(asyncio.TimeoutError):
            await acquire_scoped_semaphore(sem, timeout=30.0)
        elapsed = asyncio.get_running_loop().time() - start
        # Must reject immediately instead of waiting anywhere near the timeout.
        self.assertLess(elapsed, 1.0)

    def test_zero_limit_rejects_without_waiting_for_timeout(self):
        asyncio.run(self._check_zero_fast_fail())

    def test_positive_limit_allows_acquire_and_release(self):
        _, sem = _get_or_create_standard_model_semaphore("glm-6.6", 1)

        async def scenario():
            await asyncio.wait_for(acquire_scoped_semaphore(sem, timeout=0.1), timeout=1)
            with self.assertRaises(asyncio.TimeoutError):
                await acquire_scoped_semaphore(sem, timeout=0.05)

        asyncio.run(scenario())
        sem.release()


class ModelConcurrencyCacheTests(unittest.TestCase):
    def setUp(self):
        provider_service._model_max_concurrent_by_name.clear()

    def tearDown(self):
        provider_service._model_max_concurrent_by_name.clear()

    def test_unknown_model_returns_none(self):
        self.assertIsNone(get_cached_model_max_concurrent("no-such-model"))

    def test_cached_zero_is_preserved(self):
        provider_service._model_max_concurrent_by_name["glm-zero"] = 0
        self.assertEqual(get_cached_model_max_concurrent("glm-zero"), 0)

    def test_cached_positive_value_roundtrip(self):
        provider_service._model_max_concurrent_by_name["glm-cap"] = 5
        self.assertEqual(get_cached_model_max_concurrent("glm-cap"), 5)


class ModelConcurrencyProxyGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        standard_model_semaphores.clear()
        user_api_key_semaphores.clear()
        provider_service._model_max_concurrent_by_name.clear()
        self.original_api_keys_cache = dict(config.api_keys_cache)
        config.api_keys_cache.clear()
        config.api_keys_cache["test-key"] = {"id": 1, "bypass_busyness": True, "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000))}

    def tearDown(self):
        standard_model_semaphores.clear()
        user_api_key_semaphores.clear()
        provider_service._model_max_concurrent_by_name.clear()
        config.api_keys_cache.clear()
        config.api_keys_cache.update(self.original_api_keys_cache)

    @staticmethod
    def _make_request(model_name="cap-test"):
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
        request._body = f'{{"model":"{model_name}","messages":[]}}'.encode("utf-8")
        return request

    def _base_patches(self, routes, stack):
        import contextlib

        stack.enter_context(patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))))
        stack.enter_context(
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=routes),
            )
        )
        stack.enter_context(patch("app.services.proxy.create_request_log", new=AsyncMock()))
        stack.enter_context(patch("app.services.proxy.update_stats", new=Mock()))
        stack.enter_context(patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None))

    async def test_zero_limit_model_returns_429_before_any_handler(self):
        provider_service._model_max_concurrent_by_name["cap-test"] = 0
        route = proxy_module.RouteResult(
            provider_config={
                "id": 1,
                "base_url": "https://primary.example/v1",
                "protocol": "openai",
                "api_keys": [{"id": 11, "api_key": "sk-primary", "max_concurrent": 3}],
                "models": [{"id": 91, "model_id": 101, "model_name": "cap-test"}],
            },
            provider_name="primary",
            provider_id=1,
            provider_model_id=91,
            model_id=101,
            requested_model="cap-test",
            model_name="cap-test",
            upstream_model_name="cap-test",
            is_forced_provider=False,
        )
        handler = AsyncMock(return_value=Mock(status_code=200))
        import contextlib

        with contextlib.ExitStack() as stack:
            self._base_patches([route], stack)
            stack.enter_context(patch("app.services.proxy.handle_normal", new=handler))
            response = await proxy_request(self._make_request(), "/chat/completions")

        self.assertEqual(response.status_code, 429)
        body = response.body.decode("utf-8")
        self.assertIn("model_zero_concurrency", body)
        handler.assert_not_awaited()
        gate = standard_model_semaphores.get("stdmodel:cap-test")
        self.assertIsNotNone(gate)
        self.assertEqual(getattr(gate, "_modelgate_scoped_limit"), 0)

    async def test_positive_limit_blocks_when_saturated(self):
        provider_service._model_max_concurrent_by_name["cap-test"] = 1
        route = proxy_module.RouteResult(
            provider_config={
                "id": 1,
                "base_url": "https://primary.example/v1",
                "protocol": "openai",
                "api_keys": [{"id": 11, "api_key": "sk-primary", "max_concurrent": 3}],
                "models": [{"id": 91, "model_id": 101, "model_name": "cap-test"}],
            },
            provider_name="primary",
            provider_id=1,
            provider_model_id=91,
            model_id=101,
            requested_model="cap-test",
            model_name="cap-test",
            upstream_model_name="cap-test",
            is_forced_provider=False,
        )
        handler = AsyncMock(return_value=Mock(status_code=200))
        _, prebuilt = _get_or_create_standard_model_semaphore("cap-test", 1)
        await prebuilt.acquire()  # saturate the single slot externally

        import contextlib

        with contextlib.ExitStack() as stack:
            self._base_patches([route], stack)
            stack.enter_context(
                patch(
                    "app.services.proxy.USER_PROVIDER_MODEL_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS",
                    0.05,
                )
            )
            stack.enter_context(patch("app.services.proxy.handle_normal", new=handler))
            response = await proxy_request(self._make_request(), "/chat/completions")

        self.assertEqual(response.status_code, 429)
        body = response.body.decode("utf-8")
        self.assertIn("model_concurrency_reached", body)
        handler.assert_not_awaited()
        prebuilt.release()

    async def test_unlimited_model_skips_gate_entirely(self):
        route = proxy_module.RouteResult(
            provider_config={
                "id": 1,
                "base_url": "https://primary.example/v1",
                "protocol": "openai",
                "api_keys": [{"id": 11, "api_key": "sk-primary", "max_concurrent": 3}],
                "models": [{"id": 91, "model_id": 101, "model_name": "free-model"}],
            },
            provider_name="primary",
            provider_id=1,
            provider_model_id=91,
            model_id=101,
            requested_model="free-model",
            model_name="free-model",
            upstream_model_name="free-model",
            is_forced_provider=False,
        )

        async def fake_handle_normal(*args, **kwargs):
            provider_key_semaphore = args[13]
            if provider_key_semaphore is not None:
                provider_key_semaphore.release()
            from fastapi.responses import Response

            return Response(content=b'{"choices":[]}', status_code=200)

        import contextlib

        with contextlib.ExitStack() as stack:
            self._base_patches([route], stack)
            stack.enter_context(
                patch(
                    "app.services.proxy.handle_normal",
                    new=AsyncMock(side_effect=fake_handle_normal),
                )
            )
            response = await proxy_request(
                self._make_request("free-model"), "/chat/completions"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(standard_model_semaphores, {})


class StandardModelSchemaTests(unittest.TestCase):
    def test_model_create_accepts_zero_and_positive(self):
        from app.routes.models import ModelCreate

        payload = ModelCreate(name="m1", max_concurrent=0)
        self.assertEqual(payload.max_concurrent, 0)
        payload = ModelCreate(name="m1")
        self.assertIsNone(payload.max_concurrent)

    def test_model_create_rejects_negative(self):
        from app.routes.models import ModelCreate

        with self.assertRaises(ValidationError):
            ModelCreate(name="m1", max_concurrent=-1)

    def test_model_update_rejects_negative(self):
        from app.routes.models import ModelUpdate

        with self.assertRaises(ValidationError):
            ModelUpdate(max_concurrent=-2)

    def test_provider_key_schema_rejects_negative(self):
        from app.routes.providers import ProviderKeyCreate, ProviderKeyUpdate

        with self.assertRaises(ValidationError):
            ProviderKeyCreate(api_key="sk-x", max_concurrent=-1)
        with self.assertRaises(ValidationError):
            ProviderKeyUpdate(max_concurrent=-1)

    def test_migration_contains_max_concurrent_column(self):
        source = Path("app/core/db_migrations.py").read_text(encoding="utf-8")
        self.assertIn('"max_concurrent INTEGER"', source)

    def test_db_model_declares_max_concurrent(self):
        from app.core.db_models import Model

        self.assertTrue(hasattr(Model, "max_concurrent"))

    def test_list_serialization_exposes_max_concurrent(self):
        source = Path("app/routes/models.py").read_text(encoding="utf-8")
        self.assertIn('"max_concurrent"', source)

    def test_admin_template_exposes_standard_model_input(self):
        template_source = Path("web/templates/admin/config.html").read_text(encoding="utf-8")
        self.assertIn("model-max-concurrent", template_source)


class ProxyWrapperForwardTests(unittest.IsolatedAsyncioTestCase):
    """Regression: proxy.py's local handle_normal/handle_streaming wrappers must
    accept and forward model_concurrency_semaphore. A missing parameter made the
    wrapper raise TypeError before the runtime handler's finally could release
    the provider-key semaphore, leaking one slot per request until every key
    semaphore saturated and all traffic returned 429."""

    async def test_handle_normal_wrapper_forwards_model_semaphore(self):
        from unittest.mock import AsyncMock as _AM
        from app.services.proxy import handle_normal

        model_semaphore = object()
        runtime_handle = _AM(return_value=object())
        with patch("app.services.proxy.runtime_handle_normal", new=runtime_handle):
            result = await handle_normal(
                None, "https://example.com", {}, b"{}", "openai", "gpt",
                [], 0, {}, 1, "127.0.0.1", "test", 0,
                object(), object(),
                "req-1",
                model_concurrency_semaphore=model_semaphore,
            )
        self.assertIs(result, runtime_handle.return_value)
        self.assertIs(
            runtime_handle.await_args.kwargs["model_concurrency_semaphore"],
            model_semaphore,
        )

    async def test_handle_streaming_wrapper_forwards_model_semaphore(self):
        from unittest.mock import AsyncMock as _AM
        from app.services.proxy import handle_streaming

        model_semaphore = object()
        runtime_handle = _AM(return_value=object())
        with patch("app.services.proxy.runtime_handle_streaming", new=runtime_handle):
            result = await handle_streaming(
                "https://example.com", {}, b"{}", "openai", "gpt",
                [], 0, {}, 1, "127.0.0.1", "test", 0,
                object(), object(), object(),
                "req-1", None, None,
                model_concurrency_semaphore=model_semaphore,
            )
        self.assertIs(result, runtime_handle.return_value)
        self.assertIs(
            runtime_handle.await_args.kwargs["model_concurrency_semaphore"],
            model_semaphore,
        )

    async def test_end_to_end_with_limited_model_releases_all_semaphores(self):
        """Full proxy_request pass through the REAL wrappers: with a positive
        model limit the provider-key semaphore must be released, not leaked."""
        provider_service._model_max_concurrent_by_name.clear()
        standard_model_semaphores.clear()
        user_api_key_semaphores.clear()
        config.api_keys_cache.clear()
        config.api_keys_cache["test-key"] = {"id": 1, "bypass_busyness": True, "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000))}
        try:
            provider_service._model_max_concurrent_by_name["leak-test"] = 2
            route = proxy_module.RouteResult(
                provider_config={
                    "id": 1,
                    "base_url": "https://primary.example/v1",
                    "protocol": "openai",
                    "api_keys": [{"id": 11, "api_key": "sk-a", "max_concurrent": 1}],
                    "models": [{"id": 91, "model_id": 101, "model_name": "leak-test"}],
                },
                provider_name="primary",
                provider_id=1,
                provider_model_id=91,
                model_id=101,
                requested_model="leak-test",
                model_name="leak-test",
                upstream_model_name="leak-test",
                is_forced_provider=False,
            )
            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/v1/chat/completions",
                    "headers": [],
                    "query_string": b"",
                    "cookies": {},
                    "root_url": "",
                    "root_path": "",
                }
            )
            request._body = b'{"model":"leak-test","messages":[]}'

            from app.core.config import provider_key_semaphores
            from fastapi.responses import Response

            provider_key_semaphores.clear()

            async def fake_runtime_normal(**kwargs):
                if kwargs.get("provider_key_semaphore") is not None:
                    kwargs["provider_key_semaphore"].release()
                if kwargs.get("user_provider_model_semaphore") is not None:
                    kwargs["user_provider_model_semaphore"].release()
                if kwargs.get("model_concurrency_semaphore") is not None:
                    kwargs["model_concurrency_semaphore"].release()
                return Response(content=b'{"choices":[]}', status_code=200)

            import contextlib

            with contextlib.ExitStack() as stack:
                stack.enter_context(patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(1, None))))
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
                stack.enter_context(
                    patch(
                        "app.services.proxy.runtime_handle_normal",
                        new=AsyncMock(side_effect=fake_runtime_normal),
                    )
                )
                response = await proxy_request(request, "/chat/completions")

            self.assertEqual(response.status_code, 200)
            pk_sem = provider_key_semaphores.get("11:primary")
            self.assertIsNotNone(pk_sem)
            self.assertEqual(getattr(pk_sem, "_value"), 1)
            std_sem = standard_model_semaphores.get("stdmodel:leak-test")
            self.assertIsNotNone(std_sem)
            self.assertEqual(getattr(std_sem, "_value"), 2)
        finally:
            provider_service._model_max_concurrent_by_name.clear()
            standard_model_semaphores.clear()
            user_api_key_semaphores.clear()
            config.api_keys_cache.clear()


if __name__ == "__main__":
    unittest.main()
