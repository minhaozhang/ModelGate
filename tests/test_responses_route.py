"""Route tests for the OpenAI Responses inbound endpoints (mock proxy).

Covers spec §9.4: docs/specs/2026-08-24-openai-responses-inbound-design.md
"""
import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import Response, StreamingResponse
from fastapi.testclient import TestClient

from app.routes import responses_proxy


CHAT_OK = {
    "id": "chatcmpl-1",
    "model": "upstream-model",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello!"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}


def make_chat_sse_bytes():
    return (
        b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        b'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}\n\n'
        b"data: [DONE]\n\n"
    )


class _Capture:
    def __init__(self, result):
        self.result = result
        self.inner = None
        self.endpoint = None

    async def __call__(self, request, endpoint):
        from starlette.requests import Request as StarletteRequest

        assert isinstance(request, StarletteRequest)
        self.inner = request
        self.endpoint = endpoint
        return self.result


class ResponsesRouteTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(responses_proxy.router)
        self.client = TestClient(app)

    def _capture(self, result):
        return _Capture(result)

    def test_p1_non_streaming_ok(self):
        capture = self._capture(
            Response(json.dumps(CHAT_OK), status_code=200, media_type="application/json")
        )
        body = {
            "model": "gpt-x",
            "input": [
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]},
            ],
        }
        with patch.object(responses_proxy, "proxy_request", capture):
            resp = self.client.post(
                "/v1/responses",
                json=body,
                headers={"Authorization": "Bearer sk-test"},
            )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["object"], "response")
        self.assertEqual(payload["output"][0]["content"][0]["text"], "Hello!")
        # upstream saw the translated body
        upstream = json.loads(capture.inner._body.decode("utf-8"))
        self.assertEqual(upstream["messages"][-1]["content"], "hi")
        self.assertNotIn("stream_options", upstream)
        self.assertEqual(capture.endpoint, "/chat/completions")
        self.assertEqual(
            capture.inner.headers.get("x-inbound-protocol"), "responses"
        )

    def test_p2_invalid_json(self):
        with patch.object(
            responses_proxy,
            "proxy_request",
            self._capture(Response("{}", status_code=200)),
        ):
            resp = self.client.post(
                "/v1/responses",
                content=b"not json",
                headers={"Authorization": "Bearer sk-test"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_p3_validation_errors(self):
        good_header = {"Authorization": "Bearer sk-test"}
        cases = [
            {"input": "hi"},  # missing model
            {"model": "m", "input": []},  # empty input
            {
                "model": "m",
                "input": [
                    {"type": "message", "role": "user", "content": "hi"},
                    {"type": "item_reference", "id": "msg_1"},
                ],
            },
        ]
        for body in cases:
            with patch.object(
                responses_proxy,
                "proxy_request",
                self._capture(Response("{}", status_code=200)),
            ):
                resp = self.client.post("/v1/responses", json=body, headers=good_header)
            self.assertEqual(resp.status_code, 400, body)
            self.assertIn("error", resp.json())

    def test_p4_get_delete_not_found(self):
        resp = self.client.get("/v1/responses/resp_123")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "response_not_found")
        resp2 = self.client.delete("/v1/responses/resp_123")
        self.assertEqual(resp2.status_code, 404)
        self.assertEqual(resp2.json()["error"]["code"], "response_not_found")

    def test_p5_streaming(self):
        async def gen():
            yield make_chat_sse_bytes()

        capture = self._capture(
            StreamingResponse(gen(), status_code=200, media_type="text/event-stream")
        )
        body = {
            "model": "gpt-x",
            "input": "hi",
            "stream": True,
        }
        with patch.object(responses_proxy, "proxy_request", capture):
            resp = self.client.post(
                "/v1/responses", json=body, headers={"Authorization": "Bearer sk-test"}
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/event-stream"))
        text = resp.text
        self.assertIn("event: response.created", text)
        self.assertIn("event: response.completed", text)
        upstream = json.loads(capture.inner._body.decode("utf-8"))
        self.assertEqual(upstream["stream_options"], {"include_usage": True})

    def test_p6_upstream_401(self):
        error_payload = {
            "error": {
                "message": "Invalid API key",
                "type": "invalid_request_error",
                "code": "invalid_api_key",
            }
        }
        capture = self._capture(
            Response(
                json.dumps(error_payload), status_code=401, media_type="application/json"
            )
        )
        with patch.object(responses_proxy, "proxy_request", capture):
            resp = self.client.post(
                "/v1/responses",
                json={"model": "m", "input": "hi"},
                headers={"Authorization": "Bearer sk-bad"},
            )
        self.assertEqual(resp.status_code, 401)
        err = resp.json()["error"]
        self.assertEqual(err["code"], "invalid_api_key")
        self.assertEqual(err["message"], "Invalid API key")

    def test_p8_stream_flag_but_json_error(self):
        error_payload = {
            "error": {"message": "Invalid API key", "code": "invalid_api_key"}
        }
        capture = self._capture(
            Response(
                json.dumps(error_payload), status_code=401, media_type="application/json"
            )
        )
        with patch.object(responses_proxy, "proxy_request", capture):
            resp = self.client.post(
                "/v1/responses",
                json={"model": "m", "input": "hi", "stream": True},
                headers={"Authorization": "Bearer sk-bad"},
            )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.headers["content-type"], "application/json")
        self.assertEqual(resp.json()["error"]["code"], "invalid_api_key")

    def test_p9_options(self):
        resp = self.client.options("/v1/responses")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
