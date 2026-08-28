import asyncio
import contextlib
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import Request
from fastapi.responses import Response

import app.core.config as config
from app.core.config import user_api_key_semaphores
from app.services import proxy as proxy_module
from app.services import provider as provider_service
from app.services.proxy import proxy_request
from app.services.proxy_runtime import _get_user_api_key_limit


class UserApiKeyLimitParsingTests(unittest.TestCase):
    def test_missing_stored_limit_defaults_to_one(self):
        self.assertEqual(_get_user_api_key_limit(False), 1)

    def test_none_stored_limit_defaults_to_one(self):
        self.assertEqual(_get_user_api_key_limit(False, None), 1)

    def test_explicit_zero_is_zero(self):
        self.assertEqual(_get_user_api_key_limit(False, 0), 0)

    def test_positive_value_passthrough(self):
        self.assertEqual(_get_user_api_key_limit(False, 5), 5)

    def test_negative_treated_as_default(self):
        self.assertEqual(_get_user_api_key_limit(False, -7), 1)

    def test_bypass_busyness_still_9999(self):
        self.assertEqual(_get_user_api_key_limit(True, 0), 9999)


def _build_route(model_name: str) -> proxy_module.RouteResult:
    return proxy_module.RouteResult(
        provider_config={
            "id": 1,
            "base_url": "https://primary.example/v1",
            "protocol": "openai",
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


def _build_request(model_name: str) -> Request:
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
    request._body = json.dumps({"model": model_name, "messages": []}).encode()
    return request


class UserApiKeyMaxConcurrentEndToEndTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        user_api_key_semaphores.clear()
        config.api_keys_cache.clear()
        provider_service._model_max_concurrent_by_name.clear()
        from app.core.config import provider_key_semaphores

        provider_key_semaphores.clear()

    def tearDown(self):
        user_api_key_semaphores.clear()
        config.api_keys_cache.clear()
        provider_service._model_max_concurrent_by_name.clear()
        from app.core.config import provider_key_semaphores

        provider_key_semaphores.clear()

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

    async def test_zero_limit_key_rejected_immediately_with_429(self):
        config.api_keys_cache["test-key"] = {
            "id": 1,
            "bypass_busyness": False,
            "max_concurrent": 0,
            "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000)),
        }
        route = _build_route("any-model")
        request = _build_request("any-model")
        runtime_normal = AsyncMock(return_value=Response(status_code=200))

        with contextlib.ExitStack() as stack:
            self._patch_common(stack, route)
            stack.enter_context(
                patch("app.services.proxy.runtime_handle_normal", new=runtime_normal)
            )
            response = await proxy_request(request, "/chat/completions")

        self.assertEqual(response.status_code, 429)
        payload = json.loads(response.body)
        self.assertEqual(
            payload["error"]["code"], "user_global_concurrency_reached"
        )
        runtime_normal.assert_not_awaited()
        sem = user_api_key_semaphores.get("user:1")
        self.assertIsNotNone(sem)
        self.assertEqual(getattr(sem, "_modelgate_scoped_limit"), 0)

    async def test_positive_limit_key_acquires_and_releases(self):
        config.api_keys_cache["test-key"] = {
            "id": 1,
            "bypass_busyness": False,
            "max_concurrent": 1,
            "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000)),
        }
        route = _build_route("any-model")
        request = _build_request("any-model")

        async def fake_runtime_normal(**kwargs):
            if kwargs.get("provider_key_semaphore") is not None:
                kwargs["provider_key_semaphore"].release()
            if kwargs.get("user_provider_model_semaphore") is not None:
                kwargs["user_provider_model_semaphore"].release()
            if kwargs.get("user_api_key_semaphore") is not None:
                kwargs["user_api_key_semaphore"].release()
            return Response(content=b'{"choices":[]}', status_code=200)

        with contextlib.ExitStack() as stack:
            self._patch_common(stack, route)
            stack.enter_context(
                patch(
                    "app.services.proxy.runtime_handle_normal",
                    new=AsyncMock(side_effect=fake_runtime_normal),
                )
            )
            response = await proxy_request(request, "/chat/completions")

        self.assertEqual(response.status_code, 200)
        sem = user_api_key_semaphores.get("user:1")
        self.assertIsNotNone(sem)
        self.assertEqual(getattr(sem, "_modelgate_scoped_limit"), 1)
        # Released after the request: back to full capacity.
        self.assertEqual(getattr(sem, "_value"), 1)


if __name__ == "__main__":
    unittest.main()
