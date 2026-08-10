import unittest

from app.routes.user import aggregate_model_pricing


class AggregateModelPricingTests(unittest.TestCase):
    def test_returns_none_when_no_prices(self):
        result = aggregate_model_pricing([])
        self.assertIsNone(result["min_input_price"])
        self.assertIsNone(result["min_output_price"])
        self.assertIsNone(result["min_cached_price"])
        self.assertEqual(result["tier_samples"], [])

    def test_takes_min_across_multiple_provider_models(self):
        pms = [
            {"input": 8.0, "output": 28.0, "cached": 2.0, "tiers": []},
            {"input": 5.0, "output": 30.0, "cached": None, "tiers": []},
        ]
        result = aggregate_model_pricing(pms)
        self.assertEqual(result["min_input_price"], 5.0)
        self.assertEqual(result["min_output_price"], 28.0)
        self.assertEqual(result["min_cached_price"], 2.0)

    def test_cached_falls_back_to_input_price_when_null(self):
        pms = [
            {"input": 10.0, "output": 20.0, "cached": None, "tiers": []},
        ]
        result = aggregate_model_pricing(pms)
        self.assertEqual(result["min_cached_price"], 10.0)

    def test_ignores_none_input_prices(self):
        pms = [
            {"input": None, "output": 20.0, "cached": None, "tiers": []},
            {"input": 8.0, "output": None, "cached": None, "tiers": []},
        ]
        result = aggregate_model_pricing(pms)
        self.assertEqual(result["min_input_price"], 8.0)
        self.assertEqual(result["min_output_price"], 20.0)

    def test_merges_and_sorts_tier_samples_by_min_context(self):
        pms = [
            {"input": 4.2, "output": 16.8, "cached": 0.84, "tiers": [
                {"min_context_tokens": 128001, "max_context_tokens": None,
                 "input_price_cny_per_million": 4.2, "output_price_cny_per_million": 16.8},
            ]},
            {"input": 2.1, "output": 8.4, "cached": 0.42, "tiers": [
                {"min_context_tokens": 0, "max_context_tokens": 128000,
                 "input_price_cny_per_million": 2.1, "output_price_cny_per_million": 8.4},
            ]},
        ]
        result = aggregate_model_pricing(pms)
        self.assertEqual(len(result["tier_samples"]), 2)
        self.assertEqual(result["tier_samples"][0]["min_context_tokens"], 0)
        self.assertEqual(result["tier_samples"][1]["min_context_tokens"], 128001)


if __name__ == "__main__":
    unittest.main()
