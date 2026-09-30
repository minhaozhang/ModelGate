"""Speed monitoring (tokens/s): hourly aggregation into model_speed_stats,
three dimensions (provider / provider+model / model), catch-up windows,
admin stats API wiring, and user catalog exposure.
"""

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch


class _FakeResult:
    def __init__(self, rows=None, scalar=None, rowcount=0):
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def all(self):
        return list(self._rows)

    def scalar(self):
        return self._scalar


class _Ctx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, results):
        # results: list of _FakeResult returned per execute call, or a callable
        self._results = list(results)
        self.statements = []
        self.params = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        self.statements.append(stmt)
        self.params.append(params)
        result = self._results.pop(0) if self._results else _FakeResult()
        return result

    async def commit(self):
        self.commits += 1


class GroupSpeedRowsTests(unittest.TestCase):
    def test_three_dimensions_with_sentinels(self):
        from app.services.speed_stats import group_speed_rows

        rows = [
            SimpleNamespace(
                provider_name="p1",
                requested_model="p1/gpt-4",
                model="gpt-4",
                actual_model="gpt-4o",
                output_tokens=600,
                stream_ms=2000,
            )
        ]
        grouped = group_speed_rows(rows)

        self.assertEqual(grouped[("p1", "gpt-4o")]["requests"], 1)  # provider+model
        self.assertEqual(grouped[("p1", "")]["output_tokens"], 600)  # provider rollup
        self.assertEqual(grouped[("", "gpt-4")]["stream_ms"], 2000.0)  # model (user view)

    def test_prefix_stripped_and_fallbacks(self):
        from app.services.speed_stats import group_speed_rows

        rows = [
            SimpleNamespace(
                provider_name="p2",
                requested_model=None,  # falls back to model
                model="glm-4",
                actual_model=None,  # falls back to model
                output_tokens=100,
                stream_ms=1000,
            )
        ]
        grouped = group_speed_rows(rows)
        self.assertIn(("p2", "glm-4"), grouped)
        self.assertIn(("", "glm-4"), grouped)

    def test_invalid_rows_skipped(self):
        from app.services.speed_stats import group_speed_rows

        rows = [
            SimpleNamespace(provider_name="p", requested_model="m", model="m",
                            actual_model="m", output_tokens=0, stream_ms=1000),
            SimpleNamespace(provider_name="p", requested_model="m", model="m",
                            actual_model="m", output_tokens=10, stream_ms=0),
        ]
        self.assertEqual(group_speed_rows(rows), {})


class MissingWindowsTests(unittest.TestCase):
    def test_from_scratch_returns_bounded_windows(self):
        from app.services.speed_stats import SPEED_BACKFILL_WINDOWS, hour_floor, missing_windows

        now = datetime(2026, 9, 30, 10, 37, 5)
        windows = missing_windows(None, now)
        self.assertEqual(len(windows), SPEED_BACKFILL_WINDOWS)
        self.assertEqual(windows[-1], hour_floor(now) - timedelta(hours=1))
        self.assertEqual(windows, sorted(windows))

    def test_catchup_gap(self):
        from app.services.speed_stats import missing_windows

        now = datetime(2026, 9, 30, 10, 0, 0)
        last = datetime(2026, 9, 30, 6, 0, 0)
        windows = missing_windows(last, now)
        self.assertEqual(windows, [
            datetime(2026, 9, 30, 7, 0, 0),
            datetime(2026, 9, 30, 8, 0, 0),
            datetime(2026, 9, 30, 9, 0, 0),
        ])

    def test_no_windows_when_up_to_date(self):
        from app.services.speed_stats import missing_windows

        now = datetime(2026, 9, 30, 10, 5, 0)
        self.assertEqual(missing_windows(now.replace(hour=9), now), [])


class ComputeTokensPerSecondTests(unittest.TestCase):
    def test_basic(self):
        from app.services.speed_stats import compute_tokens_per_second

        self.assertEqual(compute_tokens_per_second(1000, 2000), 500.0)
        self.assertEqual(compute_tokens_per_second(10, 4000), 2.5)

    def test_invalid_stream(self):
        from app.services.speed_stats import compute_tokens_per_second

        self.assertIsNone(compute_tokens_per_second(1000, 0))
        self.assertIsNone(compute_tokens_per_second(1000, None))


class AggregateSpeedWindowTests(unittest.IsolatedAsyncioTestCase):
    async def test_upserts_grouped_rows(self):
        from app.services.speed_stats import aggregate_speed_window

        rows = [
            SimpleNamespace(provider_name="p1", requested_model="m1", model="m1",
                            actual_model="m1", output_tokens=300, stream_ms=1000),
        ]
        session = _FakeSession([_FakeResult(rows)])
        with patch("app.services.speed_stats.async_session_maker", return_value=_Ctx(session)):
            written = await aggregate_speed_window(datetime(2026, 9, 30, 9, 0, 0))

        self.assertEqual(written, 3)  # (p1, m1) + (p1, "") + ("", m1)
        # first statement is the SELECT, the rest are upserts
        upserts = [p for p in session.params[1:] if p]
        self.assertEqual(len(upserts), 3)
        by_key = {(p["provider"], p["model"]): p for p in upserts}
        self.assertEqual(by_key[("p1", "m1")]["requests"], 1)
        self.assertEqual(by_key[("p1", "")]["output_tokens"], 300)
        self.assertEqual(by_key[("", "m1")]["stream_ms"], 1000.0)
        self.assertEqual(session.commits, 1)

    async def test_run_orchestrates_purge_and_catchup(self):
        import app.services.speed_stats as svc

        session = _FakeSession([
            _FakeResult(scalar=None),   # MAX(period_start)
            _FakeResult(rowcount=3),    # DELETE
        ])
        calls = []

        async def fake_aggregate(window):
            calls.append(window)
            return 0

        with patch.object(svc, "async_session_maker", return_value=_Ctx(session)), \
             patch.object(svc, "aggregate_speed_window", fake_aggregate):
            summary = await svc.run_speed_stats_aggregation()

        self.assertEqual(summary["purged"], 3)
        self.assertEqual(summary["windows"], len(calls))
        self.assertEqual(summary["windows"], svc.SPEED_BACKFILL_WINDOWS)
        self.assertIn("DELETE FROM model_speed_stats", str(session.statements[1]))


class GetModelSpeedMapTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_model_to_tps(self):
        from app.services.speed_stats import get_model_speed_map

        rows = [("gpt-4", 1000, 2000), ("dead", 0, 0)]
        session = _FakeSession([_FakeResult(rows)])
        with patch("app.services.speed_stats.async_session_maker", return_value=_Ctx(session)):
            speed_map = await get_model_speed_map(days=7)

        self.assertEqual(speed_map, {"gpt-4": 500.0})


class WiringTests(unittest.TestCase):
    def test_scheduler_registers_speed_task(self):
        from app.services.scheduler import TASK_HANDLERS, TASK_REGISTRY

        self.assertIn("speed_stats_aggregate", TASK_REGISTRY)
        self.assertEqual(TASK_REGISTRY["speed_stats_aggregate"]["default_cron"], "5 * * * *")
        self.assertIn("speed_stats_aggregate", TASK_HANDLERS)

    def test_speed_route_registered(self):
        from app.routes.stats import router

        paths = {getattr(route, "path", None) for route in router.routes}
        self.assertIn("/admin/api/stats/speed", paths)

    def test_monitor_html_contains_speed_card(self):
        html = open(
            "web/templates/admin/monitor.html", encoding="utf-8"
        ).read()
        for needle in (
            "speedChart",
            "setSpeedDimension('provider_model')",
            "speed-table-body",
            "stats/speed",
            "tokens_per_s_24h",
        ):
            self.assertIn(needle, html)

    def test_user_dashboard_renders_speed_badge(self):
        html = open(
            "web/templates/user/dashboard.html", encoding="utf-8"
        ).read()
        self.assertIn("speed_tokens_per_s", html)
        self.assertIn("speedHint", html)

    def test_catalog_attaches_speed(self):
        source = open("app/routes/user.py", encoding="utf-8").read()
        self.assertIn("get_model_speed_map", source)
        self.assertIn("speed_tokens_per_s", source)

    def test_migration_creates_speed_table(self):
        from app.core.db_migrations import _DDL

        joined = " ".join(s.lower() if isinstance(s, str) else "" for s in _DDL)
        self.assertIn("create table if not exists model_speed_stats", joined)
        self.assertIn("uq_model_speed_stats", joined)


if __name__ == "__main__":
    unittest.main()
