from datetime import datetime, timedelta
from typing import Optional, Literal
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy import select, func, and_, or_, case, literal, literal_column
from sqlalchemy.types import Numeric

from app.core.database import (
    async_session_maker,
    RequestLog,
    ApiKey,
    ApiKeyTag,
    Provider,
    ProviderKey,
    ProviderDailyStat,
    ApiKeyDailyStat,
    ApiKeyModelDailyStat,
    ModelDailyStat,
)
import app.core.config as config_module
from app.services.logging import IN_FLIGHT_STATUSES
from app.core.config import (
    add_live_stats_subscriber,
    api_keys_cache,
    build_live_stats_snapshot,
    busyness_state,
    get_api_key_name,
    prune_stale_active_requests,
    remove_live_stats_subscriber,
    stats,
    TODAY_STATS_CACHE_TTL_SECONDS,
    requests_per_second,
    get_total_tokens_per_second,
)

public_router = APIRouter(prefix="/api/public", tags=["public"])
router = APIRouter(prefix="/admin/api", tags=["stats"])
ERROR_STATUS = "error"
TIMEOUT_STATUS = "timeout"
RATE_LIMITED_STATUS = "rate_limited"
LOCAL_RATE_LIMITED_STATUS = "local_rate_limited"
RATE_LIMITED_STATUSES = {RATE_LIMITED_STATUS, LOCAL_RATE_LIMITED_STATUS}
AGGREGATED_PERIODS = {"month", "year"}
TOTALS_AGGREGATED_PERIODS = {"week", "month", "year"}
WEEK_BUCKET_HOURS = 4
WEEK_BUCKET_COUNT = 42
TOKEN_COUNT_EXPR = func.coalesce(
    RequestLog.tokens["total_tokens"].as_integer(),
    RequestLog.tokens["estimated"].as_integer(),
    0,
)

from app.core.permissions import permission_required
from app.services.model_naming import (
    provider_stats_model_expr,
    user_stats_model_expr,
)

historical_stats_cache: dict = {}
historical_stats_cache_date: Optional[str] = None


def get_local_now() -> datetime:
    now = datetime.now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return now


def use_daily_aggregates(period: str) -> bool:
    return period in AGGREGATED_PERIODS


def get_day_start(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def get_week_bucket_start(dt: datetime) -> datetime:
    bucket_hour = (dt.hour // WEEK_BUCKET_HOURS) * WEEK_BUCKET_HOURS
    return dt.replace(hour=bucket_hour, minute=0, second=0, microsecond=0)


def get_token_count(tokens_payload) -> int:
    return (
        (tokens_payload or {}).get("total_tokens")
        or (tokens_payload or {}).get("estimated")
        or 0
    )


def ensure_metric_bucket(stats_map: dict, key: str) -> dict:
    if key not in stats_map:
        stats_map[key] = {
            "requests": 0,
            "tokens": 0,
            "errors": 0,
            "timeouts": 0,
            "rate_limited": 0,
        }
    return stats_map[key]


def add_metric_values(
    bucket: dict,
    requests: int = 0,
    tokens: int = 0,
    errors: int = 0,
    timeouts: int = 0,
    rate_limited: int = 0,
) -> None:
    bucket["requests"] += int(requests or 0)
    bucket["tokens"] += int(tokens or 0)
    bucket["errors"] += int(errors or 0)
    bucket["timeouts"] += int(timeouts or 0)
    bucket["rate_limited"] += int(rate_limited or 0)


def merge_named_stats(
    target: dict[str, dict], source: dict[str, dict]
) -> dict[str, dict]:
    for key, values in source.items():
        bucket = ensure_metric_bucket(target, key)
        add_metric_values(
            bucket,
            values.get("requests", 0),
            values.get("tokens", 0),
            values.get("errors", 0),
            values.get("timeouts", 0),
            values.get("rate_limited", 0),
        )
    return target


def get_api_key_name_from_cache(api_key_id: int) -> Optional[str]:
    return get_api_key_name(api_key_id)


def get_api_key_id_from_cache(name: str) -> Optional[int]:
    for value in api_keys_cache.values():
        if value["name"] == name:
            return value["id"]
    return None


async def get_provider_name_map(
    session, provider_ids: list[int] | set[int]
) -> dict[int, str]:
    provider_ids = [
        provider_id for provider_id in provider_ids if provider_id is not None
    ]
    if not provider_ids:
        return {}
    result = await session.execute(
        select(Provider).where(Provider.id.in_(provider_ids))
    )
    return {provider.id: provider.name for provider in result.scalars()}


async def get_api_key_name_map(
    session, api_key_ids: list[int] | set[int]
) -> dict[int, str]:
    api_key_ids = [api_key_id for api_key_id in api_key_ids if api_key_id is not None]
    names = {
        api_key_id: cached_name
        for api_key_id in api_key_ids
        if (cached_name := get_api_key_name_from_cache(api_key_id))
    }
    missing_ids = [api_key_id for api_key_id in api_key_ids if api_key_id not in names]
    if missing_ids:
        result = await session.execute(select(ApiKey).where(ApiKey.id.in_(missing_ids)))
        names.update({api_key.id: api_key.name for api_key in result.scalars()})
    return names


async def get_api_key_tags_map(
    session, api_key_ids: list[int] | set[int]
) -> dict[int, list[str]]:
    """Live {api_key_id: [tag, ...]} from api_key_tags."""
    api_key_ids = [i for i in api_key_ids if i is not None]
    if not api_key_ids:
        return {}
    result = await session.execute(
        select(ApiKeyTag.api_key_id, ApiKeyTag.tag).where(
            ApiKeyTag.api_key_id.in_(api_key_ids)
        )
    )
    tags_map: dict[int, list[str]] = {}
    for api_key_id, tag in result.fetchall():
        tags_map.setdefault(api_key_id, []).append(tag)
    return tags_map


def get_aggregate_window_bounds(
    start: datetime, now: datetime
) -> tuple[datetime, datetime]:
    today_start = get_day_start(now)
    return min(today_start, now), max(start, today_start)


def get_first_midnight(start: datetime) -> datetime:
    day_start = get_day_start(start)
    if start == day_start:
        return start
    return day_start + timedelta(days=1)


def get_totals_aggregate_bounds(
    start: datetime, now: datetime
) -> tuple[datetime, datetime, list[tuple[datetime, datetime]]]:
    """Daily aggregates cover full calendar days only.

    Returns (aggregate_start, aggregate_end, raw_ranges): aggregates cover
    [aggregate_start, aggregate_end); raw scans must cover the window head
    before the first full day plus today after the last aggregated day.
    """
    today_start = get_day_start(now)
    aggregate_end = min(today_start, now)
    aggregate_start = get_first_midnight(start)
    raw_ranges: list[tuple[datetime, datetime]] = []
    if start < aggregate_start:
        raw_ranges.append((start, aggregate_start))
    tail_start = max(start, today_start)
    if tail_start < now:
        raw_ranges.append((tail_start, now))
    return aggregate_start, aggregate_end, raw_ranges


def get_period_start(period: str, now: datetime) -> datetime:
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        return today_start
    if period == "week":
        bucket_start = get_week_bucket_start(now)
        return bucket_start - timedelta(
            hours=WEEK_BUCKET_HOURS * (WEEK_BUCKET_COUNT - 1)
        )
    if period == "month":
        return today_start - timedelta(days=30)
    if period == "year":
        return today_start - timedelta(days=364)
    return today_start


MONITOR_RANGE_DELTAS = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


def resolve_monitor_window(
    time_range: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str],
    now: datetime,
) -> Optional[tuple[datetime, datetime]]:
    if start_time or end_time:
        try:
            start = (
                datetime.fromisoformat(start_time)
                if start_time
                else now - timedelta(days=7)
            )
            end = datetime.fromisoformat(end_time) if end_time else now
        except ValueError:
            return None
        return start, end
    delta = MONITOR_RANGE_DELTAS.get(time_range or "")
    if delta is None:
        return None
    return now - delta, now


async def get_cached_today_stats(start: datetime) -> dict:
    from app.core.config import proxy_logger

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
        rate_limited_expr = RequestLog.status.in_(RATE_LIMITED_STATUSES)

        def _num_tokens(path: str):
            return func.nullif(RequestLog.tokens.op("->>")(path), "").cast(Numeric)

        def tokens_expr():
            # Mirrors get_token_count(): total_tokens or estimated or 0,
            # zeroed for rate-limited rows.
            return case(
                (rate_limited_expr, literal(0)),
                (_num_tokens("total_tokens") != 0, _num_tokens("total_tokens")),
                (_num_tokens("estimated") != 0, _num_tokens("estimated")),
                else_=literal(0),
            )

        def metric_cols():
            return [
                func.sum(case((~rate_limited_expr, 1), else_=0)).label("requests"),
                func.sum(tokens_expr()).label("tokens"),
                func.sum(case((RequestLog.status == ERROR_STATUS, 1), else_=0)).label("errors"),
                func.sum(case((RequestLog.status == TIMEOUT_STATUS, 1), else_=0)).label("timeouts"),
                func.sum(case((rate_limited_expr, 1), else_=0)).label("rate_limited"),
            ]

        def to_metrics(row) -> dict:
            return {
                "requests": int(row.requests or 0),
                "tokens": int(row.tokens or 0),
                "errors": int(row.errors or 0),
                "timeouts": int(row.timeouts or 0),
                "rate_limited": int(row.rate_limited or 0),
            }

        prov_result = await session.execute(
            select(Provider.name.label("name"), *metric_cols())
            .select_from(RequestLog)
            .join(Provider, Provider.id == RequestLog.provider_id)
            .where(RequestLog.created_at >= start)
            .group_by(Provider.name)
        )
        provider_stats = {row.name: to_metrics(row) for row in prov_result.fetchall()}

        key_result = await session.execute(
            select(RequestLog.api_key_id.label("kid"), *metric_cols())
            .where(
                RequestLog.created_at >= start,
                RequestLog.api_key_id.isnot(None),
            )
            .group_by(RequestLog.api_key_id)
        )
        key_name_by_id = {
            v["id"]: v["name"] for v in api_keys_cache.values() if v.get("id") is not None
        }
        api_key_stats = {}
        for row in key_result.fetchall():
            key_name = key_name_by_id.get(row.kid) or f"Key-{row.kid}"
            api_key_stats[key_name] = to_metrics(row)

        model_name_expr = provider_stats_model_expr(RequestLog.model, RequestLog.actual_model)
        model_result = await session.execute(
            select(model_name_expr.label("mname"), *metric_cols())
            .where(
                RequestLog.created_at >= start,
                RequestLog.model.isnot(None),
                RequestLog.model != "",
            )
            # group by the select alias: the bound empty-string literal inside
            # the expression gets distinct param positions in SELECT vs GROUP BY,
            # which Postgres rejects when grouping by the raw expression.
            .group_by(literal_column("mname"))
        )
        model_stats = {row.mname: to_metrics(row) for row in model_result.fetchall()}

        cache_data = {
            "date": cache_key,
            "provider": provider_stats,
            "api_key": api_key_stats,
            "model": model_stats,
        }

        config_module.today_stats_cache = cache_data
        config_module.today_stats_cache_time = now

        return cache_data


@router.get("/stats")
async def get_stats(_: bool = Depends(permission_required("page.stats"))):
    now = get_local_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_str = today_start.strftime("%Y-%m-%d")

    async with async_session_maker() as session:
        hist_result = await session.execute(
            select(
                func.coalesce(func.sum(ProviderDailyStat.requests), 0).label("requests"),
                func.coalesce(func.sum(ProviderDailyStat.tokens), 0).label("tokens"),
                func.coalesce(func.sum(ProviderDailyStat.errors), 0).label("errors"),
                func.coalesce(func.sum(ProviderDailyStat.rate_limited), 0).label("rate_limited"),
            ).where(ProviderDailyStat.date < today_str)
        )
        h = hist_result.one()

    today_cache = await get_cached_today_stats(today_start)
    today_provider = today_cache.get("provider", {})
    t_req = sum(d.get("requests", 0) for d in today_provider.values())
    t_tok = sum(d.get("tokens", 0) for d in today_provider.values())
    t_err = sum(d.get("errors", 0) for d in today_provider.values())
    t_rl = sum(d.get("rate_limited", 0) for d in today_provider.values())

    minute_key = now.strftime("%Y%m%d_%H%M")
    rpm = stats["requests_per_minute"].count(minute_key)

    return {
        "total_requests": int(h.requests) + t_req,
        "total_tokens": int(h.tokens) + t_tok,
        "total_errors": int(h.errors) + t_err,
        "total_rate_limited": int(h.rate_limited) + t_rl,
        "requests_per_minute": rpm,
        "providers": dict(stats["providers"]),
        "models": dict(stats["models"]),
    }


def get_period_range(
    period: str, now: datetime
) -> tuple[datetime, list[str], callable]:
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        intervals = [
            ((start + timedelta(minutes=30 * i)).strftime("%H:%M")) for i in range(48)
        ]

        def format_func(d: datetime) -> str:
            return d.replace(
                minute=0 if d.minute < 30 else 30,
                second=0,
                microsecond=0,
            ).strftime("%H:%M")
    elif period == "week":
        current_bucket_start = get_week_bucket_start(now)
        start = current_bucket_start - timedelta(
            hours=WEEK_BUCKET_HOURS * (WEEK_BUCKET_COUNT - 1)
        )
        intervals = [
            ((start + timedelta(hours=WEEK_BUCKET_HOURS * i)).strftime("%m/%d %H:%M"))
            for i in range(WEEK_BUCKET_COUNT)
        ]

        def format_func(d: datetime) -> str:
            bucket_index = max(
                0,
                min(
                    int((d - start).total_seconds() // (WEEK_BUCKET_HOURS * 3600)),
                    len(intervals) - 1,
                ),
            )
            return intervals[bucket_index]
    elif period == "month":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=30
        )
        intervals = [((start + timedelta(days=i)).strftime("%m/%d")) for i in range(31)]

        def format_func(d: datetime) -> str:
            return d.strftime("%m/%d")
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=364
        )
        bucket_count = ((now.date() - start.date()).days // 7) + 1
        intervals = [
            (start + timedelta(days=7 * i)).strftime("%m/%d")
            for i in range(bucket_count)
        ]

        def format_func(d: datetime) -> str:
            return (
                start + timedelta(days=((d.date() - start.date()).days // 7) * 7)
            ).strftime("%m/%d")

    return start, intervals, format_func


async def get_today_realtime_stats(
    dimension: str, start: datetime
) -> tuple[dict, dict]:
    cache = await get_cached_today_stats(start)
    return cache.get(dimension, {}), {}


async def get_daily_aggregated_stats(
    session,
    dimension: str,
    start: datetime,
    end: datetime,
) -> dict[str, dict]:
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
            name_col.label("group_key"),
            func.sum(table.requests).label("requests"),
            func.sum(table.tokens).label("tokens"),
            func.sum(table.prompt_tokens).label("prompt_tokens"),
            func.sum(table.completion_tokens).label("completion_tokens"),
            func.sum(table.errors).label("errors"),
            func.sum(table.timeouts).label("timeouts"),
            func.sum(table.rate_limited).label("rate_limited"),
        )
        .where(and_(table.date >= start_str, table.date < end_str))
        .group_by(name_col)
    )
    rows = result.fetchall()

    if dimension == "provider":
        return {
            row.group_key: {
                "requests": int(row.requests or 0),
                "tokens": int(row.tokens or 0),
                "prompt_tokens": int(row.prompt_tokens or 0),
                "completion_tokens": int(row.completion_tokens or 0),
                "errors": int(row.errors or 0),
                "timeouts": int(row.timeouts or 0),
                "rate_limited": int(row.rate_limited or 0),
            }
            for row in rows
            if row.group_key
        }

    if dimension == "model":
        return {
            row.group_key: {
                "requests": int(row.requests or 0),
                "tokens": int(row.tokens or 0),
                "prompt_tokens": int(row.prompt_tokens or 0),
                "completion_tokens": int(row.completion_tokens or 0),
                "errors": int(row.errors or 0),
                "timeouts": int(row.timeouts or 0),
                "rate_limited": int(row.rate_limited or 0),
            }
            for row in rows
            if row.group_key
        }

    api_key_ids = [row.group_key for row in rows if isinstance(row.group_key, int)]
    api_key_names = await get_api_key_name_map(session, api_key_ids)
    stats_data: dict[str, dict] = {}
    for row in rows:
        if row.group_key is None:
            continue
        key = api_key_names.get(row.group_key, f"Deleted Key #{row.group_key}")
        stats_data[key] = {
            "requests": int(row.requests or 0),
            "tokens": int(row.tokens or 0),
            "prompt_tokens": int(row.prompt_tokens or 0),
            "completion_tokens": int(row.completion_tokens or 0),
            "errors": int(row.errors or 0),
            "timeouts": int(row.timeouts or 0),
            "rate_limited": int(row.rate_limited or 0),
        }
    return stats_data


async def get_raw_grouped_stats(
    session,
    dimension: str,
    start: datetime,
    *,
    end: Optional[datetime] = None,
) -> dict[str, dict]:
    filters = [RequestLog.created_at >= start]
    if end is not None:
        filters.append(RequestLog.created_at < end)

    if dimension == "provider":
        group_expr = RequestLog.provider_id
    elif dimension == "api_key":
        group_expr = RequestLog.api_key_id
    else:
        group_expr = provider_stats_model_expr(RequestLog.model, RequestLog.actual_model)

    result = await session.execute(
        select(
            group_expr.label("group_key"),
            func.sum(
                case((RequestLog.status.notin_(RATE_LIMITED_STATUSES), 1), else_=0)
            ).label("requests"),
            func.sum(
                case(
                    (RequestLog.status.notin_(RATE_LIMITED_STATUSES), TOKEN_COUNT_EXPR),
                    else_=0,
                )
            ).label("tokens"),
            func.sum(
                case(
                    (
                        RequestLog.status.notin_(RATE_LIMITED_STATUSES),
                        func.coalesce(
                            RequestLog.tokens["prompt_tokens"].as_integer(), 0
                        ),
                    ),
                    else_=0,
                )
            ).label("prompt_tokens"),
            func.sum(
                case(
                    (
                        RequestLog.status.notin_(RATE_LIMITED_STATUSES),
                        func.coalesce(
                            RequestLog.tokens["completion_tokens"].as_integer(), 0
                        ),
                    ),
                    else_=0,
                )
            ).label("completion_tokens"),
            func.sum(case((RequestLog.status == ERROR_STATUS, 1), else_=0)).label(
                "errors"
            ),
            func.sum(case((RequestLog.status == TIMEOUT_STATUS, 1), else_=0)).label(
                "timeouts"
            ),
            func.sum(
                case((RequestLog.status.in_(RATE_LIMITED_STATUSES), 1), else_=0)
            ).label("rate_limited"),
        )
        .where(*filters)
        .group_by(group_expr)
    )
    rows = result.fetchall()

    if dimension == "provider":
        provider_names = await get_provider_name_map(
            session, [row.group_key for row in rows if row.group_key is not None]
        )
        return {
            provider_names[row.group_key]: {
                "requests": int(row.requests or 0),
                "tokens": int(row.tokens or 0),
                "prompt_tokens": int(row.prompt_tokens or 0),
                "completion_tokens": int(row.completion_tokens or 0),
                "errors": int(row.errors or 0),
                "timeouts": int(row.timeouts or 0),
                "rate_limited": int(row.rate_limited or 0),
            }
            for row in rows
            if row.group_key in provider_names
        }

    if dimension == "model":
        return {
            row.group_key: {
                "requests": int(row.requests or 0),
                "tokens": int(row.tokens or 0),
                "prompt_tokens": int(row.prompt_tokens or 0),
                "completion_tokens": int(row.completion_tokens or 0),
                "errors": int(row.errors or 0),
                "timeouts": int(row.timeouts or 0),
                "rate_limited": int(row.rate_limited or 0),
            }
            for row in rows
            if row.group_key
        }

    api_key_names = await get_api_key_name_map(
        session, [row.group_key for row in rows if row.group_key is not None]
    )
    return {
        api_key_names.get(row.group_key, f"Deleted Key #{row.group_key}"): {
            "requests": int(row.requests or 0),
            "tokens": int(row.tokens or 0),
            "prompt_tokens": int(row.prompt_tokens or 0),
            "completion_tokens": int(row.completion_tokens or 0),
            "errors": int(row.errors or 0),
            "timeouts": int(row.timeouts or 0),
            "rate_limited": int(row.rate_limited or 0),
        }
        for row in rows
        if row.group_key is not None
    }


async def aggregate_request_logs_range(
    session,
    lo: datetime,
    hi: datetime,
    pk_label_map: dict[int, Optional[str]],
) -> dict:
    """SQL aggregation of request_logs over [lo, hi).

    Mirrors the legacy per-row Python accumulation: rate-limited
    rows only contribute to the rate_limited counter, tokens use
    total_tokens-or-estimated, and bucket keys follow the
    provider/user model naming conventions.
    """
    non_rl = RequestLog.status.notin_(RATE_LIMITED_STATUSES)
    model_expr = provider_stats_model_expr(RequestLog.model, RequestLog.actual_model)
    window = (RequestLog.created_at >= lo, RequestLog.created_at < hi)

    totals_row = (
        await session.execute(
            select(
                func.sum(case((non_rl, 1), else_=0)).label("requests"),
                func.sum(case((non_rl, TOKEN_COUNT_EXPR), else_=0)).label("tokens"),
                func.sum(
                    case(
                        (non_rl, func.coalesce(RequestLog.tokens["prompt_tokens"].as_integer(), 0)),
                        else_=0,
                    )
                ).label("prompt_tokens"),
                func.sum(
                    case(
                        (non_rl, func.coalesce(RequestLog.tokens["completion_tokens"].as_integer(), 0)),
                        else_=0,
                    )
                ).label("completion_tokens"),
                func.sum(case((RequestLog.status == ERROR_STATUS, 1), else_=0)).label("errors"),
                func.sum(case((RequestLog.status == TIMEOUT_STATUS, 1), else_=0)).label("timeouts"),
                func.sum(
                    case((RequestLog.status.in_(RATE_LIMITED_STATUSES), 1), else_=0)
                ).label("rate_limited"),
            ).where(*window)
        )
    ).one()

    prov_rows = (
        await session.execute(
            select(
                RequestLog.provider_id.label("pid"),
                Provider.name.label("pname"),
                RequestLog.provider_key_id.label("pk_id"),
                RequestLog.provider_key_label.label("pk_label"),
                model_expr.label("mname"),
                func.count().label("requests"),
                func.sum(TOKEN_COUNT_EXPR).label("tokens"),
            )
            .join(Provider, Provider.id == RequestLog.provider_id)
            .where(*window, non_rl)
            .group_by(
                RequestLog.provider_id,
                Provider.name,
                RequestLog.provider_key_id,
                RequestLog.provider_key_label,
                model_expr,
            )
        )
    ).fetchall()

    provider_stats: dict[str, dict] = {}
    for r in prov_rows:
        if r.pname is None:
            continue
        bucket = provider_stats.setdefault(
            r.pname, {"requests": 0, "tokens": 0, "models": {}, "keys": {}}
        )
        bucket["requests"] += int(r.requests or 0)
        bucket["tokens"] += int(r.tokens or 0)
        if r.mname:
            mb = bucket["models"].setdefault(r.mname, {"requests": 0, "tokens": 0})
            mb["requests"] += int(r.requests or 0)
            mb["tokens"] += int(r.tokens or 0)
        key_label = r.pk_label
        if r.pk_id is not None:
            key_label = pk_label_map.get(r.pk_id, r.pk_label)
        if key_label:
            kb = bucket["keys"].setdefault(
                key_label, {"requests": 0, "tokens": 0, "models": {}}
            )
            kb["requests"] += int(r.requests or 0)
            kb["tokens"] += int(r.tokens or 0)
            if r.mname:
                km = kb["models"].setdefault(r.mname, {"requests": 0, "tokens": 0})
                km["requests"] += int(r.requests or 0)
                km["tokens"] += int(r.tokens or 0)

    umname_expr = user_stats_model_expr(RequestLog.model, RequestLog.requested_model)
    key_rows = (
        await session.execute(
            select(
                RequestLog.api_key_id.label("kid"),
                umname_expr.label("umname"),
                func.count().label("requests"),
                func.sum(TOKEN_COUNT_EXPR).label("tokens"),
            )
            .where(*window, non_rl, RequestLog.api_key_id.isnot(None))
            .group_by(RequestLog.api_key_id, umname_expr)
        )
    ).fetchall()

    api_key_names = await get_api_key_name_map(
        session, {r.kid for r in key_rows if r.kid is not None}
    )
    api_key_tags = await get_api_key_tags_map(
        session, {r.kid for r in key_rows if r.kid is not None}
    )
    api_key_stats: dict[str, dict] = {}
    for r in key_rows:
        key_name = api_key_names.get(r.kid)
        if not key_name:
            continue
        bucket = api_key_stats.setdefault(
            key_name,
            {
                "requests": 0,
                "tokens": 0,
                "models": {},
                "tags": api_key_tags.get(r.kid, []),
            },
        )
        bucket["requests"] += int(r.requests or 0)
        bucket["tokens"] += int(r.tokens or 0)
        if r.umname:
            mb = bucket["models"].setdefault(r.umname, {"requests": 0, "tokens": 0})
            mb["requests"] += int(r.requests or 0)
            mb["tokens"] += int(r.tokens or 0)

    model_rows = (
        await session.execute(
            select(
                model_expr.label("mname"),
                func.count().label("requests"),
                func.sum(TOKEN_COUNT_EXPR).label("tokens"),
            )
            .where(*window, non_rl)
            .group_by(model_expr)
        )
    ).fetchall()
    model_stats: dict[str, dict] = {}
    for r in model_rows:
        if not r.mname:
            continue
        model_stats[r.mname] = {
            "requests": int(r.requests or 0),
            "tokens": int(r.tokens or 0),
        }

    return {
        "total_requests": int(totals_row.requests or 0),
        "total_tokens": int(totals_row.tokens or 0),
        "total_prompt_tokens": int(totals_row.prompt_tokens or 0),
        "total_completion_tokens": int(totals_row.completion_tokens or 0),
        "total_errors": int(totals_row.errors or 0),
        "total_timeouts": int(totals_row.timeouts or 0),
        "total_rate_limited": int(totals_row.rate_limited or 0),
        "model_stats": model_stats,
        "provider_stats": provider_stats,
        "api_key_stats": api_key_stats,
    }


def merge_range_aggregate(target: dict, raw: dict) -> None:
    """Add a raw-range aggregate (see aggregate_request_logs_range)
    into daily-aggregate dicts of the same nested shape."""
    for name, v in raw["model_stats"].items():
        bucket = target["models"].setdefault(name, {"requests": 0, "tokens": 0})
        bucket["requests"] += v["requests"]
        bucket["tokens"] += v["tokens"]
    for name, v in raw["provider_stats"].items():
        bucket = target["providers"].setdefault(
            name, {"requests": 0, "tokens": 0, "models": {}, "keys": {}}
        )
        bucket["requests"] += v["requests"]
        bucket["tokens"] += v["tokens"]
        for mname, mv in v["models"].items():
            mb = bucket["models"].setdefault(mname, {"requests": 0, "tokens": 0})
            mb["requests"] += mv["requests"]
            mb["tokens"] += mv["tokens"]
        for label, kv in v["keys"].items():
            kb = bucket["keys"].setdefault(
                label, {"requests": 0, "tokens": 0, "models": {}}
            )
            kb["requests"] += kv["requests"]
            kb["tokens"] += kv["tokens"]
            for mname, kmv in kv["models"].items():
                km = kb["models"].setdefault(mname, {"requests": 0, "tokens": 0})
                km["requests"] += kmv["requests"]
                km["tokens"] += kmv["tokens"]
    for name, v in raw["api_key_stats"].items():
        bucket = target["api_keys"].setdefault(
            name,
            {"requests": 0, "tokens": 0, "models": {}, "tags": v.get("tags", [])},
        )
        bucket["requests"] += v["requests"]
        bucket["tokens"] += v["tokens"]
        for mname, mv in v["models"].items():
            mb = bucket["models"].setdefault(mname, {"requests": 0, "tokens": 0})
            mb["requests"] += mv["requests"]
            mb["tokens"] += mv["tokens"]


@router.get("/stats/aggregate")
async def get_aggregate_stats(
    dimension: Literal["provider", "api_key", "model"] = "provider",
    period: Literal["day", "week", "month", "year"] = "day",
    time_range: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    _: bool = Depends(permission_required("page.stats")),
):
    now = get_local_now()

    window = resolve_monitor_window(time_range, start_time, end_time, now)
    if window:
        start, end = window
        async with async_session_maker() as session:
            stats_data = {}
            if start < get_day_start(end):
                aggregate_start, aggregate_end, raw_ranges = (
                    get_totals_aggregate_bounds(start, end)
                )
                if aggregate_start < aggregate_end:
                    merge_named_stats(
                        stats_data,
                        await get_daily_aggregated_stats(
                            session, dimension, aggregate_start, aggregate_end
                        ),
                    )
                for raw_lo, raw_hi in raw_ranges:
                    merge_named_stats(
                        stats_data,
                        await get_raw_grouped_stats(
                            session, dimension, raw_lo, end=raw_hi
                        ),
                    )
            else:
                stats_data = await get_raw_grouped_stats(
                    session, dimension, start, end=end
                )
    else:
        start = get_period_start(period, now)
        async with async_session_maker() as session:
            if period in TOTALS_AGGREGATED_PERIODS:
                aggregate_start, aggregate_end, raw_ranges = (
                    get_totals_aggregate_bounds(start, now)
                )
                stats_data = {}
                if aggregate_start < aggregate_end:
                    merge_named_stats(
                        stats_data,
                        await get_daily_aggregated_stats(
                            session, dimension, aggregate_start, aggregate_end
                        ),
                    )
                for raw_lo, raw_hi in raw_ranges:
                    merge_named_stats(
                        stats_data,
                        await get_raw_grouped_stats(
                            session, dimension, raw_lo, end=raw_hi
                        ),
                    )
            else:
                stats_data = await get_raw_grouped_stats(session, dimension, start)

    total_requests = sum(d["requests"] for d in stats_data.values())
    total_tokens = sum(d["tokens"] for d in stats_data.values())
    total_prompt_tokens = sum(d.get("prompt_tokens", 0) for d in stats_data.values())
    total_completion_tokens = sum(
        d.get("completion_tokens", 0) for d in stats_data.values()
    )
    total_errors = sum(d["errors"] for d in stats_data.values())
    total_timeouts = sum(d.get("timeouts", 0) for d in stats_data.values())
    total_rate_limited = sum(d.get("rate_limited", 0) for d in stats_data.values())

    return {
        "dimension": dimension,
        "period": period,
        "total_requests": total_requests,
        "total_tokens": total_tokens,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_errors": total_errors,
        "total_timeouts": total_timeouts,
        "total_rate_limited": total_rate_limited,
        "data": stats_data,
    }


@router.get("/stats/trend")
async def get_trend_data(
    dimension: Literal["provider", "api_key", "model"] = "provider",
    period: Literal["day", "week", "month", "year"] = "day",
    name: Optional[str] = None,
    _: bool = Depends(permission_required("page.stats")),
):
    now = get_local_now()
    start, intervals, format_func = get_period_range(period, now)

    trend_data = {
        label: {
            "requests": 0,
            "tokens": 0,
            "errors": 0,
            "timeouts": 0,
            "rate_limited": 0,
        }
        for label in intervals
    }

    async with async_session_maker() as session:
        if use_daily_aggregates(period):
            aggregate_end, raw_start = get_aggregate_window_bounds(start, now)

            if dimension == "provider":
                aggregate_table = ProviderDailyStat
                filters = []
                if name:
                    filters.append(ProviderDailyStat.provider_name == name)
            elif dimension == "api_key":
                aggregate_table = ApiKeyDailyStat
                filters = []
                if name:
                    api_key_id = get_api_key_id_from_cache(name)
                    if api_key_id is None:
                        api_key_row = await session.execute(
                            select(ApiKey).where(ApiKey.name == name)
                        )
                        api_key = api_key_row.scalar_one_or_none()
                        api_key_id = api_key.id if api_key else None
                    if api_key_id is None:
                        return {
                            "dimension": dimension,
                            "period": period,
                            "name": name,
                            "intervals": intervals,
                            "data": trend_data,
                        }
                    filters.append(ApiKeyDailyStat.api_key_id == api_key_id)
            else:
                aggregate_table = ModelDailyStat
                filters = []
                if name:
                    filters.append(ModelDailyStat.model_name == name)

            if start < aggregate_end:
                result = await session.execute(
                    select(
                        aggregate_table.date,
                        func.sum(aggregate_table.requests).label("requests"),
                        func.sum(aggregate_table.tokens).label("tokens"),
                        func.sum(aggregate_table.errors).label("errors"),
                        func.sum(aggregate_table.timeouts).label("timeouts"),
                        func.sum(aggregate_table.rate_limited).label("rate_limited"),
                    )
                    .where(
                        aggregate_table.date >= start.strftime("%Y-%m-%d"),
                        aggregate_table.date < aggregate_end.strftime("%Y-%m-%d"),
                        *filters,
                    )
                    .group_by(aggregate_table.date)
                    .order_by(aggregate_table.date)
                )
                for row in result.fetchall():
                    bucket_dt = datetime.strptime(row.date, "%Y-%m-%d")
                    label = format_func(bucket_dt)
                    if label in trend_data:
                        add_metric_values(
                            trend_data[label],
                            row.requests,
                            row.tokens,
                            row.errors,
                            timeouts=row.timeouts,
                            rate_limited=row.rate_limited,
                        )

            raw_filters = (
                [RequestLog.created_at >= raw_start] if raw_start < now else []
            )
            if raw_filters:
                if dimension == "provider" and name:
                    provider_result = await session.execute(
                        select(Provider).where(Provider.name == name)
                    )
                    provider = provider_result.scalar_one_or_none()
                    if provider is None:
                        return {
                            "dimension": dimension,
                            "period": period,
                            "name": name,
                            "intervals": intervals,
                            "data": trend_data,
                        }
                    raw_filters.append(RequestLog.provider_id == provider.id)
                elif dimension == "api_key" and name:
                    api_key_id = get_api_key_id_from_cache(name)
                    if api_key_id is None:
                        api_key_result = await session.execute(
                            select(ApiKey).where(ApiKey.name == name)
                        )
                        api_key = api_key_result.scalar_one_or_none()
                        api_key_id = api_key.id if api_key else None
                    if api_key_id is None:
                        return {
                            "dimension": dimension,
                            "period": period,
                            "name": name,
                            "intervals": intervals,
                            "data": trend_data,
                        }
                    raw_filters.append(RequestLog.api_key_id == api_key_id)
                elif dimension == "model" and name:
                    raw_filters.append(
                        provider_stats_model_expr(RequestLog.model, RequestLog.actual_model)
                        == name
                    )

                result = await session.execute(
                    select(
                        func.sum(
                            case(
                                (RequestLog.status.notin_(RATE_LIMITED_STATUSES), 1),
                                else_=0,
                            )
                        ).label("requests"),
                        func.sum(
                            case(
                                (
                                    RequestLog.status.notin_(RATE_LIMITED_STATUSES),
                                    TOKEN_COUNT_EXPR,
                                ),
                                else_=0,
                            )
                        ).label("tokens"),
                        func.sum(
                            case((RequestLog.status == ERROR_STATUS, 1), else_=0)
                        ).label("errors"),
                        func.sum(
                            case((RequestLog.status == TIMEOUT_STATUS, 1), else_=0)
                        ).label("timeouts"),
                        func.sum(
                            case(
                                (RequestLog.status.in_(RATE_LIMITED_STATUSES), 1),
                                else_=0,
                            )
                        ).label("rate_limited"),
                    ).where(*raw_filters)
                )
                row = result.one()
                label = format_func(raw_start)
                if label in trend_data:
                    add_metric_values(
                        trend_data[label],
                        row.requests,
                        row.tokens,
                        row.errors,
                        row.timeouts,
                        row.rate_limited,
                    )
        else:
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
                    key = (
                        get_api_key_name_from_cache(log.api_key_id)
                        if log.api_key_id
                        else None
                    )
                    if key is None and log.api_key_id:
                        key = f"Key-{log.api_key_id}"
                else:
                    key = log.model

                if name and key != name:
                    continue

                label = format_func(log.created_at)
                if label in trend_data:
                    if log.status in RATE_LIMITED_STATUSES:
                        add_metric_values(trend_data[label], rate_limited=1)
                    else:
                        add_metric_values(
                            trend_data[label],
                            1,
                            get_token_count(log.tokens),
                            1 if log.status == ERROR_STATUS else 0,
                            1 if log.status == TIMEOUT_STATUS else 0,
                        )

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
    time_range: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    _: bool = Depends(permission_required("page.stats")),
):
    now = get_local_now()
    window = resolve_monitor_window(time_range, start_time, end_time, now)
    if window:
        start, end = window
    else:
        start = get_period_start(period, now)
        end = now

    async with async_session_maker() as session:
        total_errors_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.created_at >= start,
                RequestLog.created_at <= end,
                RequestLog.status == ERROR_STATUS,
            )
        )
        total_errors = total_errors_result.scalar() or 0

        total_timeouts_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.created_at >= start,
                RequestLog.created_at <= end,
                RequestLog.status == TIMEOUT_STATUS,
            )
        )
        total_timeouts = total_timeouts_result.scalar() or 0

        total_rate_limited_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.created_at >= start,
                RequestLog.created_at <= end,
                RequestLog.status.in_(RATE_LIMITED_STATUSES),
            )
        )
        total_rate_limited = total_rate_limited_result.scalar() or 0

        provider_rows_result = await session.execute(
            select(
                RequestLog.provider_id.label("group_key"),
                func.count(RequestLog.id).label("requests"),
                func.sum(case((RequestLog.status == ERROR_STATUS, 1), else_=0)).label(
                    "errors"
                ),
                func.sum(case((RequestLog.status == TIMEOUT_STATUS, 1), else_=0)).label(
                    "timeouts"
                ),
                func.sum(
                    case((RequestLog.status.in_(RATE_LIMITED_STATUSES), 1), else_=0)
                ).label("rate_limited"),
            )
            .where(
                RequestLog.created_at >= start,
                RequestLog.created_at <= end,
            )
            .group_by(RequestLog.provider_id)
        )
        provider_rows = provider_rows_result.fetchall()

        api_key_rows_result = await session.execute(
            select(
                RequestLog.api_key_id.label("group_key"),
                func.count(RequestLog.id).label("requests"),
                func.sum(case((RequestLog.status == ERROR_STATUS, 1), else_=0)).label(
                    "errors"
                ),
                func.sum(case((RequestLog.status == TIMEOUT_STATUS, 1), else_=0)).label(
                    "timeouts"
                ),
                func.sum(
                    case((RequestLog.status.in_(RATE_LIMITED_STATUSES), 1), else_=0)
                ).label("rate_limited"),
            )
            .where(
                RequestLog.created_at >= start,
                RequestLog.created_at <= end,
            )
            .group_by(RequestLog.api_key_id)
        )
        api_key_rows = api_key_rows_result.fetchall()

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

        top_model_group_expr = provider_stats_model_expr(
            RequestLog.model, RequestLog.actual_model
        )
        top_models_result = await session.execute(
            select(
                top_model_group_expr.label("model_name"),
                func.count(RequestLog.id).label("requests"),
            )
            .where(
                RequestLog.created_at >= start,
                RequestLog.created_at <= end,
                RequestLog.latency_ms.is_not(None),
                RequestLog.status.notin_(IN_FLIGHT_STATUSES),
                RequestLog.model.is_not(None),
            )
            .group_by(top_model_group_expr)
            .order_by(func.count(RequestLog.id).desc())
            .limit(8)
        )
        top_models = [
            row.model_name for row in top_models_result.fetchall() if row.model_name
        ]

        latency_intervals = [f"{hour:02d}:00" for hour in range(24)]
        latency_series: dict[str, dict[str, list]] = {}
        if top_models:
            latency_series = {
                model: {
                    "avg_latency_ms": [None] * 24,
                    "p95_latency_ms": [None] * 24,
                    "min_latency_ms": [None] * 24,
                    "max_latency_ms": [None] * 24,
                    "samples": [0] * 24,
                }
                for model in top_models
            }
            latency_group_expr = provider_stats_model_expr(
                RequestLog.model, RequestLog.actual_model
            )
            latency_rows_result = await session.execute(
                select(
                    latency_group_expr.label("model_name"),
                    func.extract("hour", RequestLog.created_at).label("hour_of_day"),
                    func.avg(RequestLog.latency_ms).label("avg_latency_ms"),
                    func.percentile_cont(0.95)
                    .within_group(RequestLog.latency_ms)
                    .label("p95_latency_ms"),
                    func.min(RequestLog.latency_ms).label("min_latency_ms"),
                    func.max(RequestLog.latency_ms).label("max_latency_ms"),
                    func.count(RequestLog.id).label("samples"),
                )
                .where(
                    RequestLog.created_at >= start,
                    RequestLog.created_at <= end,
                    latency_group_expr.in_(top_models),
                    RequestLog.latency_ms.is_not(None),
                    RequestLog.status.notin_(IN_FLIGHT_STATUSES),
                )
                .group_by(
                    latency_group_expr,
                    func.extract("hour", RequestLog.created_at),
                )
                .order_by(
                    latency_group_expr,
                    func.extract("hour", RequestLog.created_at),
                )
            )
            for row in latency_rows_result.fetchall():
                model_name = row.model_name
                if not model_name or model_name not in latency_series:
                    continue
                hour_of_day = int(row.hour_of_day or 0)
                if hour_of_day < 0 or hour_of_day > 23:
                    continue
                latency_series[model_name]["avg_latency_ms"][hour_of_day] = round(
                    row.avg_latency_ms or 0, 1
                )
                latency_series[model_name]["p95_latency_ms"][hour_of_day] = round(
                    row.p95_latency_ms or 0, 1
                )
                latency_series[model_name]["min_latency_ms"][hour_of_day] = round(
                    row.min_latency_ms or 0, 1
                )
                latency_series[model_name]["max_latency_ms"][hour_of_day] = round(
                    row.max_latency_ms or 0, 1
                )
                latency_series[model_name]["samples"][hour_of_day] = int(
                    row.samples or 0
                )

        top_providers_result = await session.execute(
            select(
                RequestLog.provider_id.label("provider_id"),
                func.count(RequestLog.id).label("requests"),
            )
            .where(
                RequestLog.created_at >= start,
                RequestLog.created_at <= end,
                RequestLog.latency_ms.is_not(None),
                RequestLog.status.notin_(IN_FLIGHT_STATUSES),
                RequestLog.provider_id.is_not(None),
            )
            .group_by(RequestLog.provider_id)
            .order_by(func.count(RequestLog.id).desc())
            .limit(8)
        )
        top_provider_ids = [
            row.provider_id
            for row in top_providers_result.fetchall()
            if row.provider_id is not None
        ]
        resolved_providers: dict[int, str] = {
            provider_id: providers_map.get(provider_id)
            for provider_id in top_provider_ids
            if providers_map.get(provider_id)
        }
        top_providers = list(resolved_providers.values())
        provider_latency_series: dict[str, dict[str, list]] = {}
        if top_providers:
            provider_latency_series = {
                provider_name: {
                    "avg_latency_ms": [None] * 24,
                    "p95_latency_ms": [None] * 24,
                    "min_latency_ms": [None] * 24,
                    "max_latency_ms": [None] * 24,
                    "samples": [0] * 24,
                }
                for provider_name in top_providers
            }
            provider_latency_rows_result = await session.execute(
                select(
                    RequestLog.provider_id.label("provider_id"),
                    func.extract("hour", RequestLog.created_at).label("hour_of_day"),
                    func.avg(RequestLog.latency_ms).label("avg_latency_ms"),
                    func.percentile_cont(0.95)
                    .within_group(RequestLog.latency_ms)
                    .label("p95_latency_ms"),
                    func.min(RequestLog.latency_ms).label("min_latency_ms"),
                    func.max(RequestLog.latency_ms).label("max_latency_ms"),
                    func.count(RequestLog.id).label("samples"),
                )
                .where(
                    RequestLog.created_at >= start,
                    RequestLog.created_at <= end,
                    RequestLog.provider_id.in_(list(resolved_providers.keys())),
                    RequestLog.latency_ms.is_not(None),
                    RequestLog.status.notin_(IN_FLIGHT_STATUSES),
                )
                .group_by(
                    RequestLog.provider_id,
                    func.extract("hour", RequestLog.created_at),
                )
                .order_by(
                    RequestLog.provider_id,
                    func.extract("hour", RequestLog.created_at),
                )
            )
            for row in provider_latency_rows_result.fetchall():
                provider_name = resolved_providers.get(row.provider_id)
                if not provider_name or provider_name not in provider_latency_series:
                    continue
                hour_of_day = int(row.hour_of_day or 0)
                if hour_of_day < 0 or hour_of_day > 23:
                    continue
                provider_latency_series[provider_name]["avg_latency_ms"][hour_of_day] = round(
                    row.avg_latency_ms or 0, 1
                )
                provider_latency_series[provider_name]["p95_latency_ms"][hour_of_day] = round(
                    row.p95_latency_ms or 0, 1
                )
                provider_latency_series[provider_name]["min_latency_ms"][hour_of_day] = round(
                    row.min_latency_ms or 0, 1
                )
                provider_latency_series[provider_name]["max_latency_ms"][hour_of_day] = round(
                    row.max_latency_ms or 0, 1
                )
                provider_latency_series[provider_name]["samples"][hour_of_day] = int(
                    row.samples or 0
                )

    def build_status_entries(
        rows, scope: str, resolver, masked: bool = False
    ) -> list[dict]:
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
            rate_limited = row.rate_limited or 0
            entries.append(
                {
                    "scope": scope,
                    "name": name,
                    "masked": masked,
                    "requests": requests,
                    "errors": errors,
                    "timeouts": timeouts,
                    "rate_limited": rate_limited,
                    "error_rate": (errors / requests) if requests else 0,
                    "timeout_rate": (timeouts / requests) if requests else 0,
                    "rate_limited_rate": ((rate_limited / requests) if requests else 0),
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
        lambda api_key_id: api_keys_map.get(api_key_id, f"Deleted Key #{api_key_id}"),
        masked=True,
    )

    def pick_error_hotspots(entries: list[dict]) -> list[dict]:
        return sorted(
            [item for item in entries if item["requests"] >= 3 and item["errors"] > 0],
            key=lambda item: (item["error_rate"], item["errors"], item["requests"]),
            reverse=True,
        )[:6]

    def pick_timeout_hotspots(entries: list[dict]) -> list[dict]:
        return sorted(
            [
                item
                for item in entries
                if item["requests"] >= 3 and item["timeouts"] > 0
            ],
            key=lambda item: (item["timeouts"], item["timeout_rate"], item["requests"]),
            reverse=True,
        )[:6]

    return {
        "period": period,
        "time_range": time_range,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total_errors": total_errors,
        "total_timeouts": total_timeouts,
        "total_rate_limited": total_rate_limited,
        "error_hotspots_provider": pick_error_hotspots(provider_entries),
        "error_hotspots_api_key": pick_error_hotspots(api_key_entries),
        "timeout_hotspots_provider": pick_timeout_hotspots(provider_entries),
        "timeout_hotspots_api_key": pick_timeout_hotspots(api_key_entries),
        "latency": {
            "models": top_models,
            "intervals": latency_intervals,
            "series": latency_series,
            "providers": top_providers,
            "provider_series": provider_latency_series,
        },
    }


@router.get("/stats/period")
async def get_stats_period(period: str = "day", _: bool = Depends(permission_required("page.stats"))):
    now = get_local_now()
    start = get_period_start(period, now)

    async with async_session_maker() as session:
        # Current provider_key_id -> label map (live values, not the
        # snapshot stored in request_logs.provider_key_label).
        pk_label_rows = await session.execute(select(ProviderKey.id, ProviderKey.label))
        pk_label_map: dict[int, Optional[str]] = {
            row[0]: row[1] for row in pk_label_rows.fetchall() if row[0] is not None
        }

        model_stats = {}
        provider_stats = {}
        api_key_stats = {}
        total_requests = 0
        total_tokens = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_errors = 0
        total_timeouts = 0
        total_rate_limited = 0

        if period in TOTALS_AGGREGATED_PERIODS:
            (
                aggregate_start,
                aggregate_end,
                raw_ranges,
            ) = get_totals_aggregate_bounds(start, now)
            start_str = aggregate_start.strftime("%Y-%m-%d")
            aggregate_end_str = aggregate_end.strftime("%Y-%m-%d")

            if aggregate_start < aggregate_end:
                model_rows_result = await session.execute(
                    select(
                        ModelDailyStat.model_name,
                        func.sum(ModelDailyStat.requests).label("requests"),
                        func.sum(ModelDailyStat.tokens).label("tokens"),
                        func.sum(ModelDailyStat.prompt_tokens).label("prompt_tokens"),
                        func.sum(ModelDailyStat.completion_tokens).label("completion_tokens"),
                        func.sum(ModelDailyStat.errors).label("errors"),
                        func.sum(ModelDailyStat.timeouts).label("timeouts"),
                        func.sum(ModelDailyStat.rate_limited).label("rate_limited"),
                    )
                    .where(
                        ModelDailyStat.date >= start_str,
                        ModelDailyStat.date < aggregate_end_str,
                    )
                    .group_by(ModelDailyStat.model_name)
                )
                for row in model_rows_result.fetchall():
                    if not row.model_name:
                        continue
                    model_stats[row.model_name] = {
                        "requests": int(row.requests or 0),
                        "tokens": int(row.tokens or 0),
                        "rate_limited": int(row.rate_limited or 0),
                    }
                    total_requests += int(row.requests or 0)
                    total_tokens += int(row.tokens or 0)
                    total_prompt_tokens += int(row.prompt_tokens or 0)
                    total_completion_tokens += int(row.completion_tokens or 0)
                    total_errors += int(row.errors or 0)
                    total_timeouts += int(row.timeouts or 0)
                    total_rate_limited += int(row.rate_limited or 0)

                provider_rows_result = await session.execute(
                    select(
                        ProviderDailyStat.provider_name,
                        func.sum(ProviderDailyStat.requests).label("requests"),
                        func.sum(ProviderDailyStat.tokens).label("tokens"),
                        func.sum(ProviderDailyStat.rate_limited).label("rate_limited"),
                    )
                    .where(
                        ProviderDailyStat.date >= start_str,
                        ProviderDailyStat.date < aggregate_end_str,
                    )
                    .group_by(ProviderDailyStat.provider_name)
                )
                for row in provider_rows_result.fetchall():
                    if not row.provider_name:
                        continue
                    provider_stats[row.provider_name] = {
                        "requests": int(row.requests or 0),
                        "tokens": int(row.tokens or 0),
                        "rate_limited": int(row.rate_limited or 0),
                        "models": {},
                        "keys": {},
                    }

                provider_model_rows_result = await session.execute(
                    select(
                        ModelDailyStat.provider_name,
                        ModelDailyStat.model_name,
                        func.sum(ModelDailyStat.requests).label("requests"),
                        func.sum(ModelDailyStat.tokens).label("tokens"),
                        func.sum(ModelDailyStat.rate_limited).label("rate_limited"),
                    )
                    .where(
                        ModelDailyStat.date >= start_str,
                        ModelDailyStat.date < aggregate_end_str,
                        ModelDailyStat.provider_name.is_not(None),
                    )
                    .group_by(ModelDailyStat.provider_name, ModelDailyStat.model_name)
                )
                for row in provider_model_rows_result.fetchall():
                    if not row.provider_name or not row.model_name:
                        continue
                    provider_bucket = provider_stats.setdefault(
                        row.provider_name,
                        {"requests": 0, "tokens": 0, "models": {}, "keys": {}},
                    )
                    provider_bucket["models"][row.model_name] = {
                        "requests": int(row.requests or 0),
                        "tokens": int(row.tokens or 0),
                        "rate_limited": int(row.rate_limited or 0),
                    }

                api_key_rows_result = await session.execute(
                    select(
                        ApiKeyDailyStat.api_key_id,
                        func.sum(ApiKeyDailyStat.requests).label("requests"),
                        func.sum(ApiKeyDailyStat.tokens).label("tokens"),
                        func.sum(ApiKeyDailyStat.rate_limited).label("rate_limited"),
                    )
                    .where(
                        ApiKeyDailyStat.date >= start_str,
                        ApiKeyDailyStat.date < aggregate_end_str,
                    )
                    .group_by(ApiKeyDailyStat.api_key_id)
                )
                api_key_rows = api_key_rows_result.fetchall()
                api_key_names = await get_api_key_name_map(
                    session, [row.api_key_id for row in api_key_rows if row.api_key_id]
                )
                api_key_tags = await get_api_key_tags_map(
                    session, [row.api_key_id for row in api_key_rows if row.api_key_id]
                )
                for row in api_key_rows:
                    if row.api_key_id is None:
                        continue
                    api_key_name = api_key_names.get(
                        row.api_key_id, f"Key-{row.api_key_id}"
                    )
                    api_key_stats[api_key_name] = {
                        "requests": int(row.requests or 0),
                        "tokens": int(row.tokens or 0),
                        "rate_limited": int(row.rate_limited or 0),
                        "models": {},
                        "tags": api_key_tags.get(row.api_key_id, []),
                    }

                api_key_model_rows_result = await session.execute(
                    select(
                        ApiKeyModelDailyStat.api_key_id,
                        ApiKeyModelDailyStat.model_name,
                        func.sum(ApiKeyModelDailyStat.requests).label("requests"),
                        func.sum(ApiKeyModelDailyStat.tokens).label("tokens"),
                        func.sum(ApiKeyModelDailyStat.rate_limited).label(
                            "rate_limited"
                        ),
                    )
                    .where(
                        ApiKeyModelDailyStat.date >= start_str,
                        ApiKeyModelDailyStat.date < aggregate_end_str,
                    )
                    .group_by(
                        ApiKeyModelDailyStat.api_key_id,
                        ApiKeyModelDailyStat.model_name,
                    )
                )
                for row in api_key_model_rows_result.fetchall():
                    if row.api_key_id is None or not row.model_name:
                        continue
                    api_key_name = api_key_names.get(
                        row.api_key_id, f"Key-{row.api_key_id}"
                    )
                    api_key_bucket = api_key_stats.setdefault(
                        api_key_name,
                        {"requests": 0, "tokens": 0, "models": {}, "tags": api_key_tags.get(row.api_key_id, [])},
                    )
                    api_key_bucket["models"][row.model_name] = {
                        "requests": int(row.requests or 0),
                        "tokens": int(row.tokens or 0),
                        "rate_limited": int(row.rate_limited or 0),
                    }

            async def accumulate_raw_range(
                raw_lo: datetime, raw_hi: datetime
            ) -> None:
                nonlocal total_requests, total_tokens, total_prompt_tokens, total_completion_tokens, total_errors, total_timeouts, total_rate_limited
                agg = await aggregate_request_logs_range(
                    session, raw_lo, raw_hi, pk_label_map
                )
                total_requests += agg["total_requests"]
                total_tokens += agg["total_tokens"]
                total_prompt_tokens += agg["total_prompt_tokens"]
                total_completion_tokens += agg["total_completion_tokens"]
                total_errors += agg["total_errors"]
                total_timeouts += agg["total_timeouts"]
                total_rate_limited += agg["total_rate_limited"]
                merge_range_aggregate(
                    {
                        "models": model_stats,
                        "providers": provider_stats,
                        "api_keys": api_key_stats,
                    },
                    agg,
                )

            for raw_lo, raw_hi in raw_ranges:
                await accumulate_raw_range(raw_lo, raw_hi)
        else:
            agg = await aggregate_request_logs_range(
                session, start, now, pk_label_map
            )
            total_requests = agg["total_requests"]
            total_tokens = agg["total_tokens"]
            total_prompt_tokens = agg["total_prompt_tokens"]
            total_completion_tokens = agg["total_completion_tokens"]
            total_errors = agg["total_errors"]
            total_timeouts = agg["total_timeouts"]
            total_rate_limited = agg["total_rate_limited"]
            model_stats.update(agg["model_stats"])
            provider_stats.update(agg["provider_stats"])
            api_key_stats.update(agg["api_key_stats"])

        rate_limited_upstream_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.created_at >= start,
                RequestLog.status == RATE_LIMITED_STATUS,
            )
        )
        total_rate_limited_upstream = rate_limited_upstream_result.scalar() or 0

        rate_limited_local_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.created_at >= start,
                RequestLog.status == LOCAL_RATE_LIMITED_STATUS,
            )
        )
        total_rate_limited_local = rate_limited_local_result.scalar() or 0

        disabled_result = await session.execute(
            select(Provider.name, Provider.disabled_reason).where(
                Provider.is_active == False,  # noqa: E712
            )
        )
        disabled_providers = {row.name: row.disabled_reason or "Disabled" for row in disabled_result.fetchall()}

        active_1h_result = await session.execute(
            select(func.count(func.distinct(RequestLog.api_key_id))).where(
                RequestLog.created_at >= now - timedelta(hours=1),
            )
        )
        active_1h = active_1h_result.scalar() or 0

        return {
            "period": period,
            "start": start.isoformat(),
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_errors": total_errors,
            "total_timeouts": total_timeouts,
            "total_rate_limited": total_rate_limited,
            "total_rate_limited_upstream": total_rate_limited_upstream,
            "total_rate_limited_local": total_rate_limited_local,
            "active_1h": active_1h,
            "providers": provider_stats,
            "api_keys": api_key_stats,
            "models": model_stats,
            "disabled_providers": disabled_providers,
        }


@router.get("/stats/chart")
async def get_chart_data(
    period: str = "day",
    provider: Optional[str] = None,
    api_key_id: Optional[int] = None,
    _: bool = Depends(permission_required("page.stats")),
):
    now = get_local_now()
    start, intervals, format_func = get_period_range(period, now)
    data = {
        label: {
            "requests": 0,
            "tokens": 0,
            "errors": 0,
            "timeouts": 0,
            "rate_limited": 0,
        }
        for label in intervals
    }

    async with async_session_maker() as session:
        if use_daily_aggregates(period) and provider is None and api_key_id is None:
            aggregate_end, raw_start = get_aggregate_window_bounds(start, now)
            if start < aggregate_end:
                result = await session.execute(
                    select(
                        ModelDailyStat.date,
                        func.sum(ModelDailyStat.requests).label("requests"),
                        func.sum(ModelDailyStat.tokens).label("tokens"),
                        func.sum(ModelDailyStat.errors).label("errors"),
                        func.sum(ModelDailyStat.timeouts).label("timeouts"),
                        func.sum(ModelDailyStat.rate_limited).label("rate_limited"),
                    )
                    .where(
                        ModelDailyStat.date >= start.strftime("%Y-%m-%d"),
                        ModelDailyStat.date < aggregate_end.strftime("%Y-%m-%d"),
                    )
                    .group_by(ModelDailyStat.date)
                    .order_by(ModelDailyStat.date)
                )
                for row in result.fetchall():
                    label = format_func(datetime.strptime(row.date, "%Y-%m-%d"))
                    if label in data:
                        add_metric_values(
                            data[label],
                            row.requests,
                            row.tokens,
                            errors=row.errors,
                            timeouts=row.timeouts,
                            rate_limited=row.rate_limited,
                        )

            if raw_start < now:
                result = await session.execute(
                    select(
                        func.sum(
                            case(
                                (RequestLog.status.notin_(RATE_LIMITED_STATUSES), 1),
                                else_=0,
                            )
                        ).label("requests"),
                        func.sum(
                            case(
                                (
                                    RequestLog.status.notin_(RATE_LIMITED_STATUSES),
                                    TOKEN_COUNT_EXPR,
                                ),
                                else_=0,
                            )
                        ).label("tokens"),
                    ).where(
                        RequestLog.created_at >= raw_start,
                    )
                )
                row = result.one()
                label = format_func(raw_start)
                if label in data:
                    add_metric_values(
                        data[label],
                        row.requests,
                        row.tokens,
                    )

            day_expr = func.date_trunc("day", RequestLog.created_at)
            status_rows_result = await session.execute(
                select(
                    day_expr.label("day"),
                    func.sum(case((RequestLog.status == ERROR_STATUS, 1), else_=0)).label("errors"),
                    func.sum(case((RequestLog.status == TIMEOUT_STATUS, 1), else_=0)).label("timeouts"),
                    func.sum(
                        case((RequestLog.status.in_(RATE_LIMITED_STATUSES), 1), else_=0)
                    ).label("rate_limited"),
                ).where(RequestLog.created_at >= raw_start).group_by(day_expr)
            )
            for row in status_rows_result.fetchall():
                label = format_func(row.day)
                if label not in data:
                    continue
                add_metric_values(
                    data[label],
                    errors=row.errors,
                    timeouts=row.timeouts,
                    rate_limited=row.rate_limited,
                )

            provider_stats = {}
            merge_named_stats(
                provider_stats,
                await get_daily_aggregated_stats(
                    session, "provider", start, aggregate_end
                )
                if start < aggregate_end
                else {},
            )
            if raw_start < now:
                merge_named_stats(
                    provider_stats,
                    await get_raw_grouped_stats(session, "provider", raw_start),
                )

            api_key_stats = {}
            merge_named_stats(
                api_key_stats,
                await get_daily_aggregated_stats(
                    session, "api_key", start, aggregate_end
                )
                if start < aggregate_end
                else {},
            )
            if raw_start < now:
                merge_named_stats(
                    api_key_stats,
                    await get_raw_grouped_stats(session, "api_key", raw_start),
                )
        else:
            non_rl = RequestLog.status.notin_(RATE_LIMITED_STATUSES)
            chart_filters = [RequestLog.created_at >= start]
            if provider:
                chart_filters.append(
                    provider_stats_model_expr(
                        RequestLog.model, RequestLog.actual_model
                    ).ilike(f"%{provider}%")
                )
            if api_key_id:
                chart_filters.append(RequestLog.api_key_id == api_key_id)

            hour_expr = func.date_trunc("hour", RequestLog.created_at)
            half_expr = case(
                (func.extract("minute", RequestLog.created_at) >= 30, 1), else_=0
            )
            bucket_result = await session.execute(
                select(
                    hour_expr.label("hbucket"),
                    half_expr.label("half") if period == "day" else literal(0).label("half"),
                    func.sum(case((non_rl, 1), else_=0)).label("requests"),
                    func.sum(case((non_rl, TOKEN_COUNT_EXPR), else_=0)).label("tokens"),
                    func.sum(case((RequestLog.status == ERROR_STATUS, 1), else_=0)).label("errors"),
                    func.sum(case((RequestLog.status == TIMEOUT_STATUS, 1), else_=0)).label("timeouts"),
                    func.sum(
                        case((RequestLog.status.in_(RATE_LIMITED_STATUSES), 1), else_=0)
                    ).label("rate_limited"),
                )
                .where(*chart_filters)
                .group_by(hour_expr, *( [half_expr] if period == "day" else [] ))
            )
            for row in bucket_result.fetchall():
                d = row.hbucket
                if period == "day":
                    d = d.replace(minute=30 if row.half else 0)
                label = format_func(d)
                if label in data:
                    add_metric_values(
                        data[label],
                        row.requests,
                        row.tokens,
                        errors=row.errors,
                        timeouts=row.timeouts,
                        rate_limited=row.rate_limited,
                    )

            provider_result = await session.execute(
                select(
                    RequestLog.provider_id.label("pid"),
                    Provider.name.label("pname"),
                    func.sum(case((non_rl, 1), else_=0)).label("requests"),
                    func.sum(case((non_rl, TOKEN_COUNT_EXPR), else_=0)).label("tokens"),
                )
                .join(Provider, Provider.id == RequestLog.provider_id)
                .where(*chart_filters, non_rl)
                .group_by(RequestLog.provider_id, Provider.name)
            )
            provider_stats = {}
            for row in provider_result.fetchall():
                if row.pname is None:
                    continue
                bucket = provider_stats.setdefault(
                    row.pname, {"requests": 0, "tokens": 0}
                )
                bucket["requests"] += int(row.requests or 0)
                bucket["tokens"] += int(row.tokens or 0)

            key_result = await session.execute(
                select(
                    RequestLog.api_key_id.label("kid"),
                    func.sum(case((non_rl, 1), else_=0)).label("requests"),
                    func.sum(case((non_rl, TOKEN_COUNT_EXPR), else_=0)).label("tokens"),
                )
                .where(*chart_filters, non_rl, RequestLog.api_key_id.isnot(None))
                .group_by(RequestLog.api_key_id)
            )
            api_key_stats = {}
            for row in key_result.fetchall():
                name = get_api_key_name_from_cache(row.kid)
                if not name:
                    continue
                bucket = api_key_stats.setdefault(
                    name, {"requests": 0, "tokens": 0}
                )
                bucket["requests"] += int(row.requests or 0)
                bucket["tokens"] += int(row.tokens or 0)

        return {
            "period": period,
            "intervals": intervals,
            "data": data,
            "providers": provider_stats,
            "api_keys": api_key_stats,
        }


@router.get("/stats/error-trend")
async def get_error_trend(_: bool = Depends(permission_required("page.stats"))):
    now = get_local_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=29)
    days = [(start + timedelta(days=i)).strftime("%m/%d") for i in range(30)]

    async with async_session_maker() as session:
        result = await session.execute(
            select(
                func.date(RequestLog.created_at).label("day"),
                func.sum(
                    case((RequestLog.status.notin_(RATE_LIMITED_STATUSES), 1), else_=0)
                ).label("requests"),
                func.sum(case((RequestLog.status == ERROR_STATUS, 1), else_=0)).label(
                    "errors"
                ),
                func.sum(case((RequestLog.status == TIMEOUT_STATUS, 1), else_=0)).label(
                    "timeouts"
                ),
                func.sum(
                    case((RequestLog.status.in_(RATE_LIMITED_STATUSES), 1), else_=0)
                ).label("rate_limited"),
            )
            .where(RequestLog.created_at >= start)
            .group_by(func.date(RequestLog.created_at))
            .order_by(func.date(RequestLog.created_at))
        )
        rows = result.fetchall()

    data = {}
    for row in rows:
        day_str = row.day.strftime("%m/%d")
        data[day_str] = {
            "requests": row.requests,
            "errors": row.errors or 0,
            "timeouts": row.timeouts or 0,
            "rate_limited": row.rate_limited or 0,
        }

    for d in days:
        if d not in data:
            data[d] = {"requests": 0, "errors": 0, "timeouts": 0, "rate_limited": 0}

    return {"intervals": days, "data": data}


@router.post("/stats/reaggregate")
async def reaggregate_all_stats(_: bool = Depends(permission_required("page.stats"))):
    from app.services.stats_aggregator import (
        backfill_historical_stats,
        aggregate_stats_for_date,
    )
    from datetime import date

    today = date.today().strftime("%Y-%m-%d")
    await aggregate_stats_for_date(today)
    await backfill_historical_stats()
    return {"status": "ok", "message": "Stats re-aggregated"}


@router.get("/stats/active")
async def get_active_sessions(_: bool = Depends(permission_required("page.stats"))):
    snapshot = await build_live_stats_snapshot()
    disabled_providers = dict(snapshot.get("disabled_providers", {}))
    async with async_session_maker() as session:
        result = await session.execute(
            select(Provider.name, Provider.disabled_reason).where(
                Provider.is_active == False,  # noqa: E712
                Provider.disabled_reason.isnot(None),
            )
        )
        for row in result.fetchall():
            disabled_providers[row.name] = row.disabled_reason
    return {
        "active_count": snapshot["active_users"],
        "active_requests": snapshot["active_requests"],
        "tokens_per_second": snapshot.get("tokens_per_second", 0),
        "sessions": snapshot["sessions"],
        "disabled_providers": disabled_providers,
        "key_concurrency": snapshot.get("key_concurrency", {}),
    }


@router.get("/stats/active/models")
async def get_active_sessions_by_model(_: bool = Depends(permission_required("page.stats"))):
    recent_cutoff = get_local_now() - timedelta(seconds=30)
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog)
            .where(
                or_(
                    RequestLog.status.in_(IN_FLIGHT_STATUSES),
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


def _build_provider_key_rows(
    providers_cache: dict,
    key_usage: dict,
    provider_usage: dict,
    key_health: dict,
    sem_limits: dict,
) -> list[dict]:
    """Build provider/key live rows, keeping only entries with usage today,
    sorted by usage descending."""
    from app.services.key_health import get_events_5m, get_health_level

    rows = []
    for provider_name, pcfg in providers_cache.items():
        provider_id = pcfg.get("id")
        disabled = pcfg.get("disabled_reason")
        api_keys = pcfg.get("api_keys", [])

        if not api_keys:
            usage = provider_usage.get(provider_id, 0)
            if usage <= 0:
                continue
            health = 0 if disabled else 100
            rows.append(
                {
                    "provider": provider_name,
                    "provider_disabled": bool(disabled),
                    "provider_disabled_reason": disabled or "",
                    "key_id": None,
                    "key_label": "(default)",
                    "health_score": health,
                    "health_level": get_health_level(health),
                    "concurrency_limit": 0,
                    "concurrency_in_use": 0,
                    "usage": usage,
                }
            )
            continue

        for k in api_keys:
            key_id = k["id"]
            usage = key_usage.get(key_id, 0)
            if usage <= 0:
                continue
            label = k.get("label", "") or f"Key #{key_id}"
            health = key_health.get(key_id, 100)
            conc_limit = sem_limits.get(f"{key_id}:{provider_name}", (0, 0))[0]
            conc_in_use = sem_limits.get(f"{key_id}:{provider_name}", (0, 0))[1]
            rows.append(
                {
                    "provider": provider_name,
                    "provider_disabled": bool(disabled),
                    "provider_disabled_reason": disabled or "",
                    "key_id": key_id,
                    "key_label": label,
                    "health_score": health,
                    "health_level": get_health_level(health),
                    "recent_events": get_events_5m(key_id),
                    "concurrency_limit": conc_limit,
                    "concurrency_in_use": conc_in_use,
                    "usage": usage,
                }
            )

    rows.sort(key=lambda r: r["usage"], reverse=True)
    return rows


@router.get("/stats/provider-keys-live")
async def provider_keys_live(_: bool = Depends(permission_required("page.stats"))):
    from app.services.key_health import compute_health_score

    now = get_local_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    providers_cache = config_module.providers_cache
    key_health = {
        k["id"]: compute_health_score(k["id"], True)
        for pcfg in providers_cache.values()
        for k in pcfg.get("api_keys", [])
    }
    sem_limits = {}
    for sem_key, sem in config_module.provider_key_semaphores.items():
        limit = getattr(sem, "_modelgate_scoped_limit", getattr(sem, "_value", 0)) or 0
        available = getattr(sem, "_value", 0)
        sem_limits[sem_key] = (limit, max(limit - available, 0))

    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog.provider_key_id, func.count())
            .where(
                RequestLog.created_at >= today_start,
                RequestLog.provider_key_id.isnot(None),
            )
            .group_by(RequestLog.provider_key_id)
        )
        key_usage = {row[0]: row[1] for row in result.fetchall()}

        result = await session.execute(
            select(RequestLog.provider_id, func.count())
            .where(
                RequestLog.created_at >= today_start,
                or_(
                    RequestLog.provider_key_id.is_(None),
                    RequestLog.provider_key_id == 0,
                ),
            )
            .group_by(RequestLog.provider_id)
        )
        provider_usage = {row[0]: row[1] for row in result.fetchall()}

    rows = _build_provider_key_rows(
        providers_cache, key_usage, provider_usage, key_health, sem_limits
    )
    return {"rows": rows}


@router.get("/stats/realtime")
async def get_realtime_stats(_: bool = Depends(permission_required("page.stats"))):
    snapshot = await build_live_stats_snapshot()

    now = datetime.now()
    cutoff = (now - timedelta(seconds=10)).strftime("%Y%m%d_%H%M%S")

    reqs_by_second: dict[str, int] = {}
    for k, v in requests_per_second:
        if k >= cutoff:
            reqs_by_second[k] = reqs_by_second.get(k, 0) + v

    req_active_seconds = max(len(reqs_by_second), 1)
    total_requests = sum(reqs_by_second.values())

    return {
        "requests_per_second": round(total_requests / req_active_seconds, 1),
        "tokens_per_second": get_total_tokens_per_second(),
        "active_requests": snapshot["active_requests"],
        "active_users": snapshot["active_users"],
    }


@router.websocket("/stats/live")
async def stats_live_websocket(websocket: WebSocket):
    from app.services.rbac_auth import decode_access_token

    token = websocket.cookies.get("session")
    if not token or not token.startswith("ey") or not decode_access_token(token):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    await add_live_stats_subscriber(websocket)

    try:
        await websocket.send_json(await build_live_stats_snapshot())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await remove_live_stats_subscriber(websocket)
        await prune_stale_active_requests()


@router.get("/stats/busyness")
async def get_busyness_level(_: bool = Depends(permission_required("page.stats"))):
    from app.services.busyness import compute_busyness_level, LEVEL_LABELS
    from app.services.proxy_runtime.concurrency import _get_user_provider_model_limit

    if not busyness_state:
        busyness_state.update(await compute_busyness_level())
    result = dict(busyness_state)
    result["user_provider_model_limit"] = _get_user_provider_model_limit()
    return result


@router.get("/stats/slow")
async def get_slow_requests(_: bool = Depends(permission_required("page.stats"))):
    slow_pending = []
    now = get_local_now()
    pending_cutoff = now - timedelta(seconds=60)
    completed_cutoff = now - timedelta(hours=1)
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog)
            .where(
                RequestLog.status.in_(IN_FLIGHT_STATUSES),
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
                    "input_tokens": log.request_context_tokens,
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
                    "input_tokens": log.request_context_tokens,
                }
            )

    return {
        "pending": slow_pending,
        "completed": slow_completed,
    }


@public_router.get("/stats")
async def get_public_stats():
    global historical_stats_cache, historical_stats_cache_date

    today_str = get_local_now().strftime("%Y-%m-%d")

    if historical_stats_cache_date != today_str:
        async with async_session_maker() as session:
            result = await session.execute(
                select(
                    func.coalesce(func.sum(ProviderDailyStat.requests), 0),
                    func.coalesce(func.sum(ProviderDailyStat.tokens), 0),
                ).where(ProviderDailyStat.date < today_str)
            )
            row = result.one()
            historical_stats_cache = {
                "total_requests": row[0],
                "total_tokens": row[1],
            }
            historical_stats_cache_date = today_str

    today_start = get_day_start(get_local_now())
    today_data = await get_cached_today_stats(today_start)

    today_requests = 0
    today_tokens = 0
    for provider_metrics in today_data.get("provider", {}).values():
        today_requests += provider_metrics.get("requests", 0)
        today_tokens += provider_metrics.get("tokens", 0)

    return {
        "total_requests": historical_stats_cache["total_requests"] + today_requests,
        "total_tokens": historical_stats_cache["total_tokens"] + today_tokens,
        "today_requests": today_requests,
        "today_tokens": today_tokens,
    }
