"""Translate Anthropic-format requests into OpenAI format, and OpenAI responses back to Anthropic format.

This is the inbound counterpart to ``services/proxy_runtime/adapters/anthropic.py``:

* The outbound adapter converts our internal OpenAI representation INTO Anthropic format
  when calling Anthropic-protocol providers.
* This module converts INCOMING Anthropic requests from clients INTO OpenAI format so the
  existing proxy pipeline (auth, busyness, semaphores, stats, logging, provider adapters)
  can be reused unchanged, then converts the OpenAI response back to Anthropic on the way out.
"""
from __future__ import annotations

import json

import uuid
from typing import Any, AsyncIterator


# ---------------------------------------------------------------------------
# Request: Anthropic -> OpenAI
# ---------------------------------------------------------------------------


def anthropic_to_openai_request(body: dict[str, Any]) -> dict[str, Any]:
    """Convert an Anthropic ``/v1/messages`` body to OpenAI ``/v1/chat/completions`` body."""
    openai_body: dict[str, Any] = {}

    if "model" in body:
        openai_body["model"] = body["model"]
    if "max_tokens" in body:
        openai_body["max_tokens"] = body["max_tokens"]
    if "temperature" in body:
        openai_body["temperature"] = body["temperature"]
    if "top_p" in body:
        openai_body["top_p"] = body["top_p"]
    if "top_k" in body:
        openai_body["top_k"] = body["top_k"]
    if "stream" in body:
        openai_body["stream"] = body["stream"]
    if "stop_sequences" in body:
        openai_body["stop"] = body["stop_sequences"]
    if "thinking" in body:
        openai_body["thinking"] = body["thinking"]
    if "service_tier" in body:
        openai_body["service_tier"] = body["service_tier"]

    metadata = body.get("metadata")
    if isinstance(metadata, dict):
        user_id = metadata.get("user_id")
        if user_id:
            openai_body["user"] = user_id
        openai_body["_anthropic_metadata"] = metadata

    messages: list[dict[str, Any]] = []
    system_content = _convert_system(body.get("system"))
    if system_content:
        messages.append({"role": "system", "content": system_content})

    for msg in body.get("messages", []) or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            messages.extend(_convert_user_message(content))
        elif role == "assistant":
            messages.extend(_convert_assistant_message(content))

    openai_body["messages"] = messages

    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        openai_body["tools"] = [
            _convert_anthropic_tool(t) for t in tools if isinstance(t, dict)
        ]

    tool_choice = body.get("tool_choice")
    if tool_choice is not None:
        converted = _convert_anthropic_tool_choice(tool_choice)
        if converted is not None:
            openai_body["tool_choice"] = converted
        if isinstance(tool_choice, dict) and tool_choice.get("disable_parallel_tool_use"):
            openai_body["parallel_tool_calls"] = False

    return openai_body


def _convert_system(system: Any) -> Any:
    """Convert Anthropic ``system`` to an OpenAI ``content`` value.

    If any system block carries ``cache_control`` we preserve the structured list
    form so a downstream Anthropic adapter can reattach the cache markers.
    Otherwise we fold to a plain joined string (what OpenAI providers expect).
    """
    if system is None:
        return ""
    if isinstance(system, str):
        return system
    if not isinstance(system, list):
        return ""

    has_cache_control = any(
        isinstance(b, dict) and b.get("cache_control") for b in system
    )

    if has_cache_control:
        blocks: list[dict[str, Any]] = []
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                entry: dict[str, Any] = {"type": "text", "text": block.get("text", "")}
                if block.get("cache_control"):
                    entry["cache_control"] = block["cache_control"]
                blocks.append(entry)
            elif isinstance(block, str) and block:
                blocks.append({"type": "text", "text": block})
        return blocks

    parts: list[str] = []
    for block in system:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if text:
                parts.append(text)
        elif isinstance(block, str) and block:
            parts.append(block)
    return "\n\n".join(parts)


def _flatten_system(system: Any) -> str:
    """Backwards-compat helper that always returns a string."""
    converted = _convert_system(system)
    if isinstance(converted, str):
        return converted
    if isinstance(converted, list):
        return "\n\n".join(
            b.get("text", "") for b in converted if isinstance(b, dict)
        )
    return ""


def _convert_user_message(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"role": "user", "content": content}] if content else []
    if not isinstance(content, list):
        return []

    content_parts: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []

    for block in content:
        if isinstance(block, str):
            if block:
                content_parts.append({"type": "text", "text": block})
            continue
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")
        if block_type == "text":
            text = block.get("text", "")
            if text:
                entry: dict[str, Any] = {"type": "text", "text": text}
                if block.get("cache_control"):
                    entry["cache_control"] = block["cache_control"]
                content_parts.append(entry)
        elif block_type == "image":
            converted = _convert_anthropic_image(block)
            if converted:
                if block.get("cache_control"):
                    converted["cache_control"] = block["cache_control"]
                content_parts.append(converted)
        elif block_type == "tool_result":
            tool_results.append(block)

    result: list[dict[str, Any]] = []

    # Tool results MUST precede the new user text so they sit directly after the
    # assistant tool_calls message — OpenAI providers reject otherwise.
    for tr in tool_results:
        result.append(_convert_tool_result(tr))

    if content_parts:
        has_cache = any(p.get("cache_control") for p in content_parts)
        if (
            len(content_parts) == 1
            and content_parts[0]["type"] == "text"
            and not has_cache
        ):
            result.append({"role": "user", "content": content_parts[0]["text"]})
        else:
            result.append({"role": "user", "content": content_parts})

    return result


def _convert_tool_result(block: dict[str, Any]) -> dict[str, Any]:
    raw = block.get("content", "")
    structured: list[dict[str, Any]] | None = None

    if isinstance(raw, str):
        text = raw
    elif isinstance(raw, list):
        text_parts: list[str] = []
        structured = []
        has_image = False
        for sub in raw:
            if isinstance(sub, dict):
                if sub.get("type") == "text":
                    text_parts.append(sub.get("text", ""))
                    structured.append({"type": "text", "text": sub.get("text", "")})
                elif sub.get("type") == "image":
                    has_image = True
                    img = _convert_anthropic_image(sub)
                    if img:
                        structured.append(img)
                    text_parts.append("[image]")
            elif isinstance(sub, str):
                text_parts.append(sub)
                structured.append({"type": "text", "text": sub})
        text = "\n".join(p for p in text_parts if p)
        if not has_image:
            structured = None  # plain text — collapse
    else:
        text = json.dumps(raw, ensure_ascii=False)

    msg: dict[str, Any] = {
        "role": "tool",
        "tool_call_id": block.get("tool_use_id", ""),
        "content": structured if structured else text,
    }
    if block.get("cache_control"):
        msg["cache_control"] = block["cache_control"]
    if block.get("is_error"):
        msg["is_error"] = True
    return msg


def _convert_assistant_message(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"role": "assistant", "content": content}] if content else []
    if not isinstance(content, list):
        return []

    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    thinking_entries: list[tuple[str, str]] = []  # (thinking_text, signature)
    tool_calls: list[dict[str, Any]] = []

    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")
        if block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "thinking":
            txt = block.get("thinking", "")
            reasoning_parts.append(txt)
            sig = block.get("signature", "")
            thinking_entries.append((txt, sig))
        elif block_type == "tool_use":
            tool_input = block.get("input", {})
            if isinstance(tool_input, dict):
                arguments = json.dumps(tool_input, ensure_ascii=False)
            else:
                arguments = str(tool_input)
            tool_calls.append(
                {
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": arguments,
                    },
                }
            )

    msg: dict[str, Any] = {"role": "assistant"}
    joined_text = "".join(text_parts)
    joined_reasoning = "".join(reasoning_parts)

    if tool_calls:
        # OpenAI spec allows content=None when tool_calls is present.
        msg["content"] = joined_text if joined_text else None
        msg["tool_calls"] = tool_calls
    elif joined_text:
        msg["content"] = joined_text
    elif joined_reasoning:
        # No visible text and no tool_calls — strict providers (Kimi/Moonshot)
        # reject assistant turns with empty content. Fall back to the reasoning
        # text so the turn is preserved without shifting message indices.
        msg["content"] = joined_reasoning
    else:
        # Truly empty assistant turn (e.g. content=[] from a truncated response):
        # drop it instead of emitting an invalid empty message.
        return []

    if joined_reasoning:
        msg["reasoning_content"] = joined_reasoning
    if thinking_entries:
        msg["reasoning_signature"] = thinking_entries
    return [msg]


def _convert_anthropic_image(block: dict[str, Any]) -> dict[str, Any] | None:
    source = block.get("source", {}) or {}
    src_type = source.get("type", "")
    if src_type == "base64":
        media_type = source.get("media_type", "image/jpeg")
        data = source.get("data", "")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{data}"},
        }
    if src_type == "url":
        url = source.get("url", "")
        if not url:
            return None
        return {"type": "image_url", "image_url": {"url": url}}
    return None


def _convert_anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        },
    }


def _convert_anthropic_tool_choice(choice: Any) -> Any:
    if isinstance(choice, str):
        return choice
    if isinstance(choice, dict):
        c_type = choice.get("type", "")
        if c_type == "auto":
            return "auto"
        if c_type == "none":
            return "none"
        if c_type == "any":
            return "required"
        if c_type == "tool":
            return {
                "type": "function",
                "function": {"name": choice.get("name", "")},
            }
    return None


# ---------------------------------------------------------------------------
# Response: OpenAI -> Anthropic
# ---------------------------------------------------------------------------


_FINISH_REASON_MAP = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "content_filter": "end_turn",
}


def _finish_to_stop_reason(finish_reason: str | None) -> str:
    if not finish_reason:
        return "end_turn"
    return _FINISH_REASON_MAP.get(finish_reason, "end_turn")


def openai_to_anthropic_response(
    resp: dict[str, Any], requested_model: str
) -> dict[str, Any]:
    msg_id = resp.get("id") or f"msg_{uuid.uuid4().hex[:24]}"
    model = resp.get("model") or requested_model

    content_blocks: list[dict[str, Any]] = []
    finish_reason: str | None = None

    choices = resp.get("choices") or []
    if choices and isinstance(choices[0], dict):
        choice = choices[0]
        message = choice.get("message", {}) or {}
        text = message.get("content")
        reasoning = message.get("reasoning_content")
        tool_calls = message.get("tool_calls") or []
        finish_reason = choice.get("finish_reason")

        if reasoning:
            content_blocks.append({"type": "thinking", "thinking": str(reasoning)})

        if isinstance(text, str) and text:
            content_blocks.append({"type": "text", "text": text})
        elif isinstance(text, list):
            for block in text:
                if isinstance(block, dict) and block.get("type") == "text":
                    content_blocks.append(
                        {"type": "text", "text": block.get("text", "")}
                    )
                elif isinstance(block, str) and block:
                    content_blocks.append({"type": "text", "text": block})

        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            func = tc.get("function", {}) or {}
            args_raw = func.get("arguments", "{}")
            tool_input = _parse_tool_arguments(args_raw)
            content_blocks.append(
                {
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": func.get("name", ""),
                    "input": tool_input,
                }
            )

    usage_in = resp.get("usage") or {}
    usage_out: dict[str, int] = {
        "input_tokens": int(usage_in.get("prompt_tokens", 0) or 0),
        "output_tokens": int(usage_in.get("completion_tokens", 0) or 0),
    }
    prompt_details = usage_in.get("prompt_tokens_details") or {}
    if isinstance(prompt_details, dict):
        cached = prompt_details.get("cached_tokens") or 0
        if cached:
            usage_out["cache_read_input_tokens"] = int(cached)
    # Some upstreams (anthropic adapter passthrough) put native cache counts here.
    for key in ("cache_creation_input_tokens", "cache_read_input_tokens"):
        if usage_in.get(key):
            usage_out[key] = int(usage_in[key])

    return {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content_blocks,
        "stop_reason": _finish_to_stop_reason(finish_reason),
        "stop_sequence": None,
        "usage": usage_out,
    }


def _parse_tool_arguments(args_raw: Any) -> dict[str, Any]:
    if isinstance(args_raw, dict):
        return args_raw
    if isinstance(args_raw, str):
        if not args_raw:
            return {}
        try:
            parsed = json.loads(args_raw)
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except json.JSONDecodeError:
            return {"_raw": args_raw}
    return {}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


_ERROR_TYPE_MAP = {
    "authentication_error": "authentication_error",
    "invalid_api_key": "authentication_error",
    "invalid_request_error": "invalid_request_error",
    "permission_error": "permission_error",
    "not_found_error": "not_found_error",
    "rate_limit_error": "rate_limit_error",
    "api_error": "api_error",
    "server_error": "api_error",
    "overloaded_error": "overloaded_error",
}


def openai_to_anthropic_error(
    payload: dict[str, Any], status_code: int
) -> dict[str, Any]:
    error_obj = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error_obj, dict):
        message = (
            error_obj.get("message")
            or error_obj.get("detail")
            or json.dumps(error_obj, ensure_ascii=False)
        )
        raw_type = error_obj.get("type") or ""
    elif isinstance(error_obj, str):
        message = error_obj
        raw_type = ""
    else:
        message = json.dumps(payload, ensure_ascii=False) if payload else f"HTTP {status_code}"
        raw_type = ""

    anthropic_type = _ERROR_TYPE_MAP.get(raw_type) or _status_to_anthropic_type(status_code)
    return {
        "type": "error",
        "error": {"type": anthropic_type, "message": str(message)},
    }


def _status_to_anthropic_type(status_code: int) -> str:
    if status_code == 401:
        return "authentication_error"
    if status_code == 403:
        return "permission_error"
    if status_code == 404:
        return "not_found_error"
    if status_code == 429:
        return "rate_limit_error"
    if status_code == 503:
        return "overloaded_error"
    if status_code >= 500:
        return "api_error"
    if status_code >= 400:
        return "invalid_request_error"
    return "api_error"


def build_anthropic_error_response(
    message: str, status_code: int, error_type: str | None = None
) -> dict[str, Any]:
    err_type = error_type or _status_to_anthropic_type(status_code)
    return {
        "type": "error",
        "error": {"type": err_type, "message": message},
    }


# ---------------------------------------------------------------------------
# Streaming: OpenAI SSE -> Anthropic SSE
# ---------------------------------------------------------------------------


def _format_sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class AnthropicStreamTranslator:
    """Stateful translator from OpenAI SSE deltas to Anthropic SSE events.

    Anthropic stream model:
      message_start
      [content_block_start, content_block_delta+, content_block_stop]*
      message_delta (final stop_reason + output token count)
      message_stop
    """

    def __init__(self, requested_model: str, estimated_input_tokens: int = 0):
        self._model = requested_model
        self._msg_id = f"msg_{uuid.uuid4().hex[:24]}"
        self._started = False
        self._closed = False
        self._stop_reason = "end_turn"
        self._prompt_tokens = int(estimated_input_tokens or 0)
        self._completion_tokens = 0
        self._cache_creation_tokens = 0
        self._cache_read_tokens = 0

        self._current_block_type: str | None = None
        self._current_block_index = -1
        # Maps OpenAI tool_call index -> anthropic content_block index
        self._tool_block_index: dict[int, int] = {}
        # Tool meta cached per openai index (latest id/name)
        self._tool_meta: dict[int, dict[str, str]] = {}

    # -- Public emitters ---------------------------------------------------

    def message_start_event(self) -> list[str]:
        if self._started:
            return []
        self._started = True
        usage: dict[str, int] = {
            "input_tokens": self._prompt_tokens,
            "output_tokens": 0,
        }
        if self._cache_read_tokens:
            usage["cache_read_input_tokens"] = self._cache_read_tokens
        if self._cache_creation_tokens:
            usage["cache_creation_input_tokens"] = self._cache_creation_tokens
        payload = {
            "type": "message_start",
            "message": {
                "id": self._msg_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": self._model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": usage,
            },
        }
        return [_format_sse_event("message_start", payload)]

    def consume_openai_chunk(self, chunk: dict[str, Any]) -> list[str]:
        events: list[str] = []
        if not self._started:
            events.extend(self.message_start_event())

        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
            self._prompt_tokens = int(usage.get("prompt_tokens", self._prompt_tokens) or 0)
            self._completion_tokens = int(
                usage.get("completion_tokens", self._completion_tokens) or 0
            )
            details = usage.get("prompt_tokens_details") or {}
            if isinstance(details, dict):
                cached = details.get("cached_tokens")
                if cached:
                    self._cache_read_tokens = int(cached)

        choices = chunk.get("choices") or []
        if not choices:
            return events
        choice = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice.get("delta", {}) or {}
        finish_reason = choice.get("finish_reason")

        reasoning = delta.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            events.extend(self._emit_thinking_delta(reasoning))

        content = delta.get("content")
        if isinstance(content, str) and content:
            events.extend(self._emit_text_delta(content))
        elif isinstance(content, list):
            for sub in content:
                if isinstance(sub, dict) and sub.get("type") == "text":
                    text = sub.get("text", "")
                    if text:
                        events.extend(self._emit_text_delta(text))

        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if isinstance(tc, dict):
                    events.extend(self._emit_tool_call_delta(tc))

        if finish_reason:
            self._stop_reason = _finish_to_stop_reason(finish_reason)

        return events

    def close_events(self) -> list[str]:
        if self._closed:
            return []
        self._closed = True
        events: list[str] = []
        if not self._started:
            events.extend(self.message_start_event())
        events.extend(self._close_current_block())
        # message_delta carries cumulative usage; Anthropic spec allows
        # input_tokens here so clients can recover the prompt count even when
        # we did not know it at message_start time.
        delta_usage: dict[str, int] = {
            "input_tokens": self._prompt_tokens,
            "output_tokens": self._completion_tokens,
        }
        if self._cache_read_tokens:
            delta_usage["cache_read_input_tokens"] = self._cache_read_tokens
        if self._cache_creation_tokens:
            delta_usage["cache_creation_input_tokens"] = self._cache_creation_tokens
        events.append(
            _format_sse_event(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {
                        "stop_reason": self._stop_reason,
                        "stop_sequence": None,
                    },
                    "usage": delta_usage,
                },
            )
        )
        events.append(_format_sse_event("message_stop", {"type": "message_stop"}))
        return events

    def error_event(self, message: str, error_type: str = "api_error") -> str:
        return _format_sse_event(
            "error",
            {
                "type": "error",
                "error": {"type": error_type, "message": message},
            },
        )

    # -- Internals ---------------------------------------------------------

    def _emit_text_delta(self, text: str) -> list[str]:
        events: list[str] = []
        if self._current_block_type != "text":
            events.extend(self._open_block("text"))
        events.append(
            _format_sse_event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": self._current_block_index,
                    "delta": {"type": "text_delta", "text": text},
                },
            )
        )
        return events

    def _emit_thinking_delta(self, text: str) -> list[str]:
        events: list[str] = []
        if self._current_block_type != "thinking":
            events.extend(self._open_block("thinking"))
        events.append(
            _format_sse_event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": self._current_block_index,
                    "delta": {"type": "thinking_delta", "thinking": text},
                },
            )
        )
        return events

    def _emit_tool_call_delta(self, tc: dict[str, Any]) -> list[str]:
        events: list[str] = []
        openai_index = tc.get("index")
        if openai_index is None:
            openai_index = 0
        meta = self._tool_meta.setdefault(openai_index, {"id": "", "name": ""})
        if tc.get("id"):
            meta["id"] = tc["id"]
        func = tc.get("function") or {}
        if func.get("name"):
            meta["name"] = func["name"]

        if openai_index not in self._tool_block_index:
            events.extend(
                self._open_block(
                    "tool_use", tool_id=meta["id"], tool_name=meta["name"]
                )
            )
            self._tool_block_index[openai_index] = self._current_block_index

        args = func.get("arguments")
        if isinstance(args, str) and args:
            events.append(
                _format_sse_event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": self._tool_block_index[openai_index],
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": args,
                        },
                    },
                )
            )
        return events

    def _open_block(
        self,
        block_type: str,
        tool_id: str = "",
        tool_name: str = "",
    ) -> list[str]:
        events: list[str] = []
        events.extend(self._close_current_block())
        self._current_block_index += 1
        self._current_block_type = block_type
        if block_type == "text":
            block_descriptor: dict[str, Any] = {"type": "text", "text": ""}
        elif block_type == "thinking":
            block_descriptor = {"type": "thinking", "thinking": ""}
        elif block_type == "tool_use":
            block_descriptor = {
                "type": "tool_use",
                "id": tool_id,
                "name": tool_name,
                "input": {},
            }
        else:
            block_descriptor = {"type": block_type}
        events.append(
            _format_sse_event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": self._current_block_index,
                    "content_block": block_descriptor,
                },
            )
        )
        return events

    def _close_current_block(self) -> list[str]:
        if self._current_block_type is None:
            return []
        event = _format_sse_event(
            "content_block_stop",
            {
                "type": "content_block_stop",
                "index": self._current_block_index,
            },
        )
        self._current_block_type = None
        return [event]


async def translate_openai_sse_stream(
    source: AsyncIterator[bytes | str],
    requested_model: str,
    estimated_input_tokens: int = 0,
) -> AsyncIterator[bytes]:
    """Consume an OpenAI SSE byte/str stream and yield Anthropic SSE bytes."""
    translator = AnthropicStreamTranslator(
        requested_model, estimated_input_tokens=estimated_input_tokens
    )
    buffer = ""

    try:
        async for raw in source:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            buffer += raw
            while "\n\n" in buffer:
                event_block, buffer = buffer.split("\n\n", 1)
                for evt in _handle_openai_sse_block(event_block, translator):
                    yield evt.encode("utf-8")

        if buffer.strip():
            for evt in _handle_openai_sse_block(buffer, translator):
                yield evt.encode("utf-8")

        for evt in translator.close_events():
            yield evt.encode("utf-8")
    except Exception as exc:  # noqa: BLE001
        yield translator.error_event(str(exc)).encode("utf-8")


def _handle_openai_sse_block(
    block: str, translator: AnthropicStreamTranslator
) -> list[str]:
    out: list[str] = []
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            out.extend(translator.close_events())
            continue
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(chunk, dict) and "error" in chunk and "choices" not in chunk:
            err = chunk["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            error_type = err.get("type", "api_error") if isinstance(err, dict) else "api_error"
            out.append(translator.error_event(str(message), error_type))
            continue
        if isinstance(chunk, dict):
            out.extend(translator.consume_openai_chunk(chunk))
    return out
