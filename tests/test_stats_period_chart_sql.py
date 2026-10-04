from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import unittest

from sqlalchemy.dialects import postgresql


def _row(**kw):
    return SimpleNamespace(**kw)


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows if rows is not None else []

    def fetchall(self):
        return self._rows

    def one(self):
        assert len(self._rows) == 1, "expected exactly one row"
        return self._rows[0]

    def scalar(self):
        row = self._rows[0]
        return row[0] if isinstance(row, tuple) else row


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


class _SqlAggTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from app.core import config as config_module

        self.config_module = config_module
        shared = {"k1": {"id": 7, "name": "dev-key"}}
        config_module.api_keys_cache = shared
        patcher = patch("app.routes.stats.api_keys_cache", shared)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _no_full_orm_load(self, session):
        sqls = [_compiled(s) for s in session.statements]
        for sql in sqls:
            self.assertNotIn(
                "request_logs.id, request_logs.provider_id", sql,
                "full ORM load detected",
            )
        return sqls


class StatsPeriodSqlTests(_SqlAggTestBase):
    async def test_day_period_uses_sql_aggregation(self):
        from app.routes.stats import get_stats_period

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        session = _FakeSession([
            _FakeResult([(1, "pk-A")]),          # provider key labels
            _FakeResult([_row(requests=10, tokens=500, prompt_tokens=100,
                              completion_tokens=400, errors=1, timeouts=0,
                              rate_limited=2, cost=0.75)]),  # totals
            _FakeResult([                         # provider dim rows
                _row(pid=5, pname="provA", pk_id=1, pk_label="old",
                     mname="m1", requests=8, tokens=480),
                _row(pid=5, pname="provA", pk_id=1, pk_label="old",
                     mname=None, requests=2, tokens=20),
            ]),
            _FakeResult([_row(kid=7, umname="m1", requests=6, tokens=300)]),
            _FakeResult([(7, "t1")]),             # api key tags
            _FakeResult([_row(mname="m1", requests=10, tokens=500)]),
            _FakeResult([(1,)]),                  # rl upstream
            _FakeResult([(1,)]),                  # rl local
            _FakeResult([]),                      # disabled providers
            _FakeResult([(3,)]),                  # active 1h
        ])
        with patch("app.routes.stats.async_session_maker", return_value=session):
            data = await get_stats_period(period="day", _=True)

        self.assertEqual(data["total_requests"], 10)
        self.assertEqual(data["total_tokens"], 500)
        self.assertEqual(data["total_errors"], 1)
        self.assertEqual(data["total_rate_limited"], 2)
        self.assertEqual(data["total_cost"], 0.75)

        prov = data["providers"]["provA"]
        self.assertEqual(prov["requests"], 10)
        self.assertEqual(prov["tokens"], 500)
        self.assertEqual(prov["models"]["m1"]["requests"], 8)
        # provider key label must be overridden with the live label map
        self.assertEqual(prov["keys"]["pk-A"]["requests"], 10)
        self.assertEqual(prov["keys"]["pk-A"]["models"]["m1"]["requests"], 8)

        key = data["api_keys"]["dev-key"]
        self.assertEqual(key["requests"], 6)
        self.assertEqual(key["tokens"], 300)
        self.assertEqual(key["models"]["m1"]["requests"], 6)
        self.assertEqual(key["tags"], ["t1"])

        self.assertEqual(data["models"]["m1"]["requests"], 10)
        self.assertEqual(data["models"]["m1"]["tokens"], 500)

        sqls = self._no_full_orm_load(session)
        self.assertEqual(len(sqls), 10)
        for sql in (sqls[1], sqls[2], sqls[3], sqls[5]):
            self.assertIn("FROM request_logs", sql)
        for sql in (sqls[2], sqls[3], sqls[5]):
            self.assertIn("GROUP BY", sql)


class StatsChartSqlTests(_SqlAggTestBase):
    async def test_day_chart_uses_sql_bucketing(self):
        from app.routes.stats import get_chart_data

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        session = _FakeSession([
            _FakeResult([  # hourly buckets (30-min halves)
                _row(hbucket=today.replace(hour=1), half=0,
                     requests=4, tokens=90, errors=1, timeouts=0, rate_limited=1),
                _row(hbucket=today.replace(hour=1), half=1,
                     requests=6, tokens=110, errors=0, timeouts=1, rate_limited=0),
            ]),
            _FakeResult([_row(pid=5, pname="provA", requests=10, tokens=200)]),
            _FakeResult([_row(kid=7, requests=10, tokens=200)]),
        ])
        with patch("app.routes.stats.async_session_maker", return_value=session):
            data = await get_chart_data(period="day", provider=None,
                                        api_key_id=None, _=True)

        self.assertIn("01:00", data["data"])
        self.assertIn("01:30", data["data"])
        self.assertEqual(data["data"]["01:00"]["requests"], 4)
        self.assertEqual(data["data"]["01:00"]["tokens"], 90)
        self.assertEqual(data["data"]["01:00"]["errors"], 1)
        self.assertEqual(data["data"]["01:00"]["rate_limited"], 1)
        self.assertEqual(data["data"]["01:30"]["requests"], 6)
        self.assertEqual(data["data"]["01:30"]["timeouts"], 1)
        self.assertEqual(data["data"]["01:30"]["rate_limited"], 0)

        self.assertEqual(data["providers"]["provA"]["requests"], 10)
        self.assertEqual(data["api_keys"]["dev-key"]["requests"], 10)

        sqls = self._no_full_orm_load(session)
        self.assertEqual(len(sqls), 3)
        self.assertIn("date_trunc", sqls[0])
        for sql in sqls:
            self.assertIn("GROUP BY", sql)


if __name__ == "__main__":
    unittest.main()
