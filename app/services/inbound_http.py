"""Shared HTTP plumbing for inbound protocol translation routes.

Both the Anthropic inbound route (``/v1/messages``) and the OpenAI Responses
inbound route (``/v1/responses``) rewrite the client request into an internal
chat-completions request before handing it to the proxy pipeline. These helpers
implement that rewriting once so both routes share identical behavior.
"""
from __future__ import annotations

from starlette.requests import Request as StarletteRequest


def normalize_auth_header(headers: dict[str, str]) -> dict[str, str]:
    """Non-OpenAI clients may send ``x-api-key``; downstream code wants ``authorization``."""
    lower = {k.lower(): v for k, v in headers.items()}
    if "authorization" not in lower:
        api_key = lower.get("x-api-key")
        if api_key:
            lower["authorization"] = f"Bearer {api_key}"
    return lower


def build_inner_request(
    original: StarletteRequest, new_body: bytes, new_headers: dict[str, str]
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


def strip_hop_headers(headers) -> dict[str, str]:
    skip = {"content-length", "content-encoding", "transfer-encoding"}
    return {k: v for k, v in headers.items() if k.lower() not in skip}
