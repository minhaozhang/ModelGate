import gettext
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PO = ROOT / "web/locales/zh/LC_MESSAGES/messages.po"
MO = ROOT / "web/locales/zh/LC_MESSAGES/messages.mo"
CONFIG = ROOT / "web/templates/admin/config.html"

LONG_DESC = (
    "Requests are skipped during the window. Weekly rules repeat every week; one-"
    "time rules fire once. End time earlier than or equal to start time crosses "
    "into the next day."
)


def _translations():
    with open(MO, "rb") as f:
        return gettext.GNUTranslations(f)


class AdminZhCatalogTests(unittest.TestCase):
    """zh catalog must be free of fuzzy entries (pybabel compile skips them,
    leaving the admin UI in English) and carry correct schedule-dialog strings."""

    def test_po_has_no_fuzzy_entries(self):
        po = PO.read_text(encoding="utf-8")
        self.assertNotIn("#, fuzzy", po)

    def test_mo_translates_schedule_dialog(self):
        t = _translations()
        cases = {
            "Scheduled Disable": "定时停用",
            "Scheduled disable": "定时停用",
            "Weekly": "每周",
            "One-time": "一次性",
            "Add rule": "添加规则",
            "Schedule saved": "定时规则已保存",
            "active now": "当前生效",
            "Close": "关闭",
            "Provider Keys": "供应商密钥",
            "Loading...": "加载中...",
            "Every day": "每天",
            LONG_DESC: (
                "时间窗口内的请求将被跳过。每周规则每周重复；一次性规则仅触发一次。"
                "结束时间早于或等于开始时间表示跨到次日。"
            ),
        }
        for msgid, expected in cases.items():
            self.assertEqual(t.gettext(msgid), expected, msgid)

    def test_mo_has_no_fuzzy_garbage_matches(self):
        t = _translations()
        garbage = {
            "One-time": "时间",
            "Schedule saved": "使用模型",
            "Close": "日志",
            "Clear": "年",
            "Draft": "耗时",
        }
        for msgid, wrong in garbage.items():
            self.assertNotEqual(t.gettext(msgid), wrong, msgid)


class ScheduleModalStackingTests(unittest.TestCase):
    def test_schedule_modal_stacks_above_provider_keys_modal(self):
        html = CONFIG.read_text(encoding="utf-8")

        self.assertIn('id="schedule-modal"', html)
        schedule = html[html.index('id="schedule-modal"') :]
        # z-index set inline: the precompiled Tailwind bundle has no z-[60]
        # utility, so a Tailwind-only class would silently do nothing.
        self.assertIn('style="z-index: 60;"', schedule[: schedule.index(">")])

    def test_schedule_weekday_labels_are_locale_aware(self):
        html = CONFIG.read_text(encoding="utf-8")

        self.assertIn("Intl.DateTimeFormat", html)
        self.assertIn("SCHEDULE_WEEKDAY_LABELS = Array.from", html)
        self.assertNotIn("const SCHEDULE_WEEKDAY_LABELS = ['一'", html)


if __name__ == "__main__":
    unittest.main()
