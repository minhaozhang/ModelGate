import inspect
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from starlette.requests import Request
from starlette.responses import StreamingResponse

import app.core.config as config
from app.core.config import (
    active_requests,
    build_live_stats_snapshot,
    register_active_request,
    stats,
    update_stats,
)
from app.services import proxy as proxy_module
from app.services import provider as provider_service


def _make_route(
    model_name="cap-test",
    upstream_model_name="up-cap",
    provider_name="primary",
):
    return proxy_module.RouteResult(
        provider_config={
            "id": 1,
            "base_url": "https://primary.example/v1",
            "protocol": "openai",
            "api_keys": [{"id": 11, "api_key": "sk-primary", "max_concurrent": 3}],
            "models": [
                {"id": 91, "model_id": 101, "model_name": model_name},
            ],
        },
        provider_name=provider_name,
        provider_id=1,
        provider_model_id=91,
        model_id=101,
        requested_model=model_name,
        model_name=model_name,
        upstream_model_name=upstream_model_name,
        is_forced_provider=False,
    )


def _make_request(model_name="cap-test", stream=False):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/chat/completions",
            "headers": [],
            "query_string": b"",
            "cookies": {},
            "root_path": "",
        }
    )
    payload = {"model": model_name, "messages": []}
    if stream:
        payload["stream"] = True
    request._body = json.dumps(payload).encode("utf-8")
    return request


class LocalRejectionProvenanceTests(unittest.IsolatedAsyncioTestCase):
    """Local rejections never reached an upstream, so they must not claim an
    upstream actual_model nor attribute provider model stats to the upstream
    name."""

    def setUp(self):
        provider_service._model_max_concurrent_by_name.clear()
        self.original_api_keys_cache = dict(config.api_keys_cache)
        config.api_keys_cache.clear()
        config.api_keys_cache["test-key"] = {
            "id": 1,
            "bypass_busyness": True,
            "name": "test-key",
            "tags": [],
            "allowed_provider_model_ids": list(range(1, 1000)),
            "allowed_model_ids": list(range(1, 1000)),
        }

    def tearDown(self):
        provider_service._model_max_concurrent_by_name.clear()
        config.api_keys_cache.clear()
        config.api_keys_cache.update(self.original_api_keys_cache)

    def _base_patches(self, routes, stack, log_mock, stats_mock):
        stack.enter_context(
            patch(
                "app.services.proxy.validate_api_key",
                new=AsyncMock(return_value=(1, None)),
            )
        )
        stack.enter_context(
            patch(
                "app.services.billing_rules.check_daily_quota",
                new=AsyncMock(return_value=None),
            )
        )
        stack.enter_context(
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=routes),
            )
        )
        stack.enter_context(patch("app.services.proxy.create_request_log", new=log_mock))
        stack.enter_context(patch("app.services.proxy.update_stats", new=stats_mock))
        stack.enter_context(
            patch(
                "app.services.proxy.schedule_api_key_last_used_update",
                return_value=None,
            )
        )

    async def test_daily_quota_rejection_leaves_actual_model_null(self):
        import contextlib

        log_mock = AsyncMock(return_value=1)
        stats_mock = Mock()
        with contextlib.ExitStack() as stack:
            self._base_patches([], stack, log_mock, stats_mock)
            stack.enter_context(
                patch(
                    "app.services.billing_rules.check_daily_quota",
                    new=AsyncMock(
                        return_value={
                            "charged_cny": 1.0,
                            "quota_cny": 1.0,
                            "reset_at": "2026-01-01",
                            "retry_after": 60,
                        }
                    ),
                )
            )
            response = await proxy_module.proxy_request(
                _make_request("glm-x"), "/chat/completions"
            )

        self.assertEqual(response.status_code, 429)
        kwargs = log_mock.call_args.kwargs
        self.assertEqual(kwargs.get("requested_model"), "glm-x")
        self.assertIsNone(kwargs.get("actual_model"))

    async def test_zero_concurrency_rejection_leaves_actual_model_null(self):
        import contextlib

        provider_service._model_max_concurrent_by_name["cap-test"] = 0
        log_mock = AsyncMock(return_value=1)
        stats_mock = Mock()
        with contextlib.ExitStack() as stack:
            self._base_patches([_make_route()], stack, log_mock, stats_mock)
            response = await proxy_module.proxy_request(
                _make_request("cap-test"), "/chat/completions"
            )

        self.assertEqual(response.status_code, 429)
        kwargs = log_mock.call_args.kwargs
        self.assertEqual(kwargs.get("requested_model"), "cap-test")
        self.assertIsNone(kwargs.get("actual_model"))
        self.assertIsNone(stats_mock.call_args.kwargs.get("upstream_model"))

    async def test_no_key_rejection_leaves_actual_model_null(self):
        import contextlib

        log_mock = AsyncMock(return_value=1)
        stats_mock = Mock()
        with contextlib.ExitStack() as stack:
            self._base_patches([_make_route()], stack, log_mock, stats_mock)
            stack.enter_context(
                patch("app.services.proxy.pick_api_keys", new=Mock(return_value=[]))
            )
            response = await proxy_module.proxy_request(
                _make_request("cap-test"), "/chat/completions"
            )

        self.assertEqual(response.status_code, 429)
        kwargs = log_mock.call_args.kwargs
        self.assertEqual(kwargs.get("requested_model"), "cap-test")
        self.assertIsNone(kwargs.get("actual_model"))
        self.assertIsNone(stats_mock.call_args.kwargs.get("upstream_model"))


class StreamPreCreateProvenanceTests(unittest.IsolatedAsyncioTestCase):
    """The pre-send stream log is created before client.send(), so it must
    not claim an upstream actual_model."""

    def setUp(self):
        self.original_api_keys_cache = dict(config.api_keys_cache)
        config.api_keys_cache.clear()
        config.api_keys_cache["test-key"] = {
            "id": 1,
            "bypass_busyness": True,
            "name": "test-key",
            "tags": [],
            "allowed_provider_model_ids": list(range(1, 1000)),
            "allowed_model_ids": list(range(1, 1000)),
        }

    def tearDown(self):
        config.api_keys_cache.clear()
        config.api_keys_cache.update(self.original_api_keys_cache)

    async def test_stream_precreate_log_has_no_actual_model(self):
        import contextlib

        log_mock = AsyncMock(return_value=101)
        stats_mock = Mock()
        handler = AsyncMock(return_value=StreamingResponse(iter([])))
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch(
                    "app.services.proxy.validate_api_key",
                    new=AsyncMock(return_value=(1, None)),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.billing_rules.check_daily_quota",
                    new=AsyncMock(return_value=None),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.proxy.get_provider_model_candidates",
                    new=AsyncMock(return_value=[_make_route("cap-stream", "up-stream")]),
                )
            )
            stack.enter_context(patch("app.services.proxy.create_request_log", new=log_mock))
            stack.enter_context(patch("app.services.proxy.update_stats", new=stats_mock))
            stack.enter_context(
                patch(
                    "app.services.proxy.schedule_api_key_last_used_update",
                    return_value=None,
                )
            )
            stack.enter_context(patch("app.services.proxy.handle_streaming", new=handler))
            response = await proxy_module.proxy_request(
                _make_request("cap-stream", stream=True), "/chat/completions"
            )

        self.assertEqual(response.status_code, 200)
        kwargs = log_mock.call_args.kwargs
        self.assertEqual(kwargs.get("requested_model"), "cap-stream")
        self.assertIsNone(kwargs.get("actual_model"))
        decision = kwargs.get("routing_decision") or {}
        self.assertEqual(decision.get("outcome"), "stream_started")


class InternalProxyDualModelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_api_keys_cache = dict(config.api_keys_cache)
        config.api_keys_cache.clear()
        config.api_keys_cache["internal-key"] = {
            "id": 1,
            "bypass_busyness": False,
            "name": "internal-key",
            "tags": [],
        }

    def tearDown(self):
        config.api_keys_cache.clear()
        config.api_keys_cache.update(self.original_api_keys_cache)

    async def test_internal_success_writes_dual_model_fields(self):
        from app.services.proxy_runtime import internal as internal_module
        from app.services.provider import RouteResult

        payload = {
            "choices": [
                {"message": {"content": "hi"}, "finish_reason": "stop"},
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        resp = Mock(status_code=200)
        resp.json.return_value = payload
        resp.text = json.dumps(payload)
        client = Mock()
        client.post = AsyncMock(return_value=resp)

        route = RouteResult(
            provider_config={
                "id": 1,
                "base_url": "https://primary.example/v1",
                "protocol": "openai",
                "api_keys": [{"id": 21, "api_key": "sk-i", "max_concurrent": 3}],
                "models": [{"id": 91, "model_id": 101, "model_name": "glm-int"}],
            },
            provider_name="primary",
            provider_id=1,
            provider_model_id=91,
            model_id=101,
            requested_model="glm-int",
            model_name="glm-int",
            upstream_model_name="up-int",
            is_forced_provider=False,
        )
        log_mock = AsyncMock(return_value=1)
        stats_mock = Mock()

        with patch(
            "app.services.proxy_runtime.internal.ensure_internal_api_key_exists",
            new=AsyncMock(return_value=True),
        ), patch(
            "app.services.proxy_runtime.internal.get_provider_and_model",
            new=AsyncMock(return_value=route),
        ), patch(
            "app.services.proxy_runtime.internal.pick_api_key",
            new=Mock(return_value=("sk-i", 21)),
        ), patch(
            "app.services.proxy_runtime.internal.get_http_client",
            new=Mock(return_value=client),
        ), patch(
            "app.services.proxy_runtime.internal.enrich_tokens_with_billing",
            new=AsyncMock(side_effect=lambda tokens_record, **kwargs: tokens_record),
        ), patch(
            "app.services.proxy_runtime.internal.record_key_event",
            new=Mock(),
        ), patch(
            "app.services.proxy_runtime.internal.create_request_log",
            new=log_mock,
        ), patch(
            "app.services.proxy_runtime.internal.update_stats",
            new=stats_mock,
        ):
            result = await internal_module.call_internal_model_via_proxy(
                "glm-int",
                {"messages": []},
                api_key_id=1,
                purpose="analysis",
                client_ip="internal",
                user_agent="test/ua",
            )

        self.assertTrue(result["ok"])
        log_kwargs = log_mock.call_args.kwargs
        self.assertEqual(log_kwargs.get("requested_model"), "glm-int")
        self.assertEqual(log_kwargs.get("actual_model"), "up-int")
        stats_kwargs = stats_mock.call_args.kwargs
        self.assertEqual(stats_kwargs.get("upstream_model"), "up-int")
        self.assertEqual(stats_kwargs.get("requested_model"), "glm-int")


class UpdateStatsRequestedModelTests(unittest.TestCase):
    def setUp(self):
        stats["models"].clear()
        stats["api_keys"].clear()

    def tearDown(self):
        stats["models"].clear()
        stats["api_keys"].clear()

    def test_update_stats_accepts_requested_model(self):
        self.assertIn(
            "requested_model", inspect.signature(update_stats).parameters
        )

    def test_api_key_bucket_uses_requested_model_name(self):
        update_stats(
            "prov",
            "std-chat",
            10,
            api_key_id=1,
            requested_model="prov/glm-x",
        )
        self.assertIn("glm-x", stats["api_keys"][1]["models"])
        self.assertNotIn("std-chat", stats["api_keys"][1]["models"])
        self.assertNotIn("prov/glm-x", stats["api_keys"][1]["models"])

    def test_api_key_bucket_falls_back_to_model(self):
        update_stats("prov", "std-chat", 10, api_key_id=2)
        self.assertIn("std-chat", stats["api_keys"][2]["models"])

    def test_update_request_log_supports_actual_model(self):
        from app.services.logging import update_request_log

        self.assertIn(
            "actual_model", inspect.signature(update_request_log).parameters
        )


class ActiveRequestRequestedModelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        active_requests.clear()
        self.original_api_keys_cache = dict(config.api_keys_cache)
        config.api_keys_cache.clear()
        config.api_keys_cache["live-key"] = {
            "id": 1,
            "name": "live-key",
            "tags": [],
        }

    def tearDown(self):
        active_requests.clear()
        config.api_keys_cache.clear()
        config.api_keys_cache.update(self.original_api_keys_cache)

    async def test_register_active_request_accepts_requested_model(self):
        self.assertIn(
            "requested_model",
            inspect.signature(register_active_request).parameters,
        )
        self.assertIn(
            "upstream_model",
            inspect.signature(register_active_request).parameters,
        )

    async def test_live_snapshot_shows_requested_arrow_provider_actual(self):
        await register_active_request(
            "rid-1",
            "prov",
            "std-chat",
            1,
            client_ip=None,
            prompt_tokens=5,
            requested_model="prov/glm-x",
        )
        snapshot = await build_live_stats_snapshot()
        session = snapshot["sessions"]["live-key"]
        self.assertIn("glm-x -> prov/std-chat", session["models"])
        self.assertEqual(
            session["models"]["glm-x -> prov/std-chat"]["provider"], "prov"
        )

    async def test_live_snapshot_collapses_when_requested_matches_actual(self):
        await register_active_request(
            "rid-2",
            "prov",
            "glm-x",
            1,
            client_ip=None,
            prompt_tokens=5,
            requested_model="glm-x",
        )
        snapshot = await build_live_stats_snapshot()
        session = snapshot["sessions"]["live-key"]
        self.assertIn("prov/glm-x", session["models"])
        self.assertNotIn("-> prov/glm-x", " ".join(session["models"]))

    async def test_live_snapshot_collapses_when_no_requested_model(self):
        await register_active_request(
            "rid-3",
            "prov",
            "std-chat",
            1,
            client_ip=None,
            prompt_tokens=5,
        )
        snapshot = await build_live_stats_snapshot()
        session = snapshot["sessions"]["live-key"]
        self.assertIn("prov/std-chat", session["models"])

    async def test_live_snapshot_model_entry_tracks_elapsed(self):
        from datetime import datetime, timedelta

        stale = datetime.now() - timedelta(seconds=90)
        active_requests["rid-4"] = {
            "request_id": "rid-4",
            "provider": "prov",
            "model": "std-chat",
            "requested_model": None,
            "display_model": "std-chat",
            "upstream_model": None,
            "api_key_id": 1,
            "client_ip": None,
            "prompt_tokens": 0,
            "started_at": stale,
        }
        snapshot = await build_live_stats_snapshot()
        entry = snapshot["sessions"]["live-key"]["models"]["prov/std-chat"]
        self.assertGreaterEqual(entry["elapsed_seconds"], 89)


class UserStatsModelMultiSlashTests(unittest.TestCase):
    def test_python_multi_slash_keeps_remainder(self):
        from app.services.model_naming import user_stats_model_name

        self.assertEqual(user_stats_model_name("a/b/c", None), "b/c")
        self.assertEqual(user_stats_model_name("prov/glm-5.3", None), "glm-5.3")

    def test_sql_expr_uses_strpos_not_split_part(self):
        from sqlalchemy.dialects import postgresql

        from app.core.database import RequestLog
        from app.services.model_naming import user_stats_model_expr

        sql = str(
            user_stats_model_expr(
                RequestLog.model, RequestLog.requested_model
            ).compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("strpos", sql)
        self.assertNotIn("split_part", sql)
        self.assertIn("coalesce", sql)


if __name__ == "__main__":
    unittest.main()
