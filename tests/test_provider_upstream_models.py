import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.routes.provider_models import list_upstream_models


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _SeqSession:
    def __init__(self, rows):
        self._rows = list(rows)

    async def execute(self, _stmt):
        row = self._rows.pop(0) if self._rows else None
        return _FakeResult(row)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _provider(base_url="https://upstream.test/v1"):
    return SimpleNamespace(id=3, base_url=base_url, api_key="")


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeAsyncClient:
    last_call = {}
    pending_response = None

    def __init__(self, **kwargs):
        _FakeAsyncClient.last_call = {"kwargs": kwargs}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, headers=None, **kw):
        _FakeAsyncClient.last_call["url"] = url
        _FakeAsyncClient.last_call["headers"] = headers or {}
        return _FakeAsyncClient.pending_response

    @classmethod
    def patch(cls, response):
        cls.pending_response = response
        cls.last_call = {}
        return patch("app.routes.provider_models.httpx.AsyncClient", cls)


def _session(rows):
    return patch(
        "app.routes.provider_models.async_session_maker",
        return_value=_SeqSession(rows),
    )


class UpstreamModelsTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_model_names_from_data_list(self):
        with _session([_provider(), None]), _FakeAsyncClient.patch(
            _FakeResponse(200, {"data": [{"id": "glm-5"}, {"id": "glm-5-air"}, "glm-4.5"]})
        ):
            data = await list_upstream_models(3, _=True)
        self.assertEqual(data, {"models": ["glm-5", "glm-5-air", "glm-4.5"], "total": 3})
        self.assertEqual(_FakeAsyncClient.last_call["url"], "https://upstream.test/v1/models")

    async def test_supports_models_key_and_dict_payload(self):
        with _session([_provider(), None]), _FakeAsyncClient.patch(
            _FakeResponse(200, {"models": {"a": {"name": "m-a"}, "b": {"name": "m-b"}}})
        ):
            data = await list_upstream_models(3, _=True)
        self.assertEqual(data["models"], ["m-a", "m-b"])

    async def test_skips_entries_without_name(self):
        with _session([_provider(), None]), _FakeAsyncClient.patch(
            _FakeResponse(200, {"data": [{"id": ""}, {"other": 1}, {"id": "glm-5"}]})
        ):
            data = await list_upstream_models(3, _=True)
        self.assertEqual(data["models"], ["glm-5"])

    async def test_upstream_error_status_maps_to_502(self):
        with _session([_provider(), None]), _FakeAsyncClient.patch(
            _FakeResponse(401, {"error": "bad key"})
        ):
            resp = await list_upstream_models(3, _=True)
        self.assertEqual(resp.status_code, 502)

    async def test_unknown_provider_maps_to_404(self):
        with _session([None]):
            resp = await list_upstream_models(999, _=True)
        self.assertEqual(resp.status_code, 404)

    async def test_uses_active_provider_key_for_auth(self):
        key = SimpleNamespace(api_key="sk-upstream")
        with _session([_provider(), key]), _FakeAsyncClient.patch(_FakeResponse(200, {"data": []})):
            await list_upstream_models(3, _=True)
        self.assertEqual(
            _FakeAsyncClient.last_call["headers"].get("Authorization"), "Bearer sk-upstream"
        )

    async def test_no_active_key_sends_no_authorization(self):
        prov = SimpleNamespace(id=3, base_url="https://upstream.test/v1", api_key="sk-provider")
        with _session([prov, None]), _FakeAsyncClient.patch(_FakeResponse(200, {"data": []})):
            await list_upstream_models(3, _=True)
        self.assertNotIn(
            "Authorization",
            _FakeAsyncClient.last_call["headers"],
        )


class SyncModelsFilterTests(unittest.IsolatedAsyncioTestCase):
    def _upstream(self):
        class _Client:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url, headers=None, **kw):
                return _FakeResponse(200, {"data": [{"id": "glm-5"}, {"id": "glm-5-air"}, {"id": "glm-4.5"}]})

        return _Client

    async def _run_sync(self, body):
        from app.routes.provider_models import sync_provider_models

        client_cls = self._upstream()
        created = []

        class _SyncSession:
            def __init__(self):
                self.first = True

            async def execute(self, _stmt):
                row, self.first = (_provider(), False) if self.first else (None, False)
                return _FakeResult(row)

            def add(self, obj):
                created.append(obj)

            async def flush(self):
                return None

            async def commit(self):
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with patch(
            "app.routes.provider_models.async_session_maker",
            return_value=_SyncSession(),
        ), patch(
            "app.routes.provider_models.httpx.AsyncClient", client_cls
        ), patch(
            "app.routes.provider_models.load_providers", new_callable=AsyncMock
        ):
            return await sync_provider_models(3, body, _=True), created

    async def test_only_selected_models_are_bound(self):
        from app.routes.provider_models import SyncModelsRequest

        data, created = await self._run_sync(SyncModelsRequest(models=["glm-5"]))
        self.assertEqual(data["synced"], ["glm-5"])
        self.assertEqual(data["total"], 1)
        model_names = [c.name for c in created if hasattr(c, "name")]
        self.assertEqual(model_names, ["glm-5"])

    async def test_no_body_binds_everything(self):
        data, created = await self._run_sync(None)
        self.assertEqual(data["total"], 3)

    async def test_filter_with_no_match_binds_nothing(self):
        from app.routes.provider_models import SyncModelsRequest

        data, created = await self._run_sync(SyncModelsRequest(models=["nonexistent"]))
        self.assertEqual(data["synced"], [])
        self.assertEqual(data["total"], 0)
        self.assertEqual(created, [])


if __name__ == "__main__":
    unittest.main()
