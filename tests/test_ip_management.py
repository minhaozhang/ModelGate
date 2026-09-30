"""IP management: daily report active geo lookup for problem IPs, admin IP
directory (unified list + tags), and system-config tab wiring.
"""

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def all(self):
        return list(self._rows)


class _Ctx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, results):
        self._results = list(results)
        self.statements = []
        self.params = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        self.statements.append(stmt)
        self.params.append(params)
        return self._results.pop(0) if self._results else _FakeResult()

    async def commit(self):
        self.commits += 1


class LookupCandidatesTests(unittest.TestCase):
    def test_priority_dedupe_and_cap(self):
        from app.services.daily_report import _lookup_candidates

        ip_cities = {"9.9.9.9": "北京"}
        candidates = _lookup_candidates(
            ip_cities,
            warning_ips=["9.9.9.9", "8.8.8.8"],          # 9.9.9.9 known -> skipped
            auth_fail_top=["7.7.7.7", "8.8.8.8"],         # dup 8.8.8.8 skipped
            login_fail_top=["unknown", "6.6.6.6"],
            traffic_ips=["5.5.5.5", "4.4.4.4"],
            limit=4,
        )
        self.assertEqual(candidates, ["8.8.8.8", "7.7.7.7", "6.6.6.6", "5.5.5.5"])


class CityLabelTests(unittest.TestCase):
    def test_domestic_hides_country(self):
        from app.services.daily_report import _city_label_from_lookup

        label = _city_label_from_lookup(
            {"country": "中国", "province": "广东", "city": "深圳"}
        )
        self.assertEqual(label, "广东 深圳")

    def test_foreign_includes_country(self):
        from app.services.daily_report import _city_label_from_lookup

        label = _city_label_from_lookup(
            {"country": "US", "province": "California", "city": "San Jose"}
        )
        self.assertEqual(label, "US California San Jose")

    def test_city_same_as_province(self):
        from app.services.daily_report import _city_label_from_lookup

        label = _city_label_from_lookup({"province": "上海", "city": "上海"})
        self.assertEqual(label, "上海")


class ResolveMissingCitiesTests(unittest.IsolatedAsyncioTestCase):
    async def test_merges_ok_results_and_skips_failures(self):
        import app.services.ip_location as ip_location_module
        from app.services.daily_report import _resolve_missing_cities

        async def fake_lookup(ip):
            if ip == "bad":
                return {"ok": False, "message": "boom"}
            if ip == "boom":
                raise RuntimeError("network down")
            return {"ok": True, "province": "广东", "city": "深圳", "country": ""}

        ip_cities = {}
        with patch.object(ip_location_module, "lookup_ip_location", fake_lookup):
            await _resolve_missing_cities(["good", "bad", "boom"], ip_cities)

        self.assertEqual(ip_cities, {"good": "广东 深圳"})


class TagColorTests(unittest.TestCase):
    def test_predefined_colors(self):
        from app.services.ip_directory import tag_color

        self.assertEqual(tag_color("办公室"), "blue")
        self.assertEqual(tag_color("攻击者"), "red")
        self.assertEqual(tag_color("家"), "green")

    def test_unknown_tags_stable(self):
        from app.services.ip_directory import tag_color

        first = tag_color("自定义标签")
        for _ in range(3):
            self.assertEqual(tag_color("自定义标签"), first)
        self.assertIn(first, {"blue", "green", "purple", "amber", "cyan", "pink", "slate"})


class MergeAggTests(unittest.TestCase):
    def test_merges_requests_and_audit(self):
        from app.services.ip_directory import _merge_agg

        merged = {}
        t1 = datetime(2026, 9, 29, 10, 0, 0)
        t2 = datetime(2026, 9, 30, 8, 0, 0)
        _merge_agg(merged, [("1.1.1.1", 100, t1)], is_audit=False)
        _merge_agg(merged, [("1.1.1.1", 3, t2), ("2.2.2.2", 1, t1)], is_audit=True)

        self.assertEqual(merged["1.1.1.1"]["requests"], 100)
        self.assertEqual(merged["1.1.1.1"]["admin_ops"], 3)
        self.assertEqual(merged["1.1.1.1"]["last_seen"], t2)
        self.assertEqual(merged["2.2.2.2"]["requests"], 0)


class ListIpsTests(unittest.IsolatedAsyncioTestCase):
    async def test_merges_sorts_and_paginates(self):
        from app.services.ip_directory import list_ips

        t_old = datetime(2026, 9, 20, 9, 0, 0)
        t_new = datetime(2026, 9, 30, 9, 0, 0)
        session = _FakeSession([
            _FakeResult([("1.1.1.1", 100, t_old), ("2.2.2.2", 5, t_new)]),  # request agg
            _FakeResult([("2.2.2.2", 3, t_new), ("9.9.9.9", 1, t_old)]),   # audit agg
            _FakeResult([("2.2.2.2", None, "广东", "深圳", "电信")]),        # locations
            _FakeResult([("2.2.2.2", "办公室")]),                            # tags
        ])
        with patch("app.services.ip_directory.async_session_maker", return_value=_Ctx(session)):
            result = await list_ips(search="", page=1, page_size=2)

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["page"], 1)
        # newest activity first: 2.2.2.2 (09-30) then 1.1.1.1/9.9.9.9 (09-20)
        self.assertEqual(result["items"][0]["ip"], "2.2.2.2")
        self.assertEqual(result["items"][0]["location"], "广东 深圳")
        self.assertEqual(result["items"][0]["isp"], "电信")
        self.assertEqual(result["items"][0]["tags"], ["办公室"])
        self.assertEqual(result["items"][0]["requests"], 5)
        self.assertEqual(result["items"][0]["admin_ops"], 3)
        self.assertEqual(result["items"][1]["ip"], "1.1.1.1")
        self.assertEqual(result["items"][1]["location"], "")

    async def test_search_matches_tag_names(self):
        from app.services.ip_directory import list_ips

        session = _FakeSession([
            _FakeResult([]),                                  # request agg
            _FakeResult([]),                                  # audit agg
            _FakeResult([("3.3.3.3",)]),                      # tag distinct
            _FakeResult([]),                                  # locations
            _FakeResult([("3.3.3.3", "攻击者")]),              # tags
        ])
        with patch("app.services.ip_directory.async_session_maker", return_value=_Ctx(session)):
            result = await list_ips(search="攻击", page=1, page_size=20)

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["ip"], "3.3.3.3")
        self.assertEqual(result["items"][0]["tags"], ["攻击者"])


class IpTagCrudTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_tag_idempotent_upsert(self):
        from app.services.ip_directory import add_ip_tag

        session = _FakeSession([
            _FakeResult(),                    # INSERT .. ON CONFLICT
            _FakeResult([("办公室",)]),        # tag select
        ])
        with patch("app.services.ip_directory.async_session_maker", return_value=_Ctx(session)):
            tags = await add_ip_tag("1.1.1.1", "办公室")

        self.assertEqual(tags, ["办公室"])
        self.assertIn("ON CONFLICT", str(session.statements[0]))
        self.assertEqual(session.commits, 1)

    async def test_add_tag_validation(self):
        from app.services.ip_directory import add_ip_tag

        with self.assertRaises(ValueError):
            await add_ip_tag("1.1.1.1", "   ")
        with self.assertRaises(ValueError):
            await add_ip_tag("1.1.1.1", "x" * 51)

    async def test_remove_tag_deletes(self):
        from app.services.ip_directory import remove_ip_tag

        session = _FakeSession([
            _FakeResult(),            # DELETE
            _FakeResult([]),          # tag select
        ])
        with patch("app.services.ip_directory.async_session_maker", return_value=_Ctx(session)):
            tags = await remove_ip_tag("1.1.1.1", "办公室")

        self.assertEqual(tags, [])
        self.assertIn("DELETE FROM ip_tags", str(session.statements[0]))


class WiringTests(unittest.TestCase):
    def test_ip_routes_registered(self):
        from app.routes.system_config import router

        paths = {getattr(route, "path", None) for route in router.routes}
        self.assertIn("/admin/api/system/ips", paths)
        self.assertIn("/admin/api/system/ips/{ip}/lookup", paths)
        self.assertIn("/admin/api/system/ips/{ip}/tags", paths)
        self.assertIn("/admin/api/system/ips/{ip}/tags/{tag}", paths)

    def test_migration_creates_ip_tags(self):
        from app.core.db_migrations import _DDL

        joined = " ".join(s.lower() if isinstance(s, str) else "" for s in _DDL)
        self.assertIn("create table if not exists ip_tags", joined)
        self.assertIn("uq_ip_tags", joined)

    def test_system_config_html_has_ip_tab(self):
        html = open("web/templates/admin/system_config.html", encoding="utf-8").read()
        for needle in ("sys-tab-ips", "loadIpDir", "ipAddTag", "ipRemoveTag", "ipLookup"):
            self.assertIn(needle, html)

    def test_insights_renders_city_for_fail_top_ips(self):
        html = open("web/templates/admin/insights.html", encoding="utf-8").read()
        self.assertIn("normIp", html)  # backward-compatible [ip, count] -> {ip, count, city}

    def test_daily_report_ip_top_extended_to_10(self):
        source = open("app/services/daily_report.py", encoding="utf-8").read()
        self.assertIn(")[:10]", source)


if __name__ == "__main__":
    unittest.main()
