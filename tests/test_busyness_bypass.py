import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

import core.config as config
from routes import user as user_routes
from services.proxy import proxy_request


def make_request(method: str = "GET", path: str = "/") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(b"authorization", b"Bearer test-key")],
            "query_string": b"",
            "cookies": {},
            "root_path": "",
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


class _FetchAllResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _FakeRecommendationSession:
    def __init__(self, results):
        self.results = list(results)

    async def execute(self, _statement):
        return self.results.pop(0)


class _FakeRecommendationSessionContext:
    def __init__(self, results):
        self.results = results

    async def __aenter__(self):
        return _FakeRecommendationSession(self.results)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class BusynessBypassProxyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_busyness_state = dict(config.busyness_state)
        self.original_system_rules = config.system_config.get("busyness_rules")
        self.original_api_keys_cache = dict(config.api_keys_cache)
        config.busyness_state.clear()
        config.api_keys_cache.clear()

    def tearDown(self):
        config.busyness_state.clear()
        config.busyness_state.update(self.original_busyness_state)
        config.api_keys_cache.clear()
        config.api_keys_cache.update(self.original_api_keys_cache)
        if self.original_system_rules is None:
            config.system_config.pop("busyness_rules", None)
        else:
            config.system_config["busyness_rules"] = self.original_system_rules

    async def test_bypass_key_skips_busyness_block_rule(self):
        config.busyness_state.update({"level": 1, "label": "Busy"})
        config.system_config["busyness_rules"] = [
            {
                "min_level": 1,
                "action": "block",
                "target_models": ["openai/gpt-test"],
                "message": "blocked",
            }
        ]
        config.api_keys_cache["test-key"] = {
            "id": 7,
            "name": "bypass",
            "bypass_busyness": True,
        }
        request = make_request("POST", "/v1/chat/completions")
        request._body = b'{"model":"openai/gpt-test","messages":[]}'

        with (
            patch("services.proxy.validate_api_key", new=AsyncMock(return_value=(7, None))),
            patch(
                "services.proxy.get_provider_and_model",
                new=AsyncMock(return_value=(None, None, "openai")),
            ) as provider_mock,
            patch(
                "services.proxy.get_disabled_provider_reason",
                new=AsyncMock(return_value=None),
            ),
            patch("services.proxy.logger.error"),
            patch("services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        provider_mock.assert_awaited_once()
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("busyness_block", response.body.decode("utf-8"))


class BusynessBypassRecommendationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_busyness_state = dict(config.busyness_state)
        self.original_api_keys_cache = dict(config.api_keys_cache)
        self.original_providers_cache = dict(config.providers_cache)
        self.original_recommendations_cache = dict(user_routes.USER_RECOMMENDATIONS_CACHE)
        config.busyness_state.clear()
        config.api_keys_cache.clear()
        config.providers_cache.clear()
        user_routes.USER_RECOMMENDATIONS_CACHE.clear()

    def tearDown(self):
        config.busyness_state.clear()
        config.busyness_state.update(self.original_busyness_state)
        config.api_keys_cache.clear()
        config.api_keys_cache.update(self.original_api_keys_cache)
        config.providers_cache.clear()
        config.providers_cache.update(self.original_providers_cache)
        user_routes.USER_RECOMMENDATIONS_CACHE.clear()
        user_routes.USER_RECOMMENDATIONS_CACHE.update(self.original_recommendations_cache)

    async def test_recommendations_cache_is_scoped_by_bypass_visibility(self):
        config.busyness_state.update({"level": 6, "label": "Quiet"})
        config.api_keys_cache.update(
            {
                "regular-key": {"id": 1, "bypass_busyness": False},
                "bypass-key": {"id": 2, "bypass_busyness": True},
            }
        )
        config.providers_cache["openai"] = {
            "id": 10,
            "name": "openai",
            "disabled_reason": None,
            "models": [
                {
                    "actual_model_name": "gpt-expensive",
                    "max_busyness_level": 3,
                }
            ],
        }
        row = SimpleNamespace(
            provider_id=10,
            model="gpt-expensive",
            requests=25,
            avg_latency_ms=100,
            errors=0,
        )

        def session_factory():
            return _FakeRecommendationSessionContext(
                [
                    _FetchAllResult([row]),
                    _FetchAllResult([("gpt-expensive", "Expensive")]),
                ]
            )

        with (
            patch("routes.user.async_session_maker", side_effect=session_factory),
            patch("routes.user.get_local_now", return_value=datetime(2026, 4, 27, 10, 0, 0)),
        ):
            regular = await user_routes.get_user_recommendations(
                make_request(), api_key_id=1, period="day"
            )
            bypass = await user_routes.get_user_recommendations(
                make_request(), api_key_id=2, period="day"
            )

        self.assertEqual(regular["items"], [])
        self.assertEqual(bypass["items"][0]["model"], "openai/gpt-expensive")


if __name__ == "__main__":
    unittest.main()
