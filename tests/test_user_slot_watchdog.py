import asyncio
import unittest
from datetime import datetime, timedelta

from app.core import config
from app.core.config import (
    USER_SLOT_STALE_SECONDS,
    active_requests,
    consume_user_slot_released,
    finish_active_request,
    register_active_request,
    release_stale_user_slots,
)


class _FakeSem:
    def __init__(self, value: int = 1):
        self._value = value

    def release(self):
        self._value += 1


def _make_entry(started_at: datetime, user_semaphore=None) -> dict:
    return {
        "request_id": "rid",
        "provider": "prov",
        "model": "m",
        "requested_model": None,
        "display_model": "m",
        "upstream_model": None,
        "api_key_id": 1,
        "client_ip": None,
        "prompt_tokens": 0,
        "started_at": started_at,
        "user_semaphore": user_semaphore,
    }


class UserSlotWatchdogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        active_requests.clear()
        config.user_slot_released_ids.clear()

    def tearDown(self):
        active_requests.clear()
        config.user_slot_released_ids.clear()

    async def test_stale_request_user_slot_force_released(self):
        sem = _FakeSem(value=0)
        active_requests["rid-stale"] = _make_entry(
            datetime.now() - timedelta(seconds=USER_SLOT_STALE_SECONDS + 5), sem
        )

        released = await release_stale_user_slots()

        self.assertEqual(released, 1)
        self.assertEqual(sem._value, 1)
        self.assertTrue(active_requests["rid-stale"]["user_slot_released"])

    async def test_fresh_request_not_released(self):
        sem = _FakeSem(value=0)
        active_requests["rid-fresh"] = _make_entry(
            datetime.now() - timedelta(seconds=USER_SLOT_STALE_SECONDS - 10), sem
        )

        released = await release_stale_user_slots()

        self.assertEqual(released, 0)
        self.assertEqual(sem._value, 0)

    async def test_entry_without_semaphore_skipped(self):
        active_requests["rid-nosem"] = _make_entry(
            datetime.now() - timedelta(seconds=USER_SLOT_STALE_SECONDS + 5), None
        )

        released = await release_stale_user_slots()

        self.assertEqual(released, 0)

    async def test_stale_entry_released_only_once(self):
        sem = _FakeSem(value=0)
        active_requests["rid-once"] = _make_entry(
            datetime.now() - timedelta(seconds=USER_SLOT_STALE_SECONDS + 5), sem
        )
        await release_stale_user_slots()
        await release_stale_user_slots()

        self.assertEqual(sem._value, 1)

    async def test_finish_publishes_and_consume_is_once_only(self):
        sem = _FakeSem(value=0)
        active_requests["rid-fin"] = _make_entry(
            datetime.now() - timedelta(seconds=USER_SLOT_STALE_SECONDS + 5), sem
        )
        await release_stale_user_slots()

        await finish_active_request("rid-fin")

        self.assertNotIn("rid-fin", active_requests)
        self.assertTrue(consume_user_slot_released("rid-fin"))
        self.assertFalse(consume_user_slot_released("rid-fin"))

    async def test_register_stores_user_semaphore(self):
        original = dict(config.api_keys_cache)
        config.api_keys_cache.clear()
        config.api_keys_cache["k"] = {"id": 9, "name": "k", "tags": []}
        try:
            sem = _FakeSem(value=1)
            await register_active_request(
                "rid-reg", "prov", "m", 9, user_semaphore=sem
            )
            self.assertIs(active_requests["rid-reg"]["user_semaphore"], sem)
            await finish_active_request("rid-reg")
            self.assertFalse(consume_user_slot_released("rid-reg"))
        finally:
            config.api_keys_cache.clear()
            config.api_keys_cache.update(original)


class StreamUpstreamReleaseTests(unittest.TestCase):
    def test_stream_generator_closes_upstream_response(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "proxy_runtime"
            / "stream.py"
        ).read_text(encoding="utf-8")

        self.assertIn("await resp.aclose()", src)

    def test_stream_registers_user_semaphore(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "proxy_runtime"
            / "stream.py"
        ).read_text(encoding="utf-8")

        self.assertIn("user_semaphore=user_api_key_semaphore", src)
        self.assertIn("consume_user_slot_released", src)

    def test_normal_registers_user_semaphore(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "proxy_runtime"
            / "normal.py"
        ).read_text(encoding="utf-8")

        self.assertIn("user_api_key_semaphore=None", src)
        self.assertIn("user_semaphore=user_api_key_semaphore", src)

    def test_proxy_release_honors_watchdog(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1] / "app" / "services" / "proxy.py"
        ).read_text(encoding="utf-8")

        self.assertIn("consume_user_slot_released(request_id)", src)


if __name__ == "__main__":
    unittest.main()
