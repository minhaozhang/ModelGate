from __future__ import annotations


DEEPSEEK_PROVIDER_NAMES = {"deepseek"}

DEEPSEEK_THINKING_MODEL_PREFIXES = (
    "deepseek-reasoner",
    "deepseek-r1",
    "deepseek-v3.",
    "deepseek-v4",
)


def is_deepseek_thinking_active(
    provider_name: str,
    actual_model: str,
    body_json: dict,
    model_config: dict | None,
) -> bool:
    thinking = body_json.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") == "enabled":
        return True

    if model_config and model_config.get("thinking_enabled"):
        return True

    if provider_name in DEEPSEEK_PROVIDER_NAMES:
        for prefix in DEEPSEEK_THINKING_MODEL_PREFIXES:
            if actual_model.startswith(prefix):
                return True

    return False


def patch_reasoning_content(messages: list[dict]) -> list[dict]:
    has_tool_context = any(
        m.get("role") in ("tool",) or m.get("tool_calls") or m.get("tool_call_id")
        for m in messages
    )

    if has_tool_context:
        for m in messages:
            if m.get("role") == "assistant" and "reasoning_content" not in m:
                m["reasoning_content"] = ""
        return messages

    last_user_idx = -1
    for i, m in enumerate(messages):
        if m.get("role") == "user":
            last_user_idx = i

    if last_user_idx < 0:
        return messages

    for m in messages[last_user_idx + 1:]:
        if m.get("role") == "assistant" and "reasoning_content" not in m:
            m["reasoning_content"] = ""

    return messages
