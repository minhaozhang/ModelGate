import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import provider


def _key(key_id, priority):
    return {
        "id": key_id,
        "api_key": f"sk-{key_id}",
        "label": f"k{key_id}",
        "max_concurrent": None,
        "priority": priority,
        "cost_role": "standard",
        "is_active": True,
        "disable_schedule": [],
    }


def _cfg(keys):
    return {
        "id": 3,
        "name": "prov-x",
        "base_url": "http://x",
        "api_key": "",
        "protocol": "openai",
        "models": [],
        "api_keys": keys,
        "disabled_key_reasons": [],
        "disabled_keys": [],
    }


class KeyPriorityOrderTests(unittest.TestCase):
    def tearDown(self):
        provider._key_sticky_map.clear()

    def test_highest_priority_wins_without_sticky(self):
        cfg = _cfg([_key(1, 0), _key(2, 10)])
        for _ in range(10):
            explanation = provider.explain_provider_key_candidates(cfg, None, "prov-x")
            self.assertEqual(explanation["ordered"][0]["key_id"], 2)

    def test_sticky_overrides_priority_within_ttl(self):
        cfg = _cfg([_key(1, 0), _key(2, 10)])
        provider._key_sticky_map[(42, "prov-x")] = (1, time.monotonic())
        explanation = provider.explain_provider_key_candidates(cfg, 42, "prov-x")
        self.assertEqual(explanation["ordered"][0]["key_id"], 1)

    def test_expired_sticky_falls_back_to_priority(self):
        cfg = _cfg([_key(1, 0), _key(2, 10)])
        provider._key_sticky_map[(42, "prov-x")] = (1, time.monotonic() - 1801)
        explanation = provider.explain_provider_key_candidates(cfg, 42, "prov-x")
        self.assertEqual(explanation["ordered"][0]["key_id"], 2)


class InvalidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalidate_provider_sticky_cache_scopes_to_provider(self):
        provider._key_sticky_map[(1, "prov-x")] = (7, time.monotonic())
        provider._key_sticky_map[(2, "prov-x")] = (8, time.monotonic())
        provider._key_sticky_map[(1, "prov-y")] = (9, time.monotonic())
        await provider.invalidate_provider_sticky_cache("prov-x")
        self.assertNotIn((1, "prov-x"), provider._key_sticky_map)
        self.assertNotIn((2, "prov-x"), provider._key_sticky_map)
        self.assertIn((1, "prov-y"), provider._key_sticky_map)
        provider._key_sticky_map.clear()


class _FakeResult:
    def __init__(self, row=None):
        self._row = row

    def first(self):
        return self._row

    def scalar_one_or_none(self):
        return self._row


class _RoutingFakeSession:
    """execute() returns rows keyed by the model being selected."""

    def __init__(self, rows):
        self.rows = rows
        self.committed = 0

    async def execute(self, stmt):
        model_cls = stmt.column_descriptions[0]["entity"]
        return _FakeResult(self.rows.get(model_cls))

    async def commit(self):
        self.committed += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class UpdateKeyInvalidatesStickyTests(unittest.IsolatedAsyncioTestCase):
    async def test_priority_update_clears_sticky(self):
        from app.core.database import Provider, ProviderKey
        from app.routes.providers import ProviderKeyUpdate, update_provider_key

        pk = SimpleNamespace(
            id=7,
            provider_id=3,
            api_key="sk-provider",
            label="k",
            max_concurrent=2,
            priority=0,
            cost_role="standard",
            is_active=True,
            disabled_by=None,
            disabled_reason=None,
            disabled_at=None,
            reset_at=None,
            disable_schedule=None,
        )
        session = _RoutingFakeSession({ProviderKey: pk, Provider: "prov-x"})
        provider._key_sticky_map[(42, "prov-x")] = (7, time.monotonic())
        try:
            with patch(
                "app.routes.providers.async_session_maker", return_value=session
            ), patch("app.routes.providers.load_providers", new=AsyncMock()):
                await update_provider_key(3, 7, ProviderKeyUpdate(priority=99))
            self.assertEqual(pk.priority, 99)
            self.assertNotIn((42, "prov-x"), provider._key_sticky_map)
        finally:
            provider._key_sticky_map.clear()

    async def test_label_only_update_keeps_sticky(self):
        from app.core.database import Provider, ProviderKey
        from app.routes.providers import ProviderKeyUpdate, update_provider_key

        pk = SimpleNamespace(
            id=7,
            provider_id=3,
            api_key="sk-provider",
            label="k",
            max_concurrent=2,
            priority=0,
            cost_role="standard",
            is_active=True,
            disabled_by=None,
            disabled_reason=None,
            disabled_at=None,
            reset_at=None,
            disable_schedule=None,
        )
        session = _RoutingFakeSession({ProviderKey: pk, Provider: "prov-x"})
        provider._key_sticky_map[(42, "prov-x")] = (7, time.monotonic())
        try:
            with patch(
                "app.routes.providers.async_session_maker", return_value=session
            ), patch("app.routes.providers.load_providers", new=AsyncMock()):
                await update_provider_key(3, 7, ProviderKeyUpdate(label="renamed"))
            self.assertEqual(pk.label, "renamed")
            self.assertIn((42, "prov-x"), provider._key_sticky_map)
        finally:
            provider._key_sticky_map.clear()


if __name__ == "__main__":
    unittest.main()
