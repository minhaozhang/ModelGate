from __future__ import annotations

import json
import time
import uuid

import core.config as config

from services.proxy_runtime.adapters.base import ProviderAdapter


ANTHROPIC_VERSION = "2023-06-01"


class AnthropicAdapter(ProviderAdapter):
    name = "anthropic"

    def build_headers(
        self, provider_config: dict, api_key: str | None = None
    ) -> dict[str, str]:
        key = api_key or provider_config.get("api_key") or ""
        headers = {
            "content-type": "application/json",
            "user-agent": config.OUTBOUND_USER_AGENT,
            "connection": "keep-alive",
            "accept": "*/*",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if key:
            headers["x-api-key"] = key
        return headers

    def get_target_path(self, endpoint: str) -> str:
        if endpoint.endswith("/chat/completions"):
            return "/v1/messages"
        return endpoint

    def transform_request(self, body: dict, provider_config: dict) -> dict:
        anthropic_body: dict = {}
        model = body.get("model", "")
        anthropic_body["model"] = model
        if "max_tokens" in body:
            anthropic_body["max_tokens"] = body["max_tokens"]
        else:
            anthropic_body["max_tokens"] = 4096
        if "temperature" in body:
            anthropic_body["temperature"] = body["temperature"]
        if "top_p" in body:
            anthropic_body["top_p"] = body["top_p"]
        if "top_k" in body:
            anthropic_body["top_k"] = body["top_k"]
        if "stop" in body:
            anthropic_body["stop_sequences"] = (
                body["stop"]
                if isinstance(body["stop"], list)
                else [body["stop"]]
            )
        thinking = body.get("thinking")
        if isinstance(thinking, dict):
            anthropic_body["thinking"] = thinking

        messages = body.get("messages", [])
        system_parts: list[dict] = []
        anthropic_messages: list[dict] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            text = block.get("text", "")
                            if text:
                                entry: dict = {"type": "text", "text": text}
                                if block.get("cache_control"):
                                    entry["cache_control"] = block["cache_control"]
                                system_parts.append(entry)
                        elif isinstance(block, str) and block:
                            system_parts.append({"type": "text", "text": block})
                elif isinstance(content, str) and content:
                    system_parts.append({"type": "text", "text": content})
                continue

            if role == "user":
                new_content = self._convert_content(content)
                # Merge into the previous user message if there is one. This
                # collapses (tool_result_user, text_user) pairs that the
                # inbound translator emits — Anthropic rejects consecutive
                # same-role messages.
                if (
                    anthropic_messages
                    and anthropic_messages[-1].get("role") == "user"
                    and isinstance(anthropic_messages[-1].get("content"), list)
                ):
                    anthropic_messages[-1]["content"].extend(new_content)
                else:
                    anthropic_messages.append(
                        {"role": role, "content": new_content}
                    )
            elif role == "assistant":
                rsig = msg.get("reasoning_signature")
                if isinstance(rsig, list):
                    sig_data = rsig
                elif isinstance(rsig, str) and rsig:
                    # Legacy single-signature format
                    sig_data = [("", rsig)]
                else:
                    sig_data = None
                assistant_content = self._convert_content(
                    content, reasoning_signature=sig_data
                )
                # If reasoning_content is stored on the message but no
                # thinking blocks were in the content array, reconstruct them.
                if not any(
                    isinstance(b, dict) and b.get("type") == "thinking"
                    for b in (content if isinstance(content, list) else [])
                ):
                    rc = msg.get("reasoning_content")
                    if rc:
                        tb: dict = {"type": "thinking", "thinking": rc}
                        if sig_data and sig_data[0][1]:
                            tb["signature"] = sig_data[0][1]
                        assistant_content.insert(0, tb)
                assistant_content.extend(
                    self._convert_assistant_tool_calls(msg.get("tool_calls"))
                )
                anthropic_messages.append(
                    {"role": role, "content": assistant_content}
                )
            elif role == "tool":
                tool_result_content: list[dict] = []
                if isinstance(content, str):
                    tool_result_content.append(
                        {"type": "text", "text": content}
                    )
                elif isinstance(content, list):
                    tool_result_content = content
                tool_result_block: dict = {
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": tool_result_content,
                }
                if msg.get("cache_control"):
                    tool_result_block["cache_control"] = msg["cache_control"]
                if msg.get("is_error"):
                    tool_result_block["is_error"] = True
                if anthropic_messages and anthropic_messages[-1].get("role") == "user":
                    existing = anthropic_messages[-1].get("content", [])
                    if isinstance(existing, list):
                        existing.append(tool_result_block)
                        anthropic_messages[-1]["content"] = existing
                else:
                    anthropic_messages.append(
                        {"role": "user", "content": [tool_result_block]}
                    )

        if system_parts:
            anthropic_body["system"] = system_parts
        anthropic_body["messages"] = anthropic_messages

        if "stream" in body:
            anthropic_body["stream"] = body["stream"]

        tools = body.get("tools")
        if tools:
            anthropic_body["tools"] = [
                self._convert_tool_openai_to_anthropic(t) for t in tools
            ]
        if "tool_choice" in body:
            anthropic_body["tool_choice"] = self._convert_tool_choice(
                body["tool_choice"]
            )
        if body.get("parallel_tool_calls") is False:
            tc = anthropic_body.get("tool_choice")
            if isinstance(tc, dict):
                tc["disable_parallel_tool_use"] = True
            else:
                anthropic_body["tool_choice"] = {
                    "type": "auto",
                    "disable_parallel_tool_use": True,
                }

        return anthropic_body

    def _convert_assistant_tool_calls(self, tool_calls) -> list[dict]:
        if not isinstance(tool_calls, list):
            return []

        result: list[dict] = []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function", {})
            arguments = function.get("arguments", "{}")
            if isinstance(arguments, str):
                try:
                    parsed_arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    parsed_arguments = {"raw_arguments": arguments}
            elif isinstance(arguments, dict):
                parsed_arguments = arguments
            else:
                parsed_arguments = {}

            result.append(
                {
                    "type": "tool_use",
                    "id": tool_call.get("id", ""),
                    "name": function.get("name", ""),
                    "input": parsed_arguments,
                }
            )
        return result

    def _convert_content(
        self,
        content,
        reasoning_signature: list[tuple[str, str]] | None = None,
    ) -> list[dict]:
        if isinstance(content, str):
            if content:
                return [{"type": "text", "text": content}]
            return []
        if isinstance(content, list):
            result: list[dict] = []
            sig_idx = 0
            for block in content:
                if isinstance(block, str):
                    if block:
                        result.append({"type": "text", "text": block})
                elif isinstance(block, dict):
                    block_type = block.get("type", "")
                    if block_type == "text":
                        entry: dict = {"type": "text", "text": block.get("text", "")}
                        if block.get("cache_control"):
                            entry["cache_control"] = block["cache_control"]
                        result.append(entry)
                    elif block_type == "image_url":
                        url = block.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            parts = url.split(",", 1)
                            media_type = parts[0].split(";")[0].split(":")[1]
                            data = parts[1] if len(parts) > 1 else ""
                            img: dict = {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": data,
                                },
                            }
                        else:
                            img = {
                                "type": "image",
                                "source": {
                                    "type": "url",
                                    "url": url,
                                },
                            }
                        if block.get("cache_control"):
                            img["cache_control"] = block["cache_control"]
                        result.append(img)
                    elif block_type == "thinking":
                        tb: dict = {
                            "type": "thinking",
                            "thinking": block.get("thinking", ""),
                        }
                        if reasoning_signature and sig_idx < len(reasoning_signature):
                            _, sig = reasoning_signature[sig_idx]
                            if sig:
                                tb["signature"] = sig
                            sig_idx += 1
                        result.append(tb)
            return result
        return []

    def _convert_tool_openai_to_anthropic(self, tool: dict) -> dict:
        func = tool.get("function", {})
        return {
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
        }

    def _convert_tool_choice(self, choice) -> dict:
        if isinstance(choice, str):
            if choice == "auto":
                return {"type": "auto"}
            if choice == "none":
                return {"type": "none"}
            if choice == "required":
                return {"type": "any"}
        if isinstance(choice, dict):
            func = choice.get("function", {})
            return {
                "type": "tool",
                "name": func.get("name", ""),
            }
        return {"type": "auto"}

    def transform_response(self, resp_json: dict) -> dict:
        openai_resp: dict = {
            "id": resp_json.get("id", f"chatcmpl-{uuid.uuid4().hex[:12]}"),
            "object": "chat.completion",
            "created": resp_json.get("created", int(time.time())),
            "model": resp_json.get("model", ""),
        }

        content_blocks = resp_json.get("content", [])
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[dict] = []

        for block in content_blocks:
            block_type = block.get("type", "")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "thinking":
                reasoning_parts.append(block.get("thinking", ""))
            elif block_type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(
                                block.get("input", {}),
                                ensure_ascii=False,
                            ),
                        },
                    }
                )

        message: dict = {
            "role": "assistant",
            "content": "".join(text_parts) or None,
        }
        if reasoning_parts:
            message["reasoning_content"] = "".join(reasoning_parts)
        if tool_calls:
            message["tool_calls"] = tool_calls

        stop_reason = resp_json.get("stop_reason", "")
        finish_reason = self._convert_stop_reason(stop_reason)

        openai_resp["choices"] = [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ]

        usage = resp_json.get("usage", {}) or {}
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        usage_out: dict = {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        cache_read = usage.get("cache_read_input_tokens")
        cache_creation = usage.get("cache_creation_input_tokens")
        if cache_read:
            usage_out["cache_read_input_tokens"] = int(cache_read)
            usage_out.setdefault("prompt_tokens_details", {})["cached_tokens"] = int(cache_read)
        if cache_creation:
            usage_out["cache_creation_input_tokens"] = int(cache_creation)
        openai_resp["usage"] = usage_out

        return openai_resp

    def _convert_stop_reason(self, stop_reason: str) -> str:
        mapping = {
            "end_turn": "stop",
            "max_tokens": "length",
            "stop_sequence": "stop",
            "tool_use": "tool_calls",
        }
        return mapping.get(stop_reason, stop_reason)

    def transform_error_response(self, resp_json: dict, status_code: int) -> dict:
        error = resp_json.get("error", {})
        if isinstance(error, dict):
            return {
                "error": {
                    "message": error.get("message", str(resp_json)),
                    "type": error.get("type", "api_error"),
                    "code": str(status_code),
                }
            }
        return {
            "error": {
                "message": str(resp_json),
                "type": "api_error",
                "code": str(status_code),
            }
        }

    def create_stream_context(self) -> dict:
        return {
            "msg_id": "",
            "model": "",
            "created": 0,
            "current_tool_index": 0,
            "current_tool_id": "",
            "current_tool_name": "",
            "current_tool_args": "",
            "in_tool_use": False,
            "usage": None,
        }

    async def transform_stream_chunk(
        self, raw_line: str, context: dict
    ) -> list[str]:
        if not raw_line.startswith("data: "):
            return []
        data = raw_line[6:].strip()
        if not data:
            return []

        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            return []

        event_type = event.get("type", "")
        results: list[str] = []

        if event_type == "error":
            error_obj = event.get("error", {})
            error_msg = error_obj.get("message", str(event)) if isinstance(error_obj, dict) else str(event)
            raise Exception(f"Anthropic API error: {error_msg}")

        if event_type == "message_start":
            msg = event.get("message", {})
            context["msg_id"] = msg.get("id", f"chatcmpl-{uuid.uuid4().hex[:12]}")
            context["model"] = msg.get("model", "")
            context["created"] = int(time.time())
            context["usage"] = msg.get("usage")

        elif event_type == "content_block_start":
            block = event.get("content_block", {})
            block_type = block.get("type", "")
            if block_type == "tool_use":
                context["in_tool_use"] = True
                context["current_tool_id"] = block.get("id", "")
                context["current_tool_name"] = block.get("name", "")
                context["current_tool_args"] = ""
                context["current_tool_index"] += 1
                chunk = self._build_openai_stream_chunk(
                    context,
                    delta={
                        "tool_calls": [
                            {
                                "index": context["current_tool_index"] - 1,
                                "id": context["current_tool_id"],
                                "type": "function",
                                "function": {
                                    "name": context["current_tool_name"],
                                    "arguments": "",
                                },
                            }
                        ]
                    },
                )
                results.append(f"data: {json.dumps(chunk)}\n\n")

        elif event_type == "content_block_delta":
            delta = event.get("delta", {})
            delta_type = delta.get("type", "")
            if delta_type == "text_delta":
                text = delta.get("text", "")
                chunk = self._build_openai_stream_chunk(
                    context,
                    delta={"content": text},
                )
                results.append(f"data: {json.dumps(chunk)}\n\n")
            elif delta_type == "thinking_delta":
                thinking = delta.get("thinking", "")
                chunk = self._build_openai_stream_chunk(
                    context,
                    delta={"reasoning_content": thinking},
                )
                results.append(f"data: {json.dumps(chunk)}\n\n")
            elif delta_type == "input_json_delta":
                partial_json = delta.get("partial_json", "")
                context["current_tool_args"] += partial_json
                chunk = self._build_openai_stream_chunk(
                    context,
                    delta={
                        "tool_calls": [
                            {
                                "index": context["current_tool_index"] - 1,
                                "function": {
                                    "arguments": partial_json,
                                },
                            }
                        ]
                    },
                )
                results.append(f"data: {json.dumps(chunk)}\n\n")

        elif event_type == "content_block_stop":
            context["in_tool_use"] = False

        elif event_type == "message_delta":
            delta = event.get("delta", {})
            stop_reason = delta.get("stop_reason", "")
            usage_delta = event.get("usage", {})
            if usage_delta:
                prev = context.get("usage") or {}
                merged_usage: dict = {
                    "input_tokens": usage_delta.get(
                        "input_tokens", prev.get("input_tokens", 0)
                    ),
                    "output_tokens": usage_delta.get(
                        "output_tokens", prev.get("output_tokens", 0)
                    ),
                }
                for key in (
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                ):
                    val = usage_delta.get(key) or prev.get(key)
                    if val:
                        merged_usage[key] = val
                context["usage"] = merged_usage
            finish_reason = self._convert_stop_reason(stop_reason) if stop_reason else None
            chunk = self._build_openai_stream_chunk(
                context,
                delta={},
                finish_reason=finish_reason,
                usage=self._convert_usage(context.get("usage")),
            )
            results.append(f"data: {json.dumps(chunk)}\n\n")

        return results

    def _build_openai_stream_chunk(
        self,
        context: dict,
        delta: dict | None = None,
        finish_reason: str | None = None,
        usage: dict | None = None,
    ) -> dict:
        chunk: dict = {
            "id": context.get("msg_id", ""),
            "object": "chat.completion.chunk",
            "created": context.get("created", 0),
            "model": context.get("model", ""),
            "choices": [
                {
                    "index": 0,
                    "delta": delta or {},
                    "finish_reason": finish_reason,
                }
            ],
        }
        if usage:
            chunk["usage"] = usage
        return chunk

    def _convert_usage(self, usage: dict | None) -> dict | None:
        if not usage:
            return None
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        out: dict = {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        cache_read = usage.get("cache_read_input_tokens")
        cache_creation = usage.get("cache_creation_input_tokens")
        if cache_read:
            out["cache_read_input_tokens"] = int(cache_read)
            out.setdefault("prompt_tokens_details", {})["cached_tokens"] = int(cache_read)
        if cache_creation:
            out["cache_creation_input_tokens"] = int(cache_creation)
        return out

    def transform_stream_done(self) -> str:
        return "data: [DONE]\n\n"
