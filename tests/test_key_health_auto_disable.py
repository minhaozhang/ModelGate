import asyncio
import unittest
from unittest.mock import patch

from app.services import key_health


class HealthAutoDisableTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        key_health._key_events.clear()
        key_health._health_disable_inflight.clear()

    def tearDown(self):
        key_health._key_events.clear()
        key_health._health_disable_inflight.clear()

    async def test_ten_timeouts_trigger_auto_disable_once(self):
        calls = []

        async def fake_disable(key_id):
            calls.append(key_id)

        with patch(
            "app.services.key_health._auto_disable_unhealthy_key",
            side_effect=fake_disable,
        ):
            for _ in range(10):
                key_health.record_key_event(1, "timeout")
            await asyncio.sleep(0.05)

        self.assertEqual(calls, [1])

    async def test_connect_errors_deduct_and_trigger_auto_disable(self):
        calls = []

        async def fake_disable(key_id):
            calls.append(key_id)

        with patch(
            "app.services.key_health._auto_disable_unhealthy_key",
            side_effect=fake_disable,
        ):
            for _ in range(9):
                key_health.record_key_event(5, "connect_error")
            self.assertEqual(key_health.compute_health_score(5), 10)
            key_health.record_key_event(5, "connect_error")
            await asyncio.sleep(0.05)

        self.assertEqual(calls, [5])
        self.assertEqual(
            key_health.get_events_5m(5)["connect_error"], 10
        )

    async def test_score_above_zero_does_not_trigger(self):
        calls = []

        async def fake_disable(key_id):
            calls.append(key_id)

        with patch(
            "app.services.key_health._auto_disable_unhealthy_key",
            side_effect=fake_disable,
        ):
            for _ in range(9):
                key_health.record_key_event(2, "timeout")
            await asyncio.sleep(0.05)

        self.assertEqual(calls, [])

    async def test_success_events_never_trigger(self):
        calls = []

        async def fake_disable(key_id):
            calls.append(key_id)

        with patch(
            "app.services.key_health._auto_disable_unhealthy_key",
            side_effect=fake_disable,
        ):
            for _ in range(50):
                key_health.record_key_event(3, "success")
            await asyncio.sleep(0.05)

        self.assertEqual(calls, [])

    async def test_disabled_event_pins_score_at_zero(self):
        key_health.record_key_event(4, "disabled")
        self.assertEqual(key_health.compute_health_score(4, is_active=True), 0)
        key_health.on_key_reenabled(4)
        self.assertEqual(key_health.compute_health_score(4, is_active=True), 100)

    async def test_reset_key_health_restores_full_score(self):
        for _ in range(10):
            key_health.record_key_event(6, "timeout")
        self.assertEqual(key_health.compute_health_score(6), 0)
        key_health.record_key_event(6, "disabled")
        key_health.reset_key_health(6)
        self.assertEqual(key_health.compute_health_score(6), 100)
        self.assertEqual(key_health.get_events_5m(6), {k: 0 for k in (
            "success", "rate_limited", "server_error", "client_error",
            "timeout", "connect_error",
        )})
        self.assertEqual(key_health.get_health_level(
            key_health.compute_health_score(6)), "excellent")


if __name__ == "__main__":
    unittest.main()
