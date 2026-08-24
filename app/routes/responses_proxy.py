"""User-facing OpenAI Responses API endpoints.

These routes accept ``POST /v1/responses`` style requests (Codex CLI and other
Responses-native clients), convert them to the internal chat-completions
representation, run them through the existing proxy pipeline, and translate the
response (regular JSON or SSE) back to Responses format.

The gateway is stateless: ``GET/DELETE /v1/responses/{id}``` always 404s and
``store`` / ``previous_response_id`` are dropped during translation.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.core.config import error_logger
from app.services.inbound_http import (
    build_inner_request,
    normalize_auth_header,
    strip_hop_headers,
)
from app.services.proxy import proxy_request
from app.services.responses_inbound import (
    build_responses_error,
    openai_to_responses_error,
    openai_to_responses_response,
    responses_to_openai_request,
    translate_openai_sse_to_responses,
)

router = APIRouter(tags=["responses-proxy"])


# ---------------------------------------------------------------------------
# Response translation helpers
# ---------------------------------------------------------------------------


def _responses_error_response(
    message: str,
    status_code: int,
    error_type: str | None = None,
    code: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        content=build_responses_error(message, status_code, error_type, code),
        status_code=status_code,
    )


async def _translate_non_streaming_response(
    response: Response, requested_model: str
) -> Response:
    body_bytes = getattr(response, "body", None)
    if body_bytes is None:
        return _responses_error_response(
            "Empty response from proxy", response.status_code or 502
        )

    try:
        payload = json.loads(body_bytes) if body_bytes else {}
    except json.JSONDecodeError:
        payload = {}

    status = response.status_code or 200
    if status >= 400 or (isinstance(payload, dict) and "error" in payload and "choices" not in payload):
        responses_payload = openai_to_responses_error(
            payload if isinstance(payload, dict) else {}, status
        )
    else:
        responses_payload = openai_to_responses_response(
            payload, requested_model=requested_model
        )

    new_body = json.dumps(responses_payload, ensure_ascii=False).encode("utf-8")
    headers = strip_hop_headers(response.headers)
    headers["content-type"] = "application/json"
    return Response(
        content=new_body,
        status_code=status,
        headers=headers,
        media_type="application/json",
    )


def _translate_streaming_response(
    response: StreamingResponse, requested_model: str
) -> StreamingResponse:
    source = response.body_iterator
    headers = strip_hop_headers(response.headers)
    return StreamingResponse(
        translate_openai_sse_to_responses(source, requested_model),
        status_code=response.status_code or 200,
        media_type="text/event-stream",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.api_route("/v1/responses", methods=["POST", "OPTIONS"])
async def create_response(request: Request):
    if request.method == "OPTIONS":
        return Response()

    raw_body = await request.body()
    try:
        responses_body: dict[str, Any] = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        return _responses_error_response(
            "Invalid JSON body", 400, "invalid_request_error"
        )

    if not isinstance(responses_body, dict):
        return _responses_error_response(
            "Request body must be a JSON object", 400, "invalid_request_error"
        )

    requested_model = responses_body.get("model", "") or ""

    try:
        openai_body = responses_to_openai_request(responses_body)
    except ValueError as exc:
        return _responses_error_response(
            str(exc), 400, "invalid_request_error"
        )
    except Exception as exc:  # noqa: BLE001
        error_logger.error(f"[RESPONSES INBOUND] Request translation failed: {exc}")
        return _responses_error_response(
            f"Failed to translate request: {exc}", 400, "invalid_request_error"
        )

    new_body = json.dumps(openai_body, ensure_ascii=False).encode("utf-8")
    new_headers = normalize_auth_header(dict(request.headers))
    new_headers["content-type"] = "application/json"
    new_headers["content-length"] = str(len(new_body))
    new_headers["x-inbound-protocol"] = "responses"

    inner_request = build_inner_request(request, new_body, new_headers)

    try:
        proxied = await proxy_request(inner_request, "/chat/completions")
    except Exception as exc:  # noqa: BLE001
        error_logger.error(f"[RESPONSES INBOUND] proxy_request failed: {exc}")
        return _responses_error_response(
            f"Proxy failure: {exc}", 502, "server_error"
        )

    if isinstance(proxied, StreamingResponse):
        return _translate_streaming_response(proxied, requested_model)
    return await _translate_non_streaming_response(proxied, requested_model)


@router.api_route("/v1/responses/{response_id}", methods=["GET", "DELETE"])
async def get_response(response_id: str):
    return JSONResponse(
        build_responses_error(
            f"Response {response_id} not found. The gateway is stateless; "
            "use store=false and replay conversation history in input.",
            404,
            "invalid_request_error",
            "response_not_found",
        ),
        status_code=404,
    )
