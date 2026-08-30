import unittest
from datetime import datetime

from app.services.disable_schedule import (
    normalize_rules,
    schedule_active,
    summarize_rules,
)


def _dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


class NormalizeRulesTests(unittest.TestCase):
    def test_weekly_rule_normalized(self):
        rules = normalize_rules(
            [{"type": "weekly", "days": [6, 5, 6, "x", 9], "start": "0:00", "end": "00:00"}]
        )
        self.assertEqual(rules, [{"type": "weekly", "days": [5, 6], "start": "00:00", "end": "00:00"}])

    def test_once_rule_normalized(self):
        rules = normalize_rules(
            [{"type": "once", "start": "2026-09-04 18:00", "end": "2026-09-05T08:00"}]
        )
        self.assertEqual(
            rules, [{"type": "once", "start": "2026-09-04 18:00", "end": "2026-09-05 08:00"}]
        )

    def test_invalid_rules_dropped(self):
        raw = [
            {"type": "weekly", "days": [], "start": "00:00", "end": "01:00"},
            {"type": "weekly", "days": [1], "start": "25:00", "end": "01:00"},
            {"type": "weekly", "days": [1], "start": None, "end": "01:00"},
            {"type": "once", "start": "bad", "end": "2026-09-05 08:00"},
            {"type": "once", "start": "2026-09-05 08:00", "end": "2026-09-04 08:00"},
            {"type": "unknown", "days": [1]},
            "junk",
            {"type": "weekly", "days": [2], "start": "09:00", "end": "12:00"},
        ]
        rules = normalize_rules(raw)
        self.assertEqual(
            rules, [{"type": "weekly", "days": [2], "start": "09:00", "end": "12:00"}]
        )

    def test_non_list_input_returns_empty(self):
        self.assertEqual(normalize_rules(None), [])
        self.assertEqual(normalize_rules("x"), [])
        self.assertEqual(normalize_rules({}), [])

    def test_rules_capped(self):
        raw = [{"type": "once", "start": "2026-01-01 00:00", "end": "2026-01-02 00:00"}] * 30
        self.assertEqual(len(normalize_rules(raw)), 20)


class ScheduleActiveWeeklyTests(unittest.TestCase):
    # 2026-08-28 周五(4), 08-29 周六(5), 08-30 周日(6), 08-31 周一(0)
    def test_within_same_day_window(self):
        rules = [{"type": "weekly", "days": [4], "start": "18:00", "end": "20:00"}]
        self.assertTrue(schedule_active(rules, _dt("2026-08-28 19:00")))  # 周五
        self.assertFalse(schedule_active(rules, _dt("2026-08-28 17:59")))
        self.assertFalse(schedule_active(rules, _dt("2026-08-28 20:00")))

    def test_cross_midnight_window(self):
        rules = [{"type": "weekly", "days": [0], "start": "23:00", "end": "07:00"}]
        self.assertTrue(schedule_active(rules, _dt("2026-08-31 23:30")))  # 周一
        self.assertTrue(schedule_active(rules, _dt("2026-09-01 06:59")))  # 周二凌晨
        self.assertFalse(schedule_active(rules, _dt("2026-09-01 07:00")))
        self.assertFalse(schedule_active(rules, _dt("2026-09-01 23:00")))  # 周二晚非窗口

    def test_full_day_window_end_equals_start(self):
        rules = [{"type": "weekly", "days": [5, 6], "start": "00:00", "end": "00:00"}]
        self.assertTrue(schedule_active(rules, _dt("2026-08-29 00:00")))  # 周六
        self.assertTrue(schedule_active(rules, _dt("2026-08-29 13:00")))
        self.assertTrue(schedule_active(rules, _dt("2026-08-30 23:59")))  # 周日
        self.assertFalse(schedule_active(rules, _dt("2026-08-28 23:59")))  # 周五
        self.assertFalse(schedule_active(rules, _dt("2026-08-31 00:00")))  # 周一00:00窗口已结束

    def test_wrong_day_not_active(self):
        rules = [{"type": "weekly", "days": [4], "start": "00:00", "end": "00:00"}]
        self.assertFalse(schedule_active(rules, _dt("2026-08-29 12:00")))  # 周六,规则是周五


class ScheduleActiveOnceTests(unittest.TestCase):
    def test_active_within_range(self):
        rules = [{"type": "once", "start": "2026-09-04 18:00", "end": "2026-09-05 08:00"}]
        self.assertTrue(schedule_active(rules, _dt("2026-09-04 18:00")))
        self.assertTrue(schedule_active(rules, _dt("2026-09-05 08:00")))
        self.assertFalse(schedule_active(rules, _dt("2026-09-05 08:01")))
        self.assertFalse(schedule_active(rules, _dt("2026-09-04 17:59")))

    def test_any_rule_hits(self):
        rules = [
            {"type": "weekly", "days": [1], "start": "09:00", "end": "10:00"},
            {"type": "once", "start": "2026-09-04 18:00", "end": "2026-09-05 08:00"},
        ]
        self.assertTrue(schedule_active(rules, _dt("2026-09-04 20:00")))
        self.assertTrue(schedule_active(rules, _dt("2026-09-01 09:30")))  # Tuesday

    def test_empty_or_garbage_rules_inactive(self):
        self.assertFalse(schedule_active([], _dt("2026-09-04 20:00")))
        self.assertFalse(schedule_active(None, _dt("2026-09-04 20:00")))
        self.assertFalse(
            schedule_active([{"type": "weekly", "days": [1]}], _dt("2026-09-04 20:00"))
        )


class SummarizeRulesTests(unittest.TestCase):
    def test_weekday_names(self):
        text = summarize_rules(
            [{"type": "weekly", "days": [5, 6], "start": "00:00", "end": "00:00"}]
        )
        self.assertEqual(text, "每周周六周日 00:00→00:00")

    def test_every_day(self):
        text = summarize_rules(
            [{"type": "weekly", "days": list(range(7)), "start": "23:00", "end": "07:00"}]
        )
        self.assertEqual(text, "每周每天 23:00→07:00")

    def test_once(self):
        text = summarize_rules(
            [{"type": "once", "start": "2026-09-04 18:00", "end": "2026-09-05 08:00"}]
        )
        self.assertEqual(text, "2026-09-04 18:00→2026-09-05 08:00")


if __name__ == "__main__":
    unittest.main()
