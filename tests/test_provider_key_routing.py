import unittest
from datetime import date, datetime, time

from app.services.provider_key_routing import (
    RoutingContext,
    evaluate_provider_key_candidates,
    materialize_template_rules,
)
from app.services import provider as provider_service


class ProviderKeyRoutingRuleTests(unittest.TestCase):
    def test_deny_rule_filters_matching_time_window(self):
        keys = [
            {
                "id": 11,
                "api_key": "sk-a",
                "priority": 100,
                "is_active": True,
                "routing_rules": [
                    {
                        "id": 1,
                        "action": "deny",
                        "enabled": True,
                        "start_time": time(13, 0),
                        "end_time": time(18, 0),
                    }
                ],
            },
            {"id": 12, "api_key": "sk-b", "priority": 1, "is_active": True},
        ]
        ctx = RoutingContext(now=datetime(2026, 6, 14, 14, 30), context_tokens=1000)

        candidates = evaluate_provider_key_candidates(keys, ctx)

        self.assertEqual([c.key_id for c in candidates.usable], [12])
        self.assertEqual(candidates.filtered[0].key_id, 11)
        self.assertIn("time_denied", candidates.filtered[0].filtered_reasons)

    def test_allow_rule_must_match_when_present(self):
        keys = [
            {
                "id": 11,
                "api_key": "sk-a",
                "priority": 100,
                "is_active": True,
                "routing_rules": [
                    {
                        "id": 1,
                        "action": "allow",
                        "enabled": True,
                        "start_time": time(8, 0),
                        "end_time": time(11, 0),
                    }
                ],
            },
            {"id": 12, "api_key": "sk-b", "priority": 1, "is_active": True},
        ]
        ctx = RoutingContext(now=datetime(2026, 6, 14, 14, 30), context_tokens=1000)

        candidates = evaluate_provider_key_candidates(keys, ctx)

        self.assertEqual([c.key_id for c in candidates.usable], [12])
        self.assertIn("allow_not_matched", candidates.filtered[0].filtered_reasons)

    def test_prefer_rule_boosts_sorting_but_health_zero_filters(self):
        keys = [
            {
                "id": 11,
                "api_key": "sk-a",
                "priority": 10,
                "is_active": True,
                "routing_rules": [
                    {
                        "id": 1,
                        "action": "prefer",
                        "enabled": True,
                        "priority": 50,
                        "max_context_tokens": 8000,
                    }
                ],
            },
            {"id": 12, "api_key": "sk-b", "priority": 40, "is_active": True},
            {
                "id": 13,
                "api_key": "sk-c",
                "priority": 99,
                "is_active": True,
                "routing_rules": [
                    {
                        "id": 2,
                        "action": "prefer",
                        "enabled": True,
                        "priority": 100,
                        "max_context_tokens": 8000,
                    }
                ],
            },
        ]
        ctx = RoutingContext(
            now=datetime(2026, 6, 14, 9, 30),
            context_tokens=1000,
            health_scores={11: 100, 12: 100, 13: 0},
        )

        candidates = evaluate_provider_key_candidates(keys, ctx)

        self.assertEqual([c.key_id for c in candidates.usable], [11, 12])
        self.assertEqual(candidates.filtered[0].key_id, 13)
        self.assertIn("health_unavailable", candidates.filtered[0].filtered_reasons)

    def test_cross_midnight_and_weekday_rules_match(self):
        keys = [
            {
                "id": 11,
                "api_key": "sk-a",
                "priority": 1,
                "is_active": True,
                "routing_rules": [
                    {
                        "id": 1,
                        "action": "allow",
                        "enabled": True,
                        "start_time": time(22, 0),
                        "end_time": time(2, 0),
                        "weekdays": "6,7",
                    }
                ],
            }
        ]
        ctx = RoutingContext(now=datetime(2026, 6, 14, 1, 30), context_tokens=1000)

        candidates = evaluate_provider_key_candidates(keys, ctx)

        self.assertEqual([c.key_id for c in candidates.usable], [11])

    def test_sticky_key_cannot_bypass_context_filter(self):
        keys = [
            {
                "id": 11,
                "api_key": "sk-a",
                "priority": 100,
                "is_active": True,
                "routing_rules": [
                    {
                        "id": 1,
                        "action": "allow",
                        "enabled": True,
                        "max_context_tokens": 1000,
                    }
                ],
            },
            {"id": 12, "api_key": "sk-b", "priority": 1, "is_active": True},
        ]
        ctx = RoutingContext(
            now=datetime.combine(date(2026, 6, 14), time(9, 0)),
            context_tokens=2000,
            sticky_key_id=11,
        )

        candidates = evaluate_provider_key_candidates(keys, ctx)

        self.assertEqual([c.key_id for c in candidates.usable], [12])
        self.assertIn("allow_not_matched", candidates.filtered[0].filtered_reasons)

    def test_pick_api_keys_applies_routing_rules_and_sticky_as_soft_bonus(self):
        provider_service._key_sticky_map[(123, "zhipu")] = (11, 1.0)
        provider_config = {
            "api_keys": [
                {
                    "id": 11,
                    "api_key": "sk-sticky",
                    "priority": 100,
                    "is_active": True,
                    "routing_rules": [
                        {
                            "id": 1,
                            "action": "allow",
                            "enabled": True,
                            "max_context_tokens": 1000,
                        }
                    ],
                },
                {
                    "id": 12,
                    "api_key": "sk-small",
                    "priority": 1,
                    "is_active": True,
                    "routing_rules": [
                        {
                            "id": 2,
                            "action": "prefer",
                            "enabled": True,
                            "priority": 20,
                            "max_context_tokens": 8000,
                        }
                    ],
                },
            ]
        }

        keys = provider_service.pick_api_keys(
            provider_config,
            api_key_id=123,
            provider_name="zhipu",
            context_tokens=2000,
            now=datetime(2026, 6, 14, 9, 30),
        )

        self.assertEqual(keys, [("sk-small", 12)])
        provider_service._key_sticky_map.clear()

    def test_model_route_key_scope_overrides_provider_key_priority(self):
        provider_config = {
            "api_keys": [
                {
                    "id": 11,
                    "api_key": "sk-high-priority",
                    "priority": 100,
                    "is_active": True,
                },
                {
                    "id": 12,
                    "api_key": "sk-route-scoped",
                    "priority": 1,
                    "is_active": True,
                },
            ]
        }

        keys = provider_service.pick_api_keys(
            provider_config,
            api_key_id=123,
            provider_name="zhipu",
            allowed_key_ids=[12],
        )
        explanation = provider_service.explain_provider_key_candidates(
            provider_config,
            api_key_id=123,
            provider_name="zhipu",
            allowed_key_ids=[12],
        )

        self.assertEqual(keys, [("sk-route-scoped", 12)])
        self.assertEqual([item["key_id"] for item in explanation["ordered"]], [12])
        self.assertEqual(
            [
                item["key_id"]
                for item in explanation["filtered"]
                if "route_key_scope" in item["filtered_reasons"]
            ],
            [11],
        )

    def test_materialize_template_rules_replaces_params_and_keeps_typed_values(self):
        blueprint = {
            "rules": [
                {
                    "action": "prefer",
                    "start_time": "${start_time}",
                    "end_time": "${end_time}",
                    "max_context_tokens": "${max_context_tokens}",
                    "priority": "${priority}",
                }
            ]
        }

        rules = materialize_template_rules(
            blueprint,
            {
                "start_time": "08:00",
                "end_time": "11:00",
                "max_context_tokens": 8000,
                "priority": 20,
            },
        )

        self.assertEqual(
            rules,
            [
                {
                    "action": "prefer",
                    "start_time": "08:00",
                    "end_time": "11:00",
                    "max_context_tokens": 8000,
                    "priority": 20,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
