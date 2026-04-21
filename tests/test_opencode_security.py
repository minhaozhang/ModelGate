import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from core.i18n import render
from routes import opencode
from routes.user import USER_SESSIONS


class _FakeSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def make_request(path: str, root_path: str = ""):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [(b"host", b"testserver")],
            "query_string": b"",
            "cookies": {},
            "root_path": root_path,
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


class OpenCodeReviewFixTests(unittest.TestCase):
    def setUp(self):
        USER_SESSIONS.clear()

    def tearDown(self):
        USER_SESSIONS.clear()

    def test_templates_use_modelgate_provider_key(self):
        dashboard_html = render(
            make_request("/user/dashboard"),
            "user/dashboard.html",
            name="Tester",
            api_key_id=1,
        )
        public_html = render(make_request("/opencode"), "public/opencode.html")

        self.assertIn("config.provider['modelgate']", dashboard_html)
        self.assertNotIn("config.provider['model-token-plan']", dashboard_html)
        self.assertIn("modelgate provider", dashboard_html)

        self.assertIn("config.provider['modelgate']", public_html)
        self.assertNotIn("config.provider['model-token-plan']", public_html)
        self.assertIn("modelgate provider", public_html)

    def test_placeholder_defaults_do_not_contain_internal_credentials(self):
        database_source = Path("core/database.py").read_text(encoding="utf-8")
        env_example = Path(".env.example").read_text(encoding="utf-8")

        for forbidden in ("192.168.58.128", "Zaq1%403edc", "ZxcvbnmZaq1#)"):
            self.assertNotIn(forbidden, database_source)
            self.assertNotIn(forbidden, env_example)

    def test_setup_markdown_uses_root_path_for_valid_user_session(self):
        USER_SESSIONS["valid"] = {
            "api_key_id": 7,
            "expires": datetime.now() + timedelta(hours=1),
        }

        app = FastAPI()
        app.include_router(opencode.router)
        config = {"provider": {"modelgate": {"models": {}}}}

        with (
            patch("routes.opencode.async_session_maker", return_value=_FakeSessionContext()),
            patch(
                "routes.opencode.build_opencode_config",
                new=AsyncMock(return_value=config),
            ) as build_mock,
        ):
            client = TestClient(app, root_path="/modelgate")
            client.cookies.set("user_session", "valid")
            response = client.get("/opencode/setup.md")

        self.assertEqual(response.status_code, 200)
        build_mock.assert_awaited_once()
        _, args, kwargs = build_mock.mock_calls[0]
        self.assertEqual(args[1], "http://testserver/modelgate/v1")
        self.assertEqual(kwargs["api_key_id"], 7)

    def test_setup_markdown_rejects_expired_user_session(self):
        USER_SESSIONS["expired"] = {
            "api_key_id": 9,
            "expires": datetime.now() - timedelta(minutes=1),
        }

        app = FastAPI()
        app.include_router(opencode.router)

        with (
            patch("routes.opencode.async_session_maker", return_value=_FakeSessionContext()),
            patch(
                "routes.opencode.build_opencode_config",
                new=AsyncMock(return_value={"provider": {"modelgate": {"models": {}}}}),
            ) as build_mock,
        ):
            client = TestClient(app)
            client.cookies.set("user_session", "expired")
            response = client.get("/opencode/setup.md")

        self.assertEqual(response.status_code, 400)
        build_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
