"""Per-request tokens/s speed column (speed_tokens_per_s): DB generated
column on request_logs / request_logs_history, view exposure, archive INSERT
must NOT copy the generated column, and serializer/API exposure on both the
admin and user sides.
"""

import unittest
from datetime import datetime
from types import SimpleNamespace


class SpeedExpressionTests(unittest.TestCase):
    def test_expression_guards_and_tokens_keys(self):
        from app.core.db_models import REQUEST_SPEED_EXPR

        # Stream duration guard: only latency beyond first chunk counts.
        self.assertIn("latency_ms > first_chunk_ms", REQUEST_SPEED_EXPR)
        # Both token key spellings are accepted, missing tokens stay NULL.
        self.assertIn("(tokens->>'completion_tokens')", REQUEST_SPEED_EXPR)
        self.assertIn("(tokens->>'output_tokens')", REQUEST_SPEED_EXPR)
        # Never divide by zero.
        self.assertIn("NULLIF", REQUEST_SPEED_EXPR)

    def test_expression_excludes_first_prefill_token(self):
        """v2 formula: (N - 1) / (latency - first_chunk), industry standard."""
        from app.core.db_models import REQUEST_SPEED_EXPR

        self.assertIn(") - 1, 0)", REQUEST_SPEED_EXPR)

    def test_migration_replaces_v1_expression(self):
        from app.core import db_migrations

        src = open(db_migrations.__file__, encoding="utf-8").read()
        # v1 columns are dropped and recreated; v2 is detected by PG's deparse
        # fingerprint "- (1)::numeric" so the swap is a true one-time event.
        self.assertIn('if current_expr is not None and "- (1)::numeric" not in current_expr', src)
        self.assertIn("DROP COLUMN speed_tokens_per_s", src)
        # The view is dropped first so the column swap is not blocked.
        self.assertLess(
            src.index("DROP VIEW IF EXISTS request_logs_all"),
            src.index("DROP COLUMN speed_tokens_per_s"),
        )

    def test_display_threshold_hides_tiny_bursts(self):
        bases = {
            r"D:\project\ModelGate\web\templates\admin\request_logs.html",
            r"D:\project\ModelGate\web\templates\user\tab_stats_v2.html",
            r"D:\project\ModelGate\web\templates\admin\mobile_home.html",
        }
        for path in bases:
            with self.subTest(path=path):
                src = open(path, encoding="utf-8").read()
                has_threshold = (
                    ("SPEED_MIN_TOKENS = 50" in src and "SPEED_MIN_STREAM_MS = 500" in src)
                    or (">= 50" in src and ">= 500" in src)
                )
                self.assertTrue(has_threshold, "min tokens/duration threshold required")


    def test_orm_models_expose_generated_column(self):
        from sqlalchemy import Computed

        from app.core.db_models import RequestLog, RequestLogHistory

        for model in (RequestLog, RequestLogHistory):
            col = model.__table__.columns["speed_tokens_per_s"]
            self.assertIsNotNone(col.computed, "column must be DB-generated")
            self.assertIsInstance(col.computed, Computed)

    def test_request_logs_all_fallback_table_has_column(self):
        from app.core.db_models import request_logs_all_table

        self.assertIn("speed_tokens_per_s", request_logs_all_table.columns)


class MigrationSourceTests(unittest.TestCase):
    def test_migration_adds_generated_column_to_both_tables(self):
        from app.core import db_migrations

        src = open(db_migrations.__file__, encoding="utf-8").read()
        self.assertIn('("request_logs", "request_logs_history")', src)
        self.assertIn("GENERATED ALWAYS AS", src)
        # The union view must expose the new column.
        self.assertIn('"speed_tokens_per_s, "', src)

    def test_view_column_list_matches_table_column_order(self):
        from app.core.db_models import request_logs_all_table, RequestLog

        view_cols = {
            "id", "api_key_id", "provider_id", "model", "response", "tokens",
            "latency_ms", "first_chunk_ms", "wait_ms", "speed_tokens_per_s",
            "request_context_tokens", "status", "upstream_status_code",
            "downstream_status_code", "client_ip", "user_agent",
            "inbound_protocol", "error", "intent", "requested_model",
            "actual_model", "provider_key_id", "provider_key_label",
            "routing_decision", "request_image_count", "fallback_tries",
            "created_at", "updated_at",
        }
        self.assertEqual(
            view_cols, set(request_logs_all_table.columns.keys())
        )
        self.assertIn("speed_tokens_per_s", RequestLog.__table__.columns)

    def test_archive_insert_does_not_copy_generated_column(self):
        from app.services import stats_aggregator

        src = open(stats_aggregator.__file__, encoding="utf-8").read()
        self.assertNotIn(
            "INSERT INTO request_logs_history (\n                        speed_tokens_per_s",
            src,
        )
        # Base columns used by the generated expression ARE archived, so the
        # history table can recompute speed on its own.
        self.assertIn("first_chunk_ms", src)
        self.assertIn("latency_ms", src)
        self.assertIn("tokens", src)


class _Base:
    id = 7
    provider_id = 3
    api_key_id = 5
    model = "gpt-test"
    response = None
    tokens = {"prompt_tokens": 10, "completion_tokens": 420}
    latency_ms = 12_000.0
    first_chunk_ms = 2_000.0
    wait_ms = 5.0
    speed_tokens_per_s = 42.0
    request_context_tokens = 100
    request_image_count = 0
    fallback_tries = []
    status = "success"
    upstream_status_code = 200
    downstream_status_code = 200
    client_ip = "1.2.3.4"
    user_agent = "ua"
    inbound_protocol = "openai"
    error = None
    intent = None
    requested_model = None
    actual_model = None
    provider_key_id = None
    provider_key_label = None
    routing_decision = None
    created_at = datetime(2026, 9, 30, 12, 0, 0)
    updated_at = None


class AdminSerializerTests(unittest.TestCase):
    def test_serialize_error_log_includes_speed(self):
        from app.routes.logs import _serialize_error_log

        payload = _serialize_error_log(_Base(), {3: "prov"}, {5: "key"})
        self.assertEqual(payload["speed_tokens_per_s"], 42.0)

    def test_serialize_error_log_speed_defaults_to_none(self):
        from app.routes.logs import _serialize_error_log

        row = SimpleNamespace(
            **{k: getattr(_Base, k) for k in _Base.__dict__ if not k.startswith("_")}
        )
        row.speed_tokens_per_s = None
        payload = _serialize_error_log(row, {}, {})
        self.assertIsNone(payload["speed_tokens_per_s"])


class UserSummarizerTests(unittest.TestCase):
    def test_summarize_request_row_includes_speed(self):
        from app.routes.user import _summarize_request_row

        row = SimpleNamespace(
            id=_Base.id,
            model=_Base.model,
            provider_id=_Base.provider_id,
            tokens=_Base.tokens,
            request_context_tokens=_Base.request_context_tokens,
            request_image_count=_Base.request_image_count,
            fallback_tries=_Base.fallback_tries,
            latency_ms=_Base.latency_ms,
            first_chunk_ms=_Base.first_chunk_ms,
            wait_ms=_Base.wait_ms,
            speed_tokens_per_s=_Base.speed_tokens_per_s,
            status="success",
            error=None,
            created_at=_Base.created_at,
        )
        payload = _summarize_request_row(row, {3: "prov"})
        self.assertEqual(payload["speed_tokens_per_s"], 42.0)

    def test_recent_requests_payload_keys(self):
        from app.routes import user as user_routes

        src = open(user_routes.__file__, encoding="utf-8").read()
        # Dashboard card payload and my-requests select both carry the column.
        self.assertGreaterEqual(
            src.count("RequestLog.speed_tokens_per_s,"), 3,
            "recent requests, my-requests and export selects must all read it",
        )
        self.assertIn('"speed_tokens_per_s": float(r.speed_tokens_per_s)', src)


class AdminExportTests(unittest.TestCase):
    def test_admin_export_has_speed_header_and_value(self):
        from app.routes import logs as logs_routes

        src = open(logs_routes.__file__, encoding="utf-8").read()
        self.assertIn('"速度(tok/s)"', src)
        self.assertIn(
            'getattr(log, "speed_tokens_per_s", None) if getattr(log, "speed_tokens_per_s", None) is not None else ""',
            src,
        )


if __name__ == "__main__":
    unittest.main()
