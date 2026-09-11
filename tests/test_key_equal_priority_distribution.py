import unittest
from datetime import datetime

from app.services.provider_key_routing import (
    RoutingContext,
    evaluate_provider_key_candidates,
)


def _keys():
    return [
        {"id": 1, "api_key": "sk-1", "is_active": True, "priority": 5, "routing_rules": []},
        {"id": 2, "api_key": "sk-2", "is_active": True, "priority": 5, "routing_rules": []},
    ]


def _ctx(sticky_key_id=None):
    return RoutingContext(
        now=datetime.now(),
        context_tokens=0,
        sticky_key_id=sticky_key_id,
        health_scores={1: 100, 2: 100},
        standby_open=False,
    )


class EqualPriorityDistributionTests(unittest.TestCase):
    def test_equal_priority_equal_health_randomly_ordered(self):
        firsts = set()
        for _ in range(200):
            evaluation = evaluate_provider_key_candidates(_keys(), _ctx())
            firsts.add(evaluation.usable[0].key_id)
        self.assertEqual(firsts, {1, 2})

    def test_higher_priority_still_wins(self):
        keys = _keys()
        keys[1]["priority"] = 9
        for _ in range(50):
            evaluation = evaluate_provider_key_candidates(keys, _ctx())
            self.assertEqual(evaluation.usable[0].key_id, 2)

    def test_health_breaks_tie_before_randomness(self):
        keys = _keys()
        ctx = _ctx()
        ctx.health_scores = {1: 100, 2: 60}
        for _ in range(50):
            evaluation = evaluate_provider_key_candidates(keys, ctx)
            self.assertEqual(evaluation.usable[0].key_id, 1)

    def test_sticky_still_wins_over_random(self):
        keys = _keys()
        for _ in range(50):
            evaluation = evaluate_provider_key_candidates(keys, _ctx(sticky_key_id=2))
            self.assertEqual(evaluation.usable[0].key_id, 2)


if __name__ == "__main__":
    unittest.main()
