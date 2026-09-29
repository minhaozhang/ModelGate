"""Announcement feature: admin publishes broadcast notifications, users see a
rotating banner (latest within 7 days) + detail modal; stale broadcasts are
auto-cleaned by the aggregator.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.dialects import postgresql


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _Ctx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _FakeResult(self.rows)


class GetAnnouncementsTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_broadcast_items(self):
        from datetime import datetime

        from app.services.notification import get_announcements

        row = SimpleNamespace(
            id=7,
            level="warning",
            title="维护公告",
            body="今晚 02:00 升级",
            created_at=datetime(2026, 9, 30, 8, 0, 0),
        )
        session = _FakeSession([row])
        with patch("app.services.notification.async_session_maker", return_value=_Ctx(session)):
            items = await get_announcements()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "维护公告")
        self.assertEqual(items[0]["level"], "warning")

    async def test_query_filters_broadcast_user_type_and_recent(self):
        from app.services.notification import get_announcements

        session = _FakeSession([])
        with patch("app.services.notification.async_session_maker", return_value=_Ctx(session)):
            await get_announcements(days=7, limit=5)

        sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
        self.assertIn("notifications.type =", sql)
        self.assertIn("notifications.target_api_key_id IS NULL", sql)
        self.assertIn("notifications.created_at >=", sql)
        self.assertIn("LIMIT", sql)
        self.assertEqual(
            session.statements[0].compile(dialect=postgresql.dialect()).params["param_1"], 5
        )


class PublishRouteTests(unittest.TestCase):
    def test_post_route_requires_create_permission(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1] / "app" / "routes" / "system_config.py"
        ).read_text(encoding="utf-8")
        self.assertIn('@router.post("/api/notifications")', src)
        self.assertIn('permission_required("notification.create")', src)
        self.assertIn('type="user", level=level, title=title, body=body, target_api_key_id=None', src)

    def test_user_announcements_route_registered(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "app" / "routes" / "user.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('@router.get("/user/api/announcements")', src)

    def test_rbac_seeds_include_notification_create(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        self.assertIn(
            '("notification.create", "发布公告", "notification", "create")',
            (root / "app" / "core" / "db_migrations.py").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "('notification.create', '发布公告', 'element', 'notification', 'create')",
            (root / "db" / "migrations" / "init_rbac_data.py").read_text(encoding="utf-8"),
        )


class CleanupTests(unittest.TestCase):
    def test_aggregator_cleans_system_and_broadcast_but_not_targeted(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1] / "app" / "services" / "stats_aggregator.py"
        ).read_text(encoding="utf-8")
        self.assertIn("(type = 'system' OR (type = 'user' AND target_api_key_id IS NULL))", src)


class AnnouncementUiStaticTests(unittest.TestCase):
    def test_dashboard_has_banner_rotation_and_modal(self):
        from pathlib import Path

        html = (
            Path(__file__).resolve().parents[1] / "web" / "templates" / "user" / "dashboard.html"
        ).read_text(encoding="utf-8")
        for needle in (
            "announcement-strip",
            "ann-warning",
            "announcement-dots",
            "announcement-modal",
            "loadAnnouncements",
            "restartAnnRotation",
            "switchAnnouncement",
            "openAnnouncementModal",
            "announcementGoNotifs",
            "/user/api/announcements",
        ):
            self.assertIn(needle, html)

    def test_admin_notifications_page_has_publish_form(self):
        from pathlib import Path

        html = (
            Path(__file__).resolve().parents[1]
            / "web"
            / "templates"
            / "admin"
            / "notifications.html"
        ).read_text(encoding="utf-8")
        for needle in (
            "ann-title",
            "ann-body",
            "ann-level",
            "publishAnnouncement",
            "admin/api/notifications",
        ):
            self.assertIn(needle, html)


if __name__ == "__main__":
    unittest.main()
