"""Translate OpenAI Responses API requests into chat completions, and back.

This is the Responses counterpart to ``services/anthropic_inbound.py``:

* Inbound: convert ``POST /v1/responses`` bodies from clients (Codex CLI etc.)
  into OpenAI chat-completions bodies so the existing proxy pipeline (auth,
  busyness, semaphores, stats, logging, provider adapters) is reused unchanged.
* Outbound: convert the chat-completions response (regular JSON or SSE) back
  into Responses format, including the streaming event state machine.

The gateway is stateless: ``store`` / ``previous_response_id`` are dropped and
reasoning items are not replayed; clients keep history client-side (Codex
defaults to ``store=false``).
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator

from app.core.config import error_logger


# ---------------------------------------------------------------------------
# Request: Responses -> OpenAI chat completions
# ---------------------------------------------------------------------------


def responses_to_openai_request(body: dict[str, Any]) -> dict[str, Any]:
    """Convert a ``POST /v1/responses`` body to a chat-completions body.

    Raises ``ValueError`` for request-level problems that map to HTTP 400.
    """
    model = body.get("model")
    if not model or not isinstance(model, str):
        raise ValueError("Missing or invalid 'model' field")

    openai_body: dict[str, Any] = {"model": model}

    if "max_output_tokens" in body:
        openai_body["max_tokens"] = body["max_output_tokens"]
    for key in ("temperature", "top_p", "parallel_tool_calls", "service_tier"):
        if key in body:
            openai_body[key] = body[key]
    if "stream" in body:
        openai_body["stream"] = body["stream"]
    if body.get("stream"):
        openai_body["stream_options"] = {"include_usage": True}

    metadata = body.get("metadata")
    if isinstance(metadata, dict) and metadata.get("user"):
        openai_body["user"] = metadata["user"]

    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("effort"):
        effort = str(reasoning["effort"])
        # "max" is not accepted by OpenAI-compatible upstreams (vLLM rejects it);
        # normalize to the closest supported tier.
        openai_body["reasoning_effort"] = "high" if effort == "max" else effort

    text = body.get("text")
    if isinstance(text, dict):
        if text.get("verbosity"):
            openai_body["verbosity"] = text["verbosity"]
        fmt = text.get("format")
        if isinstance(fmt, dict):
            response_format = _convert_text_format(fmt)
            if response_format:
                openai_body["response_format"] = response_format

    messages: list[dict[str, Any]] = []
    instructions = body.get("instructions") or body.get("prompt")
    if isinstance(instructions, str) and instructions:
        messages.append({"role": "system", "content": instructions})

    input_value = body.get("input")
    if isinstance(input_value, str):
        messages.append({"role": "user", "content": input_value})
    elif isinstance(input_value, list):
        for item in input_value:
            _convert_input_item(item, messages)

    if not any(m.get("role") != "system" for m in messages):
        raise ValueError(
            "Field 'input' must contain at least one user/assistant message"
        )
    openai_body["messages"] = messages

    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        converted = [
            t for t in (_convert_responses_tool(tool) for tool in tools) if t
        ]
        if converted:
            openai_body["tools"] = converted
        else:
            error_logger.warning("[RESPONSES INBOUND] all tools dropped during translation")

    tool_choice = _convert_tool_choice(body.get("tool_choice"))
    if tool_choice is not None:
        openai_body["tool_choice"] = tool_choice

    return openai_body


def _convert_input_item(item: Any, messages: list[dict[str, Any]]) -> None:
    if not isinstance(item, dict):
        return
    item_type = item.get("type", "message")

    if item_type == "message":
        role = item.get("role", "user")
        target_role = "assistant" if role == "assistant" else (
            "system" if role in ("system", "developer") else "user"
        )
        content = _convert_message_content(item.get("content", ""))
        messages.append({"role": target_role, "content": content})

    elif item_type == "function_call":
        tool_call = {
            "id": item.get("call_id") or item.get("id") or "",
            "type": "function",
            "function": {
                "name": item.get("name", ""),
                "arguments": item.get("arguments", "") or "",
            },
        }
        last = messages[-1] if messages else None
        if isinstance(last, dict) and last.get("role") == "assistant" and "tool_calls" in last:
            last["tool_calls"].append(tool_call)
        else:
            messages.append(
                {"role": "assistant", "content": "", "tool_calls": [tool_call]}
            )

    elif item_type == "function_call_output":
        content = _convert_tool_output(item.get("output", ""))
        messages.append(
            {
                "role": "tool",
                "tool_call_id": item.get("call_id", ""),
                "content": content,
            }
        )

    elif item_type == "reasoning":
        # Stateless gateway: nothing to replay.
        return

    elif item_type == "item_reference":
        raise ValueError(
            "item_reference cannot be replayed on a stateless gateway; "
            "send full items in input instead"
        )

    # Unknown item types: drop, stay forward compatible.


def _convert_message_content(content: Any) -> Any:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    texts: list[str] = []
    parts: list[dict[str, Any]] = []
    has_image = False
    for block in content:
        if isinstance(block, str):
            if block:
                texts.append(block)
                parts.append({"type": "text", "text": block})
            continue
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type in ("input_text", "output_text", "text", "summary_text"):
            text = block.get("text", "")
            texts.append(text)
            parts.append({"type": "text", "text": text})
        elif block_type == "input_image":
            url = block.get("image_url")
            if isinstance(url, dict):
                url = url.get("url")
            if url:
                image_part: dict[str, Any] = {"type": "image_url", "image_url": {"url": url}}
                if block.get("detail"):
                    image_part["image_url"]["detail"] = block["detail"]
                parts.append(image_part)
                has_image = True
        # input_file / unknown blocks: drop
    if has_image:
        return parts
    return "\n".join(t for t in texts if t)


def _convert_tool_output(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts = []
        for block in output:
            if isinstance(block, dict) and block.get("type") in (
                "output_text", "input_text", "text", "summary_text",
            ):
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return json.dumps(output, ensure_ascii=False)


def _convert_responses_tool(tool: Any) -> dict[str, Any] | None:
    if not isinstance(tool, dict):
        return None
    if tool.get("type") != "function":
        # local_shell / web_search / custom freeform tools are not supported
        # by chat-completions upstreams; drop them.
        return None
    function: dict[str, Any] = {
        "name": tool.get("name", ""),
        "description": tool.get("description", ""),
    }
    parameters = tool.get("parameters")
    if isinstance(parameters, dict) and parameters:
        function["parameters"] = parameters
    else:
        function["parameters"] = {"type": "object", "properties": {}}
    if tool.get("strict") is not None:
        function["strict"] = tool["strict"]
    return {"type": "function", "function": function}


def _convert_tool_choice(choice: Any) -> Any:
    if isinstance(choice, str) and choice in ("auto", "none", "required"):
        return choice
    if (
        isinstance(choice, dict)
        and choice.get("type") == "function"
        and choice.get("name")
    ):
        return {"type": "function", "function": {"name": choice["name"]}}
    return None


def _convert_text_format(fmt: dict[str, Any]) -> dict[str, Any] | None:
    format_type = fmt.get("type")
    if format_type == "json_schema":
        json_schema: dict[str, Any] = {
            "name": fmt.get("name") or "response",
            "schema": fmt.get("schema") or {"type": "object", "properties": {}},
        }
        if fmt.get("strict") is not None:
            json_schema["strict"] = fmt["strict"]
        if fmt.get("description"):
            json_schema["description"] = fmt["description"]
        return {"type": "json_schema", "json_schema": json_schema}
    if format_type == "json_object":
        return {"type": "json_object"}
    return None


# ---------------------------------------------------------------------------
# Response: OpenAI chat completions -> Responses (non-streaming)
# ---------------------------------------------------------------------------


def _convert_usage(usage_in: Any) -> dict[str, Any]:
    usage_in = usage_in if isinstance(usage_in, dict) else {}
    input_tokens = int(usage_in.get("prompt_tokens", 0) or 0)
    output_tokens = int(usage_in.get("completion_tokens", 0) or 0)
    total = int(usage_in.get("total_tokens", 0) or 0) or (input_tokens + output_tokens)

    usage_out: dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
    }
    prompt_details = usage_in.get("prompt_tokens_details")
    if isinstance(prompt_details, dict) and prompt_details.get("cached_tokens"):
        usage_out["input_tokens_details"] = {
            "cached_tokens": int(prompt_details["cached_tokens"])
        }
    completion_details = usage_in.get("completion_tokens_details")
    if isinstance(completion_details, dict) and completion_details.get("reasoning_tokens"):
        usage_out["output_tokens_details"] = {
            "reasoning_tokens": int(completion_details["reasoning_tokens"])
        }
    return usage_out


def _extract_assistant_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return ""


def openai_to_responses_response(
    resp: dict[str, Any], requested_model: str
) -> dict[str, Any]:
    """Convert a chat-completions response payload to a Responses response object."""
    output: list[dict[str, Any]] = []
    finish_reason: str | None = None

    choices = resp.get("choices") or []
    if choices and isinstance(choices[0], dict):
        choice = choices[0]
        message = choice.get("message") or {}
        finish_reason = choice.get("finish_reason")

        reasoning = message.get("reasoning_content") or message.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            output.append(
                {
                    "type": "reasoning",
                    "id": "rs_" + uuid.uuid4().hex[:24],
                    "summary": [{"type": "summary_text", "text": reasoning}],
                }
            )

        text = _extract_assistant_text(message.get("content"))
        if text:
            output.append(
                {
                    "type": "message",
                    "id": "msg_" + uuid.uuid4().hex[:24],
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": text, "annotations": []}
                    ],
                }
            )

        for tc in message.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            func = tc.get("function") or {}
            output.append(
                {
                    "type": "function_call",
                    "id": "fc_" + uuid.uuid4().hex[:24],
                    "call_id": tc.get("id", ""),
                    "name": func.get("name", ""),
                    "arguments": func.get("arguments", "") or "",
                    "status": "completed",
                }
            )

    status = "completed"
    incomplete_details: dict[str, Any] | None = None
    if finish_reason == "length":
        status = "incomplete"
        incomplete_details = {"reason": "max_output_tokens"}
    elif finish_reason == "content_filter":
        status = "incomplete"
        incomplete_details = {"reason": "content_filter"}

    return {
        "id": "resp_" + uuid.uuid4().hex[:24],
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "incomplete_details": incomplete_details,
        "model": resp.get("model") or requested_model,
        "output": output,
        "usage": _convert_usage(resp.get("usage")),
        "error": None,
        "temperature": None,
        "top_p": None,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def openai_to_responses_error(
    payload: dict[str, Any], status_code: int
) -> dict[str, Any]:
    error_obj = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error_obj, dict):
        message = (
            error_obj.get("message")
            or error_obj.get("detail")
            or json.dumps(error_obj, ensure_ascii=False)
        )
        error_type = error_obj.get("type")
        code = error_obj.get("code")
        param = error_obj.get("param")
    elif isinstance(error_obj, str):
        message, error_type, code, param = error_obj, None, None, None
    else:
        message = (
            json.dumps(payload, ensure_ascii=False)
            if payload
            else f"HTTP {status_code}"
        )
        error_type, code, param = None, None, None

    fallback_type, fallback_code = _status_to_responses_error(status_code)
    return {
        "error": {
            "message": str(message),
            "type": error_type or fallback_type,
            "code": code or fallback_code,
            "param": param,
        }
    }


def _status_to_responses_error(status_code: int) -> tuple[str, str | None]:
    if status_code == 401:
        return "invalid_request_error", "invalid_api_key"
    if status_code == 404:
        return "invalid_request_error", "not_found"
    if status_code == 429:
        return "rate_limit_error", None
    if status_code >= 500:
        return "server_error", None
    return "invalid_request_error", None


def build_responses_error(
    message: str,
    status_code: int,
    error_type: str | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    fallback_type, fallback_code = _status_to_responses_error(status_code)
    return {
        "error": {
            "message": message,
            "type": error_type or fallback_type,
            "code": code or fallback_code,
            "param": None,
        }
    }


# ---------------------------------------------------------------------------
# Streaming: OpenAI chat SSE -> Responses event stream
# ---------------------------------------------------------------------------


def _format_sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class ResponsesStreamTranslator:
    """Stateful translator from OpenAI chat SSE chunks to Responses events.

    Event lifecycle:
      response.created / response.in_progress
      [output_item.added, (content_part.added | function_call_arguments.delta)+,
       (output_text.delta)*, ..., output_item.done]*
      response.completed | response.incomplete | response.failed
    """

    def __init__(self, requested_model: str):
        self._model = requested_model
        self._resp_id = "resp_" + uuid.uuid4().hex[:24]
        self._created_at = int(time.time())
        self._seq = 0

        self._started = False
        self._finished = False
        self._usage: dict[str, Any] | None = None
        self._finish_reason: str | None = None
        self._reasoning_text = ""

        self._output_items: list[dict[str, Any]] = []  # sealed items
        self._msg_state: dict[str, Any] | None = None  # in-flight message item
        self._tool_states: dict[int, dict[str, Any]] = {}  # openai index -> state

    # -- Public API --------------------------------------------------------

    def start_events(self) -> list[str]:
        if self._started:
            return []
        self._started = True
        return [
            self._event(
                "response.created",
                {"response": self._response_shell()},
            ),
            self._event(
                "response.in_progress",
                {"response": self._response_shell()},
            ),
        ]

    def consume_openai_chunk(self, chunk: dict[str, Any]) -> list[str]:
        events: list[str] = []
        if not self._started:
            events.extend(self.start_events())

        # Upstream error chunk: terminal failure (choices never accompany it).
        if "error" in chunk and "choices" not in chunk:
            err = chunk["error"]
            message = (
                err.get("message") if isinstance(err, dict) else str(err)
            )
            events.extend(self.fail_events(str(message or "upstream error")))
            return events

        if isinstance(chunk.get("usage"), dict):
            self._usage = _convert_usage(chunk["usage"])

        choices = chunk.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return events
        choice = choices[0]
        delta = choice.get("delta") or {}
        finish_reason = choice.get("finish_reason")
        if finish_reason:
            self._finish_reason = finish_reason

        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            self._reasoning_text += reasoning

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
                    events.extend(self._emit_tool_delta(tc))

        return events

    def close_events(self) -> list[str]:
        if self._finished:
            return []
        events: list[str] = []
        if not self._started:
            events.extend(self.start_events())
        events.extend(self._seal_open_items(emit_events=True))

        final_type = "response.completed"
        status = "completed"
        incomplete_details = None
        if self._finish_reason == "length":
            final_type = "response.incomplete"
            status = "incomplete"
            incomplete_details = {"reason": "max_output_tokens"}
        elif self._finish_reason == "content_filter":
            final_type = "response.incomplete"
            status = "incomplete"
            incomplete_details = {"reason": "content_filter"}

        response = self._build_final_response(status, incomplete_details)
        events.append(self._event(final_type, {"response": response}))
        self._finished = True
        return events

    def fail_events(self, message: str, code: str = "server_error") -> list[str]:
        if self._finished:
            return []
        events: list[str] = []
        if not self._started:
            events.extend(self.start_events())
        # Seal in-flight items silently so partial content is still available
        # in the final response object, but per spec emit no item-level events.
        self._seal_open_items(emit_events=False)

        response = self._build_final_response("failed", None)
        response["error"] = {"code": code, "message": message}
        events.append(self._event("response.failed", {"response": response}))
        self._finished = True
        return events

    # -- Internals ---------------------------------------------------------

    def _event(self, event_type: str, payload: dict[str, Any]) -> str:
        data = dict(payload)
        data["type"] = event_type
        data["sequence_number"] = self._seq
        self._seq += 1
        return _format_sse_event(event_type, data)

    def _response_shell(self, status: str = "in_progress") -> dict[str, Any]:
        return {
            "id": self._resp_id,
            "object": "response",
            "created_at": self._created_at,
            "status": status,
            "model": self._model,
            "output": [dict(item) for item in self._output_items],
            "error": None,
            "usage": None,
            "incomplete_details": None,
        }

    def _build_final_response(
        self, status: str, incomplete_details: dict[str, Any] | None
    ) -> dict[str, Any]:
        if self._reasoning_text:
            self._output_items.insert(
                0,
                {
                    "type": "reasoning",
                    "id": "rs_" + uuid.uuid4().hex[:24],
                    "summary": [
                        {"type": "summary_text", "text": self._reasoning_text}
                    ],
                },
            )
        response = self._response_shell(status)
        response["usage"] = self._usage or _convert_usage({})
        response["incomplete_details"] = incomplete_details
        return response

    def _emit_text_delta(self, text: str) -> list[str]:
        events: list[str] = []
        if self._msg_state is None:
            item_id = "msg_" + uuid.uuid4().hex[:24]
            output_index = len(self._output_items) + len(self._tool_states) + (
                1 if self._msg_state else 0
            )
            self._msg_state = {"item_id": item_id, "output_index": output_index, "text": ""}
            events.append(
                self._event(
                    "response.output_item.added",
                    {
                        "output_index": output_index,
                        "item": {
                            "type": "message",
                            "id": item_id,
                            "role": "assistant",
                            "status": "in_progress",
                            "content": [],
                        },
                    },
                )
            )
            events.append(
                self._event(
                    "response.content_part.added",
                    {
                        "item_id": item_id,
                        "output_index": output_index,
                        "content_index": 0,
                        "part": {"type": "output_text", "text": "", "annotations": []},
                    },
                )
            )
        state = self._msg_state
        state["text"] += text
        events.append(
            self._event(
                "response.output_text.delta",
                {
                    "item_id": state["item_id"],
                    "output_index": state["output_index"],
                    "content_index": 0,
                    "delta": text,
                },
            )
        )
        return events

    def _emit_tool_delta(self, tc: dict[str, Any]) -> list[str]:
        events: list[str] = []
        openai_index = tc.get("index")
        if not isinstance(openai_index, int):
            openai_index = 0

        state = self._tool_states.get(openai_index)
        if state is None:
            item_id = "fc_" + uuid.uuid4().hex[:24]
            output_index = len(self._output_items) + len(self._tool_states) + (
                1 if self._msg_state else 0
            )
            state = {
                "item_id": item_id,
                "output_index": output_index,
                "call_id": tc.get("id") or "call_" + uuid.uuid4().hex[:24],
                "name": "",
                "arguments": "",
            }
            self._tool_states[openai_index] = state
            events.append(
                self._event(
                    "response.output_item.added",
                    {
                        "output_index": output_index,
                        "item": {
                            "type": "function_call",
                            "id": item_id,
                            "call_id": state["call_id"],
                            "name": "",
                            "arguments": "",
                            "status": "in_progress",
                        },
                    },
                )
            )
        else:
            if tc.get("id"):
                state["call_id"] = tc["id"]

        func = tc.get("function") or {}
        if func.get("name"):
            state["name"] = func["name"]

        args = func.get("arguments")
        if isinstance(args, str) and args:
            state["arguments"] += args
            events.append(
                self._event(
                    "response.function_call_arguments.delta",
                    {
                        "item_id": state["item_id"],
                        "output_index": state["output_index"],
                        "delta": args,
                    },
                )
            )
        return events

    def _seal_open_items(self, emit_events: bool) -> list[str]:
        events: list[str] = []

        open_items: list[tuple[int, str, dict[str, Any]]] = []
        if self._msg_state is not None:
            open_items.append(
                (self._msg_state["output_index"], "message", self._msg_state)
            )
        for state in self._tool_states.values():
            open_items.append((state["output_index"], "function_call", state))
        open_items.sort(key=lambda entry: entry[0])

        for _output_index, item_type, state in open_items:
            if item_type == "message":
                if emit_events:
                    events.append(
                        self._event(
                            "response.output_text.done",
                            {
                                "item_id": state["item_id"],
                                "output_index": state["output_index"],
                                "content_index": 0,
                                "text": state["text"],
                            },
                        )
                    )
                    events.append(
                        self._event(
                            "response.content_part.done",
                            {
                                "item_id": state["item_id"],
                                "output_index": state["output_index"],
                                "content_index": 0,
                                "part": {
                                    "type": "output_text",
                                    "text": state["text"],
                                    "annotations": [],
                                },
                            },
                        )
                    )
                item = {
                    "type": "message",
                    "id": state["item_id"],
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": state["text"], "annotations": []}
                    ],
                }
                if emit_events:
                    events.append(
                        self._event(
                            "response.output_item.done",
                            {"output_index": state["output_index"], "item": item},
                        )
                    )
                self._output_items.append(item)
            else:
                item = {
                    "type": "function_call",
                    "id": state["item_id"],
                    "call_id": state["call_id"],
                    "name": state["name"],
                    "arguments": state["arguments"],
                    "status": "completed",
                }
                if emit_events:
                    events.append(
                        self._event(
                            "response.function_call_arguments.done",
                            {
                                "item_id": state["item_id"],
                                "output_index": state["output_index"],
                                "arguments": state["arguments"],
                            },
                        )
                    )
                    events.append(
                        self._event(
                            "response.output_item.done",
                            {"output_index": state["output_index"], "item": item},
                        )
                    )
                self._output_items.append(item)

        self._msg_state = None
        self._tool_states = {}
        return events


async def translate_openai_sse_to_responses(
    source: AsyncIterator[bytes | str],
    requested_model: str,
) -> AsyncIterator[bytes]:
    """Consume an OpenAI chat SSE byte/str stream and yield Responses SSE bytes."""
    translator = ResponsesStreamTranslator(requested_model)
    buffer = ""

    try:
        async for raw in source:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            buffer += raw
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                for event in _handle_openai_sse_block(block, translator):
                    yield event.encode("utf-8")

        if buffer.strip():
            for event in _handle_openai_sse_block(buffer, translator):
                yield event.encode("utf-8")

        for event in translator.close_events():
            yield event.encode("utf-8")
    except Exception as exc:  # noqa: BLE001
        error_logger.error(f"[RESPONSES INBOUND] stream translation failed: {exc}")
        for event in translator.fail_events("请求处理失败，请稍后重试"):
            yield event.encode("utf-8")


def _handle_openai_sse_block(
    block: str, translator: ResponsesStreamTranslator
) -> list[str]:
    out: list[str] = []
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            out.extend(translator.close_events())
            continue
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(chunk, dict):
            out.extend(translator.consume_openai_chunk(chunk))
    return out
