import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.responses import JSONResponse

from app.routes.keys import _normalize_max_concurrent


class _FakeResult:
    def __init__(self, one=None):
        self._one = one

    def scalar_one_or_none(self):
        return self._one


class _FakeSession:
    def __init__(self):
        self.added = []
        self.committed = 0
        self._result = _FakeResult(one=None)

    async def execute(self, _stmt):
        return self._result

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed += 1

    async def refresh(self, _obj):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_ctx():
    session = _FakeSession()
    with patch("app.routes.keys.async_session_maker", return_value=session), patch(
        "app.routes.keys.load_api_keys", new=AsyncMock()
    ), patch(
        "app.routes.keys.ApiKeyModelAccess", SimpleNamespace
    ), patch(
        "app.routes.keys.ApiKeyMcpServer", SimpleNamespace
    ), patch(
        "app.routes.keys.ApiKeyTag", SimpleNamespace
    ):
        yield session


class NormalizeMaxConcurrentTests(unittest.TestCase):
    def test_none_and_minus_one_map_to_null(self):
        self.assertIsNone(_normalize_max_concurrent(None))
        self.assertIsNone(_normalize_max_concurrent(-1))

    def test_zero_passthrough(self):
        self.assertEqual(_normalize_max_concurrent(0), 0)

    def test_positive_passthrough(self):
        self.assertEqual(_normalize_max_concurrent(4), 4)

    def test_below_minus_one_rejected(self):
        result = _normalize_max_concurrent(-2)
        self.assertIsInstance(result, JSONResponse)
        self.assertEqual(result.status_code, 400)


class CreateApiKeyQuotaSentinelTests(unittest.IsolatedAsyncioTestCase):
    """The shared admin form sends -1 for an empty daily quota on BOTH create
    and update. Create used to store the sentinel raw, silently pinning those
    keys to 'explicitly unlimited' and bypassing the global default quota."""

    async def _create_with(self, quota, max_concurrent=None):
        from app.routes.keys import ApiKeyCreate, create_api_key

        captured = {}

        class _Key:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.id = 1
                self.name = kwargs.get("name")
                self.key = "sk-x"

        with patch("app.routes.keys.ApiKey", _Key):
            session_ctx = _make_ctx()
            session = next(session_ctx)
            data = ApiKeyCreate(
                name="k",
                access_mode="model",
                allowed_model_ids=[1],
                daily_quota_cny=quota,
                max_concurrent=max_concurrent,
            )
            response = await create_api_key(data, _=True)
        return captured, response

    async def test_empty_quota_sentinel_stored_as_null(self):
        captured, response = await self._create_with(-1)
        self.assertIsNone(captured["daily_quota_cny"])

    async def test_explicit_zero_quota_stored(self):
        captured, _ = await self._create_with(0)
        self.assertEqual(captured["daily_quota_cny"], 0)

    async def test_explicit_quota_stored(self):
        captured, _ = await self._create_with(12.5)
        self.assertEqual(captured["daily_quota_cny"], 12.5)

    async def test_max_concurrent_sentinel_stored_as_null(self):
        captured, _ = await self._create_with(None, max_concurrent=-1)
        self.assertIsNone(captured["max_concurrent"])

    async def test_max_concurrent_explicit_zero_stored(self):
        captured, _ = await self._create_with(None, max_concurrent=0)
        self.assertEqual(captured["max_concurrent"], 0)


class ValidateAccessPayloadTests(unittest.TestCase):
    """Empty allowed_model_ids is a legitimate state: a key with no model
    bindings can authenticate but has no usable models (check_model_access
    denies everything). It must not be rejected with 400."""

    def test_explicit_empty_list_allowed(self):
        from app.routes.keys import _validate_access_payload

        self.assertIsNone(_validate_access_payload("model", []))

    def test_update_without_access_fields_allowed(self):
        from app.routes.keys import _validate_access_payload

        self.assertIsNone(_validate_access_payload(None, None))

    def test_empty_ids_without_mode_defaults_to_model(self):
        from app.routes.keys import _validate_access_payload

        self.assertIsNone(_validate_access_payload(None, []))

    def test_invalid_mode_rejected(self):
        from app.routes.keys import _validate_access_payload

        result = _validate_access_payload("all", [1])
        self.assertEqual(result.status_code, 400)


class CreateApiKeyWithoutModelsTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_with_empty_model_list_succeeds(self):
        from app.routes.keys import ApiKeyCreate, create_api_key

        captured = {}

        class _Key:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.id = 1
                self.name = kwargs.get("name")
                self.key = "sk-x"

        with patch("app.routes.keys.ApiKey", _Key):
            session_ctx = _make_ctx()
            session = next(session_ctx)
            data = ApiKeyCreate(
                name="k",
                access_mode="model",
                allowed_model_ids=[],
            )
            response = await create_api_key(data, _=True)
        self.assertIsInstance(response, dict)
        self.assertEqual(response["id"], 1)
        access_rows = [
            obj for obj in session.added if getattr(obj, "model_id", None) is not None
        ]
        self.assertEqual(access_rows, [])


if __name__ == "__main__":
    unittest.main()
