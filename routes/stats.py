import time
from datetime import datetime, timedelta
from typing import Optional, Literal
from fastapi import APIRouter
from sqlalchemy import select, func, and_

from core.database import (
    async_session_maker,
    RequestLog,
    ApiKey,
    Provider,
    ProviderDailyStat,
    ApiKeyDailyStat,
    ModelDailyStat,
)
from core.config import (
    api_keys_cache,
    stats,
    today_stats_cache,
    today_stats_cache_time,
    TODAY_STATS_CACHE_TTL_SECONDS,
    requests_per_second,
    tokens_per_second,
    pending_requests,
)

router = APIRouter(prefix="/admin/api", tags=["stats"])


async def get_cached_today_stats(start: datetime) -> dict:
    from core.config import proxy_logger

    now = datetime.now()
    cache_key = start.strftime("%Y-%m-%d")

    if (
        today_stats_cache_time
        and (now - today_stats_cache_time).total_seconds()
        < TODAY_STATS_CACHE_TTL_SECONDS
        and today_stats_cache.get("date") == cache_key
    ):
        return today_stats_cache

    proxy_logger.info("[STATS CACHE] Refreshing today stats cache")

    async with async_session_maker() as session:
        query = select(RequestLog).where(RequestLog.created_at >= start)
        result = await session.execute(query)
        logs = result.scalars().all()

        provider_cache = {}
        provider_stats = {}
        api_key_stats = {}
        model_stats = {}

        for log in logs:
            tokens = (
                (log.tokens or {}).get("total_tokens")
                or (log.tokens or {}).get("estimated")
                or 0
            )
            is_error = log.status == "error"

            provider_name = None
            if log.provider_id:
                if log.provider_id not in provider_cache:
                    prov_result = await session.execute(
                        select(Provider).where(Provider.id == log.provider_id)
                    )
                    prov = prov_result.scalar_one_or_none()
                    provider_cache[log.provider_id] = prov.name if prov else None
                provider_name = provider_cache.get(log.provider_id)

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
                key_info = None
                for k, v in api_keys_cache.items():
                    if v["id"] == log.api_key_id:
                        key_info = v
                        break
                key_name = key_info["name"] if key_info else f"Key-{log.api_key_id}"
                if key_name not in api_key_stats:
                    api_key_stats[key_name] = {"requests": 0, "tokens": 0, "errors": 0}
                api_key_stats[key_name]["requests"] += 1
                api_key_stats[key_name]["tokens"] += tokens
                if is_error:
                    api_key_stats[key_name]["errors"] += 1

            if log.model:
                if log.model not in model_stats:
                    model_stats[log.model] = {"requests": 0, "tokens": 0, "errors": 0}
                model_stats[log.model]["requests"] += 1
                model_stats[log.model]["tokens"] += tokens
                if is_error:
                    model_stats[log.model]["errors"] += 1

        cache_data = {
            "date": cache_key,
            "provider": provider_stats,
            "api_key": api_key_stats,
            "model": model_stats,
            "logs": logs,
            "provider_cache": provider_cache,
        }

        import core.config as config

        config.today_stats_cache = cache_data
        config.today_stats_cache_time = now

        return cache_data


@router.get("/stats")
async def get_stats():
    async with async_session_maker() as session:
        total_result = await session.execute(select(func.count(RequestLog.id)))
        total_requests = total_result.scalar() or 0

        tokens_result = await session.execute(
            select(func.sum(RequestLog.tokens["total_tokens"].as_integer()))
        )
        total_tokens = tokens_result.scalar() or 0

        errors_result = await session.execute(
            select(func.count(RequestLog.id)).where(RequestLog.status == "error")
        )
        total_errors = errors_result.scalar() or 0

        now = datetime.now()
        minute_key = now.strftime("%Y%m%d_%H%M")
        rpm = stats["requests_per_minute"].count(minute_key)

        return {
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "requests_per_minute": rpm,
            "providers": dict(stats["providers"]),
            "models": dict(stats["models"]),
        }


def get_period_range(
    period: str, now: datetime
) -> tuple[datetime, list[str], callable]:
    from dateutil.relativedelta import relativedelta

    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        intervals = [
            ((start + timedelta(hours=i)).strftime("%H:00")) for i in range(24)
        ]
        format_func = lambda d: d.strftime("%H:00")
    elif period == "week":
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        intervals = [((start + timedelta(days=i)).strftime("%m/%d")) for i in range(7)]
        format_func = lambda d: d.strftime("%m/%d")
    elif period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days_in_month = (
            now.replace(month=now.month % 12 + 1, day=1) - timedelta(days=1)
        ).day
        intervals = [
            ((start + timedelta(days=i)).strftime("%m/%d"))
            for i in range(days_in_month)
        ]
        format_func = lambda d: d.strftime("%m/%d")
    else:
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        intervals = [
            (start + relativedelta(months=i)).strftime("%Y-%m") for i in range(12)
        ]
        format_func = lambda d: d.strftime("%Y-%m")

    return start, intervals, format_func


async def get_today_realtime_stats(
    dimension: str, start: datetime
) -> tuple[dict, dict]:
    cache = await get_cached_today_stats(start)
    return cache.get(dimension, {}), {}


async def get_aggregated_stats(dimension: str, start: datetime, end: datetime) -> dict:
    async with async_session_maker() as session:
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        if dimension == "provider":
            table = ProviderDailyStat
            name_col = ProviderDailyStat.provider_name
        elif dimension == "api_key":
            table = ApiKeyDailyStat
            name_col = ApiKeyDailyStat.api_key_id
        else:
            table = ModelDailyStat
            name_col = ModelDailyStat.model_name

        result = await session.execute(
            select(
                name_col,
                func.sum(table.requests).label("requests"),
                func.sum(table.tokens).label("tokens"),
                func.sum(table.errors).label("errors"),
            )
            .where(and_(table.date >= start_str, table.date < end_str))
            .group_by(name_col)
        )
        rows = result.fetchall()

        stats_data = {}
        for row in rows:
            key = row[0]
            if dimension == "api_key" and isinstance(key, int):
                key_info = None
                for k, v in api_keys_cache.items():
                    if v["id"] == key:
                        key_info = v
                        break
                key = key_info["name"] if key_info else f"Key-{key}"

            stats_data[key] = {
                "requests": row.requests or 0,
                "tokens": row.tokens or 0,
                "errors": row.errors or 0,
            }

        return stats_data


@router.get("/stats/aggregate")
async def get_aggregate_stats(
    dimension: Literal["provider", "api_key", "model"] = "provider",
    period: Literal["day", "week", "month", "year"] = "day",
):
    async with async_session_maker() as session:
        now_result = await session.execute(select(func.now()))
        now = now_result.scalar()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start, intervals, format_func = get_period_range(period, now)

    stats_data = {}

    if start < today_start:
        end = today_start
        stats_data = await get_aggregated_stats(dimension, start, end)

    today_stats, _ = await get_today_realtime_stats(dimension, today_start)
    for key, data in today_stats.items():
        if key not in stats_data:
            stats_data[key] = {"requests": 0, "tokens": 0, "errors": 0}
        stats_data[key]["requests"] += data["requests"]
        stats_data[key]["tokens"] += data["tokens"]
        stats_data[key]["errors"] += data["errors"]

    total_requests = sum(d["requests"] for d in stats_data.values())
    total_tokens = sum(d["tokens"] for d in stats_data.values())
    total_errors = sum(d["errors"] for d in stats_data.values())

    return {
        "dimension": dimension,
        "period": period,
        "total_requests": total_requests,
        "total_tokens": total_tokens,
        "total_errors": total_errors,
        "data": stats_data,
    }


@router.get("/stats/trend")
async def get_trend_data(
    dimension: Literal["provider", "api_key", "model"] = "provider",
    period: Literal["day", "week", "month", "year"] = "day",
    name: Optional[str] = None,
):
    async with async_session_maker() as session:
        now_result = await session.execute(select(func.now()))
        now = now_result.scalar()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start, intervals, format_func = get_period_range(period, now)

    trend_data = {
        label: {"requests": 0, "tokens": 0, "errors": 0} for label in intervals
    }

    if period == "day":
        async with async_session_maker() as session:
            query = select(RequestLog).where(RequestLog.created_at >= start)
            result = await session.execute(query)
            logs = result.scalars().all()

            provider_cache = {}
            for log in logs:
                if dimension == "provider":
                    key = None
                    if log.provider_id:
                        if log.provider_id not in provider_cache:
                            prov_result = await session.execute(
                                select(Provider).where(Provider.id == log.provider_id)
                            )
                            prov = prov_result.scalar_one_or_none()
                            provider_cache[log.provider_id] = (
                                prov.name if prov else None
                            )
                        key = provider_cache.get(log.provider_id)
                elif dimension == "api_key":
                    if log.api_key_id:
                        key_info = None
                        for k, v in api_keys_cache.items():
                            if v["id"] == log.api_key_id:
                                key_info = v
                                break
                        key = key_info["name"] if key_info else f"Key-{log.api_key_id}"
                    else:
                        key = None
                else:
                    key = log.model

                if name and key != name:
                    continue

                label = format_func(log.created_at)
                if label in trend_data:
                    tokens = (
                        (log.tokens or {}).get("total_tokens")
                        or (log.tokens or {}).get("estimated")
                        or 0
                    )
                    trend_data[label]["requests"] += 1
                    trend_data[label]["tokens"] += tokens
                    if log.status == "error":
                        trend_data[label]["errors"] += 1
    else:
        async with async_session_maker() as session:
            if dimension == "provider":
                table = ProviderDailyStat
                name_col = ProviderDailyStat.provider_name
            elif dimension == "api_key":
                table = ApiKeyDailyStat
                name_col = ApiKeyDailyStat.api_key_id
            else:
                table = ModelDailyStat
                name_col = ModelDailyStat.model_name

            start_str = start.strftime("%Y-%m-%d")
            today_str = today_start.strftime("%Y-%m-%d")
            query = select(table).where(
                and_(table.date >= start_str, table.date < today_str)
            )
            if name:
                query = query.where(name_col == name)

            result = await session.execute(query)
            rows = result.scalars().all()

            for row in rows:
                if dimension == "api_key":
                    key = row.api_key_id
                    key_info = None
                    for k, v in api_keys_cache.items():
                        if v["id"] == key:
                            key_info = v
                            break
                    key = key_info["name"] if key_info else f"Key-{key}"
                else:
                    key = (
                        row.provider_name if dimension == "provider" else row.model_name
                    )

                row_dt = datetime.strptime(row.date, "%Y-%m-%d")
                label = format_func(row_dt)
                if label in trend_data:
                    trend_data[label]["requests"] += row.requests or 0
                    trend_data[label]["tokens"] += row.tokens or 0
                    trend_data[label]["errors"] += row.errors or 0

        cache = await get_cached_today_stats(today_start)
        today_logs = cache.get("logs", [])
        provider_cache = cache.get("provider_cache", {})

        for log in today_logs:
            if dimension == "provider":
                key = provider_cache.get(log.provider_id)
            elif dimension == "api_key":
                if log.api_key_id:
                    key_info = None
                    for k, v in api_keys_cache.items():
                        if v["id"] == log.api_key_id:
                            key_info = v
                            break
                    key = key_info["name"] if key_info else f"Key-{log.api_key_id}"
                else:
                    key = None
            else:
                key = log.model

            if name and key != name:
                continue

            label = format_func(log.created_at)
            if label in trend_data:
                tokens = (
                    (log.tokens or {}).get("total_tokens")
                    or (log.tokens or {}).get("estimated")
                    or 0
                )
                trend_data[label]["requests"] += 1
                trend_data[label]["tokens"] += tokens
                if log.status == "error":
                    trend_data[label]["errors"] += 1

    return {
        "dimension": dimension,
        "period": period,
        "name": name,
        "intervals": intervals,
        "data": trend_data,
    }


@router.get("/stats/period")
async def get_stats_period(period: str = "day"):
    async with async_session_maker() as session:
        now_result = await session.execute(select(func.now()))
        now = now_result.scalar()

    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)

    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session_maker() as session:
        total_result = await session.execute(
            select(func.count(RequestLog.id)).where(RequestLog.created_at >= start)
        )
        total_requests = total_result.scalar() or 0

        tokens_result = await session.execute(
            select(
                func.sum(
                    func.coalesce(
                        RequestLog.tokens["total_tokens"].as_integer(),
                        RequestLog.tokens["estimated"].as_integer(),
                        0,
                    )
                )
            ).where(RequestLog.created_at >= start)
        )
        total_tokens = tokens_result.scalar() or 0

        errors_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.created_at >= start, RequestLog.status == "error"
            )
        )
        total_errors = errors_result.scalar() or 0

        provider_result = await session.execute(
            select(
                RequestLog.model,
                func.count(RequestLog.id).label("count"),
                func.sum(
                    func.coalesce(
                        RequestLog.tokens["total_tokens"].as_integer(),
                        RequestLog.tokens["estimated"].as_integer(),
                        0,
                    )
                ).label("tokens"),
            )
            .where(RequestLog.created_at >= start)
            .group_by(RequestLog.model)
        )
        model_stats = {
            row.model: {"requests": row.count, "tokens": row.tokens or 0}
            for row in provider_result
        }

        api_key_result = await session.execute(
            select(
                RequestLog.api_key_id,
                func.count(RequestLog.id).label("count"),
                func.sum(
                    func.coalesce(
                        RequestLog.tokens["total_tokens"].as_integer(),
                        RequestLog.tokens["estimated"].as_integer(),
                        0,
                    )
                ).label("tokens"),
            )
            .where(RequestLog.created_at >= start)
            .group_by(RequestLog.api_key_id)
        )
        api_key_stats = {}
        for row in api_key_result:
            if row.api_key_id:
                key_result = await session.execute(
                    select(ApiKey).where(ApiKey.id == row.api_key_id)
                )
                key = key_result.scalar_one_or_none()
                name = key.name if key else f"Key {row.api_key_id}"
                api_key_stats[name] = {"requests": row.count, "tokens": row.tokens or 0}

        provider_stats = {}
        for model, data in model_stats.items():
            prov_result = await session.execute(
                select(RequestLog.provider_id)
                .where(RequestLog.model == model)
                .distinct()
            )
            prov_ids = [r[0] for r in prov_result.fetchall() if r[0]]
            for prov_id in prov_ids:
                p_result = await session.execute(
                    select(Provider).where(Provider.id == prov_id)
                )
                p = p_result.scalar_one_or_none()
                if p:
                    if p.name not in provider_stats:
                        provider_stats[p.name] = {"requests": 0, "tokens": 0}
                    provider_stats[p.name]["requests"] += data["requests"]
                    provider_stats[p.name]["tokens"] += data["tokens"]

        return {
            "period": period,
            "start": start.isoformat(),
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "providers": provider_stats,
            "api_keys": api_key_stats,
            "models": model_stats,
        }


@router.get("/stats/chart")
async def get_chart_data(
    period: str = "day",
    provider: Optional[str] = None,
    api_key_id: Optional[int] = None,
):
    async with async_session_maker() as session:
        now_result = await session.execute(select(func.now()))
        now = now_result.scalar()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    start, intervals, format_func = get_period_range(period, now)

    async with async_session_maker() as session:
        query = select(RequestLog).where(RequestLog.created_at >= start)
        if provider:
            query = query.where(RequestLog.model.ilike(f"%{provider}%"))
        if api_key_id:
            query = query.where(RequestLog.api_key_id == api_key_id)

        result = await session.execute(query)
        logs = result.scalars().all()

        data = {label: {"requests": 0, "tokens": 0, "errors": 0} for label in intervals}

        for log in logs:
            label = format_func(log.created_at)
            if label in data:
                data[label]["requests"] += 1
                tokens = (
                    (log.tokens or {}).get("total_tokens")
                    or (log.tokens or {}).get("estimated")
                    or 0
                )
                data[label]["tokens"] += tokens
                if log.status == "error":
                    data[label]["errors"] += 1

        provider_stats = {}
        provider_cache = {}
        for log in logs:
            provider_name = None
            if log.provider_id:
                if log.provider_id not in provider_cache:
                    p_result = await session.execute(
                        select(Provider).where(Provider.id == log.provider_id)
                    )
                    p = p_result.scalar_one_or_none()
                    provider_cache[log.provider_id] = p.name if p else None
                provider_name = provider_cache.get(log.provider_id)
            if provider_name:
                if provider_name not in provider_stats:
                    provider_stats[provider_name] = {"requests": 0, "tokens": 0}
                provider_stats[provider_name]["requests"] += 1
                tokens = (
                    (log.tokens or {}).get("total_tokens")
                    or (log.tokens or {}).get("estimated")
                    or 0
                )
                provider_stats[provider_name]["tokens"] += tokens

        api_key_stats = {}
        for log in logs:
            kid = log.api_key_id
            if kid:
                key_info = None
                for k, v in api_keys_cache.items():
                    if v["id"] == kid:
                        key_info = v
                        break
                if key_info:
                    name = key_info["name"]
                    if name not in api_key_stats:
                        api_key_stats[name] = {"requests": 0, "tokens": 0}
                    api_key_stats[name]["requests"] += 1
                    tokens = (
                        (log.tokens or {}).get("total_tokens")
                        or (log.tokens or {}).get("estimated")
                        or 0
                    )
                    api_key_stats[name]["tokens"] += tokens

        return {
            "period": period,
            "intervals": intervals,
            "data": data,
            "providers": provider_stats,
            "api_keys": api_key_stats,
        }


@router.post("/stats/reaggregate")
async def reaggregate_all_stats():
    from services.stats_aggregator import (
        backfill_historical_stats,
        aggregate_stats_for_date,
    )
    from datetime import date

    today = date.today().strftime("%Y-%m-%d")
    await aggregate_stats_for_date(today)
    await backfill_historical_stats()
    return {"status": "ok", "message": "Stats re-aggregated"}


@router.get("/stats/active")
async def get_active_sessions():
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog).where(
                RequestLog.created_at >= func.now() - timedelta(minutes=1)
            )
        )
        logs = result.scalars().all()

        active_sessions = {}
        for log in logs:
            if not log.api_key_id:
                continue

            key_info = None
            for k, v in api_keys_cache.items():
                if v["id"] == log.api_key_id:
                    key_info = v
                    break

            key_name = key_info["name"] if key_info else f"Key-{log.api_key_id}"

            if key_name not in active_sessions:
                active_sessions[key_name] = {
                    "api_key_id": log.api_key_id,
                    "models": {},
                    "requests": 0,
                    "last_activity": log.created_at.isoformat(),
                }

            active_sessions[key_name]["requests"] += 1
            if log.created_at.isoformat() > active_sessions[key_name]["last_activity"]:
                active_sessions[key_name]["last_activity"] = log.created_at.isoformat()

            if log.model:
                if log.model not in active_sessions[key_name]["models"]:
                    active_sessions[key_name]["models"][log.model] = 0
                active_sessions[key_name]["models"][log.model] += 1

        return {
            "active_count": len(active_sessions),
            "sessions": active_sessions,
        }


@router.get("/stats/active/models")
async def get_active_sessions_by_model():
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog).where(
                RequestLog.created_at >= func.now() - timedelta(minutes=1)
            )
        )
        logs = result.scalars().all()

        model_sessions = {}
        for log in logs:
            if not log.model:
                continue

            model = log.model
            if model not in model_sessions:
                model_sessions[model] = {
                    "requests": 0,
                    "last_activity": log.created_at.isoformat(),
                }

            model_sessions[model]["requests"] += 1
            if log.created_at.isoformat() > model_sessions[model]["last_activity"]:
                model_sessions[model]["last_activity"] = log.created_at.isoformat()

        return {
            "active_count": len(model_sessions),
            "sessions": model_sessions,
        }


@router.get("/stats/realtime")
async def get_realtime_stats():
    now = datetime.now()
    current_second = now.strftime("%Y%m%d_%H%M%S")

    current_second_requests = sum(
        v for k, v in requests_per_second if k == current_second
    )
    current_second_tokens = sum(v for k, v in tokens_per_second if k == current_second)

    last_60_seconds = []
    for i in range(60):
        sec = (now - timedelta(seconds=i)).strftime("%Y%m%d_%H%M%S")
        reqs = sum(v for k, v in requests_per_second if k == sec)
        toks = sum(v for k, v in tokens_per_second if k == sec)
        last_60_seconds.append(
            {
                "second": (now - timedelta(seconds=i)).strftime("%H:%M:%S"),
                "requests": reqs,
                "tokens": toks,
            }
        )

    last_60_seconds.reverse()

    return {
        "requests_per_second": current_second_requests,
        "tokens_per_second": current_second_tokens,
        "history": last_60_seconds,
    }


@router.get("/stats/slow")
async def get_slow_requests():
    now_ts = time.time()

    slow_pending = []
    for req_id, req_info in pending_requests.items():
        elapsed = now_ts - req_info["start_time"]
        if elapsed >= 60:
            slow_pending.append(
                {
                    "id": req_id,
                    "provider": req_info["provider"],
                    "model": req_info["model"],
                    "key_name": req_info["key_name"],
                    "elapsed_seconds": round(elapsed, 1),
                    "stream": req_info["stream"],
                    "start_time": datetime.fromtimestamp(
                        req_info["start_time"]
                    ).isoformat(),
                }
            )

    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog)
            .where(
                RequestLog.created_at >= func.now() - timedelta(hours=1),
                RequestLog.latency_ms >= 60000,
            )
            .order_by(RequestLog.latency_ms.desc())
            .limit(50)
        )
        slow_logs = result.scalars().all()

        slow_completed = []
        for log in slow_logs:
            key_name = None
            if log.api_key_id:
                for k, v in api_keys_cache.items():
                    if v["id"] == log.api_key_id:
                        key_name = v["name"]
                        break
                if not key_name:
                    key_name = f"Key-{log.api_key_id}"

            provider_name = None
            if log.provider_id:
                prov_result = await session.execute(
                    select(Provider).where(Provider.id == log.provider_id)
                )
                prov = prov_result.scalar_one_or_none()
                provider_name = prov.name if prov else None

            slow_completed.append(
                {
                    "id": log.id,
                    "provider": provider_name,
                    "model": log.model,
                    "key_name": key_name,
                    "latency_ms": round(log.latency_ms, 0),
                    "status": log.status,
                    "created_at": log.created_at.isoformat(),
                }
            )

    return {
        "pending": slow_pending,
        "completed": slow_completed,
    }
