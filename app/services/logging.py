from typing import Any, Optional
from sqlalchemy import update, func

import app.core.config as config_module
from app.core.config import providers_cache
from app.core.database import async_session_maker, ApiKey, RequestLog, RequestContent
from sqlalchemy import delete as sa_delete

# In-flight request log statuses: "sending" (upstream request sent, first
# chunk not yet received) and "pending" (stream relaying). All stats /
# aggregation queries treat these as not-yet-completed.
IN_FLIGHT_STATUSES = ("waiting", "pending", "sending")


def _clean_null_bytes(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "").replace("\u0000", "")
    if isinstance(value, dict):
        return {k: _clean_null_bytes(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_null_bytes(v) for v in value]
    return value


def invalidate_today_stats_cache() -> None:
    config_module.today_stats_cache = {}
    config_module.today_stats_cache_time = None


async def create_request_log(
    provider_name: str,
    model: str,
    status: str = "pending",
    api_key_id: Optional[int] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    request_context_tokens: Optional[int] = None,
    response: str = "",
    tokens: Optional[dict] = None,
    latency_ms: Optional[float] = None,
    upstream_status_code: Optional[int] = None,
    downstream_status_code: Optional[int] = None,
    error: Optional[str] = None,
    inbound_protocol: Optional[str] = None,
    intent: Optional[str] = None,
    request_messages: Optional[list] = None,
    requested_model: Optional[str] = None,
    actual_model: Optional[str] = None,
    provider_key_id: Optional[int] = None,
    provider_key_label: Optional[str] = None,
    routing_decision: Optional[dict] = None,
) -> int:
    async with async_session_maker() as session:
        provider_id = None
        if provider_name:
            pinfo = providers_cache.get(provider_name)
            if pinfo:
                provider_id = pinfo.get("id")

        log = RequestLog(
            api_key_id=api_key_id,
            provider_id=provider_id,
            model=model,
            response=_clean_null_bytes(response),
            tokens=_clean_null_bytes(tokens) or {},
            latency_ms=latency_ms,
            status=status,
            upstream_status_code=upstream_status_code,
            downstream_status_code=downstream_status_code,
            client_ip=client_ip,
            user_agent=user_agent,
            request_context_tokens=request_context_tokens,
            error=_clean_null_bytes(error),
            inbound_protocol=inbound_protocol,
            intent=intent,
            requested_model=requested_model,
            actual_model=actual_model,
            provider_key_id=provider_key_id,
            provider_key_label=provider_key_label,
            routing_decision=_clean_null_bytes(routing_decision),
        )
        session.add(log)
        await session.commit()

        if request_messages is not None:
            content = RequestContent(
                log_id=log.id,
                request_messages=_clean_null_bytes(request_messages),
            )
            session.add(content)
            await session.commit()

        if status == "waiting":
            _notify_live_stats()
        config_module.remember_log_owner(log.id, api_key_id)
        config_module.mark_user_requests_dirty(api_key_id)

        return log.id


async def update_request_log(
    log_id: int,
    response: str = "",
    tokens: Optional[dict] = None,
    latency_ms: Optional[float] = None,
    status: str = "success",
    upstream_status_code: Optional[int] = None,
    downstream_status_code: Optional[int] = None,
    error: Optional[str] = None,
    actual_model: Optional[str] = None,
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
    provider_key_id: Optional[int] = None,
    provider_key_label: Optional[str] = None,
    routing_decision: Optional[dict] = None,
    request_messages: Optional[list] = None,
    wait_ms: Optional[float] = None,
) -> bool:
    async with async_session_maker() as session:
        values = dict(
            response=_clean_null_bytes(response),
            tokens=_clean_null_bytes(tokens) or {},
            latency_ms=latency_ms,
            status=status,
            upstream_status_code=upstream_status_code,
            downstream_status_code=downstream_status_code,
            error=_clean_null_bytes(error),
            actual_model=actual_model,
            updated_at=func.now(),
        )
        if wait_ms is not None:
            values["wait_ms"] = wait_ms
        if provider_name:
            pinfo = providers_cache.get(provider_name)
            if pinfo:
                values["provider_id"] = pinfo.get("id")
        if model is not None:
            values["model"] = model
        if provider_key_id is not None:
            values["provider_key_id"] = provider_key_id
        if provider_key_label is not None:
            values["provider_key_label"] = _clean_null_bytes(provider_key_label)
        if routing_decision is not None:
            values["routing_decision"] = _clean_null_bytes(routing_decision)
        result = await session.execute(
            update(RequestLog).where(RequestLog.id == log_id).values(**values)
        )
        if status != "success":
            await session.execute(
                sa_delete(RequestContent).where(RequestContent.log_id == log_id)
            )
        if request_messages is not None:
            session.add(
                RequestContent(
                    log_id=log_id,
                    request_messages=_clean_null_bytes(request_messages),
                )
            )
        await session.commit()
        if (result.rowcount or 0) > 0:
            config_module.mark_user_requests_dirty_for_log(log_id)
        return (result.rowcount or 0) > 0


def _notify_live_stats() -> None:
    try:
        import asyncio

        from app.core.config import broadcast_live_stats

        asyncio.get_running_loop().create_task(broadcast_live_stats())
    except Exception:
        pass


async def safe_update_request_log(log_id, **kwargs) -> None:
    """Best-effort update: swallow errors so log issues never kill requests."""
    if not isinstance(log_id, int):
        return
    try:
        updated = await update_request_log(log_id, **kwargs)
        if updated and "status" in kwargs:
            _notify_live_stats()
    except Exception:
        import logging as _logging

        _logging.getLogger("modelgate.logging").warning(
            "safe_update_request_log failed for log %s", log_id, exc_info=True
        )


async def update_request_log_status(
    log_id: int, status: str, first_chunk_ms: Optional[float] = None
) -> bool:
    """Phase-only update (sending -> pending): touch status/updated_at only."""
    values = {"status": status, "updated_at": func.now()}
    if first_chunk_ms is not None:
        values["first_chunk_ms"] = first_chunk_ms
    async with async_session_maker() as session:
        result = await session.execute(
            update(RequestLog).where(RequestLog.id == log_id).values(**values)
        )
        await session.commit()
        updated = (result.rowcount or 0) > 0
    if updated:
        _notify_live_stats()
        config_module.mark_user_requests_dirty_for_log(log_id)
    return updated


async def update_request_content(
    log_id: int,
    response_content: Optional[str] = None,
    response_tool_calls: Optional[list] = None,
    response_thinking: Optional[str] = None,
    response_raw: Optional[dict] = None,
) -> bool:
    from sqlalchemy import update as sa_update

    async with async_session_maker() as session:
        values = {}
        if response_content is not None:
            values["response_content"] = _clean_null_bytes(response_content)
        if response_tool_calls is not None:
            values["response_tool_calls"] = _clean_null_bytes(response_tool_calls)
        if response_thinking is not None:
            values["response_thinking"] = _clean_null_bytes(response_thinking)
        if response_raw is not None:
            values["response_raw"] = _clean_null_bytes(response_raw)
        if not values:
            return False
        result = await session.execute(
            sa_update(RequestContent)
            .where(RequestContent.log_id == log_id)
            .values(**values)
        )
        await session.commit()
        return (result.rowcount or 0) > 0


async def update_api_key_last_used(api_key_id: Optional[int]) -> None:
    if not api_key_id:
        return

    async with async_session_maker() as session:
        await session.execute(
            update(ApiKey)
            .where(ApiKey.id == api_key_id)
            .values(last_used_at=func.now())
        )
        await session.commit()
