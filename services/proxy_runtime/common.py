import asyncio

from core.config import api_keys_cache, logger
from core.log_sanitizer import (
    sanitize_headers_for_log,
    sanitize_payload_for_log,
    sanitize_text_for_log,
)
from services.logging import update_api_key_last_used


def schedule_api_key_last_used_update(api_key_id: int | None) -> None:
    if not api_key_id:
        return

    task = asyncio.create_task(update_api_key_last_used(api_key_id))

    def _handle_task_result(done_task: asyncio.Task) -> None:
        try:
            done_task.result()
        except Exception as exc:
            logger.warning(
                "[API KEY] Failed to update last_used_at: %s",
                sanitize_text_for_log(exc),
            )

    task.add_done_callback(_handle_task_result)


def log_request_info(
    provider,
    model,
    auth_header,
    messages,
    is_multimodal,
    stream,
    target_url,
    headers,
    body,
):
    key_name = (
        api_keys_cache.get(auth_header.replace("Bearer ", ""), {}).get(
            "name", "unknown"
        )
        if auth_header.startswith("Bearer ")
        else "unknown"
    )
    msg_count = len(messages)
    has_images = any(
        isinstance(m.get("content"), list)
        and any(
            c.get("type") == "image_url"
            for c in m.get("content", [])
            if isinstance(c, dict)
        )
        for m in messages
    )
    multimodal_tag = " [MULTIMODAL]" if is_multimodal or has_images else ""
    logger.info(
        f"[REQUEST] Provider: {provider.upper()}, Model: {model}, Key: {key_name}, "
        f"Messages: {msg_count}, Stream: {stream}{multimodal_tag}"
    )
    logger.info(f"[REQUEST] Target: {target_url}")
    logger.debug("[REQUEST] Headers: %s", sanitize_headers_for_log(headers))
    logger.debug("[REQUEST] Body: %s", sanitize_payload_for_log(body))
