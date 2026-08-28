import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.dialects import postgresql

from app.core.database import ProviderKey


class _FakeResult:
    def __init__(self, row=None):
        self._row = row

    def scalar_one_or_none(self):
        return self._row

    def scalar(self):
        return 1


class _FakeSession:
    def __init__(self, row=None):
        self.row = row
        self.statements = []
        self.committed = 0

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _FakeResult(self.row)

    async def commit(self):
        self.committed += 1

    async def refresh(self, _obj):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _compiled(stmt):
    return str(stmt.compile(dialect=postgresql.dialect()))


def _make_pk(**overrides):
    fields = dict(
        id=7,
        provider_id=3,
        api_key="sk-provider",
        label="k",
        max_concurrent=2,
        priority=0,
        cost_role="standard",
        is_active=True,
        disabled_by=None,
        disabled_reason=None,
        disabled_at=None,
        reset_at=None,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


class AutoDisableMarksDisabledByTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_disable_sets_disabled_by_auto(self):
        from app.services import provider_limiter

        session = _FakeSession()
        config = {"api_keys": [{"id": 7, "api_key": "sk-provider"}]}
        with patch(
            "app.services.provider_limiter.async_session_maker", return_value=session
        ), patch(
            "app.services.provider_limiter.record_key_event"
        ), patch(
            "app.services.provider_limiter.schedule_reenable_job", new=AsyncMock()
        ), patch(
            "app.services.provider.load_providers", new=AsyncMock()
        ), patch(
            "app.services.provider.invalidate_provider_key_sticky_cache",
            new=AsyncMock(),
        ):
            await provider_limiter.disable_provider_key("prov", config, 7, "quota exceeded")

        values = session.statements[0].compile(
            dialect=postgresql.dialect()
        ).params
        self.assertEqual(values.get("disabled_by"), "auto")
        self.assertFalse(values.get("is_active", True))


class ManualDisableTests(unittest.IsolatedAsyncioTestCase):
    async def _update_with(self, is_active):
        from app.routes.providers import ProviderKeyUpdate, update_provider_key

        pk = _make_pk()
        session = _FakeSession(row=pk)
        with patch(
            "app.routes.providers.async_session_maker", return_value=session
        ), patch(
            "app.routes.providers.load_providers", new=AsyncMock()
        ), patch(
            "app.services.provider_limiter.cancel_reenable_job"
        ) as cancel:
            data = ProviderKeyUpdate(is_active=is_active)
            response = await update_provider_key(3, 7, data)
        return response, pk, cancel

    async def test_manual_disable_marks_disabled_by_manual_and_cancels_job(self):
        response, pk, cancel = await self._update_with(False)
        self.assertEqual(response, {"id": 7})
        self.assertFalse(pk.is_active)
        self.assertEqual(pk.disabled_by, "manual")
        cancel.assert_called_once_with("key", 7)

    async def test_manual_enable_clears_state_and_cancels_job(self):
        pk_start = _make_pk(
            is_active=False,
            disabled_by="auto",
            disabled_reason="quota",
            disabled_at=None,
            reset_at=None,
        )
        from app.routes.providers import ProviderKeyUpdate, update_provider_key

        session = _FakeSession(row=pk_start)
        with patch(
            "app.routes.providers.async_session_maker", return_value=session
        ), patch(
            "app.routes.providers.load_providers", new=AsyncMock()
        ), patch(
            "app.services.provider_limiter.cancel_reenable_job"
        ) as cancel:
            data = ProviderKeyUpdate(is_active=True)
            await update_provider_key(3, 7, data)
        self.assertTrue(pk_start.is_active)
        self.assertIsNone(pk_start.disabled_by)
        self.assertIsNone(pk_start.disabled_reason)
        cancel.assert_called_once_with("key", 7)


class ReenableJobScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_reenable_statement_skips_manually_disabled_keys(self):
        from app.services import provider_limiter

        session = _FakeSession()
        with patch(
            "app.services.provider_limiter.async_session_maker", return_value=session
        ), patch(
            "app.services.provider_limiter.on_key_reenabled"
        ), patch(
            "app.services.provider.load_providers", new=AsyncMock()
        ):
            await provider_limiter._do_reenable_key(7)

        sql = _compiled(session.statements[0])
        self.assertIn("disabled_by", sql)
        self.assertIn("is_active", sql)


class DisabledByColumnTests(unittest.TestCase):
    def test_provider_key_model_has_disabled_by_column(self):
        self.assertIn("disabled_by", ProviderKey.__table__.columns)
        self.assertEqual(
            ProviderKey.__table__.columns["disabled_by"].type.length, 20
        )


if __name__ == "__main__":
    unittest.main()
