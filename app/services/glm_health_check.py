from __future__ import annotations

import json

from app.core.config import logger
from app.services.proxy import INTERNAL_ANALYSIS_API_KEY_ID, call_internal_model_via_proxy
from app.services.system_config import get_setting

DEFAULT_HEALTH_CHECK_MODEL = "zhipu/glm-5.3"


def _extract_reply(payload: dict | None) -> str:
    if not payload:
        return ""
    try:
        return (
            payload.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            or ""
        )
    except (IndexError, AttributeError, TypeError):
        return ""


async def run_glm_health_check() -> None:
    model = (
        await get_setting(
            "scheduler", "glm_health_check_model", DEFAULT_HEALTH_CHECK_MODEL
        )
    ).strip() or DEFAULT_HEALTH_CHECK_MODEL

    body_json = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a health check probe."},
            {"role": "user", "content": "ping"},
        ],
        "max_tokens": 8,
        "stream": False,
    }

    result = await call_internal_model_via_proxy(
        requested_model=model,
        body_json=body_json,
        api_key_id=INTERNAL_ANALYSIS_API_KEY_ID,
        purpose="glm-health-check",
        timeout_seconds=60.0,
    )

    if not result.get("ok"):
        reason = str(result.get("error") or "")[:300] or "unknown error"
        await _notify_failure(model, f"网关调用失败: {reason}")
        raise RuntimeError(f"GLM health check failed for model '{model}': {reason}")

    reply = _extract_reply(result.get("payload"))
    if not reply:
        detail = json.dumps(result.get("payload") or {}, ensure_ascii=False)[:300]
        await _notify_failure(model, f"上游响应为空: {detail}")
        raise RuntimeError(f"GLM health check got empty reply for model '{model}'")

    logger.info("[GLM HEALTH CHECK] model=%s ok reply=%s", model, reply[:50])


async def _notify_failure(model: str, reason: str) -> None:
    try:
        from app.services.notification import create_notification

        await create_notification(
            "system",
            "error",
            f"GLM 模型健康检查失败（{model}）",
            reason,
        )
    except Exception as exc:
        logger.warning("[GLM HEALTH CHECK] Failed to create notification: %s", exc)
