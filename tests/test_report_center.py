"""报表中心 / 标签统计 / 个人花费趋势的静态断言与结构检查"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TagDailyStatsModelTests(unittest.TestCase):
    def test_tag_daily_stats_table_and_indexes_declared(self):
        migrations = (ROOT / "app" / "core" / "db_migrations.py").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS tag_daily_stats", migrations)
        self.assertIn("uq_tag_daily_stats", migrations)
        self.assertIn("idx_tag_daily_stats_tag", migrations)

    def test_api_key_daily_stats_gets_cost_column_migration(self):
        migrations = (ROOT / "app" / "core" / "db_migrations.py").read_text(encoding="utf-8")
        self.assertIn(
            "ALTER TABLE api_key_daily_stats ADD COLUMN IF NOT EXISTS cost_cny",
            migrations,
        )
        models = (ROOT / "app" / "core" / "db_models.py").read_text(encoding="utf-8")
        self.assertIn("class TagDailyStat(Base):", models)

    def test_provider_key_daily_stats_table_declared(self):
        migrations = (ROOT / "app" / "core" / "db_migrations.py").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS provider_key_daily_stats", migrations)
        self.assertIn("uq_provider_key_stats", migrations)
        self.assertIn("idx_provider_key_stats_date", migrations)
        self.assertIn("ALTER TABLE provider_daily_stats ADD COLUMN IF NOT EXISTS cost_cny", migrations)
        models = (ROOT / "app" / "core" / "db_models.py").read_text(encoding="utf-8")
        self.assertIn("class ProviderKeyDailyStat(Base):", models)

    def test_aggregator_writes_provider_cost_and_key_stats(self):
        source = (ROOT / "app" / "services" / "stats_aggregator.py").read_text(encoding="utf-8")
        self.assertIn("provider_key_stats", source)
        self.assertIn("ProviderKeyDailyStat(", source)
        self.assertIn("delete(ProviderKeyDailyStat).where(ProviderKeyDailyStat.date == date_str)", source)
        # backfill safety: only re-aggregate dates whose raw logs still exist
        self.assertIn("func.to_char(RequestLogRead.created_at", source)

    def test_report_center_has_provider_and_provider_key_views(self):
        source = (ROOT / "app" / "routes" / "report_center.py").read_text(encoding="utf-8")
        self.assertIn("_query_by_provider", source)
        self.assertIn("_query_by_provider_key", source)
        self.assertIn('@router.get("/by-provider")', source)
        self.assertIn('@router.get("/by-provider-key")', source)
        self.assertIn('@router.get("/by-provider.csv")', source)
        self.assertIn('@router.get("/by-provider-key.csv")', source)
        html = (ROOT / "web" / "templates" / "admin" / "report_center.html").read_text(encoding="utf-8")
        self.assertIn("rcSetView('provider')", html)
        self.assertIn("rcSetView('provider-key')", html)
        self.assertIn("rc-head-provider-key", html)

    def test_aggregator_reads_total_cost_from_tokens_jsonb(self):
        source = (ROOT / "app" / "services" / "stats_aggregator.py").read_text(encoding="utf-8")
        self.assertIn("async def aggregate_tag_daily_stats", source)
        self.assertIn("async def backfill_tag_stats", source)
        self.assertIn('"total_cost_cny"', source)
        self.assertIn('delete(TagDailyStat).where(TagDailyStat.date == date_str)', source)

    def test_scheduler_registers_tag_aggregation_task(self):
        source = (ROOT / "app" / "services" / "scheduler.py").read_text(encoding="utf-8")
        self.assertIn('"aggregate_tag_daily_stats": {', source)
        self.assertIn('"aggregate_tag_daily_stats": _task_aggregate_tags', source)
        self.assertIn("backfill_tag_stats", source)


class ReportCenterPageTests(unittest.TestCase):
    def test_nav_links_to_report_center(self):
        nav = (ROOT / "web" / "templates" / "components" / "nav.html").read_text(encoding="utf-8")
        self.assertIn("/admin/report-center", nav)
        self.assertNotIn("mcp-servers", nav)

    def test_report_center_page_has_views_and_export(self):
        html = (ROOT / "web" / "templates" / "admin" / "report_center.html").read_text(encoding="utf-8")
        self.assertIn("rcSetView('tag')", html)
        self.assertIn("rcSetView('key')", html)
        self.assertIn("/admin/api/report-center/by-", html)
        self.assertIn("by-${rcView}.csv", html)

    def test_report_center_single_level_tabs_cover_all_reports(self):
        """报表中心整合为单层 tab:快照四维度 + 原始日志四维度,不再有 tab 之上的模式切换。"""
        html = (ROOT / "web" / "templates" / "admin" / "report_center.html").read_text(encoding="utf-8")
        for view in ("tag", "key", "provider", "provider-key", "provider_model", "user", "ip", "user_ip"):
            self.assertIn(f"rcSetView('{view}')", html)
            self.assertIn(f"rc-tab-{view}", html)
        # 顶层模式切换(用量报表/请求统计)已移除
        self.assertNotIn("rcSetMode", html)
        self.assertNotIn("rc-mode-", html)
        # 统一筛选栏:日期 + 快捷区间对全部 tab 生效;日志筛选仅日志类 tab 显示
        self.assertIn("rc-live-filters", html)
        self.assertIn("classList.toggle('hidden', !isLive(view))", html)

    def test_aggregate_api_supports_all_statuses_and_ip_city(self):
        """logs/aggregate:status=all 真正不过滤状态;ip / user_ip 维度批量带出归属地。"""
        source = (ROOT / "app" / "routes" / "logs.py").read_text(encoding="utf-8")
        self.assertIn('if status == "all":', source)
        # ip 维度与 user_ip 维度都批量查 ip_locations 并返回 ip_city
        self.assertIn('"group_by": "ip"', source)
        self.assertIn('"group_by": "user_ip"', source)
        self.assertEqual(source.count("ip_cities = await _ip_city_map"), 2)
        self.assertIn('"ip_city": ip_cities.get(r.client_ip or "", "")', source)
        # 前端 IP 报表渲染归属地列(表头 + CSV 导出)
        html = (ROOT / "web" / "templates" / "admin" / "report_center.html").read_text(encoding="utf-8")
        self.assertIn("location: T('归属地', 'Location')", html)
        self.assertIn("escapeHtml(r.ip_city || '-')", html)
        self.assertIn("'Location', 'Requests'", html)

    def test_report_center_router_uses_rbac_permission(self):
        source = (ROOT / "app" / "routes" / "report_center.py").read_text(encoding="utf-8")
        self.assertIn('permission_required("page.report_center")', source)
        self.assertIn("_query_by_tag", source)
        self.assertIn("_query_by_key", source)
        migrations = (ROOT / "app" / "core" / "db_migrations.py").read_text(encoding="utf-8")
        self.assertIn('"page.report_center"', migrations)

    def test_report_center_page_registered(self):
        pages = (ROOT / "app" / "routes" / "pages.py").read_text(encoding="utf-8")
        main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn('@router.get("/report-center"', pages)
        self.assertIn("report_center.router", main)


class UserCostTrendTests(unittest.TestCase):
    def test_cost_trend_endpoint_exists(self):
        source = (ROOT / "app" / "routes" / "user.py").read_text(encoding="utf-8")
        self.assertIn('@router.get("/user/api/cost-trend")', source)
        self.assertIn("total_cost", source)
        self.assertIn("ApiKeyDailyStat.cost_cny", source)

    def test_stats_tab_has_cost_chart_and_total(self):
        html = (ROOT / "web" / "templates" / "user" / "tab_stats_v2.html").read_text(encoding="utf-8")
        self.assertIn("v2-cost-chart", html)
        self.assertIn("v2SetCostMetric", html)
        self.assertIn("/user/api/cost-trend", html)
        self.assertIn("v2-cost-window", html)


class IpCityLabelTests(unittest.TestCase):
    """IP 报表归属地文案:_ip_city_map 的拼接规则(中国省略国家、省市同名不重复)。"""

    def _map(self, rows):
        import asyncio

        from app.routes.logs import _ip_city_map

        class _Result:
            def all(self):
                return rows

        class _Session:
            async def execute(self, _stmt):
                return _Result()

        return asyncio.run(
            _ip_city_map(_Session(), ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4", ""])
        )

    def test_city_label_formatting(self):
        mapping = self._map(
            [
                ("1.1.1.1", "中国", "广东省", "深圳市"),
                ("2.2.2.2", "中国", "北京市", "北京市"),
                ("3.3.3.3", "美国", "加利福尼亚州", "洛杉矶"),
                ("4.4.4.4", None, None, None),
            ]
        )
        self.assertEqual(mapping["1.1.1.1"], "广东省 深圳市")
        self.assertEqual(mapping["2.2.2.2"], "北京市")
        self.assertEqual(mapping["3.3.3.3"], "美国 加利福尼亚州 洛杉矶")
        self.assertNotIn("4.4.4.4", mapping)

    def test_empty_ip_list_skips_query(self):
        import asyncio

        from app.routes.logs import _ip_city_map

        class _Session:
            async def execute(self, _stmt):  # pragma: no cover - must not be called
                raise AssertionError("no query expected")

        self.assertEqual(asyncio.run(_ip_city_map(_Session(), ["", None])), {})


if __name__ == "__main__":
    unittest.main()
