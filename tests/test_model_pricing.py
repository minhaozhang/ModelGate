import unittest

from app.services.pricing import (
    PricingConfig,
    calculate_model_billing,
    select_pricing_for_context,
)


class ModelPricingTests(unittest.TestCase):
    def test_calculates_cost_with_reported_cached_input_tokens(self):
        pricing = PricingConfig(
            input_price_cny_per_million=8,
            output_price_cny_per_million=28,
            cached_input_price_cny_per_million=2,
            default_cache_hit_ratio=0,
        )

        billing = calculate_model_billing(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "prompt_tokens_details": {"cached_tokens": 200},
            },
            pricing,
        )

        self.assertEqual(billing["cached_input_tokens"], 200)
        self.assertEqual(billing["uncached_input_tokens"], 800)
        self.assertAlmostEqual(billing["total_cost_cny"], 0.0208)

    def test_calculates_cost_with_default_cache_hit_ratio_when_provider_has_no_detail(self):
        pricing = PricingConfig(
            input_price_cny_per_million=3,
            output_price_cny_per_million=6,
            cached_input_price_cny_per_million=0.025,
            default_cache_hit_ratio=25,
        )

        billing = calculate_model_billing(
            {"prompt_tokens": 1000, "completion_tokens": 100},
            pricing,
        )

        self.assertEqual(billing["cached_input_tokens"], 250)
        self.assertEqual(billing["uncached_input_tokens"], 750)
        self.assertAlmostEqual(billing["total_cost_cny"], 0.00285625)

    def test_selects_pricing_tier_by_request_context_tokens(self):
        base = PricingConfig(
            input_price_cny_per_million=2.1,
            output_price_cny_per_million=8.4,
            cached_input_price_cny_per_million=0.42,
            pricing_tiers=[
                {
                    "max_context_tokens": 524288,
                    "input_price_cny_per_million": 2.1,
                    "output_price_cny_per_million": 8.4,
                    "cached_input_price_cny_per_million": 0.42,
                },
                {
                    "min_context_tokens": 524289,
                    "input_price_cny_per_million": 4.2,
                    "output_price_cny_per_million": 16.8,
                    "cached_input_price_cny_per_million": 0.84,
                },
            ],
        )

        low = select_pricing_for_context(base, 128000)
        high = select_pricing_for_context(base, 600000)

        self.assertEqual(low.input_price_cny_per_million, 2.1)
        self.assertEqual(high.input_price_cny_per_million, 4.2)
        self.assertEqual(high.cached_input_price_cny_per_million, 0.84)


if __name__ == "__main__":
    unittest.main()
