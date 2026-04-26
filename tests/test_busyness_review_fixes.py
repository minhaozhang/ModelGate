import unittest
from unittest.mock import AsyncMock, patch

import core.config as config
from services import busyness
from services.notification import _notification_visible_to_user
from services.proxy import _get_busyness_suggestion_headers
from routes import stats as stats_routes


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _FakeBusynessSession:
    def __init__(self, values):
        self.values = list(values)

    async def execute(self, _statement):
        return _ScalarResult(self.values.pop(0))


class _FakeBusynessSessionContext:
    def __init__(self, values):
        self.session = _FakeBusynessSession(values)

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class BusynessMetricsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_providers_cache = dict(config.providers_cache)
        config.providers_cache.clear()

    def tearDown(self):
        config.providers_cache.clear()
        config.providers_cache.update(self.original_providers_cache)

    async def test_compute_busyness_counts_database_window(self):
        # active users, total requests, 429 requests, one-hour activity
        query_values = [11, 20, 11, 20]

        with patch(
            "core.database.async_session_maker",
            return_value=_FakeBusynessSessionContext(query_values),
        ):
            result = await busyness.compute_busyness_level()

        self.assertEqual(result["level"], 3)
        self.assertEqual(result["active_users_10min"], 11)
        self.assertEqual(result["rate_429_ratio"], 0.55)

    async def test_compute_busyness_uses_disabled_provider_count(self):
        config.providers_cache.update(
            {
                "one": {"disabled_reason": "limited"},
                "two": {"disabled_reason": "limited"},
                "three": {},
            }
        )
        query_values = [11, 20, 11, 20]

        with patch(
            "core.database.async_session_maker",
            return_value=_FakeBusynessSessionContext(query_values),
        ):
            result = await busyness.compute_busyness_level()

        self.assertEqual(result["level"], 1)
        self.assertEqual(result["disabled_providers"], 2)


class BusynessRuleTests(unittest.TestCase):
    def setUp(self):
        self.original_busyness_state = dict(config.busyness_state)
        self.original_rules = config.system_config.get("busyness_rules")
        config.busyness_state.clear()

    def tearDown(self):
        config.busyness_state.clear()
        config.busyness_state.update(self.original_busyness_state)
        if self.original_rules is None:
            config.system_config.pop("busyness_rules", None)
        else:
            config.system_config["busyness_rules"] = self.original_rules

    def test_suggest_rule_returns_busyness_headers(self):
        config.busyness_state.update({"level": 2, "label": "较繁忙"})
        config.system_config["busyness_rules"] = [
            {
                "min_level": 2,
                "action": "suggest",
                "message": "系统繁忙，建议使用轻量模型",
            }
        ]

        headers = _get_busyness_suggestion_headers("zhipu/glm-5.1")

        self.assertEqual(headers["X-System-Busyness"], "2")
        self.assertEqual(headers["X-System-Busyness-Message"], "系统繁忙，建议使用轻量模型")


class BusynessEndpointCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_busyness_state = dict(config.busyness_state)
        config.busyness_state.clear()

    def tearDown(self):
        config.busyness_state.clear()
        config.busyness_state.update(self.original_busyness_state)

    async def test_fallback_computation_populates_cache_before_returning(self):
        first_snapshot = {
            "level": 4,
            "name": "normal",
            "label": "Smooth",
            "color": "green",
            "disabled_providers": 0,
            "active_users_10min": 1,
            "rate_429_ratio": 0,
            "computed_at": "2026-04-26T23:50:00",
        }
        changed_snapshot = {
            **first_snapshot,
            "level": 6,
            "name": "quiet",
            "label": "Quiet",
            "color": "slate",
            "active_users_10min": 0,
            "computed_at": "2026-04-26T23:50:08",
        }

        compute_mock = AsyncMock(side_effect=[first_snapshot, changed_snapshot])
        with patch("services.busyness.compute_busyness_level", new=compute_mock):
            first_response = await stats_routes.get_busyness_level(True)
            second_response = await stats_routes.get_busyness_level(True)

        self.assertEqual(compute_mock.await_count, 1)
        self.assertEqual(first_response["active_users_10min"], 1)
        self.assertEqual(second_response["active_users_10min"], 1)
        self.assertEqual(first_response["user_provider_model_limit"], 2)
        self.assertEqual(config.busyness_state["computed_at"], "2026-04-26T23:50:00")


class NotificationVisibilityTests(unittest.TestCase):
    def test_user_can_only_mark_visible_notifications_read(self):
        public_notification = type("Notification", (), {"target_api_key_id": None})()
        own_notification = type("Notification", (), {"target_api_key_id": 7})()
        other_notification = type("Notification", (), {"target_api_key_id": 8})()

        self.assertTrue(_notification_visible_to_user(public_notification, 7))
        self.assertTrue(_notification_visible_to_user(own_notification, 7))
        self.assertFalse(_notification_visible_to_user(other_notification, 7))


if __name__ == "__main__":
    unittest.main()
