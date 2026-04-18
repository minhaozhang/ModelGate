from datetime import datetime, timedelta

from sqlalchemy import select, func, and_, delete, update, text, Integer

from core.config import proxy_logger
from core.database import (
    async_session_maker,
    RequestLog,
    RequestLogRead,
    ProviderDailyStat,
    ApiKeyDailyStat,
    ApiKeyModelDailyStat,
    ModelDailyStat,
    Provider,
    McpCallLog,
    McpCallDailyStat,
)

logger = proxy_logger
ERROR_STATUSES = {"error", "timeout"}
RATE_LIMITED_STATUS = "rate_limited"


async def aggregate_stats_for_date(date_str: str) -> dict:
    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)

    async with async_session_maker() as session:
        logs_query = select(RequestLogRead).where(
            and_(
                RequestLogRead.created_at >= start_dt,
                RequestLogRead.created_at < end_dt,
            )
        )
        result = await session.execute(logs_query)
        logs = result.scalars().all()

        provider_cache = {}
        provider_stats = {}
        api_key_stats = {}
        api_key_model_stats = {}
        model_stats = {}

        for log in logs:
            provider_name = None
            if log.provider_id:
                if log.provider_id not in provider_cache:
                    prov_result = await session.execute(
                        select(Provider).where(Provider.id == log.provider_id)
                    )
                    prov = prov_result.scalar_one_or_none()
                    provider_cache[log.provider_id] = prov.name if prov else None
                provider_name = provider_cache.get(log.provider_id)

            tokens = (
                (log.tokens or {}).get("total_tokens")
                or (log.tokens or {}).get("estimated")
                or 0
            )
            is_error = log.status in ERROR_STATUSES
            is_rate_limited = log.status == RATE_LIMITED_STATUS
            if is_rate_limited:
                tokens = 0

            if provider_name:
                if provider_name not in provider_stats:
                    provider_stats[provider_name] = {
                        "requests": 0,
                        "tokens": 0,
                        "errors": 0,
                        "rate_limited": 0,
                    }
                if is_rate_limited:
                    provider_stats[provider_name]["rate_limited"] += 1
                else:
                    provider_stats[provider_name]["requests"] += 1
                provider_stats[provider_name]["tokens"] += tokens
                if is_error:
                    provider_stats[provider_name]["errors"] += 1

            if log.api_key_id:
                if log.api_key_id not in api_key_stats:
                    api_key_stats[log.api_key_id] = {
                        "requests": 0,
                        "tokens": 0,
                        "errors": 0,
                        "rate_limited": 0,
                    }
                if is_rate_limited:
                    api_key_stats[log.api_key_id]["rate_limited"] += 1
                else:
                    api_key_stats[log.api_key_id]["requests"] += 1
                api_key_stats[log.api_key_id]["tokens"] += tokens
                if is_error:
                    api_key_stats[log.api_key_id]["errors"] += 1
                if log.model:
                    api_key_model_key = (log.api_key_id, log.model)
                    if api_key_model_key not in api_key_model_stats:
                        api_key_model_stats[api_key_model_key] = {
                            "requests": 0,
                            "tokens": 0,
                            "errors": 0,
                            "rate_limited": 0,
                        }
                    if is_rate_limited:
                        api_key_model_stats[api_key_model_key]["rate_limited"] += 1
                    else:
                        api_key_model_stats[api_key_model_key]["requests"] += 1
                    api_key_model_stats[api_key_model_key]["tokens"] += tokens
                    if is_error:
                        api_key_model_stats[api_key_model_key]["errors"] += 1

            model_key = (log.model, provider_name)
            if model_key not in model_stats:
                model_stats[model_key] = {
                    "requests": 0,
                    "tokens": 0,
                    "errors": 0,
                    "rate_limited": 0,
                }
            if is_rate_limited:
                model_stats[model_key]["rate_limited"] += 1
            else:
                model_stats[model_key]["requests"] += 1
            model_stats[model_key]["tokens"] += tokens
            if is_error:
                model_stats[model_key]["errors"] += 1

        await session.execute(
            delete(ProviderDailyStat).where(ProviderDailyStat.date == date_str)
        )
        await session.execute(
            delete(ApiKeyDailyStat).where(ApiKeyDailyStat.date == date_str)
        )
        await session.execute(
            delete(ApiKeyModelDailyStat).where(ApiKeyModelDailyStat.date == date_str)
        )
        await session.execute(
            delete(ModelDailyStat).where(ModelDailyStat.date == date_str)
        )

        for provider_name, stats in provider_stats.items():
            stat = ProviderDailyStat(
                provider_name=provider_name,
                date=date_str,
                requests=stats["requests"],
                tokens=stats["tokens"],
                errors=stats["errors"],
                rate_limited=stats["rate_limited"],
            )
            session.add(stat)

        for api_key_id, stats in api_key_stats.items():
            stat = ApiKeyDailyStat(
                api_key_id=api_key_id,
                date=date_str,
                requests=stats["requests"],
                tokens=stats["tokens"],
                errors=stats["errors"],
                rate_limited=stats["rate_limited"],
            )
            session.add(stat)

        for (api_key_id, model_name), stats in api_key_model_stats.items():
            stat = ApiKeyModelDailyStat(
                api_key_id=api_key_id,
                model_name=model_name,
                date=date_str,
                requests=stats["requests"],
                tokens=stats["tokens"],
                errors=stats["errors"],
                rate_limited=stats["rate_limited"],
            )
            session.add(stat)

        for (model_name, provider_name), stats in model_stats.items():
            stat = ModelDailyStat(
                model_name=model_name,
                provider_name=provider_name,
                date=date_str,
                requests=stats["requests"],
                tokens=stats["tokens"],
                errors=stats["errors"],
                rate_limited=stats["rate_limited"],
            )
            session.add(stat)

        await session.commit()

    total_requests = sum(s["requests"] for s in provider_stats.values())
    logger.info(
        f"[AGGREGATOR] Aggregated stats for {date_str}: {total_requests} requests, {len(provider_stats)} providers, {len(api_key_stats)} api_keys, {len(model_stats)} models"
    )

    return {
        "date": date_str,
        "total_requests": total_requests,
        "providers": len(provider_stats),
        "api_keys": len(api_key_stats),
        "models": len(model_stats),
    }


async def get_missing_dates() -> list[str]:
    async with async_session_maker() as session:
        first_log_result = await session.execute(
            select(func.min(RequestLogRead.created_at))
        )
        first_log_date = first_log_result.scalar()

        if not first_log_date:
            return []

        today_result = await session.execute(select(func.current_date()))
        db_today = today_result.scalar()

        start_date = first_log_date.date()
        end_date = db_today - timedelta(days=1)

        result = await session.execute(select(ProviderDailyStat.date).distinct())
        existing_dates = {row[0] for row in result.fetchall()}

        missing = []
        current = start_date
        while current <= end_date:
            date_str = current.strftime("%Y-%m-%d")
            if date_str not in existing_dates:
                missing.append(date_str)
            current += timedelta(days=1)

        return missing


async def backfill_historical_stats() -> None:
    missing_dates = await get_missing_dates()
    if not missing_dates:
        return

    logger.info(f"[AGGREGATOR] Backfilling {len(missing_dates)} missing dates")
    for date_str in missing_dates:
        try:
            await aggregate_stats_for_date(date_str)
        except Exception as e:
            logger.error(f"[AGGREGATOR] Error backfilling {date_str}: {e}")


async def cleanup_stale_pending_requests() -> None:
    async with async_session_maker() as session:
        result = await session.execute(
            update(RequestLog)
            .where(
                RequestLog.status == "pending",
                RequestLog.created_at < func.now() - timedelta(minutes=10),
            )
            .values(
                status="timeout",
                error="Request timed out",
                latency_ms=func.extract("epoch", func.now() - RequestLog.created_at)
                * 1000,
                updated_at=func.now(),
            )
            .returning(RequestLog.id)
        )
        updated_ids = result.scalars().all()
        await session.commit()

        if updated_ids:
            logger.info(
                f"[AGGREGATOR] Marked {len(updated_ids)} stale pending requests as timeout"
            )


async def archive_old_request_logs() -> int:
    cutoff = datetime.now() - timedelta(days=30)

    async with async_session_maker() as session:
        result = await session.execute(
            text(
                """
                WITH moved AS (
                    INSERT INTO request_logs_history (
                        id,
                        api_key_id,
                        provider_id,
                        model,
                        response,
                        tokens,
                        latency_ms,
                        request_context_tokens,
                        status,
                        upstream_status_code,
                        client_ip,
                        user_agent,
                        error,
                        created_at,
                        updated_at,
                        archive_month,
                        archived_at
                    )
                    SELECT
                        rl.id,
                        rl.api_key_id,
                        rl.provider_id,
                        rl.model,
                        rl.response,
                        rl.tokens,
                        rl.latency_ms,
                        rl.request_context_tokens,
                        rl.status,
                        rl.upstream_status_code,
                        rl.client_ip,
                        rl.user_agent,
                        rl.error,
                        rl.created_at,
                        rl.updated_at,
                        to_char(rl.created_at, 'YYYY-MM'),
                        now()
                    FROM request_logs rl
                    WHERE rl.created_at < :cutoff
                      AND rl.status != 'rate_limited'
                      AND EXISTS (
                        SELECT 1
                        FROM model_daily_stats mds
                        WHERE mds.date = to_char(rl.created_at, 'YYYY-MM-DD')
                      )
                    ON CONFLICT (id) DO NOTHING
                    RETURNING id
                )
                DELETE FROM request_logs rl
                WHERE rl.created_at < :cutoff
                  AND EXISTS (
                    SELECT 1
                    FROM model_daily_stats mds
                    WHERE mds.date = to_char(rl.created_at, 'YYYY-MM-DD')
                  )
                  AND (
                    rl.status = 'rate_limited'
                    OR EXISTS (
                      SELECT 1
                      FROM request_logs_history rh
                      WHERE rh.id = rl.id
                    )
                  )
                RETURNING id
                """
            ),
            {"cutoff": cutoff},
        )
        archived_ids = result.scalars().all()
        await session.commit()

    if archived_ids:
        logger.info(
            "[AGGREGATOR] Archived %s request logs older than 30 days",
            len(archived_ids),
        )

    return len(archived_ids)


async def aggregate_yesterday_stats() -> None:
    async with async_session_maker() as session:
        today_result = await session.execute(select(func.current_date()))
        db_today = today_result.scalar()
    yesterday = (db_today - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        await aggregate_stats_for_date(yesterday)
        await backfill_historical_stats()
    except Exception as e:
        logger.error(f"[AGGREGATOR] Error aggregating yesterday stats: {e}")


async def aggregate_mcp_stats(date_str: str) -> None:
    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)

    async with async_session_maker() as session:
        result = await session.execute(
            select(
                McpCallLog.mcp_server_id,
                func.extract("hour", McpCallLog.created_at).label("hour"),
                func.count().label("calls"),
                func.sum(func.cast(McpCallLog.is_error, Integer)).label("errors"),
                func.avg(McpCallLog.latency_ms).label("avg_latency"),
            )
            .where(
                McpCallLog.created_at >= start_dt,
                McpCallLog.created_at < end_dt,
            )
            .group_by(McpCallLog.mcp_server_id, "hour")
        )
        rows = result.all()

        await session.execute(
            delete(McpCallDailyStat).where(McpCallDailyStat.date == date_str)
        )

        for row in rows:
            stat = McpCallDailyStat(
                mcp_server_id=row.mcp_server_id,
                date=date_str,
                hour=int(row.hour) if row.hour is not None else None,
                calls=row.calls,
                errors=row.errors or 0,
                avg_latency_ms=round(float(row.avg_latency), 2) if row.avg_latency else None,
            )
            session.add(stat)

        await session.commit()

    logger.info(
        "[AGGREGATOR] Aggregated MCP stats for %s: %d groups",
        date_str,
        len(rows),
    )


async def aggregate_mcp_yesterday_stats() -> None:
    async with async_session_maker() as session:
        today_result = await session.execute(select(func.current_date()))
        db_today = today_result.scalar()
    yesterday = (db_today - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        await aggregate_mcp_stats(yesterday)
    except Exception as e:
        logger.error(f"[AGGREGATOR] Error aggregating MCP stats for {yesterday}: {e}")
