import unittest
from datetime import datetime, timedelta

from app.core import config


class TokensPerSecondThroughputTests(unittest.TestCase):
    """Tokens/s 卡片应为系统总吞吐口径：窗口内各请求速率之和。"""

    def setUp(self):
        config.completed_request_rates.clear()

    def tearDown(self):
        config.completed_request_rates.clear()

    def test_returns_sum_of_concurrent_request_rates(self):
        for _ in range(3):
            config.record_request_rate(100, 2000)
        self.assertEqual(config.get_total_tokens_per_second(), 150.0)

    def test_single_request_returns_own_rate(self):
        config.record_request_rate(500, 1000)
        self.assertEqual(config.get_total_tokens_per_second(), 500.0)

    def test_zero_when_no_recent_completions(self):
        self.assertEqual(config.get_total_tokens_per_second(), 0)

    def test_stale_entries_expire_out_of_window(self):
        stale_key = (datetime.now() - timedelta(seconds=30)).strftime("%Y%m%d_%H%M%S")
        config.completed_request_rates.append((stale_key, 999.0))
        self.assertEqual(config.get_total_tokens_per_second(), 0)

    def test_invalid_inputs_ignored(self):
        config.record_request_rate(0, 1000)
        config.record_request_rate(100, 0)
        config.record_request_rate(-5, 1000)
        self.assertEqual(config.get_total_tokens_per_second(), 0)


if __name__ == "__main__":
    unittest.main()
