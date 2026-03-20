import logging
from datetime import datetime, timedelta
from sqlalchemy import select, func, and_, delete
from sqlalchemy.orm import joinedload

from database import (
    async_session_maker,
    RequestLog,
    ProviderDailyStat,
    ApiKeyDailyStat,
    ModelDailyStat,
    ApiKey,
    Provider,
)

logger = logging.getLogger("api_proxy")


async def aggregate_stats_for_date(date_str: str) -> dict:
    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)

    async with async_session_maker() as session:
        logs_query = select(RequestLog).where(
            and_(RequestLog.created_at >= start_dt, RequestLog.created_at < end_dt)
        )
        result = await session.execute(logs_query)
        logs = result.scalars().all()

        provider_cache = {}
        provider_stats = {}
        api_key_stats = {}
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
            is_error = log.status == "error"

            if provider_name:
                if provider_name not in provider_stats:
                    provider_stats[provider_name] = {
                        "requests": 0,
                        "tokens": 0,
                        "errors": 0,
                    }
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
                    }
                api_key_stats[log.api_key_id]["requests"] += 1
                api_key_stats[log.api_key_id]["tokens"] += tokens
                if is_error:
                    api_key_stats[log.api_key_id]["errors"] += 1

            model_key = (log.model, provider_name)
            if model_key not in model_stats:
                model_stats[model_key] = {"requests": 0, "tokens": 0, "errors": 0}
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
            delete(ModelDailyStat).where(ModelDailyStat.date == date_str)
        )

        for provider_name, stats in provider_stats.items():
            stat = ProviderDailyStat(
                provider_name=provider_name,
                date=date_str,
                requests=stats["requests"],
                tokens=stats["tokens"],
                errors=stats["errors"],
            )
            session.add(stat)

        for api_key_id, stats in api_key_stats.items():
            stat = ApiKeyDailyStat(
                api_key_id=api_key_id,
                date=date_str,
                requests=stats["requests"],
                tokens=stats["tokens"],
                errors=stats["errors"],
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
            select(func.min(RequestLog.created_at))
        )
        first_log_date = first_log_result.scalar()

        if not first_log_date:
            return []

        start_date = first_log_date.date()
        end_date = datetime.now().date() - timedelta(days=1)

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
        logger.info("[AGGREGATOR] No missing dates to backfill")
        return

    logger.info(f"[AGGREGATOR] Backfilling {len(missing_dates)} missing dates")
    for date_str in missing_dates:
        try:
            await aggregate_stats_for_date(date_str)
        except Exception as e:
            logger.error(f"[AGGREGATOR] Error backfilling {date_str}: {e}")


async def aggregate_yesterday_stats() -> None:
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        await aggregate_stats_for_date(yesterday)
    except Exception as e:
        logger.error(f"[AGGREGATOR] Error aggregating yesterday stats: {e}")
