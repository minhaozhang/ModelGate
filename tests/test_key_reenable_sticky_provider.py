import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.provider import _key_sticky_map


class _FakeResult:
    def __init__(self, row=None):
        self._row = row
        self.rowcount = 1

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, results):
        self.results = list(results)

    async def execute(self, stmt):
        return self.results.pop(0)

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _provider_row(is_active=True, disabled_by=None, provider_id=5):
    return SimpleNamespace(
        id=provider_id,
        name="prov-a",
        is_active=is_active,
        disabled_by=disabled_by,
    )


def _seed_sticky():
    _key_sticky_map[(1, "prov-a")] = (22, 0.0)
    _key_sticky_map[(2, "prov-a")] = (23, 0.0)
    _key_sticky_map[(3, "other-prov")] = (24, 0.0)


class AfterKeyReenabledTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _key_sticky_map.clear()

    def tearDown(self):
        _key_sticky_map.clear()

    async def test_clears_provider_sticky_for_priority_reselection(self):
        from app.services import provider_limiter

        _seed_sticky()
        session = _FakeSession([_FakeResult(row=_provider_row())])
        with patch(
            "app.services.provider_limiter.async_session_maker",
            return_value=session,
        ), patch(
            "app.services.provider_limiter._do_reenable_provider",
            new=AsyncMock(),
        ):
            await provider_limiter._after_key_reenabled(21)

        self.assertNotIn((1, "prov-a"), _key_sticky_map)
        self.assertNotIn((2, "prov-a"), _key_sticky_map)
        self.assertIn((3, "other-prov"), _key_sticky_map)

    async def test_recovers_auto_disabled_provider_with_available_key(self):
        from app.services import provider_limiter

        reenable_mock = AsyncMock()
        session = _FakeSession(
            [_FakeResult(row=_provider_row(is_active=False, disabled_by="auto"))]
        )
        with patch(
            "app.services.provider_limiter.async_session_maker",
            return_value=session,
        ), patch(
            "app.services.provider_limiter._do_reenable_provider",
            new=reenable_mock,
        ):
            await provider_limiter._after_key_reenabled(21)

        reenable_mock.assert_awaited_once_with(5)

    async def test_skips_manual_disabled_provider(self):
        from app.services import provider_limiter

        reenable_mock = AsyncMock()
        session = _FakeSession(
            [_FakeResult(row=_provider_row(is_active=False, disabled_by="manual"))]
        )
        with patch(
            "app.services.provider_limiter.async_session_maker",
            return_value=session,
        ), patch(
            "app.services.provider_limiter._do_reenable_provider",
            new=reenable_mock,
        ):
            await provider_limiter._after_key_reenabled(21)

        reenable_mock.assert_not_awaited()

    async def test_skips_active_provider(self):
        from app.services import provider_limiter

        reenable_mock = AsyncMock()
        session = _FakeSession([_FakeResult(row=_provider_row(is_active=True))])
        with patch(
            "app.services.provider_limiter.async_session_maker",
            return_value=session,
        ), patch(
            "app.services.provider_limiter._do_reenable_provider",
            new=reenable_mock,
        ):
            await provider_limiter._after_key_reenabled(21)

        reenable_mock.assert_not_awaited()

    async def test_unknown_key_is_noop(self):
        from app.services import provider_limiter

        _seed_sticky()
        reenable_mock = AsyncMock()
        session = _FakeSession([_FakeResult(row=None)])
        with patch(
            "app.services.provider_limiter.async_session_maker",
            return_value=session,
        ), patch(
            "app.services.provider_limiter._do_reenable_provider",
            new=reenable_mock,
        ):
            await provider_limiter._after_key_reenabled(999)

        reenable_mock.assert_not_awaited()
        self.assertIn((1, "prov-a"), _key_sticky_map)

    def test_both_call_sites_invoke_after_key_reenabled(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "provider_limiter.py"
        ).read_text(encoding="utf-8")

        self.assertEqual(src.count("await _after_key_reenabled("), 2)


if __name__ == "__main__":
    unittest.main()
