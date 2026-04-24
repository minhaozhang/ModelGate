from __future__ import annotations


DEEPSEEK_PROVIDER_NAMES = {"deepseek"}

DEEPSEEK_REASONER_MODELS = {
    "deepseek-reasoner",
    "deepseek-r1",
}

DEEPSEEK_THINKING_MODELS_PREFIX = (
    "deepseek-reasoner",
    "deepseek-r1",
    "deepseek-v4",
)


def is_deepseek_thinking_active(
    provider_name: str,
    actual_model: str,
    body_json: dict,
    model_config: dict | None,
) -> bool:
    if provider_name not in DEEPSEEK_PROVIDER_NAMES:
        return False

    for prefix in DEEPSEEK_THINKING_MODELS_PREFIX:
        if actual_model.startswith(prefix):
            return True

    thinking = body_json.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") == "enabled":
        return True

    if model_config and model_config.get("thinking_enabled"):
        return True

    return False


def patch_reasoning_content(messages: list[dict]) -> list[dict]:
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
