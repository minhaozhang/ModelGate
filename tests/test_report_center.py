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


if __name__ == "__main__":
    unittest.main()
