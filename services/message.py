from __future__ import annotations
from typing import Optional


def merge_system_messages(messages: list[dict]) -> list[dict]:
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]

    if len(system_msgs) <= 1:
        return messages

    text_parts = []
    for m in system_msgs:
        content = m.get("content", "")
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    text_parts.append(c.get("text", ""))
                elif isinstance(c, str):
                    text_parts.append(c)
        else:
            text_parts.append(content)

    merged_system = {
        "role": "system",
        "content": "\n\n".join(text_parts),
    }
    return [merged_system] + other_msgs


def merge_consecutive_messages(messages: list[dict]) -> list[dict]:
    merged = []
    for m in messages:
        has_tool_content = m.get("tool_calls") or m.get("tool_call_id")
        if (
            merged
            and merged[-1].get("role") == m.get("role")
            and not has_tool_content
            and not (
                merged[-1].get("tool_calls") or merged[-1].get("tool_call_id")
            )
        ):
            prev_content = merged[-1].get("content", "")
            curr_content = m.get("content", "")
            if isinstance(prev_content, str) and isinstance(curr_content, str):
                merged[-1]["content"] = prev_content + "\n\n" + curr_content
            else:
                merged.append(m)
        else:
            merged.append(m)
    return merged


def preprocess_messages(
    body_json: dict,
    merge_messages: bool,
    is_multimodal: bool,
) -> dict:
    messages = body_json.get("messages", [])

    if merge_messages or not is_multimodal:
        messages = merge_system_messages(messages)

    if merge_messages:
        new_messages = merge_consecutive_messages(messages)
        if len(new_messages) != len(messages):
            messages = new_messages

    body_json["messages"] = messages
    return body_json
