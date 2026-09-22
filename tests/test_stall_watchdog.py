import asyncio
import unittest

from app.services.proxy_runtime.stream import (
    _KA,
    UpstreamStallTimeout,
    _stall_watchdog,
)
from app.services.sse import normalize_sse_stream


class StallWatchdogTests(unittest.IsolatedAsyncioTestCase):
    async def test_established_window_survives_long_pause(self):
        """After a data line, silence shorter than the established window
        must not kill the stream (thinking/tool-use pause)."""
        async def src():
            yield "data: chunk1"
            await asyncio.sleep(0.3)
            yield "data: chunk2"

        got = []
        async for item in _stall_watchdog(
            src(), 0.05, established_timeout_s=1.0
        ):
            got.append(item)
        self.assertEqual(got, ["data: chunk1", "data: chunk2"])

    async def test_base_window_kills_pre_data_silence(self):
        async def src():
            yield ": upstream keep-alive"
            await asyncio.sleep(0.3)
            yield "data: late"

        with self.assertRaises(UpstreamStallTimeout):
            async for _ in _stall_watchdog(src(), 0.05):
                pass

    async def test_upstream_comments_reset_timer(self):
        async def src():
            yield "data: chunk1"
            await asyncio.sleep(0.12)
            yield ": heartbeat"
            await asyncio.sleep(0.12)
            yield ": heartbeat"
            await asyncio.sleep(0.12)
            yield "data: chunk2"

        got = []
        async for item in _stall_watchdog(src(), 0.3):
            got.append(item)
        self.assertEqual(
            got, ["data: chunk1", ": heartbeat", ": heartbeat", "data: chunk2"]
        )

    async def test_keepalive_sentinel_during_silence(self):
        async def src():
            yield "data: chunk1"
            await asyncio.sleep(0.35)
            yield "data: chunk2"

        got = []
        async for item in _stall_watchdog(
            src(), 0.05, established_timeout_s=1.0, keepalive_interval_s=0.1
        ):
            got.append(item)
        self.assertEqual(got[0], "data: chunk1")
        self.assertEqual(got[-1], "data: chunk2")
        kas = [x for x in got if x is _KA]
        self.assertGreaterEqual(len(kas), 2)
        # sentinel must not appear before any data line
        self.assertNotEqual(got[0], _KA)

    async def test_keepalive_does_not_extend_deadline(self):
        async def src():
            yield "data: chunk1"
            await asyncio.sleep(10)
            yield "data: too-late"

        with self.assertRaises(UpstreamStallTimeout):
            async for _ in _stall_watchdog(
                src(), 0.05, established_timeout_s=0.25, keepalive_interval_s=0.05
            ):
                pass

    async def test_keepalive_disabled_by_zero(self):
        async def src():
            yield "data: chunk1"
            await asyncio.sleep(10)

        got = []
        with self.assertRaises(UpstreamStallTimeout):
            async for item in _stall_watchdog(src(), 0.05):
                got.append(item)
        self.assertEqual(got, ["data: chunk1"])


class NormalizeKeepaliveTests(unittest.IsolatedAsyncioTestCase):
    async def test_sentinel_passes_through_normalize(self):
        async def src():
            yield "data: hello"
            yield _KA
            yield ""
            yield "data: [DONE]"
            yield ""

        got = []
        async for item in normalize_sse_stream(src()):
            got.append(item)
        self.assertIn(_KA, got)
        self.assertIn("data: hello", got)
        self.assertIn("data: [DONE]", got)

    async def test_comments_still_swallowed(self):
        async def src():
            yield ": comment"
            yield "data: x"
            yield ""

        got = []
        async for item in normalize_sse_stream(src()):
            got.append(item)
        self.assertEqual(got, ["data: x"])


if __name__ == "__main__":
    unittest.main()
