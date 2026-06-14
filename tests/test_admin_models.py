import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.routes.models import list_all_models


class _FakeResult:
    def __init__(self, values=None, rows=None):
        self._values = values or []
        self._rows = rows or []

    def scalars(self):
        return self

    def all(self):
        return self._values

    def fetchall(self):
        return self._rows


class _FakeSession:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _stmt):
        if not self._results:
            raise AssertionError("Unexpected query")
        return self._results.pop(0)


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


if __name__ == "__main__":
    unittest.main()
