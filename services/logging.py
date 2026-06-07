from typing import Optional
from sqlalchemy import update, func

import core.config as config_module
from core.config import providers_cache
from core.database import async_session_maker, ApiKey, RequestLog, RequestContent
from sqlalchemy import delete as sa_delete


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
            response=response,
            tokens=tokens or {},
            latency_ms=latency_ms,
            status=status,
            upstream_status_code=upstream_status_code,
            downstream_status_code=downstream_status_code,
            client_ip=client_ip,
            user_agent=user_agent,
            request_context_tokens=request_context_tokens,
            error=error,
            inbound_protocol=inbound_protocol,
            intent=intent,
            requested_model=requested_model,
            actual_model=actual_model,
            provider_key_id=provider_key_id,
            provider_key_label=provider_key_label,
        )
        session.add(log)
        await session.commit()

        if request_messages is not None:
            content = RequestContent(
                log_id=log.id,
                request_messages=request_messages,
            )
            session.add(content)
            await session.commit()

        invalidate_today_stats_cache()
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
) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            update(RequestLog)
            .where(RequestLog.id == log_id)
            .values(
                response=response,
                tokens=tokens or {},
                latency_ms=latency_ms,
                status=status,
                upstream_status_code=upstream_status_code,
                downstream_status_code=downstream_status_code,
                error=error,
                updated_at=func.now(),
            )
        )
        if status != "success":
            await session.execute(
                sa_delete(RequestContent).where(RequestContent.log_id == log_id)
            )
        await session.commit()
        invalidate_today_stats_cache()
        return (result.rowcount or 0) > 0


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
            values["response_content"] = response_content
        if response_tool_calls is not None:
            values["response_tool_calls"] = response_tool_calls
        if response_thinking is not None:
            values["response_thinking"] = response_thinking
        if response_raw is not None:
            values["response_raw"] = response_raw
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
