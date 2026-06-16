import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.i18n import render
from app.routes import opencode
from app.routes.user import USER_SESSIONS


class _FakeSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeScalarResult:
    def __init__(self, values=None, one=None, rows=None):
        self._values = values or []
        self._one = one
        self._rows = rows or []

    def scalars(self):
        return self

    def all(self):
        return self._values

    def scalar_one_or_none(self):
        return self._one

    def fetchall(self):
        return self._rows

    def first(self):
        if self._rows:
            return self._rows[0]
        return None


class _SequencedSession:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _stmt):
        if not self._results:
            raise AssertionError("Unexpected query")
        return self._results.pop(0)


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

        self.assertNotIn("config.provider['model-token-plan']", dashboard_html)
        self.assertIn("modelgate", dashboard_html)
        self.assertIn("modelgate provider", dashboard_html)

        self.assertIn("config.provider['modelgate']", public_html)
        self.assertNotIn("config.provider['model-token-plan']", public_html)
        self.assertIn("modelgate provider", public_html)

    def test_placeholder_defaults_do_not_contain_internal_credentials(self):
        database_source = Path("app/core/database.py").read_text(encoding="utf-8")
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
            patch("app.routes.opencode.async_session_maker", return_value=_FakeSessionContext()),
            patch(
                "app.routes.opencode.build_opencode_config",
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
            patch("app.routes.opencode.async_session_maker", return_value=_FakeSessionContext()),
            patch(
                "app.routes.opencode.build_opencode_config",
                new=AsyncMock(return_value={"provider": {"modelgate": {"models": {}}}}),
            ) as build_mock,
        ):
            client = TestClient(app)
            client.cookies.set("user_session", "expired")
            response = client.get("/opencode/setup.md")

        self.assertEqual(response.status_code, 400)
        build_mock.assert_not_awaited()


class OpenCodeAutoModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_opencode_config_exposes_auto_for_accessible_multimodal_candidates(self):
        key = SimpleNamespace(id=7, key="sk-test")
        provider = SimpleNamespace(id=1, is_active=True)
        text_model = SimpleNamespace(
            id=101,
            name="glm-5.1",
            display_name="GLM 5.1",
            is_multimodal=False,
            max_tokens=8192,
            context_length=32768,
            thinking_enabled=False,
        )
        vision_model = SimpleNamespace(
            id=202,
            name="vision-1",
            display_name="Vision 1",
            is_multimodal=True,
            max_tokens=16384,
            context_length=65536,
            thinking_enabled=False,
        )
        text_pm = SimpleNamespace(
            id=11, provider_id=1, model_id=101, priority=1, is_active=True
        )
        vision_pm = SimpleNamespace(
            id=22, provider_id=1, model_id=202, priority=2, is_active=True
        )
        auto_model = SimpleNamespace(id=16, name="auto")
        auto_route = SimpleNamespace(
            enabled=True,
            model_ids=[101, 202],
            provider_model_ids=[],
            route_policy={},
        )
        session = _SequencedSession(
            [
                _FakeScalarResult(one=key),
                _FakeScalarResult(values=[]),
                _FakeScalarResult(rows=[]),
                _FakeScalarResult(values=[text_pm, vision_pm]),
                _FakeScalarResult(rows=[(auto_model, auto_route)]),
                _FakeScalarResult(one=provider),
                _FakeScalarResult(one=text_model),
                _FakeScalarResult(one=provider),
                _FakeScalarResult(one=vision_model),
            ]
        )

        config = await opencode.build_opencode_config(
            session, "https://leturx.cc/modelgate/v1", api_key_id=7
        )

        models = config["provider"]["modelgate"]["models"]
        self.assertIn("auto", models)
        self.assertIn("image", models["auto"]["modalities"]["input"])
        self.assertEqual(models["auto"]["limit"]["context"], 65536)

    async def test_opencode_config_does_not_expose_auto_without_candidates(self):
        key = SimpleNamespace(id=7, key="sk-test")
        provider = SimpleNamespace(id=1, is_active=True)
        model = SimpleNamespace(
            id=101,
            name="glm-5.1",
            display_name="GLM 5.1",
            is_multimodal=False,
            max_tokens=8192,
            context_length=32768,
            thinking_enabled=False,
        )
        pm = SimpleNamespace(
            id=11, provider_id=1, model_id=101, priority=1, is_active=True
        )
        auto_model = SimpleNamespace(id=16, name="auto")
        auto_route = SimpleNamespace(
            enabled=True,
            model_ids=[],
            provider_model_ids=[],
            route_policy={},
        )
        session = _SequencedSession(
            [
                _FakeScalarResult(one=key),
                _FakeScalarResult(values=[]),
                _FakeScalarResult(rows=[]),
                _FakeScalarResult(values=[pm]),
                _FakeScalarResult(rows=[(auto_model, auto_route)]),
                _FakeScalarResult(one=provider),
                _FakeScalarResult(one=model),
            ]
        )

        config = await opencode.build_opencode_config(
            session, "https://leturx.cc/modelgate/v1", api_key_id=7
        )

        models = config["provider"]["modelgate"]["models"]
        self.assertNotIn("auto", models)


if __name__ == "__main__":
    unittest.main()
