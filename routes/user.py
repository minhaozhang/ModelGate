import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select

from core.app_paths import build_app_url
from core.config import logger, providers_cache, validate_session, busyness_state
from core.database import (
    async_session_maker,
    ApiKey,
    Model,
    Provider,
    RequestLogRead as RequestLog,
    ApiKeyDailyStat,
    ApiKeyModelDailyStat,
    ModelDailyStat,
)
from core.i18n import render, translate

router = APIRouter(tags=["user"])
ERROR_STATUSES = ("error", "timeout")
ACTIVE_WINDOW_SECONDS = 30
USER_STATS_CACHE_TTL_SECONDS = 60
USER_RECOMMENDATION_REASON_TTL_SECONDS = 3600
SYSTEM_HEALTH_WINDOW_MINUTES = 20
ANALYSIS_PENDING_STALE_SECONDS = 30
RECOMMENDATION_ANALYSIS_EXPIRES_HOURS = 26

USER_SESSIONS: dict[str, dict] = {}
USER_SESSION_EXPIRE_HOURS = 24
USER_STATS_CACHE: dict[tuple[int, str, str], dict] = {}
SYSTEM_MODEL_STATS_CACHE: dict[tuple[str, str], dict] = {}
USER_RECOMMENDATIONS_CACHE: dict[tuple[int, str, str], dict] = {}
AGGREGATED_USER_PERIODS = {"month"}


def _api_key_bypasses_busyness(api_key_id: int | None) -> bool:
    if api_key_id is None:
        return False
    from core.config import api_keys_cache

    for key_info in api_keys_cache.values():
        if key_info.get("id") == api_key_id:
            return bool(key_info.get("bypass_busyness", False))
    return False


def _check_model_available(model_full_name: str, api_key_id: int | None = None) -> bool:
    parts = model_full_name.split("/", 1)
    if len(parts) != 2:
        return True
    provider_name, model_name = parts
    pconf = providers_cache.get(provider_name)
    if not pconf:
        return False
    if pconf.get("disabled_reason"):
        return False
    for m in pconf.get("models", []):
        if m.get("actual_model_name") == model_name:
            max_level = m.get("max_busyness_level")
            if max_level is not None:
                current_level = busyness_state.get("level", 6)
                if current_level > max_level:
                    if _api_key_bypasses_busyness(api_key_id):
                        return True
                    return False
            return True
    return True


def _get_provider_name_by_id(provider_id: int) -> str | None:
    for name, pconf in providers_cache.items():
        if pconf.get("id") == provider_id:
            return name
    return None


class UserLoginRequest(BaseModel):
    api_key: str


def translated_error(request: Request, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": translate(request, message)}, status_code=status_code)


def mask_name(name: str) -> str:
    if len(name) <= 4:
        return name
    return f"{name[:2]}***{name[-2:]}"


def get_user_session(user_session: Optional[str] = Cookie(None)) -> Optional[int]:
    if not user_session:
        return None
    session_data = USER_SESSIONS.get(user_session)
    if not session_data:
        return None
    if datetime.now() > session_data["expires"]:
        del USER_SESSIONS[user_session]
        return None
    return session_data.get("api_key_id")


def get_local_now() -> datetime:
    now = datetime.now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return now


def use_user_daily_aggregates(period: str) -> bool:
    return period in AGGREGATED_USER_PERIODS


def get_day_start(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def get_user_aggregate_window_bounds(
    start: datetime, now: datetime
) -> tuple[datetime, datetime]:
    today_start = get_day_start(now)
    return min(today_start, now), max(start, today_start)


def get_token_count(tokens_payload) -> int:
    return (
        (tokens_payload or {}).get("total_tokens")
        or (tokens_payload or {}).get("estimated")
        or 0
    )


def get_cache_bucket(now: datetime) -> str:
    return now.strftime("%Y%m%d%H%M")


def get_hour_cache_bucket(now: datetime) -> str:
    return now.strftime("%Y%m%d%H")


async def scheduled_daily_recommendation_analysis():
    from core.database import ProviderModel, Provider
    from services.analysis_store import (
        ANALYSIS_TYPE_USER_RECOMMENDATION,
        ANALYSIS_STATUS_RUNNING,
        ANALYSIS_STATUS_SUCCESS,
        ANALYSIS_STATUS_FAILED,
        upsert_analysis_record,
    )

    now = get_local_now()
    start = now - timedelta(days=7)

    async with async_session_maker() as session:
        rows_result = await session.execute(
            select(
                RequestLog.provider_id,
                RequestLog.model,
                func.count(RequestLog.id).label("requests"),
                func.avg(RequestLog.latency_ms).label("avg_latency_ms"),
                func.sum(
                    case((RequestLog.status.in_(ERROR_STATUSES), 1), else_=0)
                ).label("errors"),
            )
            .where(
                RequestLog.created_at >= start,
                RequestLog.status != "pending",
            )
            .group_by(RequestLog.provider_id, RequestLog.model)
        )
        rows = rows_result.fetchall()

        model_names_in_rows = {row.model for row in rows if row.model}
        display_name_map = {}
        if model_names_in_rows:
            dm_result = await session.execute(
                select(Model.name, Model.display_name).where(Model.name.in_(model_names_in_rows))
            )
            for r in dm_result.fetchall():
                display_name_map[r[0]] = r[1] or r[0]

    recommendations = []
    for row in rows:
        model_name = row.model
        if not model_name:
            continue
        requests_count = int(row.requests or 0)
        if requests_count < 10:
            continue
        errors_count = int(row.errors or 0)
        avg_latency_ms = float(row.avg_latency_ms or 0)
        error_rate = errors_count / requests_count if requests_count else 1.0
        reliability_score = max(0.0, 1.0 - (error_rate * 1.5))
        latency_score = 1 / (1 + (avg_latency_ms / 2500.0)) if avg_latency_ms > 0 else 0.0
        sample_score = min(requests_count / 20.0, 1.0)
        score = (reliability_score * 0.55) + (latency_score * 0.30) + (sample_score * 0.15)

        provider_name = _get_provider_name_by_id(row.provider_id)
        if not provider_name:
            continue
        full_name = f"{provider_name}/{model_name}"

        display_name = display_name_map.get(model_name, model_name)
        recommendations.append({
            "model": full_name,
            "display_name": display_name,
            "provider": provider_name,
            "actual_model_name": model_name,
            "requests": requests_count,
            "errors": errors_count,
            "error_rate": round(error_rate, 4),
            "avg_latency_ms": round(avg_latency_ms, 2),
            "score": round(score, 4),
        })

    recommendations.sort(
        key=lambda item: (-item["requests"], item["error_rate"], item["avg_latency_ms"])
    )
    top = recommendations[:10]
    for idx, rec in enumerate(top):
        rec["rank"] = idx + 1

    import json
    scope_key = "global:day:stats"
    try:
        await upsert_analysis_record(
            ANALYSIS_TYPE_USER_RECOMMENDATION,
            scope_key,
            status=ANALYSIS_STATUS_RUNNING,
            language="zh",
        )
        content = json.dumps(top, ensure_ascii=False)
        await upsert_analysis_record(
            ANALYSIS_TYPE_USER_RECOMMENDATION,
            scope_key,
            status=ANALYSIS_STATUS_SUCCESS,
            language="zh",
            content=content,
            expires_at=now + timedelta(hours=RECOMMENDATION_ANALYSIS_EXPIRES_HOURS),
        )
        logger.info(
            "[SCHEDULER] Daily recommendation analysis completed (%d recommendations)",
            len(top),
        )
    except Exception as exc:
        logger.warning("[SCHEDULER] Failed to save recommendation analysis: %s", exc)
        await upsert_analysis_record(
            ANALYSIS_TYPE_USER_RECOMMENDATION,
            scope_key,
            status=ANALYSIS_STATUS_FAILED,
            language="zh",
            error=str(exc),
            expires_at=now + timedelta(hours=RECOMMENDATION_ANALYSIS_EXPIRES_HOURS),
        )

def get_cached_payload(
    cache: dict,
    key: tuple,
    now: datetime,
    ttl_seconds: int = USER_STATS_CACHE_TTL_SECONDS,
) -> Optional[dict]:
    cache_item = cache.get(key)
    if not cache_item:
        return None

    created_at = cache_item.get("created_at")
    if not isinstance(created_at, datetime):
        cache.pop(key, None)
        return None

    if (now - created_at).total_seconds() >= ttl_seconds:
        cache.pop(key, None)
        return None

    return cache_item.get("payload")


def set_cached_payload(cache: dict, key: tuple, payload: dict, now: datetime) -> None:
    cache[key] = {
        "created_at": now,
        "payload": payload,
    }


def get_score_by_threshold(value: float, good: float, bad: float) -> float:
    if value <= good:
        return 1.0
    if value >= bad:
        return 0.0
    return max(0.0, 1.0 - ((value - good) / (bad - good)))


def build_system_health_summary(
    recent_requests: int,
    completed_requests: int,
    active_api_keys: int,
    error_count: int,
    avg_latency_ms: Optional[float],
    pending_requests: int,
) -> dict:
    payload = {
        "window_minutes": SYSTEM_HEALTH_WINDOW_MINUTES,
        "recent_requests": recent_requests,
        "completed_requests": completed_requests,
        "active_api_keys": active_api_keys,
        "pending_requests": pending_requests,
        "error_count": error_count,
        "error_rate": 0.0,
        "avg_latency_ms": round(float(avg_latency_ms or 0), 2)
        if avg_latency_ms
        else None,
        "score": 100,
        "status": "idle",
    }

    if recent_requests <= 0 and pending_requests <= 0:
        return payload

    error_rate = error_count / completed_requests if completed_requests > 0 else 0.0
    active_user_score = get_score_by_threshold(float(active_api_keys), 4.0, 18.0)
    pending_score = get_score_by_threshold(float(pending_requests), 1.0, 10.0)
    load_score = (active_user_score * 0.7) + (pending_score * 0.3)
    error_score = get_score_by_threshold(error_rate, 0.01, 0.18)
    latency_score = (
        get_score_by_threshold(float(avg_latency_ms), 1800.0, 15000.0)
        if avg_latency_ms
        else 1.0
    )
    score = round(
        ((error_score * 0.45) + (latency_score * 0.35) + (load_score * 0.20)) * 100
    )

    if score >= 85:
        status = "excellent"
    elif score >= 70:
        status = "healthy"
    elif score >= 50:
        status = "busy"
    else:
        status = "degraded"

    payload.update(
        {
            "error_rate": round(error_rate, 4),
            "score": score,
            "status": status,
        }
    )
    return payload


def get_user_period_range(
    now: datetime, period: str
) -> tuple[datetime, list[str], Callable[[datetime], str]]:
    week_bucket_hours = 4
    week_bucket_count = 42
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        intervals = [
            ((start + timedelta(minutes=30 * i)).strftime("%H:%M")) for i in range(48)
        ]
        format_func = lambda d: d.replace(
            minute=0 if d.minute < 30 else 30,
            second=0,
            microsecond=0,
        ).strftime("%H:%M")
    elif period == "week":
        current_bucket_start = now.replace(
            hour=(now.hour // week_bucket_hours) * week_bucket_hours,
            minute=0,
            second=0,
            microsecond=0,
        )
        start = current_bucket_start - timedelta(
            hours=week_bucket_hours * (week_bucket_count - 1)
        )
        intervals = [
            ((start + timedelta(hours=week_bucket_hours * i)).strftime("%m/%d %H:%M"))
            for i in range(week_bucket_count)
        ]

        def format_func(d: datetime) -> str:
            bucket_index = max(
                0,
                min(
                    int((d - start).total_seconds() // (week_bucket_hours * 3600)),
                    len(intervals) - 1,
                ),
            )
            return intervals[bucket_index]
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=30
        )
        intervals = [((start + timedelta(days=i)).strftime("%m/%d")) for i in range(31)]
        format_func = lambda d: d.strftime("%m/%d")

    return start, intervals, format_func


@router.get("/user/login", response_class=HTMLResponse)
async def user_login_page(request: Request):
    return HTMLResponse(content=render(request, "user/login.html"))


@router.post("/user/api/login")
async def user_login(request: Request, data: UserLoginRequest, response: Response):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key == data.api_key, ApiKey.is_active == True)
        )
        key = result.scalar_one_or_none()
        if not key:
            return translated_error(request, "Invalid API Key", 401)

        session_token = secrets.token_hex(32)
        USER_SESSIONS[session_token] = {
            "api_key_id": key.id,
            "name": key.name,
            "expires": datetime.now() + timedelta(hours=USER_SESSION_EXPIRE_HOURS),
        }

        response.set_cookie(
            key="user_session",
            value=session_token,
            httponly=True,
            max_age=USER_SESSION_EXPIRE_HOURS * 3600,
        )
        logger.info(f"[USER LOGIN] API Key '{key.name}' logged in")
        return {"success": True, "name": key.name}


@router.post("/user/api/logout")
async def user_logout(response: Response, user_session: Optional[str] = Cookie(None)):
    if user_session and user_session in USER_SESSIONS:
        del USER_SESSIONS[user_session]
    response.delete_cookie("user_session")
    return {"success": True}


@router.get("/user/api/stats")
async def get_user_stats(
    request: Request, api_key_id: int = Depends(get_user_session), period: str = "day"
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    now = get_local_now()
    start, intervals, format_func = get_user_period_range(now, period)
    cache_key = (api_key_id, period, get_cache_bucket(now))
    cached_payload = get_cached_payload(USER_STATS_CACHE, cache_key, now)
    if cached_payload is not None:
        return cached_payload

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == api_key_id))
        key = result.scalar_one_or_none()
        if not key:
            return translated_error(request, "API key not found", 404)
        trend_data = {
            label: {"requests": 0, "tokens": 0, "errors": 0} for label in intervals
        }
        total_requests = 0
        total_tokens = 0
        total_errors = 0
        model_stats = {}

        if use_user_daily_aggregates(period):
            aggregate_end, raw_start = get_user_aggregate_window_bounds(start, now)
            start_str = start.strftime("%Y-%m-%d")
            aggregate_end_str = aggregate_end.strftime("%Y-%m-%d")

            if start < aggregate_end:
                total_result = await session.execute(
                    select(
                        func.sum(ApiKeyDailyStat.requests).label("requests"),
                        func.sum(ApiKeyDailyStat.tokens).label("tokens"),
                        func.sum(ApiKeyDailyStat.errors).label("errors"),
                    ).where(
                        ApiKeyDailyStat.api_key_id == api_key_id,
                        ApiKeyDailyStat.date >= start_str,
                        ApiKeyDailyStat.date < aggregate_end_str,
                    )
                )
                total_row = total_result.one()
                total_requests += int(total_row.requests or 0)
                total_tokens += int(total_row.tokens or 0)
                total_errors += int(total_row.errors or 0)

                model_stats_result = await session.execute(
                    select(
                        ApiKeyModelDailyStat.model_name,
                        func.sum(ApiKeyModelDailyStat.requests).label("count"),
                        func.sum(ApiKeyModelDailyStat.tokens).label("tokens"),
                        func.sum(ApiKeyModelDailyStat.errors).label("errors"),
                    )
                    .where(
                        ApiKeyModelDailyStat.api_key_id == api_key_id,
                        ApiKeyModelDailyStat.date >= start_str,
                        ApiKeyModelDailyStat.date < aggregate_end_str,
                    )
                    .group_by(ApiKeyModelDailyStat.model_name)
                )
                for row in model_stats_result.fetchall():
                    if not row.model_name:
                        continue
                    model_stats[row.model_name] = {
                        "requests": int(row.count or 0),
                        "tokens": int(row.tokens or 0),
                        "errors": int(row.errors or 0),
                    }

                trend_result = await session.execute(
                    select(
                        ApiKeyDailyStat.date,
                        func.sum(ApiKeyDailyStat.requests).label("requests"),
                        func.sum(ApiKeyDailyStat.tokens).label("tokens"),
                        func.sum(ApiKeyDailyStat.errors).label("errors"),
                    )
                    .where(
                        ApiKeyDailyStat.api_key_id == api_key_id,
                        ApiKeyDailyStat.date >= start_str,
                        ApiKeyDailyStat.date < aggregate_end_str,
                    )
                    .group_by(ApiKeyDailyStat.date)
                    .order_by(ApiKeyDailyStat.date)
                )
                for row in trend_result.fetchall():
                    label = format_func(datetime.strptime(row.date, "%Y-%m-%d"))
                    if label in trend_data:
                        trend_data[label]["requests"] += int(row.requests or 0)
                        trend_data[label]["tokens"] += int(row.tokens or 0)
                        trend_data[label]["errors"] += int(row.errors or 0)

            if raw_start < now:
                raw_result = await session.execute(
                    select(RequestLog).where(
                        RequestLog.api_key_id == api_key_id,
                        RequestLog.created_at >= raw_start,
                    )
                )
                trend_logs = raw_result.scalars().all()
                for log in trend_logs:
                    tokens = get_token_count(log.tokens)
                    total_requests += 1
                    total_tokens += tokens
                    if log.status in ERROR_STATUSES:
                        total_errors += 1

                    if log.model:
                        model_bucket = model_stats.setdefault(
                            log.model,
                            {"requests": 0, "tokens": 0, "errors": 0},
                        )
                        model_bucket["requests"] += 1
                        model_bucket["tokens"] += tokens
                        if log.status in ERROR_STATUSES:
                            model_bucket["errors"] += 1

                    label = format_func(log.created_at)
                    if label in trend_data:
                        trend_data[label]["requests"] += 1
                        trend_data[label]["tokens"] += tokens
                        if log.status in ERROR_STATUSES:
                            trend_data[label]["errors"] += 1
        else:
            total_result = await session.execute(
                select(func.count(RequestLog.id)).where(
                    RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start
                )
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
                ).where(
                    RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start
                )
            )
            total_tokens = tokens_result.scalar() or 0

            errors_result = await session.execute(
                select(func.count(RequestLog.id)).where(
                    RequestLog.api_key_id == api_key_id,
                    RequestLog.status.in_(ERROR_STATUSES),
                    RequestLog.created_at >= start,
                )
            )
            total_errors = errors_result.scalar() or 0

            model_stats_result = await session.execute(
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
                    func.sum(
                        case((RequestLog.status.in_(ERROR_STATUSES), 1), else_=0)
                    ).label("errors"),
                )
                .where(
                    RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start
                )
                .group_by(RequestLog.model)
            )
            model_stats_rows = model_stats_result.fetchall()
            model_stats = {
                row.model: {
                    "requests": row.count,
                    "tokens": row.tokens or 0,
                    "errors": row.errors or 0,
                }
                for row in model_stats_rows
            }

            trend_query = select(RequestLog).where(
                RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start
            )
            trend_result = await session.execute(trend_query)
            trend_logs = trend_result.scalars().all()
            for log in trend_logs:
                label = format_func(log.created_at)
                if label in trend_data:
                    trend_data[label]["requests"] += 1
                    trend_data[label]["tokens"] += get_token_count(log.tokens)
                    if log.status in ERROR_STATUSES:
                        trend_data[label]["errors"] += 1

        health_start = now - timedelta(minutes=SYSTEM_HEALTH_WINDOW_MINUTES)
        health_result = await session.execute(
            select(
                func.count(RequestLog.id).label("recent_requests"),
                func.sum(case((RequestLog.status != "pending", 1), else_=0)).label(
                    "completed_requests"
                ),
                func.count(func.distinct(RequestLog.api_key_id)).label(
                    "active_api_keys"
                ),
                func.sum(
                    case((RequestLog.status.in_(ERROR_STATUSES), 1), else_=0)
                ).label("error_count"),
                func.avg(
                    case(
                        (RequestLog.status != "pending", RequestLog.latency_ms),
                        else_=None,
                    )
                ).label("avg_latency_ms"),
                func.sum(case((RequestLog.status == "pending", 1), else_=0)).label(
                    "pending_requests"
                ),
            ).where(RequestLog.created_at >= health_start)
        )
        health_row = health_result.one()
        system_health = build_system_health_summary(
            recent_requests=int(health_row.recent_requests or 0),
            completed_requests=int(health_row.completed_requests or 0),
            active_api_keys=int(health_row.active_api_keys or 0),
            error_count=int(health_row.error_count or 0),
            avg_latency_ms=float(health_row.avg_latency_ms or 0)
            if health_row.avg_latency_ms is not None
            else None,
            pending_requests=int(health_row.pending_requests or 0),
        )

        disabled_providers_result = await session.execute(
            select(Provider.name, Provider.disabled_reason).where(
                Provider.is_active == False,  # noqa: E712
                Provider.disabled_reason.isnot(None),
            )
        )
        disabled_providers = {
            row.name: row.disabled_reason
            for row in disabled_providers_result.fetchall()
        }

        model_names = list(model_stats.keys())
        price_map = {}
        if model_names:
            price_result = await session.execute(
                select(Model.name, Model.estimated_price).where(
                    Model.name.in_(model_names),
                    Model.estimated_price.isnot(None),
                )
            )
            price_map = {row.name: row.estimated_price for row in price_result.fetchall()}

        estimated_cost = 0.0
        for name, stats in model_stats.items():
            price = price_map.get(name)
            if price and stats.get("tokens"):
                estimated_cost += (stats["tokens"] / 1_000_000) * price

        payload = {
            "name": key.name,
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "estimated_cost": round(estimated_cost, 4),
            "models": model_stats,
            "trend": trend_data,
            "system_health": system_health,
            "disabled_providers": disabled_providers,
            "busyness": dict(busyness_state) if busyness_state else None,
        }
        set_cached_payload(USER_STATS_CACHE, cache_key, payload, now)
        return payload


@router.get("/user/api/notifications")
async def get_user_notifications(
    request: Request,
    api_key_id: int = Depends(get_user_session),
    page: int = 1,
    page_size: int = 20,
    unread: bool = False,
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)
    from services.notification import get_user_notifications as _get
    return await _get(api_key_id, page=page, page_size=page_size, unread_only=unread)


@router.get("/user/api/notifications/unread-count")
async def get_user_unread_count(
    request: Request, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)
    from services.notification import get_user_unread_count as _get
    return {"count": await _get(api_key_id)}


@router.put("/user/api/notifications/{notification_id}/read")
async def mark_user_notification_read(
    request: Request,
    notification_id: int,
    api_key_id: int = Depends(get_user_session),
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)
    from services.notification import mark_user_read
    ok = await mark_user_read(notification_id, api_key_id)
    if not ok:
        return translated_error(request, "Not found", 404)
    return {"ok": True}


@router.put("/user/api/notifications/read-all")
async def mark_all_user_notifications_read(
    request: Request, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)
    from services.notification import mark_all_user_read
    count = await mark_all_user_read(api_key_id)
    return {"ok": True, "count": count}


@router.get("/user/api/active")
async def get_user_recent_requests(
    request: Request, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    async with async_session_maker() as session:
        result = await session.execute(
            select(
                RequestLog.model,
                RequestLog.provider_id,
                RequestLog.tokens,
                RequestLog.latency_ms,
                RequestLog.status,
                RequestLog.error,
                RequestLog.created_at,
            )
            .where(RequestLog.api_key_id == api_key_id)
            .order_by(RequestLog.created_at.desc())
            .limit(5)
        )
        rows = result.fetchall()

        provider_ids = {r.provider_id for r in rows if r.provider_id}
        provider_map = {}
        if provider_ids:
            prov_result = await session.execute(
                select(Provider.id, Provider.name).where(Provider.id.in_(provider_ids))
            )
            provider_map = dict(prov_result.fetchall())

        requests = []
        for r in rows:
            token_count = get_token_count(r.tokens) if r.tokens else 0
            status_text = "error" if r.status == "error" or r.status == "failed" else "success" if r.status == "success" else r.status
            short_error = None
            if r.error:
                short_error = r.error[:120] if len(r.error) > 120 else r.error
            requests.append({
                "model": r.model,
                "provider": provider_map.get(r.provider_id, "-"),
                "tokens": token_count,
                "latency_ms": int(r.latency_ms) if r.latency_ms else None,
                "status": status_text,
                "error": short_error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })

        return {"requests": requests}


@router.get("/user/api/system-models")
async def get_system_model_stats(
    request: Request, api_key_id: int = Depends(get_user_session), period: str = "day"
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    now = get_local_now()
    start, _, _ = get_user_period_range(now, period)
    cache_key = (period, get_cache_bucket(now))
    cached_payload = get_cached_payload(SYSTEM_MODEL_STATS_CACHE, cache_key, now)
    if cached_payload is not None:
        return cached_payload

    async with async_session_maker() as session:
        models = {}
        if use_user_daily_aggregates(period):
            aggregate_end, raw_start = get_user_aggregate_window_bounds(start, now)
            if start < aggregate_end:
                result = await session.execute(
                    select(
                        ModelDailyStat.model_name,
                        func.sum(ModelDailyStat.requests).label("count"),
                        func.sum(ModelDailyStat.tokens).label("tokens"),
                    )
                    .where(
                        ModelDailyStat.date >= start.strftime("%Y-%m-%d"),
                        ModelDailyStat.date < aggregate_end.strftime("%Y-%m-%d"),
                    )
                    .group_by(ModelDailyStat.model_name)
                )
                for row in result.fetchall():
                    if row.model_name:
                        models[row.model_name] = {
                            "requests": int(row.count or 0),
                            "tokens": int(row.tokens or 0),
                        }

            if raw_start < now:
                result = await session.execute(
                    select(RequestLog.model, RequestLog.tokens).where(
                        RequestLog.created_at >= raw_start
                    )
                )
                for row in result.fetchall():
                    if not row.model:
                        continue
                    bucket = models.setdefault(row.model, {"requests": 0, "tokens": 0})
                    bucket["requests"] += 1
                    bucket["tokens"] += get_token_count(row.tokens)
        else:
            result = await session.execute(
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
            rows = result.fetchall()
            models = {
                row.model: {"requests": row.count or 0, "tokens": row.tokens or 0}
                for row in rows
                if row.model
            }

    payload = {
        "period": period,
        "total_requests": sum(v["requests"] for v in models.values()),
        "total_tokens": sum(v["tokens"] for v in models.values()),
        "models": models,
    }

    trend_data = {}
    set_cached_payload(SYSTEM_MODEL_STATS_CACHE, cache_key, payload, now)
    return payload


@router.get("/user/api/recommendations")
async def get_user_recommendations(
    request: Request, api_key_id: int = Depends(get_user_session), period: str = "day"
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    now = get_local_now()
    bypass_busyness = _api_key_bypasses_busyness(api_key_id)
    visibility_scope = "bypass" if bypass_busyness else "standard"
    cache_key = ("global", period, "v6", visibility_scope, get_cache_bucket(now))
    cached_payload = get_cached_payload(USER_RECOMMENDATIONS_CACHE, cache_key, now)
    if cached_payload is not None:
        return cached_payload

    import json as _json
    from services.analysis_store import (
        ANALYSIS_TYPE_USER_RECOMMENDATION,
        ANALYSIS_STATUS_SUCCESS,
        get_analysis_record,
    )

    all_items = []
    generated_at = now.isoformat()

    scope_key = "global:day:stats"
    record = await get_analysis_record(ANALYSIS_TYPE_USER_RECOMMENDATION, scope_key)
    if record and record.status == ANALYSIS_STATUS_SUCCESS and record.content:
        try:
            stored = _json.loads(record.content)
            if isinstance(stored, list):
                all_items = stored
                generated_at = record.updated_at.isoformat() if record.updated_at else generated_at
        except Exception:
            pass

    if not all_items:
        start = now - timedelta(days=7)
        async with async_session_maker() as session:
            rows_result = await session.execute(
                select(
                    RequestLog.provider_id,
                    RequestLog.model,
                    func.count(RequestLog.id).label("requests"),
                    func.avg(RequestLog.latency_ms).label("avg_latency_ms"),
                    func.sum(
                        case((RequestLog.status.in_(ERROR_STATUSES), 1), else_=0)
                    ).label("errors"),
                )
                .where(
                    RequestLog.created_at >= start,
                    RequestLog.status != "pending",
                )
                .group_by(RequestLog.provider_id, RequestLog.model)
            )
            rows = rows_result.fetchall()

            model_names_in_rows = {row.model for row in rows if row.model}
            display_name_map_fallback = {}
            if model_names_in_rows:
                dm_result = await session.execute(
                    select(Model.name, Model.display_name).where(Model.name.in_(model_names_in_rows))
                )
                for r in dm_result.fetchall():
                    display_name_map_fallback[r[0]] = r[1] or r[0]

        for row in rows:
            model_name = row.model
            if not model_name:
                continue
            requests_count = int(row.requests or 0)
            if requests_count < 10:
                continue
            errors_count = int(row.errors or 0)
            avg_latency_ms = float(row.avg_latency_ms or 0)
            error_rate = errors_count / requests_count if requests_count else 1.0
            reliability_score = max(0.0, 1.0 - (error_rate * 1.5))
            latency_score = 1 / (1 + (avg_latency_ms / 2500.0)) if avg_latency_ms > 0 else 0.0
            sample_score = min(requests_count / 20.0, 1.0)
            score = (reliability_score * 0.55) + (latency_score * 0.30) + (sample_score * 0.15)

            provider_name = _get_provider_name_by_id(row.provider_id)
            if not provider_name:
                continue
            full_name = f"{provider_name}/{model_name}"

            display_name = display_name_map_fallback.get(model_name, model_name)
            all_items.append({
                "model": full_name,
                "display_name": display_name,
                "provider": provider_name,
                "actual_model_name": model_name,
                "requests": requests_count,
                "errors": errors_count,
                "error_rate": round(error_rate, 4),
                "avg_latency_ms": round(avg_latency_ms, 2),
                "score": round(score, 4),
            })

        all_items.sort(key=lambda item: (-item["requests"], item["error_rate"], item["avg_latency_ms"]))

    filtered = [
        item for item in all_items
        if _check_model_available(item.get("model", ""), api_key_id)
    ]
    top = filtered[:10]
    for idx, rec in enumerate(top):
        rec["rank"] = idx + 1

    payload = {
        "period": period,
        "generated_at": generated_at,
        "items": top,
        "hourly_stats": [],
        "timing_advice": None,
        "analysis_source": "stats",
        "analysis_model_used": None,
    }
    set_cached_payload(USER_RECOMMENDATIONS_CACHE, cache_key, payload, now)
    return payload


@router.get("/user/api/system-active")
async def get_system_active_sessions(
    request: Request, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    cutoff = get_local_now() - timedelta(seconds=ACTIVE_WINDOW_SECONDS)
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog)
            .where(
                or_(
                    RequestLog.status == "pending",
                    RequestLog.created_at >= cutoff,
                )
            )
            .order_by(RequestLog.created_at.desc())
        )
        logs = result.scalars().all()
        other_key_ids = {
            log.api_key_id
            for log in logs
            if log.api_key_id is not None and log.api_key_id != api_key_id
        }
        api_key_names: dict[int, str] = {}
        if other_key_ids:
            key_result = await session.execute(
                select(ApiKey.id, ApiKey.name).where(ApiKey.id.in_(other_key_ids))
            )
            api_key_names = {row.id: row.name for row in key_result.fetchall()}

    grouped: dict[int | None, dict] = {}
    for log in logs:
        key = log.api_key_id
        if key not in grouped:
            grouped[key] = {
                "requests": 0,
                "models": {},
                "last_activity": log.created_at.isoformat(),
            }
        grouped[key]["requests"] += 1
        if log.created_at.isoformat() > grouped[key]["last_activity"]:
            grouped[key]["last_activity"] = log.created_at.isoformat()
        if log.model:
            grouped[key]["models"][log.model] = (
                grouped[key]["models"].get(log.model, 0) + 1
            )

    other_index = 1
    sessions = []
    for key in sorted(
        grouped.keys(), key=lambda value: (value != api_key_id, value or 0)
    ):
        stats = grouped[key]
        if key == api_key_id:
            display_name = translate(request, "Yourself")
            is_self = True
        elif key is None:
            display_name = translate(request, "Anonymous")
            is_self = False
        else:
            raw_name = api_key_names.get(key)
            if raw_name:
                display_name = mask_name(raw_name)
            else:
                display_name = translate(request, "Other {index}", index=other_index)
            other_index += 1
            is_self = False

        sessions.append(
            {
                "name": display_name,
                "is_self": is_self,
                "requests": stats["requests"],
                "models": stats["models"],
                "last_activity": stats["last_activity"],
            }
        )

    sessions.sort(
        key=lambda item: (
            -datetime.fromisoformat(item["last_activity"]).timestamp(),
            not item["is_self"],
            -item["requests"],
            item["name"],
        )
    )
    return {
        "active_count": len(sessions),
        "request_count": sum(item["requests"] for item in sessions),
        "sessions": sessions,
    }


@router.get("/user/api/catalog")
async def get_user_catalog(
    request: Request, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    from core.database import ApiKeyModel, Model, Provider, ProviderModel

    async with async_session_maker() as session:
        key_result = await session.execute(
            select(ApiKey).where(ApiKey.id == api_key_id)
        )
        api_key = key_result.scalar_one_or_none()
        if not api_key:
            return translated_error(request, "API Key not found", 404)

        providers_result = await session.execute(
            select(Provider).where(Provider.is_active == True)
        )
        models_result = await session.execute(
            select(Model).where(Model.is_active == True)
        )
        provider_models_result = await session.execute(
            select(ProviderModel).where(ProviderModel.is_active == True)
        )
        key_models_result = await session.execute(
            select(ApiKeyModel).where(ApiKeyModel.api_key_id == api_key_id)
        )

        providers = providers_result.scalars().all()
        models = models_result.scalars().all()
        provider_models = provider_models_result.scalars().all()
        key_models = key_models_result.scalars().all()

    provider_map = {provider.id: provider for provider in providers}
    model_map = {model.id: model for model in models}
    active_provider_models = [
        pm
        for pm in provider_models
        if pm.provider_id in provider_map and pm.model_id in model_map
    ]

    allowed_pm_ids = {item.provider_model_id for item in key_models}
    full_access = len(allowed_pm_ids) == 0
    owned_provider_models = (
        active_provider_models
        if full_access
        else [pm for pm in active_provider_models if pm.id in allowed_pm_ids]
    )

    bypass_busyness = _api_key_bypasses_busyness(api_key_id)

    def _is_model_available(provider_name: str, model_name: str) -> bool:
        pconf = providers_cache.get(provider_name)
        if not pconf:
            return False
        if pconf.get("disabled_reason"):
            return False
        for m in pconf.get("models", []):
            if m.get("actual_model_name") == model_name:
                max_level = m.get("max_busyness_level")
                if max_level is not None:
                    current_level = busyness_state.get("level", 6)
                    if current_level > max_level:
                        if bypass_busyness:
                            return True
                        return False
                return True
        return False

    def serialize_provider_models(items: list[ProviderModel]) -> list[dict]:
        grouped: dict[str, dict] = {}
        for provider_model in items:
            provider = provider_map[provider_model.provider_id]
            model = model_map[provider_model.model_id]
            provider_name = provider.name
            model_name = model.name
            display_name = model.display_name or model_name

            if not _is_model_available(provider_name, model_name):
                continue

            if provider_name not in grouped:
                grouped[provider_name] = {
                    "name": provider_name,
                    "models": [],
                }

            grouped[provider_name]["models"].append(
                {
                    "name": model_name,
                    "full_name": f"{provider_name}/{model_name}",
                    "display_name": display_name,
                    "context": model.context_length or 0,
                    "output": model.max_tokens or 0,
                    "is_multimodal": bool(model.is_multimodal),
                    "has_override": bool(provider_model.model_name_override),
                }
            )

        providers_data = []
        for provider_name in sorted(grouped.keys()):
            provider_entry = grouped[provider_name]
            provider_entry["models"].sort(key=lambda item: item["full_name"])
            provider_entry["model_count"] = len(provider_entry["models"])
            providers_data.append(provider_entry)
        return providers_data

    platform_providers = serialize_provider_models(active_provider_models)
    owned_providers = serialize_provider_models(owned_provider_models)

    return {
        "name": api_key.name,
        "full_access": full_access,
        "platform_provider_count": len(platform_providers),
        "platform_model_count": sum(
            provider["model_count"] for provider in platform_providers
        ),
        "owned_provider_count": len(owned_providers),
        "owned_model_count": sum(
            provider["model_count"] for provider in owned_providers
        ),
        "platform_providers": platform_providers,
        "owned_providers": owned_providers,
    }


@router.get("/user/dashboard", response_class=HTMLResponse)
async def user_dashboard(request: Request, api_key_id: int = Depends(get_user_session)):
    if not api_key_id:
        return RedirectResponse(url=build_app_url(request, "/user/login"))

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == api_key_id))
        key = result.scalar_one_or_none()
        if not key:
            return RedirectResponse(url=build_app_url(request, "/user/login"))

        html = render(
            request, "user/dashboard.html", name=key.name, api_key_id=api_key_id
        )
        return HTMLResponse(content=html)


@router.get("/user/documents", response_class=HTMLResponse)
async def user_documents_page(
    request: Request, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return RedirectResponse(url=build_app_url(request, "/user/login"))
    html = render(request, "user/documents.html")
    return HTMLResponse(content=html)


@router.get("/user/documents/{doc_id}", response_class=HTMLResponse)
async def user_document_detail_page(
    request: Request, doc_id: int, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return RedirectResponse(url=build_app_url(request, "/user/login"))
    from services.documents import get_document

    doc = await get_document(doc_id)
    if not doc or not doc.get("is_published"):
        return RedirectResponse(url=build_app_url(request, "/user/documents"))
    html = render(request, "user/document_detail.html", doc=doc)
    return HTMLResponse(content=html)


@router.get("/user/api/documents")
async def user_api_documents(
    request: Request,
    api_key_id: int = Depends(get_user_session),
    category: Optional[str] = None,
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)
    from services.documents import list_documents, list_categories

    docs = await list_documents(published_only=True, category=category)
    categories = await list_categories(published_only=True)
    return {"documents": docs, "categories": categories}


@router.get("/user/api/documents/{doc_id}")
async def user_api_document_detail(
    request: Request,
    doc_id: int,
    api_key_id: int = Depends(get_user_session),
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)
    from services.documents import get_document

    doc = await get_document(doc_id)
    if not doc or not doc.get("is_published"):
        return translated_error(request, "Document not found", 404)
    return {
        "id": doc.get("id"),
        "title": doc.get("title"),
        "category": doc.get("category"),
        "content": doc.get("content"),
        "updated_at": doc.get("updated_at") or "",
    }


@router.get("/user/api/documents/{doc_id}/files")
async def user_api_document_files(
    request: Request,
    doc_id: int,
    user_session: Optional[str] = Cookie(None),
    session: Optional[str] = Cookie(None),
):
    api_key_id = get_user_session(user_session)
    is_admin = validate_session(session)
    if not api_key_id and not is_admin:
        return translated_error(request, "Not authenticated", 401)
    from services.documents import get_document
    from services.document_files import list_files

    doc = await get_document(doc_id)
    if not doc or (not doc.get("is_published") and not is_admin):
        return translated_error(request, "Document not found", 404)

    files = await list_files(doc_id)
    result = []
    for f in files:
        url = ""
        if f.get("object_name"):
            from services.storage import get_presigned_url

            url = get_presigned_url(f["object_name"], expires_hours=1)
        result.append(
            {
                "id": f["id"],
                "filename": f["filename"],
                "file_type": f["file_type"],
                "file_size": f["file_size"],
                "content_type": f["content_type"],
                "download_url": url,
            }
        )
    return {"files": result}


@router.get("/user/api/documents/{doc_id}/files/{file_id}/download")
async def user_api_document_file_download(
    request: Request,
    doc_id: int,
    file_id: int,
    user_session: Optional[str] = Cookie(None),
    session: Optional[str] = Cookie(None),
):
    api_key_id = get_user_session(user_session)
    is_admin = validate_session(session)
    if not api_key_id and not is_admin:
        return translated_error(request, "Not authenticated", 401)
    from services.documents import get_document
    from services.document_files import get_file
    from services.storage import get_presigned_url

    doc = await get_document(doc_id)
    if not doc or (not doc.get("is_published") and not is_admin):
        return translated_error(request, "Document not found", 404)

    f = await get_file(file_id)
    if not f or f["document_id"] != doc_id:
        return translated_error(request, "File not found", 404)
    url = get_presigned_url(f["object_name"], expires_hours=1)
    if not url:
        return translated_error(request, "File not found", 404)
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url)


@router.get("/user/api/mcp-info")
async def get_mcp_info(request: Request, user_session: Optional[str] = Cookie(None)):
    api_key_id = get_user_session(user_session)
    if not api_key_id:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    from services.mcp_proxy import get_cached_tools, get_servers_by_api_key

    servers = await get_servers_by_api_key(api_key_id)
    if not servers:
        return {"has_mcp": False}

    all_tools = []
    server_infos = []
    for server in servers:
        tools = get_cached_tools(server.id)
        prefixed_tools = []
        prefix = server.tool_prefix or ""
        for tool in tools:
            tool_name = tool.get("name")
            if not tool_name:
                continue
            prefixed_tools.append({
                **tool,
                "name": f"{prefix}{tool_name}" if prefix else tool_name,
            })
        all_tools.extend(prefixed_tools)
        server_infos.append({
            "name": server.name,
            "url": server.url,
            "tool_prefix": server.tool_prefix,
            "tool_count": len(prefixed_tools),
        })

    domain = "https://leturx.cc"
    endpoint = f"{domain}/modelgate/mcp-proxy"

    return {
        "has_mcp": True,
        "servers": server_infos,
        "tools": all_tools,
        "endpoint": endpoint,
    }
