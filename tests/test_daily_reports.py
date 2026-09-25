import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DailyReportStaticTests(unittest.TestCase):
    def test_service_module_exists(self):
        src = (ROOT / "app" / "services" / "daily_report.py").read_text(encoding="utf-8")
        self.assertIn("async def generate_daily_report", src)
        self.assertIn('RequestLogRead.status == AUTH_FAILED_STATUS', src)
        self.assertIn('AuditLog.detail.like("登录失败%")', src)
        self.assertIn('"daily_report"', src)

    def test_route_module_registers_endpoints(self):
        src = (ROOT / "app" / "routes" / "daily_reports.py").read_text(encoding="utf-8")
        self.assertIn('prefix="/admin/api/daily-reports"', src)
        self.assertIn('@router.get("")', src)
        self.assertIn('@router.get("/{date_str}")', src)
        self.assertIn('@router.post("/run")', src)
        self.assertIn('permission_required("page.daily_reports")', src)
        self.assertIn('permission_required("scheduler.trigger")', src)

    def test_router_mounted_in_main(self):
        src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn("daily_reports,", src)
        self.assertIn("daily_reports.router", src)

    def test_page_route_registered(self):
        src = (ROOT / "app" / "routes" / "pages.py").read_text(encoding="utf-8")
        self.assertIn('@router.get("/daily-reports"', src)
        self.assertIn("admin/daily_reports.html", src)

    def test_scheduler_task_registered(self):
        src = (ROOT / "app" / "services" / "scheduler.py").read_text(encoding="utf-8")
        self.assertIn('"daily_ops_report"', src)
        self.assertIn('"35 0 * * *"', src)
        self.assertIn('"daily_ops_report": _task_daily_ops_report', src)

    def test_model_and_migration(self):
        models = (ROOT / "app" / "core" / "db_models.py").read_text(encoding="utf-8")
        self.assertIn("class DailyReport(Base)", models)
        self.assertIn('"daily_reports"', models)
        migrations = (ROOT / "app" / "core" / "db_migrations.py").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS daily_reports", migrations)
        self.assertIn('"page.daily_reports"', migrations)

    def test_database_exports_model(self):
        src = (ROOT / "app" / "core" / "database.py").read_text(encoding="utf-8")
        self.assertIn("DailyReport,", src)

    def test_template_renders_sections(self):
        tpl = (ROOT / "web" / "templates" / "admin" / "daily_reports.html").read_text(encoding="utf-8")
        for needle in (
            "drSecurity",
            "drErrors",
            "drUsage",
            "drAi",
            "/admin/api/daily-reports",
            "drOpenRerun",
            "ai-models/list",
        ):
            self.assertIn(needle, tpl)

    def test_ai_analysis_manual_only(self):
        src = (ROOT / "app" / "services" / "daily_report.py").read_text(encoding="utf-8")
        self.assertIn("async def _ai_analyze", src)
        self.assertIn('if ai_model:\n            sections["ai"]', src)
        self.assertIn('purpose="daily-report-analysis"', src)
        sched = (ROOT / "app" / "services" / "scheduler.py").read_text(encoding="utf-8")
        self.assertIn("await generate_daily_report(yesterday)", sched)

    def test_ai_models_endpoint(self):
        src = (ROOT / "app" / "routes" / "daily_reports.py").read_text(encoding="utf-8")
        self.assertIn('@router.get("/ai-models/list")', src)
        self.assertIn('ai_model = str(body.get("ai_model") or "").strip()', src)
        self.assertIn('generate_daily_report(date_str, ai_model=ai_model or None)', src)

    def test_nav_has_daily_reports_link(self):
        nav = (ROOT / "web" / "templates" / "components" / "nav.html").read_text(encoding="utf-8")
        self.assertIn("/admin/daily-reports", nav)
        self.assertIn("Daily Reports", nav)

    def test_auth_failed_logging_in_proxy(self):
        src = (ROOT / "app" / "services" / "proxy.py").read_text(encoding="utf-8")
        self.assertIn('status="auth_failed"', src)
        self.assertIn("invalid_api_key", src)

    def test_login_failure_audited(self):
        src = (ROOT / "app" / "routes" / "auth.py").read_text(encoding="utf-8")
        self.assertIn("write_audit_log", src)
        self.assertIn("登录失败", src)

    def test_aggregator_reads_nested_billing_cost(self):
        src = (ROOT / "app" / "services" / "stats_aggregator.py").read_text(encoding="utf-8")
        self.assertIn('((log.tokens or {}).get("billing") or {}).get("total_cost_cny")', src)
        self.assertNotIn('(log.tokens or {}).get("total_cost_cny")', src)
        self.assertIn("async def backfill_cost_fix", src)
        self.assertIn("cost_nested_backfill", src)

    def test_aggregator_excludes_null_key_rows(self):
        src = (ROOT / "app" / "services" / "stats_aggregator.py").read_text(encoding="utf-8")
        self.assertIn("RequestLogRead.api_key_id.isnot(None)", src)

    def test_thresholds_in_defaults_and_ui(self):
        cfg = (ROOT / "app" / "services" / "system_config.py").read_text(encoding="utf-8")
        for key in ("error_rate_warn", "auth_fail_warn", "login_fail_warn", "rate_limit_warn", "ip_req_warn", "ip_auth_fail_warn"):
            self.assertIn(key, cfg)
        route = (ROOT / "app" / "routes" / "system_config.py").read_text(encoding="utf-8")
        self.assertIn('"daily_report"', route)
        ui = (ROOT / "web" / "templates" / "admin" / "system_config.html").read_text(encoding="utf-8")
        self.assertIn("daily_report-error_rate_warn", ui)
        self.assertIn("daily_report-ip_auth_fail_warn", ui)
        self.assertIn("saveDailyReport", ui)

    def test_ip_distribution_in_security_section(self):
        src = (ROOT / "app" / "services" / "daily_report.py").read_text(encoding="utf-8")
        self.assertIn('"ip_top": ip_top_data', src)
        self.assertIn("ip_req_warn", src)
        self.assertIn("ip_auth_fail_warn", src)
        self.assertIn("IpLocation", src)

    def test_by_key_report_includes_tags(self):
        src = (ROOT / "app" / "routes" / "report_center.py").read_text(encoding="utf-8")
        self.assertIn("ApiKeyTag", src)
        self.assertIn('string_agg(ApiKeyTag.tag, "/")', src)
        self.assertIn('"tags": [t for t in (row.key_tags or "").split("/") if t]', src)
        csv_route = src
        self.assertIn("_BY_KEY_CSV_KEYS", csv_route)
        tpl = (ROOT / "web" / "templates" / "admin" / "report_center.html").read_text(encoding="utf-8")
        self.assertIn("r.tags", tpl)
        self.assertIn("rc-head-key", tpl)

    def test_request_logs_ip_city(self):
        src = (ROOT / "app" / "routes" / "logs.py").read_text(encoding="utf-8")
        self.assertIn("_ip_city_map", src)
        self.assertIn('"ip_city": ip_city_map.get(log.client_ip or "")', src)
        tpl = (ROOT / "web" / "templates" / "admin" / "request_logs.html").read_text(encoding="utf-8")
        self.assertIn("log.ip_city", tpl)


if __name__ == "__main__":
    unittest.main()
