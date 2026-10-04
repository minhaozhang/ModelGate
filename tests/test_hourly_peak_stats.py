"""Hourly gateway peak recorder (max concurrency / max tokens per hour):

* sampler service state machine + throttled persistence,
* /stats/realtime passthrough of hour_peaks,
* static template guards for the mobile three-pod cluster, the collapsible
  request trend, and the 1000 tok/s speedo baseline (monitor + mobile).
"""

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def one(self):
        return self._row

    def scalar_one_or_none(self):
        return self._row


class _Ctx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, row=None):
        self._row = row
        self.added = []
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _FakeResult(self._row)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None


def _reset_state(ps):
    ps._state.update(
        date="",
        hour=-1,
        max_concurrency=0,
        max_tokens_per_second=0.0,
        last_persist_at=0.0,
        dirty=False,
    )


class PeakSamplerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import app.core.config as config
        import app.services.peak_stats as ps

        self.config = config
        self.ps = ps
        self._buckets = list(config.token_buckets)
        _reset_state(ps)

    def tearDown(self):
        self.config.token_buckets.clear()
        self.config.token_buckets.extend(self._buckets)
        _reset_state(self.ps)

    async def test_observe_tracks_current_hour_maxima(self):
        now = datetime.now()
        async with self.config.active_requests_lock:
            self.config.active_requests["pk-test-1"] = {"started_at": now}
            self.config.active_requests["pk-test-2"] = {"started_at": now}
        session = _FakeSession(row=None)
        try:
            with patch.object(self.ps, "async_session_maker", return_value=_Ctx(session)):
                await self.ps.observe_peak_sample(now)
            payload = self.ps.peaks_payload()
        finally:
            async with self.config.active_requests_lock:
                self.config.active_requests.pop("pk-test-1", None)
                self.config.active_requests.pop("pk-test-2", None)
        self.assertEqual(payload["date"], now.strftime("%Y-%m-%d"))
        self.assertEqual(payload["hour"], now.hour)
        self.assertGreaterEqual(payload["max_concurrency"], 2)
        # first observed change forces a row insert for the bucket
        self.assertEqual(len(session.added), 1)
        row = session.added[0]
        self.assertEqual(row.date, now.strftime("%Y-%m-%d"))
        self.assertEqual(row.hour, now.hour)
        self.assertGreaterEqual(row.max_concurrency, 2)

    async def test_rollover_persists_previous_bucket_then_resets(self):
        now = datetime.now()
        self.ps._state.update(
            date="2000-01-01",
            hour=5,
            max_concurrency=7,
            max_tokens_per_second=99.5,
            dirty=True,
        )
        session = _FakeSession(row=None)
        with patch.object(self.ps, "async_session_maker", return_value=_Ctx(session)):
            await self.ps.observe_peak_sample(now)
        # previous bucket written before the reset
        self.assertEqual(len(session.added), 1)
        self.assertEqual(session.added[0].date, "2000-01-01")
        self.assertEqual(session.added[0].hour, 5)
        self.assertEqual(session.added[0].max_concurrency, 7)
        self.assertEqual(session.added[0].max_tokens_per_second, 99.5)
        # state now tracks the fresh bucket
        payload = self.ps.peaks_payload()
        self.assertEqual(payload["date"], now.strftime("%Y-%m-%d"))
        self.assertEqual(payload["hour"], now.hour)

    async def test_persist_updates_existing_row_with_max(self):
        now = datetime.now()
        self.ps._state.update(
            date="2000-01-01",
            hour=5,
            max_concurrency=3,
            max_tokens_per_second=12.0,
            dirty=True,
        )
        existing = SimpleNamespace(
            date="2000-01-01",
            hour=5,
            max_concurrency=1,
            max_tokens_per_second=20.0,
            updated_at=None,
        )
        session = _FakeSession(row=existing)
        with patch.object(self.ps, "async_session_maker", return_value=_Ctx(session)):
            await self.ps._persist(now, force=True)
        # per-field max: concurrency rises, tps keeps the larger stored value
        self.assertEqual(existing.max_concurrency, 3)
        self.assertEqual(existing.max_tokens_per_second, 20.0)
        self.assertEqual(len(session.added), 0)

    async def test_no_write_when_nothing_changed(self):
        now = datetime.now()
        self.ps._state.update(date="2000-01-01", hour=5, dirty=False)
        with patch.object(self.ps, "async_session_maker") as maker:
            await self.ps._persist(now, force=False)
        maker.assert_not_called()


class RealtimePeaksPassthroughTests(unittest.IsolatedAsyncioTestCase):
    async def test_realtime_includes_hour_peaks(self):
        import app.routes.stats as stats_mod

        peaks = {"date": "2026-10-04", "hour": 20, "max_concurrency": 4, "max_tokens_per_second": 812.3}
        snapshot = {
            "active_requests": 4,
            "active_users": 2,
            "hour_peaks": peaks,
        }
        with patch.object(stats_mod, "build_live_stats_snapshot", return_value=snapshot), \
             patch.object(stats_mod, "get_total_tokens_per_second", lambda: 812.3), \
             patch.object(stats_mod, "requests_per_second", {}), \
             patch.object(stats_mod, "permission_required", lambda *_a, **_k: (lambda: True)):
            data = await stats_mod.get_realtime_stats(_=True)
        self.assertEqual(data["hour_peaks"], peaks)
        self.assertEqual(data["active_requests"], 4)


class HourlyPeaksTemplateGuards(unittest.TestCase):
    MOBILE = "web/templates/admin/mobile_home.html"
    MONITOR = "web/templates/admin/monitor.html"

    @staticmethod
    def _read(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_mobile_cluster_markers(self):
        html = self._read(self.MOBILE)
        for marker in (
            "mg-cluster",
            'id="cluster-panel"',
            "ag-tach-dial",
            "ag-speedo-dial",
            "ag-status-dial",
            "ag-lamp-corner",
            "mountStatusDial",
            "setKeysHealth",
            "hour_peaks",
            "mg-peak-chip",       # per-dial hourly peak readout under speedo/tach
            'id="total-cost"',    # period cost card (ex-busyness slot) fed by /stats/period total_cost
            "mg-status-busyness", # busyness level replaces the verdict badge
            "SPEED_TIERS = [1000, 2000, 5000, 10000, 25000, 50000]",
            "mount('speedo', 'ag-speedo-dial', 1000",
            "updateClusterLive",
            "loadClusterSystemInfo",
            "loadClusterKeysStatus",
            "velPct",             # spring integrator parity with monitor
            "prefers-reduced-motion",
        ):
            self.assertIn(marker, html, f"mobile_home.html missing {marker}")

    def test_mobile_cluster_drops_outer_pods(self):
        html = self._read(self.MOBILE)
        self.assertNotIn("mountTopDial", html, "top-keys pod must not be ported to mobile")
        self.assertNotIn("ag-fuel-dial", html, "fuel dial pod must not be ported to mobile")
        self.assertNotIn(
            "ag-odometer",
            html,
            "the cost odometer overflows the small mobile speedo - monitor only",
        )

    def test_mobile_trend_collapsible_and_subtitle_removed(self):
        html = self._read(self.MOBILE)
        for marker in (
            "toggleSection('trend')",
            'id="trend-content"',
            'id="chevron-trend"',
            'id="trendChart"',
        ):
            self.assertIn(marker, html, f"mobile_home.html missing {marker}")
        self.assertNotIn(
            "Admin Dashboard",
            html,
            "the Admin Dashboard subtitle under the wordmark was removed by design",
        )

    def test_monitor_speedo_baseline_and_trip_peaks(self):
        html = self._read(self.MONITOR)
        for marker in (
            "SPEED_TIERS = [1000, 2000, 5000, 10000, 25000, 50000]",
            "mount('speedo', 'ag-speedo-dial', 1000",
            'id="mg-peak-conc"',   # hourly peaks moved onto the dials (chips)
            'id="mg-peak-tps"',
            "clusterHourPeak",
            "hour_peaks",
        ):
            self.assertIn(marker, html, f"monitor.html missing {marker}")


if __name__ == "__main__":
    unittest.main()
