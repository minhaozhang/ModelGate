from datetime import datetime, timedelta
from typing import Optional, Literal
from fastapi import APIRouter, Cookie, Depends, HTTPException
from sqlalchemy import select, func, and_, or_, case

from core.database import (
    async_session_maker,
    RequestLog,
    ApiKey,
    Provider,
    ProviderDailyStat,
    ApiKeyDailyStat,
    ModelDailyStat,
)
import core.config as config_module
from core.config import (
    api_keys_cache,
    stats,
    TODAY_STATS_CACHE_TTL_SECONDS,
    requests_per_second,
    tokens_per_second,
)

router = APIRouter(prefix="/admin/api", tags=["stats"])
ERROR_STATUS = "error"
TIMEOUT_STATUS = "timeout"
ERROR_STATUSES = (ERROR_STATUS, TIMEOUT_STATUS)


def require_admin(session: Optional[str] = Cookie(None)):
    from core.config import validate_session
    if not validate_session(session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


def get_local_now() -> datetime:
    now = datetime.now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return now


def get_period_start(period: str, now: datetime) -> datetime:
    if period == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        start = now - timedelta(days=now.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == "year":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def get_cached_today_stats(start: datetime) -> dict:
    from core.config import proxy_logger

    now = datetime.now()
    cache_key = start.strftime("%Y-%m-%d")

    if (
        config_module.today_stats_cache_time
        and (now - config_module.today_stats_cache_time).total_seconds()
        < TODAY_STATS_CACHE_TTL_SECONDS
        and config_module.today_stats_cache.get("date") == cache_key
    ):
        return config_module.today_stats_cache

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
            is_error = log.status in ERROR_STATUSES

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

        config_module.today_stats_cache = cache_data
        config_module.today_stats_cache_time = now

        return cache_data


@router.get("/stats")
async def get_stats(_: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        total_result = await session.execute(select(func.count(RequestLog.id)))
        total_requests = total_result.scalar() or 0

        tokens_result = await session.execute(
            select(func.sum(RequestLog.tokens["total_tokens"].as_integer()))
        )
        total_tokens = tokens_result.scalar() or 0

        errors_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.status.in_(ERROR_STATUSES)
            )
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
        intervals = [
            ((start + timedelta(hours=6 * i)).strftime("%m/%d %H:%M"))
            for i in range(28)
        ]
        format_func = lambda d: d.replace(
            hour=(d.hour // 6) * 6,
            minute=0,
            second=0,
            microsecond=0,
        ).strftime("%m/%d %H:%M")
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
    _: bool = Depends(require_admin),
):
    now = get_local_now()
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
    _: bool = Depends(require_admin),
):
    now = get_local_now()
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
                    if log.status in ERROR_STATUSES:
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
                if log.status in ERROR_STATUSES:
                    trend_data[label]["errors"] += 1

    return {
        "dimension": dimension,
        "period": period,
        "name": name,
        "intervals": intervals,
        "data": trend_data,
    }


@router.get("/stats/monitor-details")
async def get_monitor_details(
    period: Literal["day", "week", "month", "year"] = "day",
    _: bool = Depends(require_admin),
):
    now = get_local_now()
    start = get_period_start(period, now)
    _, intervals, format_func = get_period_range(period, now)
    trend_data = {
        label: {"requests": 0, "tokens": 0, "errors": 0, "timeouts": 0}
        for label in intervals
    }

    async with async_session_maker() as session:
        total_errors_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.created_at >= start,
                RequestLog.status == ERROR_STATUS,
            )
        )
        total_errors = total_errors_result.scalar() or 0

        total_timeouts_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.created_at >= start,
                RequestLog.status == TIMEOUT_STATUS,
            )
        )
        total_timeouts = total_timeouts_result.scalar() or 0

        provider_rows_result = await session.execute(
            select(
                RequestLog.provider_id.label("group_key"),
                func.count(RequestLog.id).label("requests"),
                func.sum(
                    case((RequestLog.status == ERROR_STATUS, 1), else_=0)
                ).label("errors"),
                func.sum(
                    case((RequestLog.status == TIMEOUT_STATUS, 1), else_=0)
                ).label("timeouts"),
            )
            .where(RequestLog.created_at >= start)
            .group_by(RequestLog.provider_id)
        )
        provider_rows = provider_rows_result.fetchall()

        api_key_rows_result = await session.execute(
            select(
                RequestLog.api_key_id.label("group_key"),
                func.count(RequestLog.id).label("requests"),
                func.sum(
                    case((RequestLog.status == ERROR_STATUS, 1), else_=0)
                ).label("errors"),
                func.sum(
                    case((RequestLog.status == TIMEOUT_STATUS, 1), else_=0)
                ).label("timeouts"),
            )
            .where(RequestLog.created_at >= start)
            .group_by(RequestLog.api_key_id)
        )
        api_key_rows = api_key_rows_result.fetchall()

        model_rows_result = await session.execute(
            select(
                RequestLog.model.label("group_key"),
                func.count(RequestLog.id).label("requests"),
                func.sum(
                    case((RequestLog.status == ERROR_STATUS, 1), else_=0)
                ).label("errors"),
                func.sum(
                    case((RequestLog.status == TIMEOUT_STATUS, 1), else_=0)
                ).label("timeouts"),
            )
            .where(RequestLog.created_at >= start)
            .group_by(RequestLog.model)
        )
        model_rows = model_rows_result.fetchall()

        provider_ids = [row.group_key for row in provider_rows if row.group_key]
        api_key_ids = [row.group_key for row in api_key_rows if row.group_key]

        providers_map: dict[int, str] = {}
        if provider_ids:
            providers_result = await session.execute(
                select(Provider).where(Provider.id.in_(provider_ids))
            )
            providers_map = {
                provider.id: provider.name for provider in providers_result.scalars()
            }

        api_keys_map: dict[int, str] = {}
        if api_key_ids:
            api_keys_result = await session.execute(
                select(ApiKey).where(ApiKey.id.in_(api_key_ids))
            )
            api_keys_map = {
                api_key.id: api_key.name for api_key in api_keys_result.scalars()
            }

        trend_logs_result = await session.execute(
            select(
                RequestLog.created_at,
                RequestLog.status,
                RequestLog.tokens,
            ).where(RequestLog.created_at >= start)
        )
        trend_logs = trend_logs_result.fetchall()
        for log in trend_logs:
            label = format_func(log.created_at)
            if label not in trend_data:
                continue
            tokens = (log.tokens or {}).get("total_tokens") or (
                log.tokens or {}
            ).get("estimated") or 0
            trend_data[label]["requests"] += 1
            trend_data[label]["tokens"] += tokens
            if log.status == ERROR_STATUS:
                trend_data[label]["errors"] += 1
            elif log.status == TIMEOUT_STATUS:
                trend_data[label]["timeouts"] += 1

        top_models_result = await session.execute(
            select(
                RequestLog.model,
                func.count(RequestLog.id).label("requests"),
            )
            .where(
                RequestLog.created_at >= start,
                RequestLog.latency_ms.is_not(None),
                RequestLog.status != "pending",
                RequestLog.model.is_not(None),
            )
            .group_by(RequestLog.model)
            .order_by(func.count(RequestLog.id).desc())
            .limit(8)
        )
        top_models = [row.model for row in top_models_result.fetchall() if row.model]

        latency_intervals = [f"{hour:02d}:00" for hour in range(24)]
        latency_series: dict[str, dict[str, list]] = {}
        if top_models:
            latency_series = {
                model: {
                    "latency_ms": [None] * 24,
                    "samples": [0] * 24,
                }
                for model in top_models
            }
            latency_rows_result = await session.execute(
                select(
                    RequestLog.model,
                    func.extract("hour", RequestLog.created_at).label("hour_of_day"),
                    func.avg(RequestLog.latency_ms).label("avg_latency_ms"),
                    func.count(RequestLog.id).label("samples"),
                )
                .where(
                    RequestLog.created_at >= start,
                    RequestLog.model.in_(top_models),
                    RequestLog.latency_ms.is_not(None),
                    RequestLog.status != "pending",
                )
                .group_by(RequestLog.model, func.extract("hour", RequestLog.created_at))
                .order_by(RequestLog.model, func.extract("hour", RequestLog.created_at))
            )
            for row in latency_rows_result.fetchall():
                model_name = row.model
                if not model_name or model_name not in latency_series:
                    continue
                hour_of_day = int(row.hour_of_day or 0)
                if hour_of_day < 0 or hour_of_day > 23:
                    continue
                latency_series[model_name]["latency_ms"][hour_of_day] = round(
                    row.avg_latency_ms or 0, 1
                )
                latency_series[model_name]["samples"][hour_of_day] = int(
                    row.samples or 0
                )

    def build_status_entries(rows, scope: str, resolver, masked: bool = False) -> list[dict]:
        entries = []
        for row in rows:
            group_key = row.group_key
            if group_key is None:
                continue
            name = resolver(group_key)
            if not name:
                continue
            requests = row.requests or 0
            errors = row.errors or 0
            timeouts = row.timeouts or 0
            entries.append(
                {
                    "scope": scope,
                    "name": name,
                    "masked": masked,
                    "requests": requests,
                    "errors": errors,
                    "timeouts": timeouts,
                    "error_rate": (errors / requests) if requests else 0,
                    "timeout_rate": (timeouts / requests) if requests else 0,
                }
            )
        return entries

    provider_entries = build_status_entries(
        provider_rows,
        "provider",
        lambda provider_id: providers_map.get(provider_id),
    )
    api_key_entries = build_status_entries(
        api_key_rows,
        "api_key",
        lambda api_key_id: api_keys_map.get(api_key_id, f"Key-{api_key_id}"),
        masked=True,
    )
    model_entries = build_status_entries(
        model_rows,
        "model",
        lambda model_name: model_name,
    )

    all_entries = provider_entries + api_key_entries + model_entries
    error_hotspots = sorted(
        [item for item in all_entries if item["requests"] >= 3 and item["errors"] > 0],
        key=lambda item: (item["error_rate"], item["errors"], item["requests"]),
        reverse=True,
    )[:6]
    timeout_hotspots = sorted(
        [item for item in all_entries if item["requests"] >= 3 and item["timeouts"] > 0],
        key=lambda item: (item["timeouts"], item["timeout_rate"], item["requests"]),
        reverse=True,
    )[:6]

    return {
        "period": period,
        "start": start.isoformat(),
        "total_errors": total_errors,
        "total_timeouts": total_timeouts,
        "trend": {
            "intervals": intervals,
            "data": trend_data,
        },
        "error_hotspots": error_hotspots,
        "timeout_hotspots": timeout_hotspots,
        "latency": {
            "models": top_models,
            "intervals": latency_intervals,
            "series": latency_series,
        },
    }


@router.get("/stats/period")
async def get_stats_period(period: str = "day", _: bool = Depends(require_admin)):
    now = get_local_now()

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
                RequestLog.created_at >= start,
                RequestLog.status.in_(ERROR_STATUSES),
            )
        )
        total_errors = errors_result.scalar() or 0

        logs_result = await session.execute(
            select(RequestLog).where(RequestLog.created_at >= start)
        )
        logs = logs_result.scalars().all()

        provider_ids = {log.provider_id for log in logs if log.provider_id}
        api_key_ids = {log.api_key_id for log in logs if log.api_key_id}

        providers_map = {}
        if provider_ids:
            providers_result = await session.execute(
                select(Provider).where(Provider.id.in_(provider_ids))
            )
            providers_map = {provider.id: provider.name for provider in providers_result.scalars()}

        api_keys_map = {}
        if api_key_ids:
            api_keys_result = await session.execute(
                select(ApiKey).where(ApiKey.id.in_(api_key_ids))
            )
            api_keys_map = {api_key.id: api_key.name for api_key in api_keys_result.scalars()}

        model_stats = {}
        provider_stats = {}
        api_key_stats = {}

        for log in logs:
            tokens = (
                (log.tokens or {}).get("total_tokens")
                or (log.tokens or {}).get("estimated")
                or 0
            )

            if log.model:
                if log.model not in model_stats:
                    model_stats[log.model] = {"requests": 0, "tokens": 0}
                model_stats[log.model]["requests"] += 1
                model_stats[log.model]["tokens"] += tokens

            provider_name = providers_map.get(log.provider_id)
            if provider_name:
                if provider_name not in provider_stats:
                    provider_stats[provider_name] = {
                        "requests": 0,
                        "tokens": 0,
                        "models": {},
                    }
                provider_stats[provider_name]["requests"] += 1
                provider_stats[provider_name]["tokens"] += tokens
                if log.model:
                    models = provider_stats[provider_name]["models"]
                    if log.model not in models:
                        models[log.model] = {"requests": 0, "tokens": 0}
                    models[log.model]["requests"] += 1
                    models[log.model]["tokens"] += tokens

            api_key_name = api_keys_map.get(log.api_key_id)
            if api_key_name:
                if api_key_name not in api_key_stats:
                    api_key_stats[api_key_name] = {
                        "requests": 0,
                        "tokens": 0,
                        "models": {},
                    }
                api_key_stats[api_key_name]["requests"] += 1
                api_key_stats[api_key_name]["tokens"] += tokens
                if log.model:
                    models = api_key_stats[api_key_name]["models"]
                    if log.model not in models:
                        models[log.model] = {"requests": 0, "tokens": 0}
                    models[log.model]["requests"] += 1
                    models[log.model]["tokens"] += tokens

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
    _: bool = Depends(require_admin),
):
    now = get_local_now()
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
                if log.status in ERROR_STATUSES:
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
async def reaggregate_all_stats(_: bool = Depends(require_admin)):
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
async def get_active_sessions(_: bool = Depends(require_admin)):
    recent_cutoff = get_local_now() - timedelta(seconds=30)
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog)
            .where(
                or_(
                    RequestLog.status == "pending",
                    RequestLog.created_at >= recent_cutoff,
                )
            )
            .order_by(RequestLog.created_at.desc())
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

        ordered_sessions = dict(
            sorted(
                active_sessions.items(),
                key=lambda item: item[1]["last_activity"],
                reverse=True,
            )
        )

        return {
            "active_count": len(ordered_sessions),
            "sessions": ordered_sessions,
        }


@router.get("/stats/active/models")
async def get_active_sessions_by_model(_: bool = Depends(require_admin)):
    recent_cutoff = get_local_now() - timedelta(seconds=30)
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog)
            .where(
                or_(
                    RequestLog.status == "pending",
                    RequestLog.created_at >= recent_cutoff,
                )
            )
            .order_by(RequestLog.created_at.desc())
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

        ordered_sessions = dict(
            sorted(
                model_sessions.items(),
                key=lambda item: item[1]["last_activity"],
                reverse=True,
            )
        )

        return {
            "active_count": len(ordered_sessions),
            "sessions": ordered_sessions,
        }


@router.get("/stats/realtime")
async def get_realtime_stats(_: bool = Depends(require_admin)):
    now = datetime.now()
    cutoff = (now - timedelta(seconds=10)).strftime("%Y%m%d_%H%M%S")

    reqs_by_second: dict[str, int] = {}
    for k, v in requests_per_second:
        if k >= cutoff:
            reqs_by_second[k] = reqs_by_second.get(k, 0) + v

    tokens_by_second: dict[str, int] = {}
    for k, v in tokens_per_second:
        if k >= cutoff:
            tokens_by_second[k] = tokens_by_second.get(k, 0) + v

    req_active_seconds = max(len(reqs_by_second), 1)
    token_active_seconds = max(len([v for v in tokens_by_second.values() if v > 0]), 1)
    total_requests = sum(reqs_by_second.values())
    total_tokens = sum(tokens_by_second.values())

    return {
        "requests_per_second": round(total_requests / req_active_seconds, 1),
        "tokens_per_second": round(total_tokens / token_active_seconds, 1),
    }


@router.get("/stats/slow")
async def get_slow_requests(_: bool = Depends(require_admin)):
    slow_pending = []
    now = get_local_now()
    pending_cutoff = now - timedelta(seconds=60)
    completed_cutoff = now - timedelta(hours=1)
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog)
            .where(
                RequestLog.status == "pending",
                RequestLog.created_at <= pending_cutoff,
            )
            .order_by(RequestLog.created_at.asc())
            .limit(50)
        )
        pending_logs = result.scalars().all()

        for log in pending_logs:
            elapsed = max((now - log.created_at).total_seconds(), 0)

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

            slow_pending.append(
                {
                    "id": log.id,
                    "provider": provider_name,
                    "model": log.model,
                    "key_name": key_name,
                    "elapsed_seconds": round(elapsed, 1),
                    "stream": True,
                    "start_time": log.created_at.isoformat(),
                }
            )

        result = await session.execute(
            select(RequestLog)
            .where(
                RequestLog.created_at >= completed_cutoff,
                RequestLog.latency_ms.is_not(None),
                RequestLog.latency_ms >= 60000,
            )
            .order_by(RequestLog.latency_ms.desc())
            .limit(50)
        )
        slow_logs = result.scalars().all()

        slow_completed = []
        for log in slow_logs:
            if log.latency_ms is None:
                continue

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
