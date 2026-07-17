import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.responses import JSONResponse

from app.routes.models import (
    AutoModelConfigUpdate,
    get_auto_model_config,
    get_model_api_keys,
    list_all_models,
    update_auto_model_config,
    update_model_api_keys,
)
from app.core.database import ApiKeyModelAccess


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

    async def test_get_model_api_keys_returns_all_keys_and_bound_set(self):
        from datetime import datetime, timedelta

        key_a = SimpleNamespace(id=1, name="Key A", email="a@x.com",
                                is_active=True, expires_at=None)
        key_b = SimpleNamespace(id=2, name="Key B", email="b@x.com",
                                is_active=False, expires_at=datetime.now() - timedelta(days=1))
        key_c = SimpleNamespace(id=3, name="Key C", email=None,
                                is_active=True, expires_at=None)
        session = _FakeSession(
            [
                _FakeResult(one=SimpleNamespace(id=42)),  # model lookup
                _FakeResult(values=[key_a, key_b, key_c]),  # all api keys
                _FakeResult(rows=[(1, "vip"), (3, "premium"), (99, "orphan")]),  # ApiKeyTag rows (api_key_id, tag)
                _FakeResult(rows=[(2,)]),  # bound api_key_ids for this model
            ]
        )

        with patch(
            "app.routes.models.async_session_maker",
            return_value=_FakeSessionContext(session),
        ):
            data = await get_model_api_keys(42, _=True)

        self.assertEqual(data["model_id"], 42)
        ids = [k["id"] for k in data["api_keys"]]
        self.assertEqual(ids, [1, 2, 3])
        b_key = next(k for k in data["api_keys"] if k["id"] == 2)
        self.assertFalse(b_key["is_active"])
        self.assertTrue(b_key["is_expired"])
        a_key = next(k for k in data["api_keys"] if k["id"] == 1)
        self.assertEqual(a_key["tags"], ["vip"])
        self.assertEqual(data["bound_key_ids"], [2])

    async def test_get_model_api_keys_returns_404_when_model_missing(self):
        session = _FakeSession([_FakeResult(one=None)])

        with patch(
            "app.routes.models.async_session_maker",
            return_value=_FakeSessionContext(session),
        ):
            data = await get_model_api_keys(999, _=True)

        self.assertIsInstance(data, JSONResponse)
        self.assertEqual(data.status_code, 404)

    async def test_put_model_api_keys_set_semantics_diff_and_add(self):
        existing_model = SimpleNamespace(id=42)
        session = _FakeSession(
            [
                _FakeResult(one=existing_model),  # model exists
                _FakeResult(),                    # delete (not_in [1,3])
                _FakeResult(rows=[(3,)]),         # existing api_key_ids after delete
            ]
        )

        with (
            patch(
                "app.routes.models.async_session_maker",
                return_value=_FakeSessionContext(session),
            ),
            patch("app.routes.models.load_api_keys") as load_keys,
        ):
            from app.routes.models import ModelApiKeysUpdate
            data = await update_model_api_keys(42, ModelApiKeysUpdate(api_key_ids=[1, 3]), _=True)

        self.assertEqual(data, {"model_id": 42, "api_key_ids": [1, 3]})
        added_ids = [obj.api_key_id for obj in session.added if isinstance(obj, ApiKeyModelAccess)]
        self.assertEqual(sorted(added_ids), [1])
        load_keys.assert_awaited_once()

    async def test_put_model_api_keys_empty_list_clears_all(self):
        existing_model = SimpleNamespace(id=42)
        session = _FakeSession(
            [
                _FakeResult(one=existing_model),  # model exists
                _FakeResult(),                    # delete all where model_id==42
            ]
        )

        with (
            patch(
                "app.routes.models.async_session_maker",
                return_value=_FakeSessionContext(session),
            ),
            patch("app.routes.models.load_api_keys"),
        ):
            from app.routes.models import ModelApiKeysUpdate
            data = await update_model_api_keys(42, ModelApiKeysUpdate(api_key_ids=[]), _=True)

        self.assertEqual(data, {"model_id": 42, "api_key_ids": []})
        self.assertEqual(session.added, [])

    async def test_put_model_api_keys_returns_404_when_model_missing(self):
        session = _FakeSession([_FakeResult(one=None)])

        with patch(
            "app.routes.models.async_session_maker",
            return_value=_FakeSessionContext(session),
        ):
            from app.routes.models import ModelApiKeysUpdate
            data = await update_model_api_keys(999, ModelApiKeysUpdate(api_key_ids=[1]), _=True)

        self.assertIsInstance(data, JSONResponse)
        self.assertEqual(data.status_code, 404)

    async def test_put_model_api_keys_rejects_non_positive_id_with_400(self):
        with patch("app.routes.models.async_session_maker") as session_ctx:
            from app.routes.models import ModelApiKeysUpdate
            data = await update_model_api_keys(
                42, ModelApiKeysUpdate(api_key_ids=[0, 1]), _=True
            )

        self.assertIsInstance(data, JSONResponse)
        self.assertEqual(data.status_code, 400)
        session_ctx.assert_not_called()

    async def test_put_model_api_keys_returns_400_on_integrity_error(self):
        from sqlalchemy.exc import IntegrityError

        class _FakeSessionIntegrity(_FakeSession):
            def __init__(self, results):
                super().__init__(results)
                self.rolled_back = False

            async def commit(self):
                raise IntegrityError("INSERT", {}, Exception("FK violation"))

            async def rollback(self):
                self.rolled_back = True

        existing_model = SimpleNamespace(id=42)
        session = _FakeSessionIntegrity(
            [
                _FakeResult(one=existing_model),  # model exists
                _FakeResult(),                    # delete (not_in [1])
                _FakeResult(rows=[]),             # existing api_key_ids after delete
            ]
        )

        with (
            patch(
                "app.routes.models.async_session_maker",
                return_value=_FakeSessionContext(session),
            ),
            patch("app.routes.models.load_api_keys") as load_keys,
        ):
            from app.routes.models import ModelApiKeysUpdate
            data = await update_model_api_keys(
                42, ModelApiKeysUpdate(api_key_ids=[1]), _=True
            )

        self.assertIsInstance(data, JSONResponse)
        self.assertEqual(data.status_code, 400)
        self.assertTrue(session.rolled_back)
        load_keys.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
