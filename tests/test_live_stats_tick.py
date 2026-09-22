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

    async def test_tick_stops_when_last_subscriber_removed(self):
        sub = _make_subscriber()
        with patch("app.core.config.LIVE_STATS_TICK_SECONDS", 0.01):
            await config.add_live_stats_subscriber(sub)
            task = config._tick_task
            self.assertIsNotNone(task)
            await asyncio.sleep(0.05)
            self.assertFalse(task.done())
            await config.remove_live_stats_subscriber(sub)
            self.assertIsNone(config._tick_task)
            await asyncio.sleep(0.05)
            self.assertTrue(task.done())
            self.assertEqual(config._tick_task, None)

    async def test_tick_restarts_after_removal(self):
        sub = _make_subscriber()
        with patch("app.core.config.LIVE_STATS_TICK_SECONDS", 0.01):
            await config.add_live_stats_subscriber(sub)
            await config.remove_live_stats_subscriber(sub)
            await config.add_live_stats_subscriber(sub)
            task = config._tick_task
            self.assertIsNotNone(task)
            await asyncio.sleep(0.05)
            self.assertFalse(task.done())
            await config.remove_live_stats_subscriber(sub)
            self.assertIsNone(config._tick_task)


class MyRequestsCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        config._user_requests_cache.clear()
        config._user_requests_dirty.clear()
        config._log_owner_cache.clear()

    def tearDown(self):
        config._user_requests_cache.clear()
        config._user_requests_dirty.clear()
        config._log_owner_cache.clear()

    async def test_clean_cache_skips_db_query(self):
        calls = []

        async def fake_rows(api_key_id, limit=10):
            calls.append(api_key_id)
            return [{"id": 1, "status": "success"}]

        with patch(
            "app.routes.user.build_user_recent_requests",
            side_effect=fake_rows,
        ):
            first = await config.build_user_my_requests_rows(7)
            second = await config.build_user_my_requests_rows(7)
        self.assertEqual(first, [{"id": 1, "status": "success"}])
        self.assertEqual(second, first)
        self.assertEqual(calls, [7])

    async def test_dirty_flag_forces_refresh(self):
        calls = []

        async def fake_rows(api_key_id, limit=10):
            calls.append(api_key_id)
            return [{"id": len(calls), "status": "success"}]

        with patch(
            "app.routes.user.build_user_recent_requests",
            side_effect=fake_rows,
        ):
            await config.build_user_my_requests_rows(7)
            config.mark_user_requests_dirty(7)
            rows = await config.build_user_my_requests_rows(7)
        self.assertEqual(calls, [7, 7])
        self.assertEqual(rows[0]["id"], 2)

    async def test_log_owner_targets_one_user(self):
        config.remember_log_owner(101, 7)
        async def fake_rows(api_key_id, limit=10):
            return [{"id": api_key_id}]

        with patch(
            "app.routes.user.build_user_recent_requests",
            side_effect=fake_rows,
        ):
            await config.build_user_my_requests_rows(7)
            await config.build_user_my_requests_rows(9)
            config.mark_user_requests_dirty_for_log(101)
            self.assertEqual(config._user_requests_dirty, {7})
            config.mark_user_requests_dirty_for_log(999)
            self.assertEqual(config._user_requests_dirty, {7, 9})

    async def test_dirty_only_tracked_for_cached_users(self):
        config.mark_user_requests_dirty(42)
        self.assertEqual(config._user_requests_dirty, set())


if __name__ == "__main__":
    unittest.main()
