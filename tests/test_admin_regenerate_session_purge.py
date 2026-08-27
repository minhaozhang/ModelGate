import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.responses import JSONResponse

from app.routes.user import USER_SESSIONS
from app.routes.keys import regenerate_api_key


class _FakeResult:
    def __init__(self, one=None):
        self._one = one

    def scalar_one_or_none(self):
        return self._one


class _FakeSession:
    def __init__(self, result):
        self._result = result
        self.committed = 0
        self.refreshed = 0

    async def execute(self, _stmt):
        return self._result

    async def commit(self):
        self.committed += 1

    async def refresh(self, _obj):
        self.refreshed += 1


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _seed_sessions(*owners):
    """Seed USER_SESSIONS; owners are api_key_ids (None allowed)."""
    tokens = []
    for idx, owner in enumerate(owners):
        token = f"tok-{idx}"
        USER_SESSIONS[token] = {
            "api_key_id": owner,
            "name": f"user-{owner}",
            "expires": None,
        }
        tokens.append(token)
    return tokens


class AdminRegeneratePurgesPortalSessionsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        USER_SESSIONS.clear()

    def tearDown(self):
        USER_SESSIONS.clear()

    async def test_regenerate_purges_only_target_key_sessions(self):
        tokens = _seed_sessions(7, 7, 9)
        key = SimpleNamespace(id=7)
        request = Mock()

        with (
            patch(
                "app.routes.keys.async_session_maker",
                return_value=_FakeSessionContext(_FakeSession(_FakeResult(one=key))),
            ),
            patch("app.routes.keys.load_api_keys", new=AsyncMock()),
            patch("app.routes.keys.generate_api_key", return_value="sk-new"),
            patch("app.services.audit.write_audit_log", new=AsyncMock()) as audit,
        ):
            response = await regenerate_api_key(request, key_id=7)

        self.assertIsInstance(response, dict)
        self.assertEqual(response["key"], "sk-new")
        # Target-key sessions purged...
        self.assertNotIn(tokens[0], USER_SESSIONS)
        self.assertNotIn(tokens[1], USER_SESSIONS)
        # ...other keys' sessions untouched.
        self.assertIn(tokens[2], USER_SESSIONS)

    async def test_regenerate_writes_audit_log_when_sessions_purged(self):
        _seed_sessions(5)
        key = SimpleNamespace(id=5, key="sk-x")
        request = Mock()

        with (
            patch(
                "app.routes.keys.async_session_maker",
                return_value=_FakeSessionContext(_FakeSession(_FakeResult(one=key))),
            ),
            patch("app.routes.keys.load_api_keys", new=AsyncMock()),
            patch("app.services.audit.write_audit_log", new=AsyncMock()) as audit,
        ):
            await regenerate_api_key(request, key_id=5)

        audit.assert_awaited_once()
        self.assertEqual(audit.await_args.args[1], "delete")
        self.assertEqual(audit.await_args.args[2], "user_session")
        self.assertEqual(audit.await_args.args[3], "5")
        self.assertEqual(audit.await_args.kwargs["user_id"], 5)

    async def test_regenerate_skips_audit_when_no_sessions_purged(self):
        _seed_sessions(99)
        key = SimpleNamespace(id=5, key="sk-y")
        request = Mock()

        with (
            patch(
                "app.routes.keys.async_session_maker",
                return_value=_FakeSessionContext(_FakeSession(_FakeResult(one=key))),
            ),
            patch("app.routes.keys.load_api_keys", new=AsyncMock()),
            patch("app.services.audit.write_audit_log", new=AsyncMock()) as audit,
        ):
            await regenerate_api_key(request, key_id=5)

        audit.assert_not_awaited()
        self.assertIn("tok-0", USER_SESSIONS)

    async def test_regenerate_missing_key_returns_404_without_purge(self):
        tokens = _seed_sessions(7)
        request = Mock()

        with (
            patch(
                "app.routes.keys.async_session_maker",
                return_value=_FakeSessionContext(_FakeSession(_FakeResult(one=None))),
            ),
            patch("app.routes.keys.load_api_keys", new=AsyncMock()),
        ):
            response = await regenerate_api_key(request, key_id=404)

        self.assertIsInstance(response, JSONResponse)
        self.assertEqual(response.status_code, 404)
        self.assertIn(tokens[0], USER_SESSIONS)


if __name__ == "__main__":
    unittest.main()
