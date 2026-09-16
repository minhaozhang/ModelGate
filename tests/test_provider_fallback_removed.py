import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.dialects import postgresql

from app.core.database import Provider
from app.services.provider import pick_api_key


class _FakeResult:
    def __init__(self, rows=None, row=None):
        self._rows = rows or []
        self._row = row

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._row

    def scalar(self):
        return 1


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


class NoFallbackKeyTests(unittest.TestCase):
    def test_pick_api_key_returns_none_when_all_keys_unavailable(self):
        config = {
            "api_key": "sk-legacy-stale",
            "api_keys": [
                {"id": 1, "api_key": "sk-a", "is_active": False},
            ],
        }
        self.assertEqual(pick_api_key(config, None, "xiaomi"), (None, None))

    def test_pick_api_key_returns_none_when_no_keys_configured(self):
        config = {"api_key": "sk-legacy-stale", "api_keys": []}
        self.assertEqual(pick_api_key(config, None, "xiaomi"), (None, None))

    def test_pick_api_key_returns_none_without_legacy_field(self):
        self.assertEqual(pick_api_key({"api_keys": []}, None, "xiaomi"), (None, None))

    def test_pick_api_key_still_returns_active_key(self):
        config = {
            "api_key": "sk-legacy-stale",
            "api_keys": [
                {"id": 1, "api_key": "sk-a", "is_active": False},
                {"id": 2, "api_key": "sk-b", "is_active": True},
            ],
        }
        self.assertEqual(pick_api_key(config, None, "xiaomi"), ("sk-b", 2))

    def test_provider_model_has_no_legacy_api_key_column(self):
        self.assertNotIn("api_key", Provider.__table__.columns)


class AuthFailureNoAutoReenableTests(unittest.IsolatedAsyncioTestCase):
    async def test_sweep_excludes_auth_failures_without_reset_at(self):
        from app.services import provider_limiter

        session = _FakeSession([_FakeResult(), _FakeResult()])
        with patch(
            "app.services.provider_limiter.async_session_maker", return_value=session
        ), patch("app.services.provider.load_providers", new=AsyncMock()):
            await provider_limiter.auto_reenable_disabled_keys_and_providers()

        selects = [s for s in session.statements if "SELECT" in _compiled(s)]
        self.assertEqual(len(selects), 2)
        for stmt in selects:
            sql = _compiled(stmt).upper()
            self.assertIn("ILIKE", sql)
            self.assertIn("NOT (", sql)
            self.assertIn("RESET_AT IS NULL", sql)
            self.assertIn("RESET_AT <=", sql)
            params = stmt.compile(dialect=postgresql.dialect()).params
            like_params = [v for v in params.values() if isinstance(v, str) and v.startswith("%")]
            self.assertTrue(
                any("invalid api key" in v for v in like_params),
                f"auth keyword params missing: {params}",
            )

    async def test_auth_failure_like_covers_all_keywords(self):
        from app.services.provider_limiter import _auth_failure_like

        clause = _auth_failure_like(Provider.disabled_reason)
        compiled = str(clause.compile(dialect=postgresql.dialect()))
        self.assertIn("disabled_reason", compiled)
        self.assertIn("LIKE", compiled.upper())


if __name__ == "__main__":
    unittest.main()
