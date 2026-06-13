import unittest

from app.core import config
from app.core.i18n import render
from app.routes.proxy import list_models
from app.services import provider as provider_service
from app.services.auth import validate_api_key
from app.services.proxy import check_model_access
from tests.test_opencode_security import make_request


class ModelNameRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_providers_cache = dict(config.providers_cache)
        self.original_api_keys_cache = dict(config.api_keys_cache)
        self.original_alias_index = dict(provider_service._alias_index)
        self.original_model_name_index = dict(
            getattr(provider_service, "_model_name_index", {})
        )
        config.providers_cache.clear()
        config.api_keys_cache.clear()
        provider_service._alias_index.clear()
        if hasattr(provider_service, "_model_name_index"):
            provider_service._model_name_index.clear()

    def tearDown(self):
        config.providers_cache.clear()
        config.providers_cache.update(self.original_providers_cache)
        config.api_keys_cache.clear()
        config.api_keys_cache.update(self.original_api_keys_cache)
        provider_service._alias_index.clear()
        provider_service._alias_index.update(self.original_alias_index)
        if hasattr(provider_service, "_model_name_index"):
            provider_service._model_name_index.clear()
            provider_service._model_name_index.update(self.original_model_name_index)

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

    async def test_model_access_binding_allows_any_provider_model_for_same_model(self):
        key_info = {
            "allowed_provider_model_ids": [],
            "allowed_model_ids": [101],
        }

        self.assertTrue(
            check_model_access(key_info, provider_model_id=99, model_id=101)
        )
        self.assertFalse(
            check_model_access(key_info, provider_model_id=99, model_id=202)
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
