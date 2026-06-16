import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.core import config
from app.core.i18n import render
from app.routes.models import resolve_model
from app.routes.proxy import list_models
from app.services import auto_model_routes as auto_route_service
from app.services import provider as provider_service
from app.services.auth import validate_api_key
from app.services.proxy import (
    build_model_access_denied_message,
    check_model_access,
    proxy_request,
)
from tests.test_opencode_security import make_request


class ModelNameRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_providers_cache = dict(config.providers_cache)
        self.original_api_keys_cache = dict(config.api_keys_cache)
        self.original_system_settings = dict(config.system_settings)
        self.original_auto_routes = dict(auto_route_service._auto_model_routes_cache)
        self.original_alias_index = dict(provider_service._alias_index)
        self.original_model_name_index = dict(
            getattr(provider_service, "_model_name_index", {})
        )
        config.providers_cache.clear()
        config.api_keys_cache.clear()
        config.system_settings.clear()
        auto_route_service._auto_model_routes_cache.clear()
        provider_service._alias_index.clear()
        if hasattr(provider_service, "_model_name_index"):
            provider_service._model_name_index.clear()

    def tearDown(self):
        config.providers_cache.clear()
        config.providers_cache.update(self.original_providers_cache)
        config.api_keys_cache.clear()
        config.api_keys_cache.update(self.original_api_keys_cache)
        config.system_settings.clear()
        config.system_settings.update(self.original_system_settings)
        auto_route_service._auto_model_routes_cache.clear()
        auto_route_service._auto_model_routes_cache.update(self.original_auto_routes)
        provider_service._alias_index.clear()
        provider_service._alias_index.update(self.original_alias_index)
        if hasattr(provider_service, "_model_name_index"):
            provider_service._model_name_index.clear()
            provider_service._model_name_index.update(self.original_model_name_index)

    def enable_auto_route(self, model_ids=None, provider_model_ids=None):
        auto_route_service._auto_model_routes_cache["auto"] = {
            "model_name": "auto",
            "virtual_model_id": 999,
            "enabled": True,
            "model_ids": model_ids or [],
            "provider_model_ids": provider_model_ids or [],
            "route_policy": {},
        }

    async def test_model_name_routes_to_best_provider_and_keeps_upstream_name(self):
        config.providers_cache.update(
            {
                "slow": {
                    "id": 1,
                    "base_url": "https://slow.example/v1",
                    "api_key": "slow-key",
                    "api_keys": [],
                    "models": [
                        {
                            "id": 11,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "glm-5.1",
                            "model_tags": "",
                            "priority": 0,
                        }
                    ],
                },
                "fast": {
                    "id": 2,
                    "base_url": "https://fast.example/v1",
                    "api_key": "fast-key",
                    "api_keys": [],
                    "models": [
                        {
                            "id": 22,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "local_model",
                            "model_tags": "",
                            "priority": 5,
                        }
                    ],
                },
            }
        )
        provider_service._model_name_index["glm-5.1"] = [
            ("slow", config.providers_cache["slow"]["models"][0], "", 0),
            ("fast", config.providers_cache["fast"]["models"][0], "", 5),
        ]

        route = await provider_service.get_provider_and_model("glm-5.1")

        self.assertEqual(route.provider_name, "fast")
        self.assertEqual(route.model_name, "glm-5.1")
        self.assertEqual(route.upstream_model_name, "local_model")
        self.assertEqual(route.provider_model_id, 22)
        self.assertEqual(route.model_id, 101)

    async def test_model_name_skips_disabled_high_priority_provider_model(self):
        config.providers_cache.update(
            {
                "disabled-fast": {
                    "id": 1,
                    "base_url": "https://disabled.example/v1",
                    "api_key": "disabled-key",
                    "api_keys": [],
                    "disabled_reason": "quota exceeded",
                    "models": [
                        {
                            "id": 11,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "disabled-upstream",
                            "model_tags": "",
                            "priority": 100,
                        }
                    ],
                },
                "available-slow": {
                    "id": 2,
                    "base_url": "https://available.example/v1",
                    "api_key": "available-key",
                    "api_keys": [],
                    "models": [
                        {
                            "id": 22,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "available-upstream",
                            "model_tags": "",
                            "priority": 1,
                        }
                    ],
                },
            }
        )
        provider_service._model_name_index["glm-5.1"] = [
            (
                "disabled-fast",
                config.providers_cache["disabled-fast"]["models"][0],
                "",
                100,
            ),
            (
                "available-slow",
                config.providers_cache["available-slow"]["models"][0],
                "",
                1,
            ),
        ]

        route = await provider_service.get_provider_and_model("glm-5.1")

        self.assertEqual(route.provider_name, "available-slow")
        self.assertEqual(route.upstream_model_name, "available-upstream")
        self.assertEqual(route.provider_model_id, 22)

    async def test_model_name_priority_beats_health(self):
        config.providers_cache.update(
            {
                "zhipu": {
                    "id": 1,
                    "base_url": "https://zhipu.example/v1",
                    "api_key": "",
                    "api_keys": [
                        {
                            "id": 11,
                            "api_key": "zhipu-key",
                            "is_active": True,
                        }
                    ],
                    "models": [
                        {
                            "id": 91,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "glm-5.1",
                            "model_tags": "",
                            "priority": 1,
                        }
                    ],
                },
                "jintou": {
                    "id": 6,
                    "base_url": "http://jintou.example/v1",
                    "api_key": "",
                    "api_keys": [
                        {
                            "id": 16,
                            "api_key": "jintou-key",
                            "is_active": True,
                        }
                    ],
                    "models": [
                        {
                            "id": 16,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "local_model",
                            "model_tags": "",
                            "priority": 2,
                        }
                    ],
                },
            }
        )
        provider_service._model_name_index["glm-5.1"] = [
            ("zhipu", config.providers_cache["zhipu"]["models"][0], "", 1),
            ("jintou", config.providers_cache["jintou"]["models"][0], "", 2),
        ]

        with patch("app.services.provider.compute_health_score", return_value=100):
            route = await provider_service.get_provider_and_model("glm-5.1")

        self.assertEqual(route.provider_name, "jintou")
        self.assertEqual(route.upstream_model_name, "local_model")
        self.assertEqual(route.provider_model_id, 16)

    async def test_provider_model_candidates_keep_sorted_fallback_order(self):
        config.providers_cache.update(
            {
                "primary": {
                    "id": 1,
                    "base_url": "https://primary.example/v1",
                    "api_key": "",
                    "api_keys": [{"id": 11, "api_key": "primary-key"}],
                    "models": [
                        {
                            "id": 91,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "glm-5.1",
                            "model_tags": "",
                            "priority": 100,
                        }
                    ],
                },
                "fallback": {
                    "id": 2,
                    "base_url": "https://fallback.example/v1",
                    "api_key": "",
                    "api_keys": [{"id": 12, "api_key": "fallback-key"}],
                    "models": [
                        {
                            "id": 92,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "local_model",
                            "model_tags": "",
                            "priority": 10,
                        }
                    ],
                },
            }
        )
        provider_service._model_name_index["glm-5.1"] = [
            ("fallback", config.providers_cache["fallback"]["models"][0], "", 10),
            ("primary", config.providers_cache["primary"]["models"][0], "", 100),
        ]

        routes = await provider_service.get_provider_model_candidates("glm-5.1")

        self.assertEqual([r.provider_name for r in routes], ["primary", "fallback"])
        self.assertEqual([r.upstream_model_name for r in routes], ["glm-5.1", "local_model"])

    async def test_provider_model_rule_can_prefer_small_context_provider(self):
        config.providers_cache.update(
            {
                "zhipu": {
                    "id": 1,
                    "base_url": "https://zhipu.example/v1",
                    "api_key": "",
                    "api_keys": [{"id": 11, "api_key": "zhipu-key"}],
                    "models": [
                        {
                            "id": 91,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "glm-5.1",
                            "model_tags": "",
                            "priority": 100,
                        }
                    ],
                },
                "jintou": {
                    "id": 2,
                    "base_url": "https://jintou.example/v1",
                    "api_key": "",
                    "api_keys": [{"id": 12, "api_key": "jintou-key"}],
                    "models": [
                        {
                            "id": 92,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "local_model",
                            "model_tags": "",
                            "priority": 10,
                            "routing_rules": [
                                {
                                    "id": 1,
                                    "action": "prefer",
                                    "enabled": True,
                                    "priority": 120,
                                    "max_context_tokens": 8000,
                                }
                            ],
                        }
                    ],
                },
            }
        )
        provider_service._model_name_index["glm-5.1"] = [
            ("zhipu", config.providers_cache["zhipu"]["models"][0], "", 100),
            ("jintou", config.providers_cache["jintou"]["models"][0], "", 10),
        ]

        routes = await provider_service.get_provider_model_candidates(
            "glm-5.1",
            context_tokens=2000,
            now=datetime(2026, 6, 14, 9, 30),
        )

        self.assertEqual([r.provider_name for r in routes], ["jintou", "zhipu"])
        self.assertEqual(routes[0].upstream_model_name, "local_model")

    async def test_provider_model_standby_rule_keeps_fallback_after_normal_routes(self):
        config.providers_cache.update(
            {
                "zhipu": {
                    "id": 1,
                    "base_url": "https://zhipu.example/v1",
                    "api_key": "",
                    "api_keys": [{"id": 11, "api_key": "zhipu-key"}],
                    "models": [
                        {
                            "id": 91,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "glm-5.1",
                            "model_tags": "",
                            "priority": 100,
                        }
                    ],
                },
                "metered": {
                    "id": 2,
                    "base_url": "https://metered.example/v1",
                    "api_key": "",
                    "api_keys": [{"id": 12, "api_key": "metered-key"}],
                    "models": [
                        {
                            "id": 92,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "glm-5.1-payg",
                            "model_tags": "",
                            "priority": 1000,
                            "routing_rules": [
                                {
                                    "id": 1,
                                    "action": "standby",
                                    "enabled": True,
                                    "priority": 0,
                                }
                            ],
                        }
                    ],
                },
            }
        )
        provider_service._model_name_index["glm-5.1"] = [
            ("metered", config.providers_cache["metered"]["models"][0], "", 1000),
            ("zhipu", config.providers_cache["zhipu"]["models"][0], "", 100),
        ]

        routes = await provider_service.get_provider_model_candidates(
            "glm-5.1",
            context_tokens=2000,
            now=datetime(2026, 6, 14, 9, 30),
        )

        self.assertEqual([r.provider_name for r in routes], ["zhipu", "metered"])
        self.assertEqual(routes[1].upstream_model_name, "glm-5.1-payg")

    async def test_provider_model_explanation_includes_standby_and_filtered_reasons(self):
        config.providers_cache.update(
            {
                "zhipu": {
                    "id": 1,
                    "base_url": "https://zhipu.example/v1",
                    "api_key": "",
                    "api_keys": [{"id": 11, "api_key": "zhipu-key"}],
                    "models": [
                        {
                            "id": 91,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "glm-5.1",
                            "model_tags": "",
                            "priority": 100,
                        }
                    ],
                },
                "metered": {
                    "id": 2,
                    "base_url": "https://metered.example/v1",
                    "api_key": "",
                    "api_keys": [{"id": 12, "api_key": "metered-key"}],
                    "models": [
                        {
                            "id": 92,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "glm-5.1-payg",
                            "model_tags": "",
                            "priority": 1000,
                            "routing_rules": [
                                {
                                    "id": 1,
                                    "name": "按量备用",
                                    "action": "standby",
                                    "enabled": True,
                                }
                            ],
                        }
                    ],
                },
                "blocked": {
                    "id": 3,
                    "base_url": "https://blocked.example/v1",
                    "api_key": "",
                    "api_keys": [{"id": 13, "api_key": "blocked-key"}],
                    "models": [
                        {
                            "id": 93,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "glm-5.1-blocked",
                            "model_tags": "",
                            "priority": 2000,
                            "routing_rules": [
                                {
                                    "id": 2,
                                    "name": "下午禁用",
                                    "action": "deny",
                                    "enabled": True,
                                    "start_time": "13:00",
                                    "end_time": "18:00",
                                }
                            ],
                        }
                    ],
                },
            }
        )
        provider_service._model_name_index["glm-5.1"] = [
            ("blocked", config.providers_cache["blocked"]["models"][0], "", 2000),
            ("metered", config.providers_cache["metered"]["models"][0], "", 1000),
            ("zhipu", config.providers_cache["zhipu"]["models"][0], "", 100),
        ]

        explanation = await provider_service.explain_provider_model_candidates(
            "glm-5.1",
            context_tokens=2000,
            now=datetime(2026, 6, 14, 14, 30),
        )

        self.assertEqual(
            [item["provider"] for item in explanation["ordered"]],
            ["zhipu", "metered"],
        )
        self.assertTrue(explanation["ordered"][1]["standby"])
        self.assertIn("按量备用", explanation["ordered"][1]["matched_rules"])
        self.assertEqual(explanation["filtered"][0]["provider"], "blocked")
        self.assertIn("route_denied", explanation["filtered"][0]["filtered_reasons"])

    async def test_resolve_model_uses_same_priority_order_as_runtime_routing(self):
        config.providers_cache.update(
            {
                "zhipu": {
                    "id": 1,
                    "base_url": "https://zhipu.example/v1",
                    "api_key": "",
                    "api_keys": [{"id": 11, "api_key": "zhipu-key"}],
                    "models": [
                        {
                            "id": 91,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "glm-5.1",
                            "model_tags": "",
                            "priority": 1,
                        }
                    ],
                },
                "jintou": {
                    "id": 6,
                    "base_url": "http://jintou.example/v1",
                    "api_key": "",
                    "api_keys": [{"id": 16, "api_key": "jintou-key"}],
                    "models": [
                        {
                            "id": 16,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "local_model",
                            "model_tags": "",
                            "priority": 2,
                        }
                    ],
                },
            }
        )
        provider_service._model_name_index["glm-5.1"] = [
            ("zhipu", config.providers_cache["zhipu"]["models"][0], "", 1),
            ("jintou", config.providers_cache["jintou"]["models"][0], "", 2),
        ]

        with patch("app.services.key_health.compute_health_score", return_value=100):
            result = await resolve_model("glm-5.1", True)

        self.assertEqual(result["selected"], "jintou")
        self.assertEqual(result["providers"][0]["provider"], "jintou")

    async def test_validate_api_key_no_longer_allows_model_name_without_access_check(self):
        config.api_keys_cache["mg_test"] = {
            "id": 7,
            "name": "limited",
            "allowed_provider_model_ids": [22],
            "allowed_model_ids": [],
            "time_rules": [],
        }

        api_key_id, error = await validate_api_key("Bearer mg_test", "glm-5.1")

        self.assertEqual(api_key_id, 7)
        self.assertIsNone(error)
        self.assertFalse(
            check_model_access(
                config.api_keys_cache["mg_test"],
                provider_model_id=99,
                model_id=101,
            )
        )
        self.assertTrue(
            check_model_access(
                config.api_keys_cache["mg_test"],
                provider_model_id=22,
                model_id=101,
            )
        )

    async def test_validate_api_key_rejects_expired_key(self):
        config.api_keys_cache["mg_expired"] = {
            "id": 8,
            "name": "expired",
            "allowed_provider_model_ids": [],
            "allowed_model_ids": [],
            "time_rules": [],
            "expires_at": datetime.now() - timedelta(seconds=1),
        }

        api_key_id, error = await validate_api_key("Bearer mg_expired", "glm-5.1")

        self.assertIsNone(api_key_id)
        self.assertIn("API Key 已过期", error)

    def test_model_access_denied_message_guides_user_to_permissions_and_opencode(self):
        message = build_model_access_denied_message("glm-5.1")

        self.assertIn("glm-5.1", message)
        self.assertIn("没有模型权限", message)
        self.assertIn("https://leturx.cc/modelgate/user/login", message)
        self.assertIn("OpenCode", message)
        self.assertIn("重新获取或更新", message)
        self.assertNotIn("api_key=", message)

    async def test_proxy_model_access_denied_returns_actionable_guidance(self):
        config.api_keys_cache["mg_test"] = {
            "id": 7,
            "name": "limited",
            "allowed_provider_model_ids": [22],
            "allowed_model_ids": [],
            "time_rules": [],
        }
        request = make_request("/v1/chat/completions")
        request._body = b'{"model":"glm-5.1","messages":[]}'
        route = provider_service.RouteResult(
            provider_config={"id": 1, "models": []},
            provider_name="zhipu",
            provider_id=1,
            provider_model_id=99,
            model_id=101,
            requested_model="glm-5.1",
            model_name="glm-5.1",
            upstream_model_name="glm-5.1",
        )

        with (
            patch(
                "app.services.proxy.validate_api_key",
                new=AsyncMock(return_value=(7, None)),
            ),
            patch(
                "app.services.proxy.explain_provider_model_candidates",
                new=AsyncMock(return_value={"ordered": [], "filtered": []}),
            ),
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=[route]),
            ),
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        body = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 401)
        self.assertIn("model_access_denied", body)
        self.assertIn("没有模型权限", body)
        self.assertIn("https://leturx.cc/modelgate/user/login", body)
        self.assertIn("OpenCode", body)
        self.assertNotIn("mg_test", body)
        self.assertNotIn("api_key=", body)

    async def test_proxy_rejects_forced_provider_route_with_model_only_access(self):
        config.api_keys_cache["mg_test"] = {
            "id": 7,
            "name": "model-only",
            "allowed_provider_model_ids": [],
            "allowed_model_ids": [101],
            "time_rules": [],
        }
        request = make_request("/v1/chat/completions")
        request._body = b'{"model":"zhipu/glm-5.1","messages":[]}'
        route = provider_service.RouteResult(
            provider_config={"id": 1, "models": []},
            provider_name="zhipu",
            provider_id=1,
            provider_model_id=99,
            model_id=101,
            requested_model="zhipu/glm-5.1",
            model_name="glm-5.1",
            upstream_model_name="glm-5.1",
            is_forced_provider=True,
        )

        with (
            patch(
                "app.services.proxy.validate_api_key",
                new=AsyncMock(return_value=(7, None)),
            ),
            patch(
                "app.services.proxy.explain_provider_model_candidates",
                new=AsyncMock(return_value={"ordered": [], "filtered": []}),
            ),
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=[route]),
            ),
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        body = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 401)
        self.assertIn("model_access_denied", body)
        self.assertIn("zhipu/glm-5.1", body)

    async def test_model_access_binding_allows_auto_routed_provider_model_for_same_model(self):
        key_info = {
            "allowed_provider_model_ids": [],
            "allowed_model_ids": [101],
        }

        self.assertTrue(
            check_model_access(
                key_info,
                provider_model_id=99,
                model_id=101,
                is_forced_provider=False,
            )
        )
        self.assertFalse(
            check_model_access(
                key_info,
                provider_model_id=99,
                model_id=202,
                is_forced_provider=False,
            )
        )

    async def test_model_access_binding_allows_auto_request_without_underlying_model_access(self):
        key_info = {
            "allowed_provider_model_ids": [],
            "allowed_model_ids": [999],
        }

        self.assertTrue(
            check_model_access(
                key_info,
                provider_model_id=99,
                model_id=101,
                requested_model_id=999,
                is_forced_provider=False,
            )
        )
        self.assertFalse(
            check_model_access(
                key_info,
                provider_model_id=99,
                model_id=101,
                requested_model_id=None,
                is_forced_provider=False,
            )
        )

    async def test_model_access_binding_does_not_allow_forced_provider_route(self):
        key_info = {
            "allowed_provider_model_ids": [],
            "allowed_model_ids": [101],
        }

        self.assertFalse(
            check_model_access(
                key_info,
                provider_model_id=99,
                model_id=101,
                is_forced_provider=True,
            )
        )
        self.assertTrue(
            check_model_access(
                {
                    "allowed_provider_model_ids": [99],
                    "allowed_model_ids": [],
                },
                provider_model_id=99,
                model_id=101,
                is_forced_provider=True,
            )
        )

    async def test_list_models_returns_deduped_model_names_without_providers(self):
        config.providers_cache.update(
            {
                "zhipu": {
                    "models": [
                        {
                            "model_name": "glm-5",
                            "actual_model_name": "glm-5",
                        }
                    ]
                },
                "deepseek": {
                    "models": [
                        {
                            "model_name": "glm-5",
                            "actual_model_name": "glm-5",
                        },
                        {
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                        },
                    ]
                },
            }
        )

        response = await list_models()

        self.assertEqual(
            response,
            {
                "object": "list",
                "data": [
                    {"id": "glm-5", "object": "model", "owned_by": "modelgate"},
                    {"id": "glm-5.1", "object": "model", "owned_by": "modelgate"},
                ],
            },
        )

    async def test_auto_model_routes_across_configured_standard_models_by_priority(self):
        self.enable_auto_route(model_ids=[101, 202])
        config.providers_cache.update(
            {
                "cheap": {
                    "id": 1,
                    "base_url": "https://cheap.example/v1",
                    "api_key": "cheap-key",
                    "api_keys": [],
                    "models": [
                        {
                            "id": 11,
                            "model_id": 101,
                            "model_name": "glm-5.1",
                            "actual_model_name": "glm-5.1",
                            "upstream_model_name": "glm-5.1",
                            "is_multimodal": False,
                            "model_tags": "",
                            "priority": 5,
                        }
                    ],
                },
                "fast": {
                    "id": 2,
                    "base_url": "https://fast.example/v1",
                    "api_key": "fast-key",
                    "api_keys": [],
                    "models": [
                        {
                            "id": 22,
                            "model_id": 202,
                            "model_name": "deepseek-v3",
                            "actual_model_name": "deepseek-v3",
                            "upstream_model_name": "deepseek-v3",
                            "is_multimodal": False,
                            "model_tags": "",
                            "priority": 20,
                        }
                    ],
                },
            }
        )
        provider_service._model_name_index["glm-5.1"] = [
            ("cheap", config.providers_cache["cheap"]["models"][0], "", 5)
        ]
        provider_service._model_name_index["deepseek-v3"] = [
            ("fast", config.providers_cache["fast"]["models"][0], "", 20)
        ]

        route = await provider_service.get_provider_and_model("auto")

        self.assertEqual(route.provider_name, "fast")
        self.assertEqual(route.requested_model, "auto")
        self.assertEqual(route.model_name, "deepseek-v3")
        self.assertEqual(route.provider_model_id, 22)

    async def test_auto_model_image_request_only_uses_multimodal_candidates(self):
        self.enable_auto_route(model_ids=[101, 202])
        config.providers_cache.update(
            {
                "text-only": {
                    "id": 1,
                    "base_url": "https://text.example/v1",
                    "api_key": "text-key",
                    "api_keys": [],
                    "models": [
                        {
                            "id": 11,
                            "model_id": 101,
                            "model_name": "fast-text",
                            "actual_model_name": "fast-text",
                            "upstream_model_name": "fast-text",
                            "is_multimodal": False,
                            "model_tags": "",
                            "priority": 100,
                        }
                    ],
                },
                "vision": {
                    "id": 2,
                    "base_url": "https://vision.example/v1",
                    "api_key": "vision-key",
                    "api_keys": [],
                    "models": [
                        {
                            "id": 22,
                            "model_id": 202,
                            "model_name": "vision-model",
                            "actual_model_name": "vision-model",
                            "upstream_model_name": "vision-model",
                            "is_multimodal": True,
                            "model_tags": "",
                            "priority": 1,
                        }
                    ],
                },
            }
        )
        provider_service._model_name_index["fast-text"] = [
            ("text-only", config.providers_cache["text-only"]["models"][0], "", 100)
        ]
        provider_service._model_name_index["vision-model"] = [
            ("vision", config.providers_cache["vision"]["models"][0], "", 1)
        ]

        routes = await provider_service.get_provider_model_candidates(
            "auto",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe this"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
                    ],
                }
            ],
        )

        self.assertEqual([route.provider_name for route in routes], ["vision"])
        self.assertEqual(routes[0].model_name, "vision-model")

    async def test_list_models_includes_auto_only_when_enabled(self):
        config.providers_cache.update(
            {
                "zhipu": {
                    "models": [
                        {
                            "model_name": "glm-5",
                            "actual_model_name": "glm-5",
                        }
                    ]
                }
            }
        )

        self.assertEqual(
            [item["id"] for item in (await list_models())["data"]],
            ["glm-5"],
        )

        self.enable_auto_route(model_ids=[101])

        self.assertEqual(
            [item["id"] for item in (await list_models())["data"]],
            ["auto", "glm-5"],
        )

    async def test_auto_model_enabled_without_candidates_is_not_exposed_or_routed(self):
        auto_route_service._auto_model_routes_cache["auto"] = {
            "model_name": "auto",
            "virtual_model_id": 999,
            "enabled": True,
            "model_ids": [],
            "provider_model_ids": [],
            "route_policy": {},
        }
        config.providers_cache.update(
            {
                "zhipu": {
                    "api_key": "zhipu-key",
                    "api_keys": [],
                    "models": [
                        {
                            "id": 11,
                            "model_id": 101,
                            "model_name": "glm-5",
                            "actual_model_name": "glm-5",
                            "upstream_model_name": "glm-5",
                            "priority": 1,
                        }
                    ],
                }
            }
        )
        provider_service._model_name_index["glm-5"] = [
            ("zhipu", config.providers_cache["zhipu"]["models"][0], "", 1)
        ]

        self.assertEqual(
            [item["id"] for item in (await list_models())["data"]],
            ["glm-5"],
        )
        route = await provider_service.get_provider_and_model("auto")
        self.assertIsNone(route.provider_config)
        self.assertEqual(route.model_name, "auto")


class ModelNameRoutingTemplateTests(unittest.TestCase):
    def test_admin_api_key_template_exposes_model_level_binding_mode(self):
        html = render(make_request("/admin/api-keys"), "admin/api_keys.html")

        self.assertIn("allowed_model_ids", html)
        self.assertIn("access-mode-model", html)
        self.assertIn("access-mode-provider-model", html)

    def test_provider_config_template_exposes_upstream_model_name(self):
        html = render(make_request("/admin/config"), "admin/config.html")

        self.assertIn("updatePMUpstreamModel", html)
        self.assertIn("upstream_model_name", html)
        self.assertNotIn("updatePMAlias", html)
        self.assertIn("auto-model-enabled", html)
        self.assertIn("saveAutoModelConfig", html)
        self.assertIn("selectAllAutoModels", html)

    def test_user_catalog_template_uses_model_name_as_primary_identifier(self):
        html = render(
            make_request("/user/dashboard"),
            "user/dashboard.html",
            name="Tester",
            api_key_id=1,
        )

        self.assertIn("model.model_name", html)
        self.assertNotIn("model.full_name", html)


if __name__ == "__main__":
    unittest.main()
