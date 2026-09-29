"""update_request_log must use PATCH semantics.

Regression tests: a partial update (e.g. proxy.py `_persist_tries` only
passes `fallback_tries`) must not clobber already-written terminal state
(status/error/upstream_status_code/...) with defaults.
"""

import inspect
import unittest
from unittest.mock import patch

from sqlalchemy.dialects import postgresql


def _fake_result(rowcount=1):
    class _Result:
        pass

    r = _Result()
    r.rowcount = rowcount
    return r


class _Ctx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self):
        self.statements = []
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _fake_result()

    async def commit(self):
        return None


def _params(stmt):
    return stmt.compile(dialect=postgresql.dialect()).params


def _sql(stmt):
    return str(stmt.compile(dialect=postgresql.dialect()))


class UpdateRequestLogPatchSemanticsTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, **kwargs):
        from app.services.logging import update_request_log

        session = _FakeSession()
        with patch("app.services.logging.async_session_maker", return_value=_Ctx(session)):
            ok = await update_request_log(123, **kwargs)
        self.assertTrue(ok)
        return session

    async def test_signature_has_patch_defaults(self):
        from app.services.logging import update_request_log

        params = inspect.signature(update_request_log).parameters
        self.assertIsNone(params["response"].default)
        self.assertIsNone(params["status"].default)

    async def test_partial_update_keeps_terminal_state(self):
        """_persist_tries passes fallback_tries only — nothing else may change."""
        session = await self._run(fallback_tries=[{"provider": "qwen"}])

        self.assertEqual(len(session.statements), 1, "no RequestContent DELETE expected")
        sql = _sql(session.statements[0])
        self.assertIn("UPDATE request_logs", sql)
        self.assertIn("updated_at", sql)
        params = _params(session.statements[0])
        self.assertIn("fallback_tries", params)
        for absent in (
            "status",
            "response",
            "tokens",
            "error",
            "upstream_status_code",
            "downstream_status_code",
            "latency_ms",
        ):
            self.assertNotIn(absent, params, f"partial update must not touch {absent}")

    async def test_terminal_error_update_writes_all_explicit_fields(self):
        session = await self._run(
            status="error",
            error="upstream 404",
            upstream_status_code=404,
            downstream_status_code=404,
            latency_ms=123.0,
        )

        self.assertEqual(len(session.statements), 2, "error status must purge request content")
        self.assertIn("UPDATE request_logs", _sql(session.statements[0]))
        self.assertIn("DELETE FROM request_contents", _sql(session.statements[1]))
        params = _params(session.statements[0])
        self.assertEqual(params["status"], "error")
        self.assertEqual(params["error"], "upstream 404")
        self.assertEqual(params["upstream_status_code"], 404)

    async def test_success_update_does_not_purge_request_content(self):
        session = await self._run(
            response="ok",
            tokens={"total": 10},
            latency_ms=5.0,
            status="success",
            upstream_status_code=200,
            downstream_status_code=200,
        )

        self.assertEqual(len(session.statements), 1)
        params = _params(session.statements[0])
        self.assertEqual(params["status"], "success")
        self.assertEqual(params["response"], "ok")
        self.assertEqual(params["tokens"], {"total": 10})

    async def test_request_messages_still_stored(self):
        session = await self._run(status="error", request_messages=[{"role": "user"}])

        self.assertEqual(len(session.added), 1)


if __name__ == "__main__":
    unittest.main()
