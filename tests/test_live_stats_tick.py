import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.core import config


def _make_subscriber():
    sub = AsyncMock()
    sub.send_json = AsyncMock()
    return sub


class LiveStatsTickTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        config.live_stats_subscribers.clear()
        config.user_live_stats_subscribers.clear()
        config.active_requests.clear()
        config.token_buckets.clear()
        config._tokens_per_second_ewma = None
        config._tick_last_active = False

    def tearDown(self):
        config.live_stats_subscribers.clear()
        config.user_live_stats_subscribers.clear()
        config.active_requests.clear()
        config.token_buckets.clear()
        config._tokens_per_second_ewma = None
        config._tick_last_active = False
        task = config._tick_task
        if task is not None and not task.done():
            task.cancel()
        config._tick_task = None

    async def test_no_subscribers_no_push(self):
        with patch(
            "app.core.config.broadcast_live_stats", new=AsyncMock()
        ) as mock_b:
            pushed = await config._live_stats_tick_once()
        self.assertFalse(pushed)
        mock_b.assert_not_awaited()

    async def test_admin_subscriber_active_request_pushes(self):
        sub = _make_subscriber()
        config.live_stats_subscribers.add(sub)
        config.active_requests["rid"] = {"started_at": None}
        with patch(
            "app.core.config.broadcast_live_stats", new=AsyncMock()
        ) as mock_b:
            pushed = await config._live_stats_tick_once()
        self.assertTrue(pushed)
        mock_b.assert_awaited_once()
        self.assertTrue(config._tick_last_active)

    async def test_user_subscriber_pushes(self):
        sub = _make_subscriber()
        config.user_live_stats_subscribers[7] = {sub}
        config.token_buckets.append(("20260922_120000", 100))
        with patch(
            "app.core.config.broadcast_live_stats", new=AsyncMock()
        ) as mock_b:
            pushed = await config._live_stats_tick_once()
        self.assertTrue(pushed)
        mock_b.assert_awaited_once()

    async def test_token_buckets_count_as_flowing(self):
        sub = _make_subscriber()
        config.live_stats_subscribers.add(sub)
        config.token_buckets.append(("20260922_120000", 100))
        with patch(
            "app.core.config.broadcast_live_stats", new=AsyncMock()
        ) as mock_b:
            pushed = await config._live_stats_tick_once()
        self.assertTrue(pushed)
        mock_b.assert_awaited_once()

    async def test_idle_after_activity_pushes_final_zero_once(self):
        sub = _make_subscriber()
        config.live_stats_subscribers.add(sub)
        config._tick_last_active = True
        with patch(
            "app.core.config.broadcast_live_stats", new=AsyncMock()
        ) as mock_b:
            first = await config._live_stats_tick_once()
            self.assertTrue(first)
            mock_b.assert_awaited_once()
            self.assertFalse(config._tick_last_active)
            second = await config._live_stats_tick_once()
            self.assertFalse(second)
            mock_b.assert_awaited_once()

    async def test_ensure_starts_single_loop(self):
        sub = _make_subscriber()
        with patch(
            "app.core.config.LIVE_STATS_TICK_SECONDS", 0.01
        ):
            await config.add_live_stats_subscriber(sub)
            await config.add_live_stats_subscriber(sub)
            self.assertIsNotNone(config._tick_task)
            task = config._tick_task
            await asyncio.sleep(0.1)
        self.assertFalse(task.done())
        task.cancel()
        config._tick_task = None


if __name__ == "__main__":
    unittest.main()
