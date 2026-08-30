import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.dialects import postgresql

from app.core.database import Provider, ProviderKey


class _FakeResult:
    def __init__(self, rows=None, row=None, rowcount=1):
        self._rows = rows or []
        self._row = row
        self.rowcount = rowcount

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._row

    def scalar_one_or_none(self):
        return self._row

    def scalar(self):
        return 1


class _FakeSession:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []
        self.committed = 0

    async def execute(self, stmt):
        self.statements.append(stmt)
        return self.results.pop(0)

    async def commit(self):
        self.committed += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _compiled(stmt):
    return str(stmt.compile(dialect=postgresql.dialect()))


class SweepManualGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_sweep_excludes_manual_keys_and_providers(self):
        from app.services import provider_limiter

        session = _FakeSession([_FakeResult(), _FakeResult()])
        with patch(
            "app.services.provider_limiter.async_session_maker", return_value=session
        ), patch("app.services.provider.load_providers", new=AsyncMock()):
            await provider_limiter.auto_reenable_disabled_keys_and_providers()

        selects = [s for s in session.statements if "SELECT" in _compiled(s)]
        self.assertEqual(len(selects), 2)
        for stmt in selects:
            sql = _compiled(stmt)
            self.assertIn("disabled_by IS NULL", sql)
            self.assertIn("disabled_by !=", sql)
            params = stmt.compile(dialect=postgresql.dialect()).params
            self.assertIn("manual", list(params.values()))

    async def test_sweep_reenables_auto_disabled_and_clears_disabled_by(self):
        from app.services import provider_limiter

        fake_key = SimpleNamespace(id=11)
        fake_provider = SimpleNamespace(id=5, name="prov-a")
        session = _FakeSession(
            [
                _FakeResult(rows=[fake_key]),
                _FakeResult(rows=[fake_provider]),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        with patch(
            "app.services.provider_limiter.async_session_maker", return_value=session
        ), patch("app.services.provider.load_providers", new=AsyncMock()):
            await provider_limiter.auto_reenable_disabled_keys_and_providers()

        updates = [s for s in session.statements if "UPDATE" in _compiled(s)]
        self.assertEqual(len(updates), 2)
        for stmt in updates:
            values = stmt.compile(dialect=postgresql.dialect()).params
            self.assertIs(values.get("is_active"), True)
            self.assertIn("disabled_by", values)
            self.assertIsNone(values.get("disabled_by"))

    async def test_provider_model_has_disabled_by_column(self):
        self.assertIn("disabled_by", Provider.__table__.columns)
        self.assertIn("disabled_by", ProviderKey.__table__.columns)


class ScheduledProviderReenableGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduled_provider_reenable_skips_manual(self):
        from app.services import provider_limiter

        session = _FakeSession([_FakeResult(rowcount=1), _FakeResult(row="prov-a")])
        with patch(
            "app.services.provider_limiter.async_session_maker", return_value=session
        ), patch("app.services.provider.load_providers", new=AsyncMock()), patch(
            "app.services.notification.create_notification", new=AsyncMock()
        ):
            await provider_limiter._do_reenable_provider(5)

        updates = [s for s in session.statements if "UPDATE" in _compiled(s)]
        self.assertEqual(len(updates), 1)
        sql = _compiled(updates[0])
        self.assertIn("disabled_by IS NULL", sql)
        self.assertIn("disabled_by !=", sql)
        values = updates[0].compile(dialect=postgresql.dialect()).params
        self.assertIsNone(values.get("disabled_by"))


class AutoProviderDisableMarksDisabledByTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_provider_disable_sets_disabled_by_auto(self):
        from app.services import provider_limiter

        session = _FakeSession([_FakeResult(row=5)])
        with patch(
            "app.services.provider_limiter.async_session_maker", return_value=session
        ), patch("app.services.provider.load_providers", new=AsyncMock()), patch(
            "app.services.notification.create_notification", new=AsyncMock()
        ):
            await provider_limiter.disable_provider("prov-a", "quota exceeded")

        update_stmt = next(s for s in session.statements if "UPDATE" in _compiled(s))
        values = update_stmt.compile(dialect=postgresql.dialect()).params
        self.assertEqual(values.get("disabled_by"), "auto")
        self.assertIs(values.get("is_active"), False)


class ManualProviderToggleTests(unittest.IsolatedAsyncioTestCase):
    def _make_provider(self):
        return SimpleNamespace(
            id=3,
            name="prov-a",
            base_url="http://x",
            api_key="sk",
            protocol="openai",
            merge_consecutive_messages=False,
            is_active=True,
            disabled_by=None,
            disabled_reason=None,
            disabled_at=None,
            reset_at=None,
        )

    async def _update_with(self, is_active):
        from app.routes.providers import ProviderUpdate, update_provider

        provider = self._make_provider()
        session = _FakeSession([_FakeResult(row=provider)])
        with patch(
            "app.routes.providers.async_session_maker", return_value=session
        ), patch("app.routes.providers.load_providers", new=AsyncMock()):
            data = ProviderUpdate(is_active=is_active)
            await update_provider(3, data)

        return provider

    async def test_manual_disable_marks_disabled_by_manual(self):
        provider = await self._update_with(False)
        self.assertFalse(provider.is_active)
        self.assertEqual(provider.disabled_by, "manual")
        self.assertIsNotNone(provider.disabled_at)
        self.assertIsNone(provider.reset_at)

    async def test_manual_enable_clears_disabled_by(self):
        provider = self._make_provider()
        provider.is_active = False
        provider.disabled_by = "auto"
        provider.disabled_reason = "quota"
        provider.disabled_at = provider.reset_at = None

        from app.routes.providers import ProviderUpdate, update_provider

        session = _FakeSession([_FakeResult(row=provider)])
        with patch(
            "app.routes.providers.async_session_maker", return_value=session
        ), patch("app.routes.providers.load_providers", new=AsyncMock()):
            await update_provider(3, ProviderUpdate(is_active=True))

        self.assertTrue(provider.is_active)
        self.assertIsNone(provider.disabled_by)
        self.assertIsNone(provider.disabled_reason)
        self.assertIsNone(provider.reset_at)


if __name__ == "__main__":
    unittest.main()
