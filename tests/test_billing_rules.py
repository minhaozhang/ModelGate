import unittest
from datetime import datetime
from unittest.mock import patch

from app.services.billing_rules import (
    BillingRules,
    check_daily_quota,
    charge_daily_usage,
    get_daily_charged,
    get_period_multiplier,
    load_billing_rules,
    parse_peak_windows,
    resolve_key_quota,
    seconds_until_midnight,
)


def _rules(**kwargs):
    base = dict(
        peak_windows=[(9 * 60, 12 * 60), (14 * 60, 18 * 60)],
        weekend_offpeak=True,
        peak_multiplier=1.5,
        offpeak_multiplier=0.8,
        default_daily_quota_cny=None,
    )
    base.update(kwargs)
    return BillingRules(**base)


class ParsePeakWindowsTests(unittest.TestCase):
    def test_normal_windows(self):
        self.assertEqual(
            parse_peak_windows("09:00-12:00,14:00-18:00"),
            [(540, 720), (840, 1080)],
        )

    def test_cross_midnight(self):
        self.assertEqual(parse_peak_windows("22:00-06:00"), [(1320, 360)])

    def test_empty_and_whitespace(self):
        self.assertEqual(parse_peak_windows("  ,  ,"), [])

    def test_invalid_format_raises(self):
        for bad in ("9:00", "09-12:00", "25:00-26:00", "09:61-10:00", "09:00-09:00"):
            with self.assertRaises(ValueError):
                parse_peak_windows(bad)


class PeriodMultiplierTests(unittest.TestCase):
    def test_weekday_peak_inside_window(self):
        # 2026-08-25 is a Tuesday
        period, mult = get_period_multiplier(_rules(), datetime(2026, 8, 25, 10, 0))
        self.assertEqual(period, "peak")
        self.assertEqual(mult, 1.5)

    def test_weekday_offpeak_outside_window(self):
        period, mult = get_period_multiplier(_rules(), datetime(2026, 8, 25, 13, 0))
        self.assertEqual(period, "offpeak")
        self.assertEqual(mult, 0.8)

    def test_weekend_all_offpeak(self):
        # 2026-08-29 is a Saturday, inside a weekday peak window hour
        period, mult = get_period_multiplier(_rules(), datetime(2026, 8, 29, 10, 0))
        self.assertEqual(period, "offpeak")
        self.assertEqual(mult, 0.8)

    def test_weekend_peak_when_disabled(self):
        period, _ = get_period_multiplier(
            _rules(weekend_offpeak=False), datetime(2026, 8, 29, 10, 0)
        )
        self.assertEqual(period, "peak")

    def test_cross_midnight_window_late_and_early(self):
        rules = _rules(peak_windows=[(22 * 60, 6 * 60)])
        self.assertEqual(
            get_period_multiplier(rules, datetime(2026, 8, 25, 23, 30))[0], "peak"
        )
        self.assertEqual(
            get_period_multiplier(rules, datetime(2026, 8, 25, 5, 0))[0], "peak"
        )
        self.assertEqual(
            get_period_multiplier(rules, datetime(2026, 8, 25, 12, 0))[0], "offpeak"
        )

    def test_boundary_start_inclusive_end_exclusive(self):
        rules = _rules()
        self.assertEqual(
            get_period_multiplier(rules, datetime(2026, 8, 25, 9, 0))[0], "peak"
        )
        self.assertEqual(
            get_period_multiplier(rules, datetime(2026, 8, 25, 12, 0))[0], "offpeak"
        )


class MidnightTests(unittest.TestCase):
    def test_seconds_until_midnight(self):
        now = datetime(2026, 8, 25, 23, 0, 0)
        self.assertEqual(seconds_until_midnight(now), 3600)

    def test_min_one_second(self):
        self.assertEqual(seconds_until_midnight(datetime(2026, 8, 25, 23, 59, 59)), 1)


class LoadRulesTests(unittest.TestCase):
    def test_defaults(self):
        async def fake_get(category, key, default=""):
            return default

        with patch("app.services.billing_rules.get_setting", fake_get):
            import asyncio

            rules = asyncio.run(load_billing_rules())
        self.assertEqual(rules.peak_multiplier, 1.5)
        self.assertEqual(rules.offpeak_multiplier, 0.8)
        self.assertTrue(rules.weekend_offpeak)
        self.assertIsNone(rules.default_daily_quota_cny)
        self.assertEqual(len(rules.peak_windows), 2)

    def test_invalid_windows_degrade_to_offpeak(self):
        async def fake_get(category, key, default=""):
            if key == "peak_windows":
                return "not-a-window"
            return default

        with patch("app.services.billing_rules.get_setting", fake_get):
            import asyncio

            rules = asyncio.run(load_billing_rules())
        self.assertEqual(rules.peak_windows, [])


class QuotaLogicTests(unittest.TestCase):
    def _patch_session(self, maker, fake_key):
        async def fake_get(session, key_id):
            return fake_key

        maker.return_value.__aenter__.return_value.get = fake_get
        maker.return_value.__aexit__.return_value = False

    def test_resolve_key_quota_explicit_values(self):
        import asyncio

        class FakeKey:
            daily_quota_cny = 5.0

        with patch(
            "app.services.billing_rules.async_session_maker"
        ) as maker:
            self._patch_session(maker, FakeKey())
            # explicit quota
            self.assertEqual(asyncio.run(resolve_key_quota(1)), 5.0)

            # explicit zero = unlimited
            FakeKey.daily_quota_cny = 0
            self.assertIsNone(asyncio.run(resolve_key_quota(1)))

    def test_resolve_key_quota_falls_back_to_global_default(self):
        import asyncio

        class FakeKey:
            daily_quota_cny = None

        async def fake_rules():
            return _rules(default_daily_quota_cny=10.0)

        async def fake_get_key(session, key_id):
            return FakeKey()

        with patch(
            "app.services.billing_rules.async_session_maker"
        ) as maker, patch(
            "app.services.billing_rules.load_billing_rules", fake_rules
        ):
            maker.return_value.__aenter__.return_value.get = fake_get_key
            maker.return_value.__aexit__.return_value = False
            self.assertEqual(asyncio.run(resolve_key_quota(1)), 10.0)

    def test_check_quota_blocking(self):
        import asyncio

        async def fake_resolve(key_id):
            return 10.0

        async def fake_charged(key_id, day=None):
            return 10.0

        with patch(
            "app.services.billing_rules.resolve_key_quota", fake_resolve
        ), patch("app.services.billing_rules.get_daily_charged", fake_charged):
            info = asyncio.run(check_daily_quota(1))
        self.assertIsNotNone(info)
        self.assertEqual(info["quota_cny"], 10.0)
        self.assertGreater(info["retry_after"], 0)

    def test_check_quota_allows_below(self):
        import asyncio

        async def fake_resolve(key_id):
            return 10.0

        async def fake_charged(key_id, day=None):
            return 9.99

        with patch(
            "app.services.billing_rules.resolve_key_quota", fake_resolve
        ), patch("app.services.billing_rules.get_daily_charged", fake_charged):
            self.assertIsNone(asyncio.run(check_daily_quota(1)))

    def test_check_quota_unlimited(self):
        import asyncio

        async def fake_resolve(key_id):
            return None

        with patch("app.services.billing_rules.resolve_key_quota", fake_resolve):
            self.assertIsNone(asyncio.run(check_daily_quota(1)))

    def test_check_quota_swallows_errors(self):
        import asyncio

        async def boom(key_id):
            raise RuntimeError("db down")

        with patch("app.services.billing_rules.resolve_key_quota", boom):
            self.assertIsNone(asyncio.run(check_daily_quota(1)))


class ChargeUsageTests(unittest.TestCase):
    def test_charge_zero_or_missing_key_noop(self):
        import asyncio

        self.assertIsNone(asyncio.run(charge_daily_usage(0, 5.0)))
        self.assertIsNone(asyncio.run(charge_daily_usage(1, 0)))
        self.assertIsNone(asyncio.run(charge_daily_usage(1, -1)))

    def test_charge_failure_is_best_effort(self):
        import asyncio

        async def boom(*a, **k):
            raise RuntimeError("db down")

        with patch("app.services.billing_rules.load_billing_rules", boom):
            self.assertIsNone(asyncio.run(charge_daily_usage(1, 1.0)))


if __name__ == "__main__":
    unittest.main()
