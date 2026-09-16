import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import provider
from app.services.disable_schedule import normalize_rules

WEEKEND_RULE = {"type": "weekly", "days": [5, 6], "start": "00:00", "end": "00:00"}
# 全周全天规则,任何时刻都处于禁用窗口,避免测试结果依赖运行日期
ALWAYS_RULE = {"type": "weekly", "days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "00:00"}
PAST_ONCE_RULE = {"type": "once", "start": "2000-01-01 00:00", "end": "2000-01-02 00:00"}


class _FakeResult:
    def __init__(self, row=None):
        self._row = row

    def first(self):
        return self._row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    def __init__(self, row=None):
        self.row = row
        self.committed = 0

    async def execute(self, stmt):
        return _FakeResult(self.row)

    async def commit(self):
        self.committed += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _key(key_id, schedule=None):
    return {
        "id": key_id,
        "api_key": f"sk-{key_id}",
        "label": f"k{key_id}",
        "max_concurrent": None,
        "priority": 0,
        "cost_role": "standard",
        "is_active": True,
        "disable_schedule": schedule or [],
    }


def _provider_config(keys, legacy=""):
    return {
        "id": 3,
        "name": "prov-x",
        "base_url": "http://x",
        "api_key": legacy,
        "protocol": "openai",
        "models": [],
        "merge_consecutive_messages": False,
        "disabled_reason": None,
        "disable_schedule": [],
        "api_keys": keys,
        "disabled_key_reasons": [],
        "disabled_keys": [],
    }


class PickApiKeyScheduleTests(unittest.TestCase):
    def tearDown(self):
        provider._key_sticky_map.clear()

    def test_scheduled_key_skipped(self):
        pc = _provider_config([_key(1, [ALWAYS_RULE]), _key(2)])
        _, key_id = provider.pick_api_key(pc, None, "prov-x")
        self.assertEqual(key_id, 2)

    def test_sticky_scheduled_key_skipped(self):
        pc = _provider_config([_key(1, [ALWAYS_RULE]), _key(2)])
        provider._key_sticky_map[(42, "prov-x")] = (1, time.monotonic())
        _, key_id = provider.pick_api_key(pc, 42, "prov-x")
        self.assertEqual(key_id, 2)
        self.assertEqual(provider._key_sticky_map[(42, "prov-x")][0], 2)

    def test_all_scheduled_returns_no_key(self):
        pc = _provider_config([_key(1, [ALWAYS_RULE])], legacy="sk-legacy")
        api_key, key_id = provider.pick_api_key(pc, None, "prov-x")
        self.assertIsNone(api_key)
        self.assertIsNone(key_id)

    def test_expired_once_rule_not_blocked(self):
        pc = _provider_config([_key(1, [PAST_ONCE_RULE]), _key(2)])
        _, key_id = provider.pick_api_key(pc, None, "prov-x")
        # 候选随机,但两者都可用即不抛错;定向验证:
        self.assertIn(key_id, (1, 2))

    def test_explain_marks_schedule_blocked(self):
        pc = _provider_config([_key(1, [ALWAYS_RULE]), _key(2)])
        explanation = provider.explain_provider_key_candidates(pc, None, "prov-x")
        ordered_ids = [item["key_id"] for item in explanation["ordered"]]
        self.assertEqual(ordered_ids, [2])
        blocked = [
            item
            for item in explanation["filtered"]
            if "schedule_blocked" in item["filtered_reasons"]
        ]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["key_id"], 1)
        self.assertIsNone(blocked[0]["api_key"])

    def test_explain_past_rule_not_filtered(self):
        pc = _provider_config([_key(1, [PAST_ONCE_RULE])])
        explanation = provider.explain_provider_key_candidates(pc, None, "prov-x")
        self.assertEqual(len(explanation["ordered"]), 1)
        self.assertEqual(
            [f for f in explanation["filtered"] if "schedule_blocked" in f["filtered_reasons"]],
            [],
        )


class ProviderScheduleRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._cache_backup = dict(provider.providers_cache)

    def tearDown(self):
        provider.providers_cache.clear()
        provider.providers_cache.update(self._cache_backup)

    async def test_forced_provider_blocked_returns_unroutable(self):
        cfg = _provider_config([_key(1)])
        cfg["disable_schedule"] = [ALWAYS_RULE]
        provider.providers_cache["prov-x"] = cfg
        with patch.object(provider, "_model_name_index", {}), patch.object(
            provider, "_alias_index", {}
        ):
            routes = await provider.get_provider_model_candidates("prov-x/gpt")
        self.assertEqual(len(routes), 1)
        self.assertIsNone(routes[0].provider_config)

    async def test_forced_provider_active_window_routes(self):
        cfg = _provider_config([_key(1)])
        cfg["disable_schedule"] = [PAST_ONCE_RULE]
        provider.providers_cache["prov-x"] = cfg
        with patch.object(provider, "_model_name_index", {}), patch.object(
            provider, "_alias_index", {}
        ):
            routes = await provider.get_provider_model_candidates("prov-x/gpt")
        self.assertIsNotNone(routes[0].provider_config)

    async def test_explain_filters_scheduled_provider(self):
        cfg = _provider_config([_key(1)])
        cfg["disable_schedule"] = [ALWAYS_RULE]
        provider.providers_cache["prov-x"] = cfg
        pm = {"id": 9, "model_name": "gpt", "model_id": 1, "upstream_model_name": "gpt"}
        with patch.object(
            provider,
            "_model_name_index",
            {"gpt": [("prov-x", pm, "", 0)]},
        ), patch.object(provider, "_alias_index", {}):
            explanation = await provider.explain_provider_model_candidates("gpt")
        self.assertEqual(explanation["ordered"], [])
        blocked = [
            entry
            for entry in explanation["filtered"]
            if "schedule_blocked" in entry["filtered_reasons"]
        ]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["provider"], "prov-x")


class ScheduleApiPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_provider_persists_normalized_schedule(self):
        from app.routes.providers import ProviderUpdate, update_provider

        p = SimpleNamespace(
            id=3,
            name="prov-x",
            base_url="http://x",
            api_key="sk",
            protocol="openai",
            merge_consecutive_messages=False,
            is_active=True,
            disabled_by=None,
            disabled_reason=None,
            disabled_at=None,
            reset_at=None,
            disable_schedule=None,
        )
        session = _FakeSession(row=p)
        raw = [
            WEEKEND_RULE,
            {"type": "weekly", "days": [], "start": "00:00", "end": "01:00"},
            "junk",
        ]
        with patch(
            "app.routes.providers.async_session_maker", return_value=session
        ), patch("app.routes.providers.load_providers", new=AsyncMock()):
            await update_provider(3, ProviderUpdate(disable_schedule=raw))
        self.assertEqual(p.disable_schedule, normalize_rules([WEEKEND_RULE]))

    async def test_update_key_persists_normalized_schedule(self):
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
        session = _FakeSession(row=pk)
        with patch(
            "app.routes.providers.async_session_maker", return_value=session
        ), patch("app.routes.providers.load_providers", new=AsyncMock()):
            await update_provider_key(
                3,
                7,
                ProviderKeyUpdate(disable_schedule=[{"type": "once", "start": "bad", "end": "x"}]),
            )
        self.assertEqual(pk.disable_schedule, [])

    async def test_clear_schedule_with_empty_list(self):
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
            disable_schedule=[WEEKEND_RULE],
        )
        session = _FakeSession(row=pk)
        with patch(
            "app.routes.providers.async_session_maker", return_value=session
        ), patch("app.routes.providers.load_providers", new=AsyncMock()):
            await update_provider_key(3, 7, ProviderKeyUpdate(disable_schedule=[]))
        self.assertEqual(pk.disable_schedule, [])


if __name__ == "__main__":
    unittest.main()
