import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.routes.models import list_all_models, update_auto_model_config, AutoModelConfigUpdate


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
        session = _FakeSession([_FakeResult(one=None)])

        with (
            patch(
                "app.routes.models.async_session_maker",
                return_value=_FakeSessionContext(session),
            ),
            patch("app.services.system_config.save_setting") as save_setting,
            patch("app.services.provider.load_providers") as load_providers,
        ):
            await update_auto_model_config(
                AutoModelConfigUpdate(enabled=True, model_ids=[101]),
                _=True,
            )

        self.assertEqual(len(session.added), 1)
        auto_model = session.added[0]
        self.assertEqual(auto_model.name, "auto")
        self.assertTrue(auto_model.is_virtual)
        self.assertTrue(auto_model.is_active)
        self.assertEqual(auto_model.display_name, "Auto")
        self.assertEqual(session.committed, 1)
        save_setting.assert_awaited_once()
        load_providers.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
