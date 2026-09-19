import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

import app.core.config as config
from app.routes import user as user_routes
from app.services.proxy import proxy_request


def make_request(method: str = "GET", path: str = "/") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(b"authorization", b"Bearer test-key")],
            "query_string": b"",
            "cookies": {},
            "root_path": "",
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


class BusynessBypassProxyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_busyness_state = dict(config.busyness_state)
        self.original_system_rules = config.system_config.get("busyness_rules")
        self.original_api_keys_cache = dict(config.api_keys_cache)
        config.busyness_state.clear()
        config.api_keys_cache.clear()

    def tearDown(self):
        config.busyness_state.clear()
        config.busyness_state.update(self.original_busyness_state)
        config.api_keys_cache.clear()
        config.api_keys_cache.update(self.original_api_keys_cache)
        if self.original_system_rules is None:
            config.system_config.pop("busyness_rules", None)
        else:
            config.system_config["busyness_rules"] = self.original_system_rules

    async def test_bypass_key_skips_busyness_block_rule(self):
        config.busyness_state.update({"level": 1, "label": "Busy"})
        config.system_config["busyness_rules"] = [
            {
                "min_level": 1,
                "action": "block",
                "target_models": ["openai/gpt-test"],
                "message": "blocked",
            }
        ]
        config.api_keys_cache["test-key"] = {
            "id": 7,
            "name": "bypass",
            "bypass_busyness": True,
        }
        request = make_request("POST", "/v1/chat/completions")
        request._body = b'{"model":"openai/gpt-test","messages":[]}'

        with (
            patch("app.services.proxy.validate_api_key", new=AsyncMock(return_value=(7, None))),
            patch(
                "app.services.proxy.get_provider_model_candidates",
                new=AsyncMock(return_value=[(None, None, "openai")]),
            ) as provider_mock,
            patch(
                "app.services.proxy.get_disabled_provider_reason",
                new=AsyncMock(return_value=None),
            ),
            patch("app.services.proxy.logger.error"),
            patch("app.services.proxy.schedule_api_key_last_used_update", return_value=None),
        ):
            response = await proxy_request(request, "/chat/completions")

        provider_mock.assert_awaited_once()
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("busyness_block", response.body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
