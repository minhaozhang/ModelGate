import json
import re
import uuid
from typing import Optional

from core.config import logger


def parse_minimax_tool_calls(content: str) -> tuple[str, list[dict]]:
    tool_calls = []
    pattern = r"<minimax:tool_call>\s*(.*?)\s*</minimax:tool_call>"
    matches = re.findall(pattern, content, re.DOTALL)

    for match in matches:
        invoke_pattern = r'<invoke\s+name="([^"]+)"[^>]*>(.*?)</invoke>'
        invoke_matches = re.findall(invoke_pattern, match, re.DOTALL)

        for func_name, params_xml in invoke_matches:
            arguments = {}
            param_pattern = r'<parameter\s+name="([^"]+)"[^>]*>(.*?)</parameter>'
            param_matches = re.findall(param_pattern, params_xml, re.DOTALL)

            for param_name, param_value in param_matches:
                arguments[param_name] = param_value.strip()

            tool_calls.append(
                {
                    "id": f"call_{uuid.uuid4().hex[:24]}",
                    "type": "function",
                    "function": {
                        "name": func_name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            )

    cleaned_content = re.sub(pattern, "", content, flags=re.DOTALL).strip()

    return cleaned_content, tool_calls


def process_minimax_response(resp_json: dict) -> None:
    if "choices" not in resp_json or not resp_json["choices"]:
        return
    message = resp_json["choices"][0].get("message", {})
    content = message.get("content", "")
    if "<Parsed>" in content and "</Parsed>" in content:
        start_idx = content.find("<Parsed>")
        end_idx = content.find("</Parsed>") + 9
        reasoning = content[start_idx + 8 : end_idx - 9]
        remaining = content[:start_idx] + content[end_idx:]
        message["reasoning_content"] = reasoning
        message["content"] = remaining.strip()
        content = remaining.strip()
    if "<minimax:tool_call>" in content:
        cleaned_content, tool_calls = parse_minimax_tool_calls(content)
        if tool_calls:
            message["content"] = cleaned_content if cleaned_content else None
            message["tool_calls"] = tool_calls
            resp_json["choices"][0]["finish_reason"] = "tool_calls"
            logger.info(f"[MINIMAX TOOL_CALLS] Parsed {len(tool_calls)} tool calls")


def _build_tool_call_chunk(chunk: dict, tc: dict, index: int) -> str:
    tc_chunk = {
        "id": chunk.get("id", ""),
        "object": chunk.get("object", "chat.completion.chunk"),
        "created": chunk.get("created", 0),
        "model": chunk.get("model", ""),
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": index,
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            },
                        }
                    ]
                },
                "finish_reason": None,
            }
        ],
    }
    return f"data: {json.dumps(tc_chunk)}\n\n"


def _build_finish_chunk(chunk: dict) -> str:
    finish_chunk = {
        "id": chunk.get("id", ""),
        "object": chunk.get("object", "chat.completion.chunk"),
        "created": chunk.get("created", 0),
        "model": chunk.get("model", ""),
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "tool_calls",
            }
        ],
    }
    return f"data: {json.dumps(finish_chunk)}\n\n"


class MinimaxStreamProcessor:
    def __init__(self):
        self.total_raw_content = ""
        self.in_thinking = False
        self.in_tool_call = False
        self.thinking_buffer = ""

    def process_content(
        self,
        content: str,
        chunk: dict,
        delta: dict,
        seen_tool_call_keys: set[str],
        stream_tool_calls: list[dict],
        _collect_tool_calls_fn,
    ) -> Optional[tuple[str, str]]:
        """
        Process MiniMax stream content. Returns:
        - None: skip this line entirely
        - ("skip", None): suppress content, yield modified chunk
        - ("yield", extra_lines): yield the modified line + extra SSE lines
        """
        self.total_raw_content += content

        if "<minimax:tool_call>" in self.total_raw_content:
            self.in_tool_call = True

        if self.in_tool_call:
            return self._handle_tool_call(
                chunk, delta, seen_tool_call_keys, stream_tool_calls, _collect_tool_calls_fn
            )
        else:
            return self._handle_thinking(chunk, delta)

    def _handle_tool_call(
        self, chunk, delta, seen_keys, collected, collect_fn
    ) -> Optional[tuple[str, str]]:
        if "</minimax:tool_call>" not in self.total_raw_content:
            delta.pop("content", None)
            return ("skip", None)

        cleaned, tool_calls = parse_minimax_tool_calls(self.total_raw_content)
        if not tool_calls:
            self.total_raw_content = ""
            self.in_tool_call = False
            return ("skip", None)

        collect_fn(tool_calls, seen_keys, collected)
        extra_lines = ""
        for i, tc in enumerate(tool_calls):
            extra_lines += _build_tool_call_chunk(chunk, tc, i)
            logger.info(f"[MINIMAX TOOL_CALL] {tc['function']['name']}")
        extra_lines += _build_finish_chunk(chunk)

        self.total_raw_content = ""
        self.in_tool_call = False
        return ("yield", extra_lines)

    def _handle_thinking(self, chunk, delta) -> tuple[str, str]:
        content = delta.get("content", "")
        self.thinking_buffer += content
        new_content = ""
        new_reasoning = ""

        i = 0
        while i < len(self.thinking_buffer):
            if not self.in_thinking:
                start_idx = self.thinking_buffer.find("<Parsed>", i)
                if start_idx != -1:
                    new_content += self.thinking_buffer[i:start_idx]
                    i = start_idx + 8
                    self.in_thinking = True
                else:
                    new_content += self.thinking_buffer[i:]
                    break
            else:
                end_idx = self.thinking_buffer.find("</Parsed>", i)
                if end_idx != -1:
                    new_reasoning += self.thinking_buffer[i:end_idx]
                    i = end_idx + 9
                    self.in_thinking = False
                else:
                    new_reasoning += self.thinking_buffer[i:]
                    break

        self.thinking_buffer = ""

        if new_content:
            delta["content"] = new_content
        else:
            delta.pop("content", None)
        if new_reasoning:
            delta["reasoning_content"] = new_reasoning

        total_reasoning = new_reasoning
        total_content = new_content

        return ("content", total_content, total_reasoning)
