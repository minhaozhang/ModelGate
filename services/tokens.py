import json
from typing import Optional

from core.config import logger


def _coerce_int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
            return int(value)
    return None


def _first_usage_int(usage: dict, *keys: str) -> Optional[int]:
    for key in keys:
        value = _coerce_int(usage.get(key))
        if value is not None:
            return value
    return None


def _estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(len(text) // 4, 1)


def _estimate_prompt_tokens(req_body: Optional[dict]) -> int:
    if not req_body:
        return 0

    payload = {}
    for key in (
        "messages",
        "input",
        "prompt",
        "tools",
        "tool_choice",
        "temperature",
        "max_tokens",
    ):
        if key in req_body:
            payload[key] = req_body[key]

    if not payload:
        payload = req_body

    try:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        serialized = str(payload)

    return _estimate_text_tokens(serialized)


def estimate_request_context_tokens(req_body: Optional[dict]) -> int:
    return _estimate_prompt_tokens(req_body)


def _tool_call_key(tool_call: dict) -> str:
    if not isinstance(tool_call, dict):
        return ""

    tool_call_id = tool_call.get("id")
    if tool_call_id:
        return str(tool_call_id)

    function = tool_call.get("function")
    function_name = ""
    if isinstance(function, dict):
        function_name = str(function.get("name") or "")

    index = tool_call.get("index")
    if index is not None or function_name:
        return f"{index}:{function_name}"

    try:
        return json.dumps(tool_call, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(tool_call)


def _collect_tool_calls(
    tool_calls: Optional[list], seen_keys: set[str], collected: list[dict]
):
    if not isinstance(tool_calls, list):
        return

    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        key = _tool_call_key(tool_call)
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        collected.append(tool_call)


def build_response_meta(
    response_text: str = "",
    reasoning_text: str = "",
    tool_calls: Optional[list] = None,
    finish_reason: Optional[str] = None,
) -> dict:
    collected_tool_calls = tool_calls if isinstance(tool_calls, list) else []
    has_text = bool((response_text or "").strip())
    has_reasoning = bool((reasoning_text or "").strip())
    has_tool_calls = bool(collected_tool_calls)

    response_types = []
    if has_text:
        response_types.append("text")
    if has_reasoning:
        response_types.append("reasoning")
    if has_tool_calls:
        response_types.append("tool_calls")
    if not response_types:
        response_types.append("empty")

    tool_names = []
    for tool_call in collected_tool_calls:
        function = tool_call.get("function") if isinstance(tool_call, dict) else None
        if isinstance(function, dict) and function.get("name"):
            tool_names.append(str(function["name"]))

    return {
        "response_types": response_types,
        "has_text": has_text,
        "has_reasoning": has_reasoning,
        "has_tool_calls": has_tool_calls,
        "tool_call_count": len(collected_tool_calls),
        "tool_names": tool_names,
        "finish_reason": finish_reason or "",
    }


def log_response_meta(provider: str, model: str, response_meta: dict):
    response_types = "/".join(response_meta.get("response_types", [])) or "empty"
    finish_reason = response_meta.get("finish_reason") or "unknown"
    tool_call_count = response_meta.get("tool_call_count", 0)
    tool_names = ", ".join(response_meta.get("tool_names", [])[:3]) or "-"
    logger.info(
        f"[RESPONSE META] Provider: {provider}, Model: {model}, Types: {response_types}, "
        f"Finish: {finish_reason}, ToolCalls: {tool_call_count}, Tools: {tool_names}"
    )


def build_tokens_record(
    usage: Optional[dict],
    req_body: Optional[dict] = None,
    response_text: str = "",
    reasoning_text: str = "",
    response_meta: Optional[dict] = None,
) -> dict:
    raw_usage = usage if isinstance(usage, dict) else {}
    tokens_record = dict(raw_usage)

    prompt_tokens = _first_usage_int(
        raw_usage,
        "prompt_tokens",
        "input_tokens",
        "promptTokens",
        "inputTokens",
    )
    completion_tokens = _first_usage_int(
        raw_usage,
        "completion_tokens",
        "output_tokens",
        "completionTokens",
        "outputTokens",
    )
    total_tokens = _first_usage_int(
        raw_usage,
        "total_tokens",
        "totalTokens",
    )

    estimated = False

    if prompt_tokens is None:
        if total_tokens is not None and completion_tokens is not None:
            prompt_tokens = max(total_tokens - completion_tokens, 0)
        else:
            prompt_tokens = _estimate_prompt_tokens(req_body)
            estimated = True

    if completion_tokens is None:
        if total_tokens is not None and prompt_tokens is not None:
            completion_tokens = max(total_tokens - prompt_tokens, 0)
        else:
            completion_tokens = _estimate_text_tokens(response_text + reasoning_text)
            estimated = True

    if total_tokens is None:
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
        estimated = True

    tokens_record.update(
        {
            "prompt_tokens": prompt_tokens or 0,
            "completion_tokens": completion_tokens or 0,
            "total_tokens": total_tokens or 0,
            "estimated": estimated,
        }
    )
    if response_meta:
        tokens_record["response_meta"] = response_meta
    return tokens_record
