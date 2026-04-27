import re
from datetime import datetime

from sqlalchemy import select, update

from core.config import logger, provider_key_semaphores, providers_cache
from core.database import Provider, ProviderKey, async_session_maker


def parse_reset_time(reason: str) -> datetime | None:
    if not reason:
        return None
    match = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", reason)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


async def _do_reenable_provider(provider_id: int) -> None:
    logger.info("[REENABLE-JOB] Re-enabling provider id=%d at %s", provider_id, datetime.utcnow())
    async with async_session_maker() as session:
        await session.execute(
            update(Provider)
            .where(Provider.id == provider_id, Provider.is_active == False)  # noqa: E712
            .values(is_active=True, disabled_reason=None, disabled_at=None, reset_at=None)
        )
        await session.commit()

        result = await session.execute(
            select(Provider.name).where(Provider.id == provider_id)
        )
        name = result.scalar()

    from services.provider import load_providers
    await load_providers()

    if name:
        _cancel_reenable_job("provider", provider_id)
        try:
            from services.notification import create_notification
            await create_notification("system", "info", f"供应商已自动恢复：{name}", f"精确时间恢复 (id={provider_id})")
        except Exception:
            pass


async def _do_reenable_key(key_id: int) -> None:
    logger.info("[REENABLE-JOB] Re-enabling key id=%d at %s", key_id, datetime.utcnow())
    async with async_session_maker() as session:
        await session.execute(
            update(ProviderKey)
            .where(ProviderKey.id == key_id, ProviderKey.is_active == False)  # noqa: E712
            .values(is_active=True, disabled_reason=None, disabled_at=None, reset_at=None)
        )
        await session.commit()

    from services.provider import load_providers
    await load_providers()

    _cancel_reenable_job("key", key_id)


def _get_scheduler():
    from services.scheduler import scheduler
    return scheduler


def _cancel_reenable_job(entity_type: str, entity_id: int) -> None:
    job_id = f"reenable_{entity_type}_{entity_id}"
    try:
        sched = _get_scheduler()
        if sched.get_job(job_id):
            sched.remove_job(job_id)
    except Exception:
        pass


async def schedule_reenable_job(entity_type: str, entity_id: int, reset_at: datetime) -> None:
    from apscheduler.triggers.date import DateTrigger

    job_id = f"reenable_{entity_type}_{entity_id}"
    sched = _get_scheduler()

    if sched.get_job(job_id):
        sched.remove_job(job_id)

    func = _do_reenable_provider if entity_type == "provider" else _do_reenable_key

    sched.add_job(
        func,
        trigger=DateTrigger(run_date=reset_at),
        args=[entity_id],
        id=job_id,
        replace_existing=True,
    )
    logger.info(
        "[REENABLE-JOB] Scheduled %s id=%d to re-enable at %s",
        entity_type, entity_id, reset_at.isoformat(),
    )


async def disable_provider(provider_name: str, reason: str) -> None:
    reset_at = parse_reset_time(reason)

    logger.warning("[PROVIDER] Disabling provider '%s' due to: %s (reset_at=%s)", provider_name, reason, reset_at)

    async with async_session_maker() as session:
        result = await session.execute(
            update(Provider)
            .where(Provider.name == provider_name)
            .values(is_active=False, disabled_reason=reason[:255], disabled_at=datetime.utcnow(), reset_at=reset_at)
            .returning(Provider.id)
        )
        provider_id = result.scalar()
        await session.commit()

    providers_cache.pop(provider_name, None)
    prefix = f":{provider_name}"
    keys_to_remove = [k for k in provider_key_semaphores if k.endswith(prefix)]
    for k in keys_to_remove:
        provider_key_semaphores.pop(k, None)
    from services.provider import load_providers
    await load_providers()

    if reset_at and reset_at > datetime.utcnow() and provider_id:
        await schedule_reenable_job("provider", provider_id, reset_at)

    try:
        from services.notification import create_notification
        await create_notification("system", "error", f"供应商 '{provider_name}' 已被禁用", reason[:200])
    except Exception:
        pass


async def disable_provider_key(
    provider_name: str,
    provider_config: dict,
    provider_key_id: int | None,
    reason: str,
) -> None:
    if provider_key_id is None:
        await disable_provider(provider_name, reason)
        return

    reset_at = parse_reset_time(reason)

    logger.warning(
        "[PROVIDER KEY] Disabling key %s of provider '%s' due to: %s (reset_at=%s)",
        provider_key_id,
        provider_name,
        reason,
        reset_at,
    )
    async with async_session_maker() as session:
        await session.execute(
            update(ProviderKey)
            .where(ProviderKey.id == provider_key_id)
            .values(is_active=False, disabled_reason=reason[:255], disabled_at=datetime.utcnow(), reset_at=reset_at)
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

    if reset_at and reset_at > datetime.utcnow():
        await schedule_reenable_job("key", provider_key_id, reset_at)

    from services.provider import invalidate_provider_key_sticky_cache, load_providers

    await invalidate_provider_key_sticky_cache(provider_name, provider_key_id)
    await load_providers()


def check_usage_limit_error(resp_json: dict, provider_name: str) -> str | None:
    provider_name = (provider_name or "").lower()
    quota_keywords = [
        "usage limit",
        "insufficient_quota",
        "billing_not_active",
        "account_deactivated",
        "quota exceeded",
        "quota",
        "\u4f59\u989d",
        "\u989d\u5ea6",
        "\u7528\u91cf",
        "\u4f7f\u7528\u4e0a\u9650",
        "\u8d85\u51fa",
        "\u65e0\u53ef\u7528\u4f59\u989d",
        "\u8c03\u7528\u6b21\u6570",
    ]

    def looks_like_usage_limit(*parts: object) -> bool:
        normalized = " ".join(str(part or "") for part in parts).lower()
        return any(keyword in normalized for keyword in quota_keywords)

    error_obj = resp_json.get("error")
    if isinstance(error_obj, dict):
        msg = (
            error_obj.get("message")
            or error_obj.get("msg")
            or error_obj.get("detail")
            or ""
        )
        code = error_obj.get("code") or error_obj.get("status_code")
        if looks_like_usage_limit(msg, code):
            return f"{msg} ({code})" if code not in (None, "") else str(msg)

    base_resp = resp_json.get("base_resp")
    if isinstance(base_resp, dict):
        status_code = base_resp.get("status_code")
        status_msg = base_resp.get("status_msg") or base_resp.get("message")
        if (
            provider_name == "minimax"
            and status_code not in (None, "", 0, "0", 200, "200")
            and looks_like_usage_limit(status_msg, status_code)
        ):
            return f"{status_msg} ({status_code})"

    return None


async def auto_reenable_disabled_keys_and_providers() -> None:
    from sqlalchemy import or_, select

    from core.database import Provider, ProviderKey, async_session_maker

    now = datetime.utcnow()

    reenabled_keys = []
    reenabled_providers = []

    async with async_session_maker() as session:
        disabled_keys = await session.execute(
            select(ProviderKey).where(
                ProviderKey.is_active == False,  # noqa: E712
                or_(ProviderKey.reset_at == None, ProviderKey.reset_at <= now),  # noqa: E711
            )
        )
        disabled_key_rows = disabled_keys.scalars().all()

        disabled_providers_q = await session.execute(
            select(Provider).where(
                Provider.is_active == False,  # noqa: E712
                or_(Provider.reset_at == None, Provider.reset_at <= now),  # noqa: E711
            )
        )
        disabled_provider_rows = disabled_providers_q.scalars().all()

        logger.info(
            "[AUTO-REENABLE] Found %d disabled key(s), %d disabled provider(s) eligible for re-enable",
            len(disabled_key_rows),
            len(disabled_provider_rows),
        )

        if disabled_key_rows:
            key_ids = [k.id for k in disabled_key_rows]
            await session.execute(
                update(ProviderKey)
                .where(ProviderKey.id.in_(key_ids))
                .values(is_active=True, disabled_reason=None, disabled_at=None, reset_at=None)
            )
            reenabled_keys = key_ids

        if disabled_provider_rows:
            provider_ids = [p.id for p in disabled_provider_rows]
            await session.execute(
                update(Provider)
                .where(Provider.id.in_(provider_ids))
                .values(is_active=True, disabled_reason=None, disabled_at=None, reset_at=None)
            )
            reenabled_providers = [p.name for p in disabled_provider_rows]

        await session.commit()

        logger.info(
            "[AUTO-REENABLE] Re-enabled %d key(s): %s, %d provider(s): %s",
            len(reenabled_keys),
            reenabled_keys,
            len(reenabled_providers),
            reenabled_providers,
        )

    if reenabled_keys or reenabled_providers:
        from services.provider import load_providers

        await load_providers()

        try:
            from services.notification import create_notification
            names = reenabled_providers or []
            if reenabled_keys and not names:
                names = [f"{len(reenabled_keys)} key(s)"]
            if names:
                await create_notification("system", "info", f"供应商已自动恢复：{', '.join(names)}", "自动重新启用完成")
        except Exception:
            pass


async def restore_pending_reenable_jobs() -> None:
    from core.database import Provider, ProviderKey, async_session_maker

    now = datetime.utcnow()
    restored = 0

    async with async_session_maker() as session:
        result = await session.execute(
            select(Provider.id, Provider.reset_at).where(
                Provider.is_active == False,  # noqa: E712
                Provider.reset_at != None,  # noqa: E711
                Provider.reset_at > now,
            )
        )
        for row in result:
            await schedule_reenable_job("provider", row.id, row.reset_at)
            restored += 1

        result = await session.execute(
            select(ProviderKey.id, ProviderKey.reset_at).where(
                ProviderKey.is_active == False,  # noqa: E712
                ProviderKey.reset_at != None,  # noqa: E711
                ProviderKey.reset_at > now,
            )
        )
        for row in result:
            await schedule_reenable_job("key", row.id, row.reset_at)
            restored += 1

    if restored:
        logger.info("[REENABLE-JOB] Restored %d pending re-enable job(s) from DB", restored)
