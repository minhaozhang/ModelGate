"""Mobile admin log detail: ip-location endpoint + template wiring.

Covers:
- /admin/api/logs/ip-location label building (cn region+isp, foreign fallback)
- LAN IPs are answered locally (no provider/DB hit)
- mobile_home.html wiring for lazy geo + slim token rows
- nav.html must not use Tailwind dark: variants (OS color scheme hijack bug)
"""

import unittest
from unittest.mock import AsyncMock, patch

MOBILE = r"web\templates\admin\mobile_home.html"
NAV = r"web\templates\components\nav.html"


class IpLocationEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_lan_ip_answered_locally(self):
        import app.routes.logs as logs_mod

        data = await logs_mod.get_log_ip_location(ip="192.168.1.5", _=True)
        self.assertFalse(data["ok"])
        self.assertIn("局域网", data["label"])

    async def test_cn_ip_builds_region_and_isp_label(self):
        import app.routes.logs as logs_mod

        fake = {
            "ok": True,
            "province": "广东省",
            "city": "深圳市",
            "country": "",
            "isp": "中国电信",
        }
        with patch(
            "app.services.ip_location.lookup_ip_location",
            AsyncMock(return_value=fake),
        ):
            data = await logs_mod.get_log_ip_location(ip="1.2.3.4", _=True)
        self.assertTrue(data["ok"])
        for part in ("广东省", "深圳市", "中国电信"):
            self.assertIn(part, data["label"])

    async def test_foreign_ip_falls_back_to_country(self):
        import app.routes.logs as logs_mod

        fake = {
            "ok": True,
            "province": "",
            "city": "Ashburn",
            "country": "United States",
            "isp": "Comcast",
        }
        with patch(
            "app.services.ip_location.lookup_ip_location",
            AsyncMock(return_value=fake),
        ):
            data = await logs_mod.get_log_ip_location(ip="8.8.8.8", _=True)
        self.assertTrue(data["ok"])
        self.assertIn("United States", data["label"])
        self.assertIn("Comcast", data["label"])

    async def test_failed_lookup_surfaces_message(self):
        import app.routes.logs as logs_mod

        fake = {"ok": False, "message": "两个数据源均无法解析该 IP"}
        with patch(
            "app.services.ip_location.lookup_ip_location",
            AsyncMock(return_value=fake),
        ):
            data = await logs_mod.get_log_ip_location(ip="1.1.1.1", _=True)
        self.assertFalse(data["ok"])
        self.assertIn("无法解析", data["label"])


class MobileLogsTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mobile = open(MOBILE, encoding="utf-8").read()
        cls.nav = open(NAV, encoding="utf-8").read()

    def test_ip_geo_wiring_present(self):
        for marker in (
            "loadLogIpGeo",
            "data-ipgeo",
            "logs/ip-location",
            "ipGeoCache",
        ):
            self.assertIn(marker, self.mobile, f"mobile_home.html missing {marker}")

    def test_detail_has_token_total_and_ctx_est(self):
        # slim rows: ctx/cache moved to the expandable detail with a real total
        for marker in ("logTotal", "logCtx"):
            self.assertIn(marker, self.mobile, f"mobile_home.html missing {marker}")
        # the collapsed row must no longer render the ctx estimate
        row = self.mobile.split('class="flex items-center gap-2 text-[10px] log-tokens mt-1"')[1]
        row = row.split("</div>")[0]
        self.assertNotIn("logCtx", row)
        self.assertNotIn("logCache", row)

    def test_key_dropdown_dark_overrides(self):
        for marker in (
            "body.theme-dark .text-gray-700",
            "body.theme-dark #logs-key-dropdown > div:hover",
        ):
            self.assertIn(marker, self.mobile, f"mobile_home.html missing {marker}")

    def test_nav_has_no_os_dark_variants(self):
        # regression guard: dark: variants follow prefers-color-scheme, not the
        # app theme, which left a dark unreadable sidebar under light mode
        self.assertNotIn("dark:", self.nav)


if __name__ == "__main__":
    unittest.main()
