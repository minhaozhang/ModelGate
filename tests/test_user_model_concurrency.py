import contextlib
import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

from fastapi import Request
from fastapi.responses import Response

import app.core.config as config
from app.core.config import user_model_semaphores
from app.services import proxy as proxy_module
from app.services import provider as provider_service
from app.services.proxy import proxy_request
from app.services.proxy_runtime import (
    _get_user_model_limit,
)
from app.services.proxy_runtime.concurrency import (
    _model_gauge_cap,
    _time_cap,
)


class UserModelGaugeCapTests(unittest.TestCase):
    def setUp(self):
        from app.core.config import standard_model_semaphores

        standard_model_semaphores.clear()

    def tearDown(self):
        from app.core.config import standard_model_semaphores

        standard_model_semaphores.clear()

    def _make_sem(self, limit, value, waiters=None):
        sem = Mock()
        sem._modelgate_scoped_limit = limit
        sem._value = value
        sem._waiters = waiters
        return sem

    def test_no_semaphore_defaults_to_two(self):
        self.assertEqual(_model_gauge_cap("any-model"), 2)

    def test_zero_or_negative_limit_defaults_to_two(self):
        from app.core.config import standard_model_semaphores

        standard_model_semaphores["stdmodel:m"] = self._make_sem(0, 0)
        self.assertEqual(_model_gauge_cap("m"), 2)

    def test_saturated_with_waiters_caps_one(self):
        from app.core.config import standard_model_semaphores

        standard_model_semaphores["stdmodel:m"] = self._make_sem(4, 0, waiters=[object()])
        self.assertEqual(_model_gauge_cap("m"), 1)

    def test_no_available_slots_caps_one(self):
        from app.core.config import standard_model_semaphores

        standard_model_semaphores["stdmodel:m"] = self._make_sem(4, 0)
        self.assertEqual(_model_gauge_cap("m"), 1)

    def test_half_capacity_caps_two(self):
        from app.core.config import standard_model_semaphores

        standard_model_semaphores["stdmodel:m"] = self._make_sem(4, 2)
        self.assertEqual(_model_gauge_cap("m"), 2)

    def test_low_capacity_caps_one(self):
        from app.core.config import standard_model_semaphores

        standard_model_semaphores["stdmodel:m"] = self._make_sem(4, 1)
        self.assertEqual(_model_gauge_cap("m"), 1)


class UserTimeCapTests(unittest.TestCase):
    def setUp(self):
        config.system_settings["concurrency.offpeak_start_hour"] = "20"
        config.system_settings["concurrency.offpeak_end_hour"] = "11"
        config.system_settings["concurrency.peak_user_model_limit"] = "2"
        config.system_settings["concurrency.offpeak_user_model_limit"] = "1"

    def tearDown(self):
        for key in (
            "concurrency.offpeak_start_hour",
            "concurrency.offpeak_end_hour",
            "concurrency.peak_user_model_limit",
            "concurrency.offpeak_user_model_limit",
        ):
            config.system_settings.pop(key, None)

    def test_peak_hour_uses_peak_limit(self):
        self.assertEqual(_time_cap(datetime(2026, 9, 26, 14, 0)), 2)

    def test_offpeak_evening_uses_offpeak_limit(self):
        self.assertEqual(_time_cap(datetime(2026, 9, 26, 21, 0)), 1)

    def test_offpeak_after_midnight_uses_offpeak_limit(self):
        self.assertEqual(_time_cap(datetime(2026, 9, 26, 3, 0)), 1)

    def test_equal_start_end_means_no_window(self):
        config.system_settings["concurrency.offpeak_start_hour"] = "20"
        config.system_settings["concurrency.offpeak_end_hour"] = "20"
        self.assertEqual(_time_cap(datetime(2026, 9, 26, 3, 0)), 2)

    def test_invalid_setting_falls_back(self):
        config.system_settings["concurrency.peak_user_model_limit"] = "bogus"
        self.assertEqual(_time_cap(datetime(2026, 9, 26, 14, 0)), 2)


class UserModelLimitTests(unittest.TestCase):
    def setUp(self):
        config.system_settings["concurrency.peak_user_model_limit"] = "2"
        config.system_settings["concurrency.offpeak_user_model_limit"] = "2"
        config.system_settings["concurrency.offpeak_start_hour"] = "20"
        config.system_settings["concurrency.offpeak_end_hour"] = "11"

    def tearDown(self):
        for key in (
            "concurrency.offpeak_start_hour",
            "concurrency.offpeak_end_hour",
            "concurrency.peak_user_model_limit",
            "concurrency.offpeak_user_model_limit",
        ):
            config.system_settings.pop(key, None)
        from app.core.config import standard_model_semaphores

        standard_model_semaphores.clear()

    def test_bypass_returns_9999(self):
        self.assertEqual(_get_user_model_limit(True, "m"), 9999)

    def test_dynamic_uses_gauge_and_time_cap(self):
        from app.core.config import standard_model_semaphores

        sem = Mock()
        sem._modelgate_scoped_limit = 4
        sem._value = 3
        sem._waiters = None
        standard_model_semaphores["stdmodel:m"] = sem
        self.assertEqual(_get_user_model_limit(False, "m"), 2)

    def test_no_config_uses_time_cap_only(self):
        self.assertEqual(_get_user_model_limit(False, "unknown"), 2)

    def test_model_cfg_fixed_cap(self):
        self.assertEqual(
            _get_user_model_limit(False, "m", model_cfg=3), 3
        )

    def test_model_cfg_zero_disables(self):
        self.assertEqual(
            _get_user_model_limit(False, "m", model_cfg=0), 0
        )

    def test_model_cfg_none_falls_back_to_dynamic(self):
        self.assertEqual(
            _get_user_model_limit(False, "unknown", model_cfg=None), 2
        )

    def test_bypass_beats_model_cfg(self):
        self.assertEqual(
            _get_user_model_limit(True, "m", model_cfg=0), 9999
        )


class UserModelIndexedTiersTests(unittest.TestCase):
    TIERS = [{"min_idle_pct": 80, "limit": 4}, {"min_idle_pct": 50, "limit": 2}]

    def setUp(self):
        from app.core.config import standard_model_semaphores

        standard_model_semaphores.clear()

    def tearDown(self):
        from app.core.config import standard_model_semaphores

        standard_model_semaphores.clear()

    def _set_idle(self, limit, available, waiters=None):
        from app.core.config import standard_model_semaphores

        sem = Mock()
        sem._modelgate_scoped_limit = limit
        sem._value = available
        sem._waiters = waiters
        standard_model_semaphores["stdmodel:m"] = sem

    def test_fully_idle_hits_top_tier(self):
        self._set_idle(10, 10)
        self.assertEqual(
            _get_user_model_limit(False, "m", model_tiers=self.TIERS), 4
        )

    def test_eighty_pct_idle_hits_top_tier(self):
        self._set_idle(10, 8)
        self.assertEqual(
            _get_user_model_limit(False, "m", model_tiers=self.TIERS), 4
        )

    def test_sixty_pct_idle_hits_second_tier(self):
        self._set_idle(10, 6)
        self.assertEqual(
            _get_user_model_limit(False, "m", model_tiers=self.TIERS), 2
        )

    def test_busy_below_all_tiers_falls_back_to_dynamic(self):
        self._set_idle(10, 3)
        # gauge cap 1 x time cap 2 -> 1
        self.assertEqual(
            _get_user_model_limit(False, "m", model_tiers=self.TIERS), 1
        )

    def test_waiters_count_as_zero_idle_for_tiers(self):
        self._set_idle(10, 9, waiters=[object()])
        # idle treated as 0 -> below all tiers -> dynamic (gauge cap 1)
        self.assertEqual(
            _get_user_model_limit(False, "m", model_tiers=self.TIERS), 1
        )

    def test_no_gauge_means_idle_hits_top_tier(self):
        self.assertEqual(
            _get_user_model_limit(False, "m", model_tiers=self.TIERS), 4
        )

    def test_tier_zero_disables(self):
        tiers = [{"min_idle_pct": 0, "limit": 0}]
        self.assertEqual(
            _get_user_model_limit(False, "m", model_tiers=tiers), 0
        )

    def test_model_cfg_fixed_cap_beats_tiers(self):
        self._set_idle(10, 10)
        self.assertEqual(
            _get_user_model_limit(False, "m", model_cfg=3, model_tiers=self.TIERS), 3
        )

    def test_key_concurrency_narrows_tier(self):
        self._set_idle(10, 10)
        self.assertEqual(
            _get_user_model_limit(
                False, "m", model_tiers=self.TIERS, key_max_concurrent=2
            ),
            2,
        )

    def test_key_concurrency_narrows_fixed_cap(self):
        self.assertEqual(
            _get_user_model_limit(
                False, "m", model_cfg=5, key_max_concurrent=3
            ),
            3,
        )

    def test_key_concurrency_narrows_dynamic(self):
        self.assertEqual(
            _get_user_model_limit(
                False, "unknown", key_max_concurrent=1
            ),
            1,
        )

    def test_key_zero_disables(self):
        self._set_idle(10, 10)
        self.assertEqual(
            _get_user_model_limit(
                False, "m", model_tiers=self.TIERS, key_max_concurrent=0
            ),
            0,
        )


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


class UserModelCreatingEndToEndTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        user_model_semaphores.clear()
        config.api_keys_cache.clear()
        provider_service._model_max_concurrent_by_name.clear()
        from app.core.config import user_api_key_semaphores, provider_key_semaphores, standard_model_semaphores

        user_api_key_semaphores.clear()
        provider_key_semaphores.clear()
        standard_model_semaphores.clear()

    def tearDown(self):
        user_model_semaphores.clear()
        config.api_keys_cache.clear()
        provider_service._model_max_concurrent_by_name.clear()
        from app.core.config import user_api_key_semaphores, provider_key_semaphores, standard_model_semaphores

        user_api_key_semaphores.clear()
        provider_key_semaphores.clear()
        standard_model_semaphores.clear()

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

    async def test_model_level_zero_rejected_with_429(self):
        from app.services.provider import (
            _model_per_key_concurrency_by_name,
        )

        _model_per_key_concurrency_by_name["any-model"] = 0
        try:
            config.api_keys_cache["test-key"] = {
                "id": 1,
                "bypass_busyness": False,
                "max_concurrent": None,
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
            self.assertEqual(payload["error"]["code"], "user_model_concurrency_reached")
            runtime_normal.assert_not_awaited()
            sem = user_model_semaphores.get("usermodel:1:any-model")
            self.assertIsNotNone(sem)
            self.assertEqual(getattr(sem, "_modelgate_scoped_limit"), 0)
        finally:
            _model_per_key_concurrency_by_name.clear()

    async def test_model_level_fixed_cap_applies(self):
        from app.services.provider import (
            _model_per_key_concurrency_by_name,
        )

        _model_per_key_concurrency_by_name["any-model"] = 4
        try:
            config.api_keys_cache["test-key"] = {
                "id": 1,
                "bypass_busyness": False,
                "max_concurrent": 9,
                "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000)),
            }
            route = _build_route("any-model")
            request = _build_request("any-model")

            async def fake_runtime_normal(**kwargs):
                if kwargs.get("provider_key_semaphore") is not None:
                    kwargs["provider_key_semaphore"].release()
                if kwargs.get("user_provider_model_semaphore") is not None:
                    kwargs["user_provider_model_semaphore"].release()
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
            sem = user_model_semaphores.get("usermodel:1:any-model")
            self.assertIsNotNone(sem)
            self.assertEqual(getattr(sem, "_modelgate_scoped_limit"), 4)
            self.assertEqual(getattr(sem, "_value"), 4)
        finally:
            _model_per_key_concurrency_by_name.clear()

    async def test_model_tiers_narrowed_by_key_concurrency(self):
        from app.services.provider import (
            _model_per_key_concurrency_tiers_by_name,
        )

        _model_per_key_concurrency_tiers_by_name["any-model"] = [
            {"min_idle_pct": 80, "limit": 4},
            {"min_idle_pct": 50, "limit": 2},
        ]
        try:
            config.api_keys_cache["test-key"] = {
                "id": 1,
                "bypass_busyness": False,
                "max_concurrent": 2,
                "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000)),
            }
            route = _build_route("any-model")
            request = _build_request("any-model")

            async def fake_runtime_normal(**kwargs):
                if kwargs.get("provider_key_semaphore") is not None:
                    kwargs["provider_key_semaphore"].release()
                if kwargs.get("user_provider_model_semaphore") is not None:
                    kwargs["user_provider_model_semaphore"].release()
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
            sem = user_model_semaphores.get("usermodel:1:any-model")
            self.assertIsNotNone(sem)
            # top tier 4 (no gauge -> idle 100%) narrowed by key's own 2
            self.assertEqual(getattr(sem, "_modelgate_scoped_limit"), 2)
        finally:
            _model_per_key_concurrency_tiers_by_name.clear()

    async def test_bypass_skips_model_layer_entirely(self):
        from app.services.provider import (
            _model_per_key_concurrency_by_name,
        )

        _model_per_key_concurrency_by_name["any-model"] = 0
        try:
            config.api_keys_cache["test-key"] = {
                "id": 1,
                "bypass_busyness": True,
                "max_concurrent": None,
                "allowed_provider_model_ids": list(range(1, 1000)), "allowed_model_ids": list(range(1, 1000)),
            }
            route = _build_route("any-model")
            request = _build_request("any-model")

            async def fake_runtime_normal(**kwargs):
                if kwargs.get("provider_key_semaphore") is not None:
                    kwargs["provider_key_semaphore"].release()
                if kwargs.get("user_provider_model_semaphore") is not None:
                    kwargs["user_provider_model_semaphore"].release()
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
            self.assertIsNone(user_model_semaphores.get("usermodel:1:any-model"))
        finally:
            _model_per_key_concurrency_by_name.clear()


if __name__ == "__main__":
    unittest.main()
