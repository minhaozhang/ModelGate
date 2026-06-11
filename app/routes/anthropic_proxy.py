"""User-facing Anthropic-protocol endpoints.

These routes accept Anthropic ``/v1/messages`` style requests, convert them to the internal
OpenAI representation, run them through the existing proxy pipeline, and translate the
response (regular JSON or SSE) back to Anthropic format.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.requests import Request as StarletteRequest

from app.core.config import error_logger
from app.services.anthropic_inbound import (
    anthropic_to_openai_request,
    build_anthropic_error_response,
    openai_to_anthropic_error,
    openai_to_anthropic_response,
    translate_openai_sse_stream,
)
from app.services.proxy import proxy_request

router = APIRouter(tags=["anthropic-proxy"])


# ---------------------------------------------------------------------------
# Request wrapping helpers
# ---------------------------------------------------------------------------


def _normalize_auth_header(headers: dict[str, str]) -> dict[str, str]:
    """Anthropic clients typically send ``x-api-key``; downstream code wants ``authorization``."""
    lower = {k.lower(): v for k, v in headers.items()}
    if "authorization" not in lower:
        api_key = lower.get("x-api-key")
        if api_key:
            lower["authorization"] = f"Bearer {api_key}"
    return lower


def _build_inner_request(
    original: Request, new_body: bytes, new_headers: dict[str, str]
) -> StarletteRequest:
    """Build a Starlette Request that downstream proxy code can consume.

    The body is pre-cached and headers are rewritten via ``scope``. The original receive
    channel is preserved so ``request.is_disconnected()`` keeps working for streaming.
    """
    new_scope = dict(original.scope)
    new_scope["headers"] = [
        (key.encode("latin-1"), value.encode("latin-1"))
        for key, value in new_headers.items()
    ]

    receive = getattr(original, "_receive", None)
    if receive is None:
        async def _empty_receive():
            return {"type": "http.disconnect"}
        receive = _empty_receive

    new_request = StarletteRequest(new_scope, receive=receive)
    new_request._body = new_body  # cache, so .body() returns ours
    return new_request


# ---------------------------------------------------------------------------
# Response translation helpers
# ---------------------------------------------------------------------------


def _anthropic_error_response(
    message: str,
    status_code: int,
    error_type: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        content=build_anthropic_error_response(message, status_code, error_type),
        status_code=status_code,
        headers=headers,
    )


def _strip_hop_headers(headers) -> dict[str, str]:
    skip = {"content-length", "content-encoding", "transfer-encoding"}
    return {k: v for k, v in headers.items() if k.lower() not in skip}


async def _translate_non_streaming_response(
    response: Response, requested_model: str
) -> Response:
    body_bytes = getattr(response, "body", None)
    if body_bytes is None:
        # Defensive: still return what we have, but mark as api error
        return _anthropic_error_response(
            "Empty response from proxy", response.status_code or 502
        )

    try:
        payload = json.loads(body_bytes) if body_bytes else {}
    except json.JSONDecodeError:
        payload = {}

    status = response.status_code or 200
    if status >= 400 or (isinstance(payload, dict) and "error" in payload and "choices" not in payload):
        anthropic_payload = openai_to_anthropic_error(payload if isinstance(payload, dict) else {}, status)
    else:
        anthropic_payload = openai_to_anthropic_response(payload, requested_model=requested_model)

    new_body = json.dumps(anthropic_payload, ensure_ascii=False).encode("utf-8")
    headers = _strip_hop_headers(response.headers)
    headers["content-type"] = "application/json"
    return Response(
        content=new_body,
        status_code=status,
        headers=headers,
        media_type="application/json",
    )


def _translate_streaming_response(
    response: StreamingResponse,
    requested_model: str,
    estimated_input_tokens: int = 0,
) -> StreamingResponse:
    source = response.body_iterator
    headers = _strip_hop_headers(response.headers)
    return StreamingResponse(
        translate_openai_sse_stream(
            source, requested_model, estimated_input_tokens=estimated_input_tokens
        ),
        status_code=response.status_code or 200,
        media_type="text/event-stream",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.api_route("/v1/messages", methods=["POST", "OPTIONS"])
@router.api_route("/anthropic/v1/messages", methods=["POST", "OPTIONS"])
async def anthropic_messages(request: Request):
    if request.method == "OPTIONS":
        return Response()

    raw_body = await request.body()
    try:
        anthropic_body: dict[str, Any] = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        return _anthropic_error_response(
            "Invalid JSON body", 400, "invalid_request_error"
        )

    if not isinstance(anthropic_body, dict):
        return _anthropic_error_response(
            "Request body must be a JSON object", 400, "invalid_request_error"
        )

    requested_model = anthropic_body.get("model", "") or ""
    raw_messages = anthropic_body.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        return _anthropic_error_response(
            "Field 'messages' must be a non-empty array", 400, "invalid_request_error"
        )

    try:
        openai_body = anthropic_to_openai_request(anthropic_body)
    except Exception as exc:  # noqa: BLE001
        error_logger.error(f"[ANTHROPIC INBOUND] Request translation failed: {exc}")
        return _anthropic_error_response(
            f"Failed to translate request: {exc}", 400, "invalid_request_error"
        )

    if not openai_body.get("model"):
        return _anthropic_error_response(
            "Missing 'model' field", 400, "invalid_request_error"
        )

    # Pre-estimate input tokens so streaming message_start carries a sensible
    # input_tokens value (OpenAI providers only send the real count at end-of-stream).
    estimated_input_tokens = 0
    if openai_body.get("stream"):
        try:
            from app.services.tokens import estimate_request_context_tokens

            estimated_input_tokens = int(
                estimate_request_context_tokens(openai_body) or 0
            )
        except Exception:  # noqa: BLE001
            estimated_input_tokens = 0

    new_body = json.dumps(openai_body, ensure_ascii=False).encode("utf-8")
    new_headers = _normalize_auth_header(dict(request.headers))
    # Force content-type / content-length to match new body
    new_headers["content-type"] = "application/json"
    new_headers["content-length"] = str(len(new_body))
    new_headers["x-inbound-protocol"] = "anthropic"

    inner_request = _build_inner_request(request, new_body, new_headers)

    try:
        proxied = await proxy_request(inner_request, "/chat/completions")
    except Exception as exc:  # noqa: BLE001
        error_logger.error(f"[ANTHROPIC INBOUND] proxy_request failed: {exc}")
        return _anthropic_error_response(
            f"Proxy failure: {exc}", 502, "api_error"
        )

    if isinstance(proxied, StreamingResponse):
        return _translate_streaming_response(
            proxied, requested_model, estimated_input_tokens=estimated_input_tokens
        )
    return await _translate_non_streaming_response(proxied, requested_model)


@router.api_route("/v1/messages/count_tokens", methods=["POST", "OPTIONS"])
@router.api_route("/anthropic/v1/messages/count_tokens", methods=["POST", "OPTIONS"])
async def anthropic_count_tokens(request: Request):
    if request.method == "OPTIONS":
        return Response()

    raw_body = await request.body()
    try:
        anthropic_body: dict[str, Any] = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        return _anthropic_error_response(
            "Invalid JSON body", 400, "invalid_request_error"
        )

    from app.services.tokens import estimate_request_context_tokens

    try:
        openai_body = anthropic_to_openai_request(anthropic_body)
    except Exception as exc:  # noqa: BLE001
        return _anthropic_error_response(
            f"Failed to translate request: {exc}", 400, "invalid_request_error"
        )

    estimated = estimate_request_context_tokens(openai_body)
    return JSONResponse({"input_tokens": int(estimated)})


@router.get("/anthropic/v1/models")
async def anthropic_list_models():
    from app.core.config import providers_cache

    models = []
    for provider_name, cfg in providers_cache.items():
        for pm in cfg.get("models", []) or []:
            model_name = pm.get("model_name") or pm.get("actual_model_name", "")
            full_id = f"{provider_name}/{model_name}"
            models.append(
                {
                    "type": "model",
                    "id": full_id,
                    "display_name": model_name,
                    "created_at": None,
                }
            )
    return {
        "data": models,
        "has_more": False,
        "first_id": models[0]["id"] if models else None,
        "last_id": models[-1]["id"] if models else None,
    }
