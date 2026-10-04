"""Admin monitor instrument cluster: odometer endpoint (all-time cost/request
totals off the provider daily aggregates) plus static template guards for the
Porsche-style triple gauge cluster.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def one(self):
        return self._row


class _Ctx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, row):
        self._row = row
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _FakeResult(self._row)


def _reset_cache(target):
    target._odometer_cache["at"] = 0.0
    target._odometer_cache["data"] = None


class OdometerEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_all_time_cost_and_requests(self):
        import app.routes.stats as stats_mod

        _reset_cache(stats_mod)
        row = SimpleNamespace(cost=1234.567, requests=98765)
        session = _FakeSession(row)
        with patch.object(stats_mod, "async_session_maker", return_value=_Ctx(session)), \
             patch.object(stats_mod, "permission_required", lambda *_a, **_k: (lambda: True)):
            data = await stats_mod.get_odometer(_=True)
        self.assertEqual(data["total_cost"], 1234.57)
        self.assertEqual(data["total_requests"], 98765)
        # The aggregate must read the provider daily stats table.
        stmt_sql = str(session.statements[0]).lower()
        self.assertIn("provider_daily_stat", stmt_sql)
        self.assertIn("cost_cny", stmt_sql)

    async def test_cache_short_circuits_within_ttl(self):
        import time

        import app.routes.stats as stats_mod

        _reset_cache(stats_mod)
        cached = {"total_cost": 1.0, "total_requests": 2}
        stats_mod._odometer_cache["at"] = time.monotonic()
        stats_mod._odometer_cache["data"] = cached
        with patch.object(stats_mod, "async_session_maker") as maker:
            data = await stats_mod.get_odometer(_=True)
        maker.assert_not_called()
        self.assertEqual(data, cached)


class MonitorClusterTemplateTests(unittest.TestCase):
    """Static guards for the triple gauge cluster markup (added with the
    monitor cluster panel; kept green once the template lands)."""

    TEMPLATE = "web/templates/admin/monitor.html"

    def _read(self):
        with open(self.TEMPLATE, encoding="utf-8") as fh:
            return fh.read()

    def test_cluster_markers_present(self):
        html = self._read()
        for marker in (
            "cluster-panel",
            "ag-top",             # left pod: top-3 key usage leaderboard
            "mountTopDial",
            "setTopKeys",
            "ag-tach",            # center tach: concurrency
            "ag-speedo",          # speed: tokens/s
            "ag-status",          # status dial: keys/cpu/mem/disk bars
            "ag-fuel",            # right pod: key health arc (E -> F)
            "mg-peak-chip",       # per-dial hourly peak readout (ex-odometer slot)
            "mg-status-busyness", # busyness level replaces the verdict badge
            "ag-redzone",         # tach redline arc
            "ag-console",         # bottom console: trip computer
            "ag-lamp-corner",     # tell-tales pinned to the tach face
            "ag-trip",            # trip computer (active users / uptime / total requests)
            "ag-status-dial",
            "ag-bar-row",         # segmented vehicle-computer bars
            "mountStatusDial",
            "setStatusSys",
            "peakShort",
            "_agTicks",
            "velPct",             # spring integrator
            "prefers-reduced-motion",
        ):
            self.assertIn(marker, html, f"monitor.html missing {marker}")

    def test_lamp_wiring_present(self):
        html = self._read()
        for marker in (
            "ag-lamp-redline",
            "ag-lamp-fuel",
            "ag-lamp-disabled",
            "ag-lamp-offline",
            "disabled_providers",   # disabled lamp driven by live snapshot
            "clusterLastLiveAt",    # offline watchdog heartbeat
        ):
            self.assertIn(marker, html, f"monitor.html missing {marker}")


if __name__ == "__main__":
    unittest.main()
