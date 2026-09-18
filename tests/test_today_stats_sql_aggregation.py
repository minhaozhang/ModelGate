import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.dialects import postgresql

LOGGING_SRC = (Path(__file__).resolve().parent.parent / "app" / "services" / "logging.py").read_text(encoding="utf-8")
STATS_SRC = (Path(__file__).resolve().parent.parent / "app" / "routes" / "stats.py").read_text(encoding="utf-8")


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return self._rows


class _FakeSession:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return self.results.pop(0)

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _compiled(stmt):
    return str(stmt.compile(dialect=postgresql.dialect()))


class LogWriteNoInvalidateTests(unittest.TestCase):
    def test_request_log_writes_do_not_invalidate_today_stats_cache(self):
        occurrences = LOGGING_SRC.count("invalidate_today_stats_cache")
        self.assertEqual(occurrences, 1, "only the def may remain; no call sites")


class TodayStatsSqlAggregationTests(unittest.IsolatedAsyncioTestCase):
    async def test_rebuild_uses_sql_group_by_not_orm_load(self):
        from datetime import datetime

        from app.core import config as config_module
        from app.routes.stats import get_cached_today_stats

        config_module.today_stats_cache = {}
        config_module.today_stats_cache_time = None

        row = SimpleNamespace(
            requests=5, tokens=1234, errors=1, timeouts=0, rate_limited=2
        )
        provider_row = SimpleNamespace(name="xiaomi", **vars(row))
        key_row = SimpleNamespace(kid=7, **vars(row))
        model_row = SimpleNamespace(mname="glm-5.3", **vars(row))

        session = _FakeSession(
            [_FakeResult([provider_row]), _FakeResult([key_row]), _FakeResult([model_row])]
        )
        with patch("app.routes.stats.async_session_maker", return_value=session), patch(
            "app.routes.stats.api_keys_cache",
            {"k1": {"id": 7, "name": "dev-key"}},
        ):
            data = await get_cached_today_stats(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))

        sqls = [_compiled(s) for s in session.statements]
        self.assertEqual(len(sqls), 3)
        for sql in sqls:
            self.assertIn("GROUP BY", sql)
            self.assertNotIn("SELECT request_logs.id, request_logs.provider_id", sql)

        provider_sql = sqls[0]
        self.assertIn("JOIN PROVIDERS ON", provider_sql.upper())

        prov_params = session.statements[0].compile(dialect=postgresql.dialect()).params
        param_values = [str(v) for v in prov_params.values()]
        self.assertTrue(any("total_tokens" in v for v in param_values), prov_params)
        self.assertTrue(any("estimated" in v for v in param_values), prov_params)

        self.assertEqual(data["provider"]["xiaomi"]["requests"], 5)
        self.assertEqual(data["api_key"]["dev-key"]["tokens"], 1234)
        self.assertEqual(data["model"]["glm-5.3"]["rate_limited"], 2)
        self.assertNotIn("logs", data)
        self.assertNotIn("provider_cache", data)

    def test_cache_payload_no_longer_holds_orm_logs(self):
        self.assertNotIn('"logs": logs', STATS_SRC)


if __name__ == "__main__":
    unittest.main()
