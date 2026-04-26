import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import core.config as config
from services import busyness
from services.notification import _notification_visible_to_user
from services.proxy import _get_busyness_suggestion_headers


class BusynessMetricsTests(unittest.TestCase):
    def setUp(self):
        self.original_requests_per_minute = list(config.stats["requests_per_minute"])
        self.original_rate_limited_per_minute = list(
            config.stats.get("rate_limited_per_minute", [])
        )
        self.original_providers = dict(config.stats["providers"])
        self.original_requests_per_second = list(config.requests_per_second)
        config.stats["requests_per_minute"] = []
        config.stats["rate_limited_per_minute"] = []
        config.stats["providers"].clear()
        config.requests_per_second.clear()

    def tearDown(self):
        config.stats["requests_per_minute"] = self.original_requests_per_minute
        config.stats["rate_limited_per_minute"] = self.original_rate_limited_per_minute
        config.stats["providers"].clear()
        config.stats["providers"].update(self.original_providers)
        config.requests_per_second[:] = self.original_requests_per_second

    def test_429_ratio_uses_only_recent_rate_limited_events(self):
        now_key = datetime.now().strftime("%Y%m%d_%H%M")
        old_key = (datetime.now() - timedelta(hours=2)).strftime("%Y%m%d_%H%M")
        config.stats["requests_per_minute"] = [now_key] * 10
        config.stats["rate_limited_per_minute"] = [now_key] * 6 + [old_key] * 100
        config.stats["providers"]["zhipu"]["rate_limited"] = 100

        self.assertEqual(busyness._calc_429_ratio_10min(), 0.6)

    def test_request_activity_keeps_one_hour_history_for_busyness(self):
        thirty_minutes_ago = (
            datetime.now() - timedelta(minutes=30)
        ).strftime("%Y%m%d_%H%M%S")
        config.requests_per_second.append((thirty_minutes_ago, 1))

        config.update_stats("zhipu", "glm-4", 1)

        self.assertTrue(busyness._has_recent_requests(busyness.WINDOW_1HOUR))


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
