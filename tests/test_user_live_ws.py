import asyncio
import unittest
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.core.config as config
from app.routes.user import USER_SESSIONS, router


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class UserLiveWebSocketTests(unittest.TestCase):
    def setUp(self):
        USER_SESSIONS.clear()
        self.original_busyness = dict(config.busyness_state)
        self.original_user_subs = set(config.user_live_stats_subscribers)
        self.original_providers_cache = dict(config.providers_cache)

    def tearDown(self):
        USER_SESSIONS.clear()
        config.busyness_state.clear()
        config.busyness_state.update(self.original_busyness)
        config.providers_cache.clear()
        config.providers_cache.update(self.original_providers_cache)
        config.user_live_stats_subscribers.clear()
        config.user_live_stats_subscribers.update(self.original_user_subs)

    def test_rejects_missing_session(self):
        client = build_client()
        with self.assertRaises(WebSocketDisconnect) as ctx:
            with client.websocket_connect("/user/api/live"):
                pass
        self.assertEqual(ctx.exception.code, 4401)

    def test_rejects_expired_session(self):
        USER_SESSIONS["expired"] = {
            "api_key_id": 9,
            "expires": datetime.now() - timedelta(minutes=1),
        }
        client = build_client()
        client.cookies.set("user_session", "expired")
        with self.assertRaises(WebSocketDisconnect) as ctx:
            with client.websocket_connect("/user/api/live"):
                pass
        self.assertEqual(ctx.exception.code, 4401)

    def test_authenticated_receives_user_snapshot(self):
        USER_SESSIONS["tok"] = {
            "api_key_id": 5,
            "expires": datetime.now() + timedelta(hours=1),
        }
        config.busyness_state.update(
            {"level": 2, "label": "Busy", "active_users_10min": 3, "rate_429_ratio": 0.01}
        )
        client = build_client()
        client.cookies.set("user_session", "tok")
        with client.websocket_connect("/user/api/live") as ws:
            data = ws.receive_json()
        self.assertIn("active_requests", data)
        self.assertIn("tokens_per_second", data)
        self.assertIn("disabled_providers", data)
        self.assertEqual(data["busyness"]["level"], 2)
        self.assertEqual(data["busyness"]["active_users_10min"], 3)

    def test_broadcast_pushes_user_snapshot_to_user_subscribers(self):
        class FakeUserSocket:
            def __init__(self):
                self.sent = []

            async def send_json(self, payload):
                self.sent.append(payload)

        async def run():
            fake = FakeUserSocket()
            await config.add_user_live_stats_subscriber(fake)
            await config.broadcast_live_stats()
            await config.remove_user_live_stats_subscriber(fake)
            return fake

        fake = asyncio.run(run())
        self.assertEqual(len(fake.sent), 1)
        self.assertIn("busyness", fake.sent[0])
        self.assertIn("active_requests", fake.sent[0])

    def test_broadcast_skips_user_snapshot_without_subscribers(self):
        async def run():
            await config.broadcast_live_stats()

        self.assertIsNone(asyncio.run(run()))


if __name__ == "__main__":
    unittest.main()
