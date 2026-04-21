from sqlalchemy import update

from core.config import (
    providers_cache,
    provider_semaphores,
    logger,
)
from core.database import async_session_maker, Provider, ProviderKey


async def disable_provider(provider_name: str, reason: str) -> None:
    logger.warning("[PROVIDER] Disabling provider '%s' due to: %s", provider_name, reason)
    async with async_session_maker() as session:
        await session.execute(
            update(Provider)
            .where(Provider.name == provider_name)
            .values(is_active=False, disabled_reason=reason[:255])
        )
        await session.commit()
    providers_cache.pop(provider_name, None)
    provider_semaphores.pop(provider_name, None)
    from services.provider import load_providers
    await load_providers()


async def disable_provider_key(
    provider_name: str,
    provider_config: dict,
    provider_key_id: int | None,
    reason: str,
) -> None:
    if provider_key_id is None:
        await disable_provider(provider_name, reason)
        return

    logger.warning(
        "[PROVIDER KEY] Disabling key %s of provider '%s' due to: %s",
        provider_key_id,
        provider_name,
        reason,
    )
    async with async_session_maker() as session:
        await session.execute(
            update(ProviderKey)
            .where(ProviderKey.id == provider_key_id)
            .values(is_active=False, disabled_reason=reason[:255])
        )
        await session.commit()

    keys = provider_config.get("api_keys") or []
    active_keys = [k for k in keys if k["id"] != provider_key_id]
    provider_config["api_keys"] = active_keys

    if not active_keys and not provider_config.get("api_key"):
        logger.warning(
            "[PROVIDER] All keys disabled for '%s', disabling provider",
            provider_name,
        )
        await disable_provider(provider_name, reason)
        return

    from services.provider import load_providers, invalidate_provider_key_sticky_cache
    await invalidate_provider_key_sticky_cache(provider_name, provider_key_id)
    await load_providers()


def check_usage_limit_error(resp_json: dict, provider_name: str) -> str | None:
    error_obj = resp_json.get("error")
    if not isinstance(error_obj, dict):
        base_resp = resp_json.get("base_resp")
        if isinstance(base_resp, dict):
            status_code = base_resp.get("status_code")
            status_msg = base_resp.get("status_msg") or base_resp.get("message")
            if status_code not in (None, "", 0, "0", 200, "200") and status_msg:
                return f"{status_msg} ({status_code})"
        return None

    code = str(error_obj.get("code", ""))
    message = error_obj.get("message", "")
    error_type = str(error_obj.get("type", "")).lower()
    http_code = error_obj.get("http_code")
    normalized_message = message.lower()

    if code == "1308":
        return f"{message} ({code})"

    if error_type == "rate_limit_error" and "usage limit" in normalized_message:
        return f"{message} (http_code={http_code or code})"

    usage_keywords = [
        "使用上限",
        "用量上限",
        "超出用量",
        "无可用余额",
        "insufficient_quota",
        "account_deactivated",
        "billing_not_active",
    ]
    for kw in usage_keywords:
        if kw in message or kw in normalized_message:
            return f"{message} ({code})"

    if "usage limit" in normalized_message and "exceeded" in normalized_message:
        return f"{message} ({code})"

    if "quota" in normalized_message and (
        "exceeded" in normalized_message or "limit" in normalized_message
    ):
        return f"{message} ({code})"

    return None
