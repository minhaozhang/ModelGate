import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.routes.models import (
    AutoModelConfigUpdate,
    get_auto_model_config,
    list_all_models,
    update_auto_model_config,
)


class _FakeResult:
    def __init__(self, values=None, rows=None, one=None):
        self._values = values or []
        self._rows = rows or []
        self._one = one

    def scalars(self):
        return self

    def all(self):
        return self._values

    def fetchall(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._one

    def first(self):
        if self._rows:
            return self._rows[0]
        return None


class _FakeSession:
    def __init__(self, results):
        self._results = list(results)
        self.added = []
        self.committed = 0

    async def execute(self, _stmt):
        if not self._results:
            raise AssertionError("Unexpected query")
        return self._results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed += 1

    async def flush(self):
        return None


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class AdminModelListTests(unittest.IsolatedAsyncioTestCase):
    async def test_bound_key_count_includes_model_level_api_key_access(self):
        model = SimpleNamespace(
            id=101,
            name="glm-5",
            display_name="GLM-5",
            max_tokens=8192,
            context_length=131072,
            thinking_enabled=True,
            thinking_budget=8192,
            is_multimodal=False,
            is_active=True,
            is_virtual=False,
            tags="",
        )
        session = _FakeSession(
            [
                _FakeResult(values=[model]),
                _FakeResult(rows=[]),
                _FakeResult(rows=[(101, 9)]),
            ]
        )

        with patch(
            "app.routes.models.async_session_maker",
            return_value=_FakeSessionContext(session),
        ):
            data = await list_all_models(_=True)

        self.assertEqual(data["models"][0]["bound_key_count"], 1)
        self.assertFalse(data["models"][0]["is_virtual"])

    async def test_saving_auto_model_config_creates_virtual_auto_model(self):
        session = _FakeSession([_FakeResult(one=None), _FakeResult(one=None)])

        with (
            patch(
                "app.routes.models.async_session_maker",
                return_value=_FakeSessionContext(session),
            ),
            patch("app.services.provider.load_providers") as load_providers,
            patch("app.routes.models.load_api_keys") as load_api_keys,
        ):
            await update_auto_model_config(
                AutoModelConfigUpdate(enabled=True, model_ids=[101]),
                _=True,
            )

        self.assertEqual(len(session.added), 2)
        auto_model = session.added[0]
        auto_route = session.added[1]
        self.assertEqual(auto_model.name, "auto")
        self.assertTrue(auto_model.is_virtual)
        self.assertTrue(auto_model.is_active)
        self.assertEqual(auto_model.display_name, "auto")
        self.assertTrue(auto_route.enabled)
        self.assertEqual(auto_route.model_ids, [101])
        self.assertEqual(session.committed, 1)
        load_providers.assert_awaited_once()
        load_api_keys.assert_awaited_once()

    async def test_saving_auto_model_config_with_provider_model_candidates_activates_auto_model(self):
        existing_auto = SimpleNamespace(
            id=16,
            name="auto",
            display_name="Auto",
            is_active=False,
            is_virtual=False,
            tags=None,
        )
        session = _FakeSession(
            [
                _FakeResult(one=existing_auto),
                _FakeResult(one=None),
                _FakeResult(rows=[(202,)]),
            ]
        )

        with (
            patch(
                "app.routes.models.async_session_maker",
                return_value=_FakeSessionContext(session),
            ),
            patch("app.services.provider.load_providers"),
            patch("app.routes.models.load_api_keys"),
        ):
            await update_auto_model_config(
                AutoModelConfigUpdate(enabled=True, provider_model_ids=[22]),
                _=True,
            )

        self.assertTrue(existing_auto.is_active)
        self.assertTrue(existing_auto.is_virtual)
        self.assertEqual(existing_auto.display_name, "auto")
        auto_route = session.added[0]
        self.assertEqual(auto_route.virtual_model_id, 16)
        self.assertEqual(auto_route.provider_model_ids, [22])

    async def test_auto_model_config_maps_provider_model_candidates_to_standard_models(self):
        model = SimpleNamespace(id=16, name="auto")
        route = SimpleNamespace(
            enabled=True,
            model_ids=[],
            provider_model_ids=[22, 33],
            route_policy={},
        )
        session = _FakeSession(
            [
                _FakeResult(rows=[(model, route)]),
                _FakeResult(rows=[(101,), (202,)]),
            ]
        )

        with patch(
            "app.routes.models.async_session_maker",
            return_value=_FakeSessionContext(session),
        ):
            data = await get_auto_model_config(_=True)

        self.assertTrue(data["enabled"])
        self.assertEqual(data["provider_model_ids"], [22, 33])
        self.assertEqual(data["model_ids"], [101, 202])


if __name__ == "__main__":
    unittest.main()
