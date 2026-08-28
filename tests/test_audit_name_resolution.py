import unittest
from unittest.mock import patch

from app.routes.audit import _NAME_RESOLVERS, _resolve_resource_names
from types import SimpleNamespace


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    def __init__(self, results):
        self._results = list(results)
        self.queries = []

    async def execute(self, stmt):
        self.queries.append(stmt)
        return self._results.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSessionMaker:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self._session


def _log(resource, resource_id):
    return SimpleNamespace(resource=resource, resource_id=resource_id)


class ResolveResourceNamesTests(unittest.IsolatedAsyncioTestCase):
    async def test_simple_resolver_maps_names(self):
        session = _FakeSession([_FakeResult([(5, "zhoubo"), (7, "wangjin")])])
        with patch(
            "app.routes.audit.async_session_maker",
            _FakeSessionMaker(session),
        ):
            names = await _resolve_resource_names(
                [_log("api_key", "5"), _log("api_key", "7")]
            )
        self.assertEqual(names[("api_key", "5")], "zhoubo")
        self.assertEqual(names[("api_key", "7")], "wangjin")

    async def test_provider_model_resolves_via_model_join(self):
        session = _FakeSession([_FakeResult([(91, "glm-5.3")])])
        with patch(
            "app.routes.audit.async_session_maker",
            _FakeSessionMaker(session),
        ):
            names = await _resolve_resource_names([_log("provider_model", "91")])
        self.assertEqual(names[("provider_model", "91")], "glm-5.3")

    async def test_bad_ids_and_unknown_resources_are_skipped(self):
        session = _FakeSession([])
        with patch(
            "app.routes.audit.async_session_maker",
            _FakeSessionMaker(session),
        ):
            names = await _resolve_resource_names(
                [_log("api_key", "not-a-number"), _log("system_config", None), _log("time_rule", "3")]
            )
        self.assertEqual(names, {})
        self.assertEqual(session.queries, [])

    async def test_user_session_maps_to_api_key_name(self):
        self.assertIs(_NAME_RESOLVERS["user_session"][0], _NAME_RESOLVERS["api_key"][0])


if __name__ == "__main__":
    unittest.main()
