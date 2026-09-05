import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


class AdminHomePanelTests(unittest.TestCase):
    """Admin home: active-user durations replace the slow-requests panel,
    and provider/key live status takes its place."""

    def test_slow_requests_panel_removed(self):
        html = _read("web/templates/admin/home.html")

        self.assertNotIn("slow-requests", html)
        self.assertNotIn("renderSlowRequests", html)
        self.assertNotIn("loadSlowRequests", html)
        self.assertNotIn("stats/slow", html)

    def test_provider_keys_live_panel_present(self):
        html = _read("web/templates/admin/home.html")

        self.assertIn("provider-keys-live", html)
        self.assertIn("provider-keys-count", html)
        self.assertIn("stats/provider-keys-live", html)
        self.assertIn("health-badge", html)

    def test_active_users_have_ticking_duration(self):
        html = _read("web/templates/admin/home.html")

        self.assertIn("live-duration", html)
        self.assertIn("formatDuration", html)
        self.assertIn("120", html)
        self.assertIn("text-orange-500", html)
        self.assertIn("text-red-600", html)

    def test_mobile_home_uses_explicit_provider_field(self):
        html = _read("web/templates/admin/mobile_home.html")

        self.assertIn("info.provider", html)


class ProviderKeyRowBuilderTests(unittest.TestCase):
    def test_rows_filtered_sorted_and_carry_fields(self):
        from app.routes.stats import _build_provider_key_rows

        providers_cache = {
            "alpha": {
                "id": 1,
                "disabled_reason": None,
                "api_keys": [
                    {"id": 11, "label": "k11"},
                    {"id": 12, "label": "k12"},
                ],
                "models": [],
            },
            "beta": {
                "id": 2,
                "disabled_reason": "circuit breaker",
                "api_keys": [{"id": 21, "label": "k21"}],
                "models": [],
            },
            "gamma": {
                "id": 3,
                "disabled_reason": None,
                "api_keys": [],
                "models": [],
            },
        }
        rows = _build_provider_key_rows(
            providers_cache,
            key_usage={11: 30, 12: 5, 21: 50},
            provider_usage={3: 0},
            key_health={11: 90, 12: 45, 21: 100},
            sem_limits={},
        )

        self.assertEqual(
            [r["key_label"] for r in rows], ["k21", "k11", "k12"]
        )
        self.assertTrue(all(r["usage"] > 0 for r in rows))
        self.assertEqual(rows[0]["provider"], "beta")
        self.assertTrue(rows[0]["provider_disabled"])
        self.assertEqual(rows[0]["health_score"], 100)
        self.assertEqual(rows[0]["health_level"], "excellent")
        self.assertEqual(rows[1]["health_score"], 90)
        self.assertEqual(rows[2]["health_level"], "warning")
        self.assertNotIn("gamma", [r["provider"] for r in rows])
