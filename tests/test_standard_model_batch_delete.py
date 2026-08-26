import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import IntegrityError

from app.routes.models import (
    ModelBatchDeleteRequest,
    batch_delete_models,
    delete_model,
)


def _model(mid, name="glm-5"):
    return SimpleNamespace(id=mid, name=name)


class _FakeResult:
    def __init__(self, values=None, rows=None, one=None, scalar=None):
        self._values = values or []
        self._rows = rows or []
        self._one = one
        self._scalar = scalar

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

    def scalar(self):
        return self._scalar


class _FakeSession:
    """Dispatches by query order; records deletes/commit/rollback."""

    def __init__(self, results_per_model):
        # results_per_model: list of result-groups; each group is consumed for one model
        self._groups = [list(g) for g in results_per_model]
        self.deleted_objects = []
        self.executed_statements = []
        self.commit_count = 0
        self.rollback_count = 0

    async def execute(self, stmt):
        self.executed_statements.append(stmt)
        if not self._groups:
            raise AssertionError("Unexpected query: no result group left")
        group = self._groups[0]
        if not group:
            raise AssertionError("Unexpected query within current group")
        result = group.pop(0)
        if not group:
            self._groups.pop(0)  # group consumed by this logical item
        return result

    async def delete(self, obj):
        self.deleted_objects.append(obj)

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        self.rollback_count += 1

    def _advance_group(self):
        if self._groups:
            self._groups.pop(0)

    @property
    def delete_stmt_count(self):
        return len(self.executed_statements)


class _Ctx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _group_no_bindings(model=None):
    model = model or _model(1)
    return [
        _FakeResult(one=model),      # select Model
        _FakeResult(rows=[]),        # pm key names
        _FakeResult(rows=[]),        # access key names
        _FakeResult(rows=[]),        # bound providers
    ]


def _group_provider_bound(model, providers=("zhipu",), total=None):
    total = total or len(providers)
    return [
        _FakeResult(one=model),
        _FakeResult(rows=[]),
        _FakeResult(rows=[]),
        _FakeResult(rows=[(p,) for p in providers]),  # bound provider names
        _FakeResult(scalar=total),                     # count(*)
        _FakeResult(),                                 # cascade: DELETE provider_models
    ]


class BatchDeleteModelsTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_delete_success_multiple_models(self):
        session = _FakeSession([_group_no_bindings(_model(1)), _group_no_bindings(_model(2))])
        with patch(
            "app.routes.models.async_session_maker", return_value=_Ctx(session)
        ):
            data = await batch_delete_models(
                ModelBatchDeleteRequest(ids=[1, 2]), _=True
            )
        self.assertEqual(data["deleted"], [1, 2])
        self.assertEqual(data["deleted_count"], 2)
        self.assertEqual(data["failed"], [])
        self.assertEqual(session.commit_count, 2)

    async def test_batch_delete_ids_deduped_and_invalid_dropped(self):
        session = _FakeSession([_group_no_bindings(_model(7))])
        with patch(
            "app.routes.models.async_session_maker", return_value=_Ctx(session)
        ):
            data = await batch_delete_models(
                ModelBatchDeleteRequest(ids=[7, 7, 0, -3]), _=True
            )
        self.assertEqual(data["deleted"], [7])
        self.assertEqual(len(data["failed"]), 0)

    async def test_batch_delete_empty_ids_rejected(self):
        resp = await batch_delete_models(ModelBatchDeleteRequest(ids=[]), _=True)
        self.assertEqual(resp.status_code, 400)

    async def test_batch_delete_key_bound_model_fails_like_single(self):
        model = _model(3)
        group = [
            _FakeResult(one=model),
            _FakeResult(rows=[("proj-a",)]),   # pm key names via ApiKeyModel
            _FakeResult(rows=[]),
            _FakeResult(rows=[]),
        ]
        session = _FakeSession([group])
        with patch(
            "app.routes.models.async_session_maker", return_value=_Ctx(session)
        ):
            data = await batch_delete_models(
                ModelBatchDeleteRequest(ids=[3]), _=True
            )
        self.assertEqual(data["deleted"], [])
        self.assertEqual(len(data["failed"]), 1)
        failed = data["failed"][0]
        self.assertEqual(failed["code"], "model_bound_to_keys")
        self.assertIn("proj-a", failed["error"])
        self.assertIn(model.name, failed["error"])
        self.assertEqual(session.commit_count, 0)

    async def test_batch_delete_provider_bound_requires_cascade_like_single(self):
        session = _FakeSession([_group_provider_bound(_model(4))])
        with patch(
            "app.routes.models.async_session_maker", return_value=_Ctx(session)
        ):
            data = await batch_delete_models(
                ModelBatchDeleteRequest(ids=[4], cascade_unbind=False), _=True
            )
        self.assertEqual(data["failed"][0]["code"], "model_bound_to_providers")
        self.assertEqual(data["failed"][0]["bound_providers"], ["zhipu"])
        self.assertEqual(data["failed"][0]["total"], 1)
        self.assertEqual(data["deleted"], [])

    async def test_batch_delete_with_cascade_unbinds_providers_and_deletes(self):
        session = _FakeSession([_group_provider_bound(_model(5), ["zhipu", "openai"], total=3)])
        load_providers = AsyncMock()
        with (
            patch("app.routes.models.async_session_maker", return_value=_Ctx(session)),
            patch("app.services.provider.load_providers", load_providers),
        ):
            data = await batch_delete_models(
                ModelBatchDeleteRequest(ids=[5], cascade_unbind=True), _=True
            )
        self.assertEqual(data["deleted"], [5])
        self.assertEqual(data["failed"], [])
        self.assertEqual(len(session.deleted_objects), 1)  # the Model itself
        load_providers.assert_awaited_once()

    async def test_batch_delete_missing_model_reported_as_not_found(self):
        missing = [
            _FakeResult(one=None),
        ]
        session = _FakeSession([missing, _group_no_bindings(_model(9))])
        with patch(
            "app.routes.models.async_session_maker", return_value=_Ctx(session)
        ):
            data = await batch_delete_models(
                ModelBatchDeleteRequest(ids=[8, 9]), _=True
            )
        self.assertEqual(data["deleted"], [9])
        self.assertEqual(len(data["failed"]), 1)
        self.assertEqual(data["failed"][0]["id"], 8)
        self.assertEqual(data["failed"][0]["code"], "not_found")

    async def test_batch_delete_continues_after_integrity_conflict(self):
        ok_group = _group_no_bindings(_model(10))

        conflict_group = _group_no_bindings(_model(11))

        class _BoomSession(_FakeSession):
            async def delete(self, obj):
                if getattr(obj, "id", None) == 11:
                    raise IntegrityError("stmt", {}, Exception("fk"))
                await super().delete(obj)

        session = _BoomSession([conflict_group, ok_group])
        with patch(
            "app.routes.models.async_session_maker", return_value=_Ctx(session)
        ):
            data = await batch_delete_models(
                ModelBatchDeleteRequest(ids=[11, 10]), _=True
            )
        self.assertEqual(data["deleted"], [10])
        failed = {f["id"]: f["code"] for f in data["failed"]}
        self.assertEqual(failed.get(11), "integrity_conflict")
        self.assertEqual(session.rollback_count, 1)

    async def test_batch_delete_mixed_outcomes_reload_flag_only_when_unbound(self):
        # model A unbinds providers (needs reload); model B plain delete (no reload flag needed but reload still once)
        groups = [
            _group_provider_bound(_model(21)),
            _group_no_bindings(_model(22)),
        ]
        session = _FakeSession(groups)
        load_providers = AsyncMock()
        with (
            patch("app.routes.models.async_session_maker", return_value=_Ctx(session)),
            patch("app.services.provider.load_providers", load_providers),
        ):
            data = await batch_delete_models(
                ModelBatchDeleteRequest(ids=[21, 22], cascade_unbind=True), _=True
            )
        self.assertEqual(sorted(data["deleted"]), [21, 22])
        load_providers.assert_awaited_once()


class SingleDeleteRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_delete_still_works_via_shared_helper(self):
        session = _FakeSession([_group_no_bindings(_model(30))])
        with patch(
            "app.routes.models.async_session_maker", return_value=_Ctx(session)
        ):
            data = await delete_model(30, cascade_unbind=False, _=True)
        self.assertEqual(data, {"deleted": True})

    async def test_single_delete_provider_bound_returns_409_payload(self):
        session = _FakeSession([_group_provider_bound(_model(31))])
        with patch(
            "app.routes.models.async_session_maker", return_value=_Ctx(session)
        ):
            resp = await delete_model(31, cascade_unbind=False, _=True)
        self.assertIsInstance(resp.status_code, int)
        self.assertEqual(resp.status_code, 409)
        body = resp.body_handler if hasattr(resp, "body_handler") else None


if __name__ == "__main__":
    unittest.main()
