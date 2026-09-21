import unittest
from datetime import datetime, timedelta

from app.core import config


def _reset_ewma():
    config._tokens_per_second_ewma = None


class TokensPerSecondThroughputTests(unittest.TestCase):
    """Tokens/s = 最近 N 秒令牌桶总量 / N（EWMA 平滑显示）。"""

    def setUp(self):
        config.token_buckets.clear()
        _reset_ewma()

    def tearDown(self):
        config.token_buckets.clear()
        _reset_ewma()

    def test_burst_averaged_over_window(self):
        # 同一秒完成 10 个请求、各 100 tokens：真实速率 = 1000/10s = 100
        for _ in range(10):
            config.record_tokens_second(100)
        self.assertEqual(config.get_total_tokens_per_second(), 100.0)

    def test_tokens_accumulate_into_same_second_bucket(self):
        config.record_tokens_second(40)
        config.record_tokens_second(20)
        # 60 tokens / 10s 窗口
        self.assertEqual(config.get_total_tokens_per_second(), 6.0)

    def test_zero_when_no_recent_tokens(self):
        self.assertEqual(config.get_total_tokens_per_second(), 0)

    def test_stale_buckets_expire_out_of_window(self):
        stale_key = (datetime.now() - timedelta(seconds=30)).strftime("%Y%m%d_%H%M%S")
        config.token_buckets.append((stale_key, 999))
        self.assertEqual(config.get_total_tokens_per_second(), 0)

    def test_invalid_inputs_ignored(self):
        config.record_tokens_second(0)
        self.assertEqual(config.get_total_tokens_per_second(), 0)

    def test_negative_correction_clamped_to_zero(self):
        config.record_tokens_second(50)
        config.record_tokens_second(-80)
        self.assertEqual(config.get_total_tokens_per_second(), 0)

    def test_ewma_smooths_toward_raw(self):
        config.record_tokens_second(1000)  # raw = 100
        first = config.get_total_tokens_per_second()
        self.assertEqual(first, 100.0)  # 首次直接取 raw
        config.token_buckets.clear()
        config.record_tokens_second(0) if False else None
        second = config.get_total_tokens_per_second()  # raw = 0
        # ewma = 100*0.7 + 0*0.3 = 70
        self.assertEqual(second, 70.0)

    def test_stream_text_delta_estimates_len_div_4(self):
        config.record_stream_text_delta("abcd" * 10)  # 40 chars -> 10 tokens
        config.record_stream_text_delta("")  # ignored
        self.assertEqual(config.get_total_tokens_per_second(), 1.0)

    def test_ewma_decays_to_zero(self):
        config.record_tokens_second(1000)
        for _ in range(40):
            value = config.get_total_tokens_per_second()
            config.token_buckets.clear()
        self.assertEqual(value, 0)


if __name__ == "__main__":
    unittest.main()
