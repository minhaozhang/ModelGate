from typing import Optional
from sqlalchemy import update, func

from core.config import providers_cache
from core.database import async_session_maker, RequestLog


async def create_request_log(
    provider_name: str,
    model: str,
    api_key_id: Optional[int] = None,
    request_body: Optional[dict] = None,
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
            status="pending",
        )
        session.add(log)
        await session.commit()
        return log.id


async def update_request_log(
    log_id: int,
    response: str = "",
    tokens: Optional[dict] = None,
    latency_ms: Optional[float] = None,
    status: str = "success",
    upstream_status_code: Optional[int] = None,
    error: Optional[str] = None,
):
    async with async_session_maker() as session:
        await session.execute(
            update(RequestLog)
            .where(RequestLog.id == log_id)
            .values(
                response=response,
                tokens=tokens or {},
                latency_ms=latency_ms,
                status=status,
                upstream_status_code=upstream_status_code,
                error=error,
                updated_at=func.now(),
            )
        )
        await session.commit()


async def log_request(
    provider_name: str,
    model: str,
    response: str,
    tokens: dict,
    latency_ms: float,
    status: str,
    api_key_id: Optional[int] = None,
    upstream_status_code: Optional[int] = None,
    error: Optional[str] = None,
):
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
            tokens=tokens,
            latency_ms=latency_ms,
            status=status,
            upstream_status_code=upstream_status_code,
            error=error,
        )
        session.add(log)
        await session.commit()
