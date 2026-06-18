import unittest
from types import SimpleNamespace

from app.routes.user import _build_billing_detail_rows, _billing_rows_to_csv


class UserBillingExportTests(unittest.TestCase):
    def test_billing_detail_rows_are_aggregated_by_provider_model_and_token_type(self):
        logs = [
            SimpleNamespace(
                provider_id=1,
                model="glm-5.2",
                tokens={
                    "billing": {
                        "provider_name": "zhipu",
                        "model_name": "glm-5.2",
                        "uncached_input_tokens": 800,
                        "cached_input_tokens": 200,
                        "completion_tokens": 500,
                        "input_cost_cny": 0.0064,
                        "cached_input_cost_cny": 0.0004,
                        "output_cost_cny": 0.014,
                    }
                },
            ),
            SimpleNamespace(
                provider_id=1,
                model="glm-5.2",
                tokens={
                    "billing": {
                        "provider_name": "zhipu",
                        "model_name": "glm-5.2",
                        "uncached_input_tokens": 100,
                        "cached_input_tokens": 50,
                        "completion_tokens": 10,
                        "input_cost_cny": 0.0008,
                        "cached_input_cost_cny": 0.0001,
                        "output_cost_cny": 0.00028,
                    }
                },
            ),
        ]

        rows = _build_billing_detail_rows(logs)

        self.assertEqual(len(rows), 3)
        self.assertEqual([row["token_type"] for row in rows], ["输入", "输出", "缓存输入"])
        self.assertEqual(rows[0]["provider"], "zhipu")
        self.assertEqual(rows[0]["model"], "glm-5.2")
        self.assertEqual(rows[0]["tokens"], 900)
        self.assertAlmostEqual(rows[0]["cost_cny"], 0.0072)
        self.assertEqual(rows[1]["tokens"], 510)
        self.assertAlmostEqual(rows[1]["cost_cny"], 0.01428)
        self.assertEqual(rows[2]["tokens"], 250)
        self.assertAlmostEqual(rows[2]["cost_cny"], 0.0005)

    def test_billing_csv_contains_aggregated_rows_not_raw_requests(self):
        rows = [
            {"provider": "zhipu", "model": "glm-5.2", "token_type": "输入", "tokens": 900, "cost_cny": 0.0072},
            {"provider": "zhipu", "model": "glm-5.2", "token_type": "输出", "tokens": 510, "cost_cny": 0.01428},
        ]

        csv_text = _billing_rows_to_csv(rows)

        self.assertIn("provider,model,token_type,tokens,cost_cny", csv_text)
        self.assertIn("zhipu,glm-5.2,输入,900,0.0072", csv_text)
        self.assertIn("zhipu,glm-5.2,输出,510,0.01428", csv_text)


if __name__ == "__main__":
    unittest.main()
