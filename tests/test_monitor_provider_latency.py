import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MonitorProviderLatencyBackendTests(unittest.TestCase):
    def _monitor_body(self):
        source = (ROOT / "app" / "routes" / "stats.py").read_text(encoding="utf-8")
        start = source.index("async def get_monitor_details")
        end = source.index("@router.get(\"/stats/period\")")
        return source[start:end]

    def test_latency_payload_has_provider_dimension(self):
        body = self._monitor_body()

        self.assertIn('"providers"', body)
        self.assertIn('"provider_series"', body)

    def test_provider_latency_query_excludes_null_provider_and_keeps_p95(self):
        body = self._monitor_body()

        self.assertIn("RequestLog.provider_id.is_not(None)", body)
        self.assertIn("provider_latency", body)
        self.assertGreaterEqual(
            body.count("percentile_cont(0.95)"), 2,
            "provider latency query must compute p95 like the model query",
        )

    def test_provider_series_resolved_via_providers_map(self):
        body = self._monitor_body()

        self.assertIn("providers_map.get(", body)


class MonitorProviderLatencyUiTests(unittest.TestCase):
    def _html(self):
        return (ROOT / "web" / "templates" / "admin" / "monitor.html").read_text(
            encoding="utf-8"
        )

    def test_latency_card_has_dimension_switch(self):
        html = self._html()

        self.assertIn("latency-dim-model", html)
        self.assertIn("latency-dim-provider", html)
        self.assertIn("setLatencyDimension('provider')", html)
        self.assertIn("setLatencyDimension('model')", html)
        self.assertIn("let currentLatencyDimension = 'model'", html)
        self.assertIn("currentLatencyDimension === 'provider'", html)

    def test_latency_chart_reads_provider_series(self):
        html = self._html()

        self.assertIn("provider_series", html)
        self.assertIn("latencyData.providers", html)

    def test_latency_i18n_has_provider_variants(self):
        html = self._html()

        self.assertIn("hourlyP95ResponseTimeProvider", html)
        self.assertIn("hourlyAverageResponseTimeProvider", html)
        self.assertIn("hourlyResponseTimeRangeProvider", html)
        self.assertIn("responseTimeHeatmapProvider", html)
        self.assertIn("providerResponseTime", html)
        self.assertIn("modelResponseTime", html)

    def test_heatmap_corner_label_follows_dimension(self):
        html = self._html()

        self.assertIn("heatmapCornerLabel", html)


if __name__ == "__main__":
    unittest.main()
