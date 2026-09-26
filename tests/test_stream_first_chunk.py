import asyncio
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

from app.core import config
from app.core.config import active_requests, STREAM_FIRST_CHUNK_TIMEOUT_SECONDS


class _FakeStreamResp:
    def __init__(self, lines=None, hang=False, error=None):
        self.status_code = 200
        self.headers = {}
        self.closed = False
        self._lines = lines or []
        self._hang = hang
        self._error = error

    async def aiter_lines(self):
        if self._error is not None:
            raise self._error
        if self._hang:
            await asyncio.sleep(3600)
            return
        for line in self._lines:
            yield line

    async def aclose(self):
        self.closed = True


def _client_for(resp=None, send_hang=False):
    client = Mock()
    client.build_request = Mock(return_value=Mock())
    if send_hang:
        async def slow_send(req, stream=True):
            await asyncio.sleep(3600)

        client.send = slow_send
    else:
        client.send = AsyncMock(return_value=resp)
    return client


async def _call_stream(stream_module, client, sems=None):
    provider_sem, upm_sem, user_sem = sems or (
        asyncio.Semaphore(0),
        asyncio.Semaphore(0),
        asyncio.Semaphore(0),
    )
    req_stub = Mock()
    req_stub.is_disconnected = AsyncMock(return_value=False)
    response = await stream_module.handle_streaming(
        "https://up.example/v1/chat/completions",
        {},
        b"{}",
        "prov",
        "mdl",
        [],
        0.0,
        {},
        1,
        "ip",
        "ua",
        0,
        provider_sem,
        upm_sem,
        user_sem,
        None,
        "rid-fc",
        None,
        req_stub,
    )
    return response, provider_sem, upm_sem, user_sem


def _patches(client):
    return [
        patch(
            "app.services.proxy_runtime.stream.get_http_client",
            Mock(return_value=client),
        ),
        patch(
            "app.services.proxy_runtime.stream.STREAM_FIRST_CHUNK_TIMEOUT_SECONDS",
            0.05,
        ),
        patch(
            "app.services.proxy_runtime.stream._record_stream_result",
            new=AsyncMock(),
        ),
    ]


class StreamFirstChunkTimeoutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        active_requests.clear()
        config.user_slot_released_ids.clear()

    def tearDown(self):
        active_requests.clear()
        config.user_slot_released_ids.clear()

    def test_default_timeout_is_5s(self):
        self.assertEqual(STREAM_FIRST_CHUNK_TIMEOUT_SECONDS, 5.0)

    def test_first_chunk_timeout_scales_with_context(self):
        from app.services.proxy_runtime.stream import _first_chunk_timeout

        self.assertEqual(_first_chunk_timeout(None), 5.0)
        self.assertEqual(_first_chunk_timeout(0), 5.0)
        self.assertEqual(_first_chunk_timeout(30000), 12.5)
        self.assertEqual(_first_chunk_timeout(55000), 18.75)
        self.assertEqual(_first_chunk_timeout(77000), 24.25)
        self.assertEqual(_first_chunk_timeout(1000000), 60.0)

    def test_first_chunk_timeout_scales_with_images(self):
        from app.services.proxy_runtime.stream import _first_chunk_timeout

        self.assertEqual(_first_chunk_timeout(None, 0), 5.0)
        self.assertEqual(_first_chunk_timeout(0, 1), 15.0)
        self.assertEqual(_first_chunk_timeout(0, 3), 35.0)
        self.assertEqual(_first_chunk_timeout(30000, 2), 32.5)
        self.assertEqual(_first_chunk_timeout(1000000, 1), 120.0)

    def test_count_image_parts_detects_images(self):
        from app.services.tokens import count_image_parts

        image_url = "data:image/png;base64," + "A" * 200
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "看图"},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ]
        }
        self.assertEqual(count_image_parts(body), 1)
        self.assertEqual(
            count_image_parts({"messages": [{"role": "user", "content": "hi"}]}),
            0,
        )
        self.assertEqual(count_image_parts(None), 0)

    async def test_send_headers_timeout_triggers_error(self):
        from app.services.proxy_runtime import stream as stream_module

        client = _client_for(send_hang=True)
        sems = (asyncio.Semaphore(0), asyncio.Semaphore(0), asyncio.Semaphore(0))
        with patch("app.services.proxy_runtime.stream.get_http_client", Mock(return_value=client)), patch(
            "app.services.proxy_runtime.stream.STREAM_FIRST_CHUNK_TIMEOUT_SECONDS", 0.05
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await _call_stream(stream_module, client, sems)
            self.assertIn("did not respond", str(ctx.exception))
            self.assertIsInstance(
                ctx.exception, stream_module.UpstreamFirstChunkTimeout
            )
        provider_sem, upm_sem, _ = sems
        self.assertEqual(provider_sem._value, 1)
        self.assertEqual(upm_sem._value, 1)
        self.assertNotIn("rid-fc", active_requests)

    async def test_first_chunk_timeout_closes_upstream_and_errors(self):
        from app.services.proxy_runtime import stream as stream_module

        resp = _FakeStreamResp(hang=True)
        client = _client_for(resp=resp)
        sems = (asyncio.Semaphore(0), asyncio.Semaphore(0), asyncio.Semaphore(0))
        with patch("app.services.proxy_runtime.stream.get_http_client", Mock(return_value=client)), patch(
            "app.services.proxy_runtime.stream.STREAM_FIRST_CHUNK_TIMEOUT_SECONDS", 0.05
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await _call_stream(stream_module, client, sems)
            self.assertIn("first-chunk timeout", str(ctx.exception))
            self.assertIsInstance(
                ctx.exception, stream_module.UpstreamFirstChunkTimeout
            )
        self.assertTrue(resp.closed)
        provider_sem, upm_sem, _ = sems
        self.assertEqual(provider_sem._value, 1)
        self.assertEqual(upm_sem._value, 1)
        self.assertNotIn("rid-fc", active_requests)

    async def test_upstream_error_during_first_chunk_closes_connection(self):
        from app.services.proxy_runtime import stream as stream_module

        resp = _FakeStreamResp(error=ConnectionError("reset by peer"))
        client = _client_for(resp=resp)
        with patch("app.services.proxy_runtime.stream.get_http_client", Mock(return_value=client)), patch(
            "app.services.proxy_runtime.stream.STREAM_FIRST_CHUNK_TIMEOUT_SECONDS", 0.05
        ):
            with self.assertRaises(ConnectionError):
                await _call_stream(stream_module, client)
        self.assertTrue(resp.closed)

    async def test_connect_error_raises_with_provider_and_key(self):
        import httpx

        from app.services.proxy_runtime import stream as stream_module

        client = Mock()
        client.build_request = Mock(return_value=Mock())

        async def refused(req, stream=True):
            raise httpx.ConnectError("[Errno 11001] getaddrinfo failed")

        client.send = refused
        req_stub = Mock()
        req_stub.is_disconnected = AsyncMock(return_value=False)
        events = []
        with patch("app.services.proxy_runtime.stream.get_http_client", Mock(return_value=client)), patch(
            "app.services.proxy_runtime.stream.record_key_event",
            side_effect=lambda kid, etype, *a, **k: events.append((kid, etype)),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await stream_module.handle_streaming(
                    "https://up.example/v1/chat/completions",
                    {},
                    b"{}",
                    "prov",
                    "mdl",
                    [],
                    0.0,
                    {},
                    1,
                    "ip",
                    "ua",
                    0,
                    asyncio.Semaphore(0),
                    asyncio.Semaphore(0),
                    asyncio.Semaphore(0),
                    None,
                    "rid-ce",
                    None,
                    req_stub,
                    chosen_key_id=7,
                    provider_key_label="主力",
                )
        self.assertIsInstance(ctx.exception, stream_module.UpstreamConnectError)
        self.assertIn("provider=prov", str(ctx.exception))
        self.assertIn("key=主力", str(ctx.exception))
        self.assertIn("getaddrinfo failed", str(ctx.exception))
        self.assertEqual(events, [(7, "connect_error")])

    async def test_empty_2xx_stream_errors_instead_of_success(self):
        from app.services.proxy_runtime import stream as stream_module

        resp = _FakeStreamResp(lines=[])
        client = _client_for(resp=resp)
        with patch("app.services.proxy_runtime.stream.get_http_client", Mock(return_value=client)), patch(
            "app.services.proxy_runtime.stream.STREAM_FIRST_CHUNK_TIMEOUT_SECONDS", 0.05
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await _call_stream(stream_module, client)
            self.assertIn("without sending any SSE data", str(ctx.exception))
            self.assertNotIsInstance(
                ctx.exception, stream_module.UpstreamFirstChunkTimeout
            )
        self.assertTrue(resp.closed)

    def test_proxy_returns_compact_hint_after_exhausted(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1] / "app" / "services" / "proxy.py"
        ).read_text(encoding="utf-8")

        self.assertIn("UpstreamFirstChunkTimeout", src)
        self.assertIn("first_chunk_timed_out", src)
        self.assertIn("COMPACT_HINT_MIN_TOKENS", src)
        self.assertIn("context_length_exceeded", src)

    async def test_success_first_chunk_flows_and_releases_all(self):
        from app.services.proxy_runtime import stream as stream_module

        resp = _FakeStreamResp(
            lines=['data: {"choices":[{"delta":{"content":"hi"}}]}']
        )
        client = _client_for(resp=resp)
        with patch("app.services.proxy_runtime.stream.get_http_client", Mock(return_value=client)), patch(
            "app.services.proxy_runtime.stream._record_stream_result",
            new=AsyncMock(),
        ):
            response, provider_sem, upm_sem, user_sem = await _call_stream(
                stream_module, client
            )
            self.assertEqual(response.status_code, 200)
            chunk = await response.body_iterator.__anext__()
            self.assertTrue(chunk.startswith("data: "))
            self.assertTrue(chunk.endswith("\n\n"))
            await response.body_iterator.aclose()
        self.assertEqual(provider_sem._value, 1)
        self.assertEqual(upm_sem._value, 1)
        self.assertEqual(user_sem._value, 1)
        self.assertNotIn("rid-fc", active_requests)


if __name__ == "__main__":
    unittest.main()
