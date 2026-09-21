import unittest

from app.core.config import stats, update_stats
from app.services.model_naming import (
    provider_stats_model_expr,
    provider_stats_model_name,
    user_stats_model_expr,
    user_stats_model_name,
)


class UserStatsModelNameTests(unittest.TestCase):
    def test_requested_model_wins(self):
        self.assertEqual(
            user_stats_model_name("glm-5.3", "upstream-glm"), "glm-5.3"
        )

    def test_multi_slash_strips_first_segment_only(self):
        self.assertEqual(
            user_stats_model_name("prov1/glm/team-a", "upstream-glm"), "glm/team-a"
        )

    def test_provider_prefix_stripped(self):
        self.assertEqual(
            user_stats_model_name("prov1/glm-5.3", "upstream-glm"), "glm-5.3"
        )

    def test_auto_kept_as_is(self):
        self.assertEqual(user_stats_model_name("auto", "upstream-glm"), "auto")

    def test_falls_back_to_model(self):
        self.assertEqual(user_stats_model_name(None, "glm-5.3"), "glm-5.3")
        self.assertEqual(user_stats_model_name("", "glm-5.3"), "glm-5.3")

    def test_prefix_only_falls_back_to_raw(self):
        self.assertEqual(user_stats_model_name("prov1/", "glm-5.3"), "prov1/")

    def test_all_missing_returns_none(self):
        self.assertIsNone(user_stats_model_name(None, None))
        self.assertIsNone(user_stats_model_name("", ""))


class ProviderStatsModelNameTests(unittest.TestCase):
    def test_actual_model_wins(self):
        self.assertEqual(
            provider_stats_model_name("upstream-glm", "glm-5.3"), "upstream-glm"
        )

    def test_empty_actual_falls_back(self):
        self.assertEqual(provider_stats_model_name("", "glm-5.3"), "glm-5.3")
        self.assertEqual(provider_stats_model_name(None, "glm-5.3"), "glm-5.3")


class SqlExpressionTests(unittest.TestCase):
    def _compile(self, expr):
        from sqlalchemy.dialects import postgresql

        return str(
            expr.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

    def test_user_expr_compiles(self):
        from app.core.database import RequestLog

        sql = self._compile(
            user_stats_model_expr(RequestLog.model, RequestLog.requested_model)
        )
        self.assertIn("strpos", sql)
        self.assertIn("coalesce", sql)
        self.assertNotIn("split_part", sql)

    def test_provider_expr_compiles(self):
        from app.core.database import RequestLog

        sql = self._compile(
            provider_stats_model_expr(RequestLog.model, RequestLog.actual_model)
        )
        self.assertIn("coalesce", sql)


class UpdateStatsUpstreamModelTests(unittest.TestCase):
    def setUp(self):
        stats["models"].clear()
        stats["api_keys"].clear()

    def test_models_bucket_uses_upstream_name(self):
        update_stats("prov", "glm-5.3", 10, api_key_id=1, upstream_model="up-glm")
        self.assertIn("up-glm", stats["models"])
        self.assertNotIn("glm-5.3", stats["models"])
        self.assertIn("glm-5.3", stats["api_keys"][1]["models"])

    def test_models_bucket_falls_back_to_model(self):
        update_stats("prov", "glm-5.3", 10, api_key_id=None)
        self.assertIn("glm-5.3", stats["models"])


class StreamFallbackLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def _record(self, status, log_id):
        from unittest.mock import AsyncMock, Mock, patch

        from app.services.proxy_runtime import response_handler

        create_log = AsyncMock(return_value=0)
        with (
            patch(
                "app.services.proxy_runtime.response_handler.update_request_log",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "app.services.proxy_runtime.response_handler.create_request_log",
                new=create_log,
            ),
            patch(
                "app.services.proxy_runtime.response_handler.update_request_content",
                new=AsyncMock(),
            ),
            patch(
                "app.services.proxy_runtime.response_handler.update_stats", new=Mock()
            ),
            patch(
                "app.services.proxy_runtime.response_handler.record_tokens_second",
                new=Mock(),
            ),
            patch(
                "app.services.proxy_runtime.response_handler.enrich_tokens_with_billing",
                new=AsyncMock(side_effect=lambda tokens_record, **kw: tokens_record),
            ),
        ):
            await response_handler._record_stream_result(
                "content",
                "",
                [],
                "stop",
                None,
                {},
                "prov",
                "glm-5.3",
                1,
                "127.0.0.1",
                "test",
                0,
                0,
                log_id,
                status,
                upstream_status_code=200,
                provider_key_id=9,
                upstream_model="up-glm",
                requested_model="prov1/glm-5.3",
            )
        return create_log

    async def test_success_fallback_keeps_dual_model_fields(self):
        create_log = await self._record("success", log_id=None)
        kwargs = create_log.call_args.kwargs
        self.assertEqual(kwargs.get("requested_model"), "prov1/glm-5.3")
        self.assertEqual(kwargs.get("actual_model"), "up-glm")

    async def test_error_fallback_keeps_dual_model_fields(self):
        create_log = await self._record("error", log_id=None)
        kwargs = create_log.call_args.kwargs
        self.assertEqual(kwargs.get("requested_model"), "prov1/glm-5.3")
        self.assertEqual(kwargs.get("actual_model"), "up-glm")

    async def test_cancelled_fallback_keeps_dual_model_fields(self):
        create_log = await self._record("cancelled", log_id=None)
        kwargs = create_log.call_args.kwargs
        self.assertEqual(kwargs.get("requested_model"), "prov1/glm-5.3")
        self.assertEqual(kwargs.get("actual_model"), "up-glm")

    async def test_update_failure_falls_back_with_dual_model_fields(self):
        create_log = await self._record("success", log_id=77)
        create_log.assert_awaited_once()
        kwargs = create_log.call_args.kwargs
        self.assertEqual(kwargs.get("requested_model"), "prov1/glm-5.3")
        self.assertEqual(kwargs.get("actual_model"), "up-glm")


if __name__ == "__main__":
    unittest.main()
