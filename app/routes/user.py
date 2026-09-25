import secrets
import csv
import io
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Optional

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import case, func, select

from app.core.app_paths import build_app_url
from app.core.config import (
    active_requests,
    active_requests_lock,
    add_user_live_stats_subscriber,
    build_user_live_stats_snapshot,
    build_user_sessions_payload,
    build_user_my_requests_rows,
    busyness_state,
    logger,
    prune_stale_active_requests,
    providers_cache,
    remove_user_live_stats_subscriber,
    validate_session,
)
from app.core.database import (
    async_session_maker,
    ApiKey,
    ApiKeyModel,
    ApiKeyTag,
    Model,
    Provider,
    ProviderModel,
    RequestLog,
    ApiKeyDailyStat,
    ApiKeyModelDailyStat,
    ModelDailyStat,
    TagDailyStat,
    generate_api_key,
)
from app.core.i18n import render, translate
from app.services.logging import IN_FLIGHT_STATUSES
from app.services.model_naming import (
    provider_stats_model_expr,
    provider_stats_model_name,
    user_stats_model_expr,
    user_stats_model_name,
)

router = APIRouter(tags=["user"])
ERROR_STATUSES = ("error", "timeout")
USER_STATS_CACHE_TTL_SECONDS = 60
SYSTEM_HEALTH_WINDOW_MINUTES = 20
ANALYSIS_PENDING_STALE_SECONDS = 30

USER_SESSIONS: dict[str, dict] = {}
USER_SESSION_EXPIRE_HOURS = 24
USER_STATS_CACHE: dict[tuple[int, str, str], dict] = {}
SYSTEM_MODEL_STATS_CACHE: dict[tuple[str, str], dict] = {}
AGGREGATED_USER_PERIODS = {"month"}


def _api_key_bypasses_busyness(api_key_id: int | None) -> bool:
    if api_key_id is None:
        return False
    from app.core.config import api_keys_cache

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


async def _get_user_allowed_model_names(api_key_id: int) -> set[str] | None:
    """Return set of 'provider_name/model_name' the user's key is allowed to use.
    Returns None if the key has no restrictions (allow all).
    """
    async with async_session_maker() as session:
        pm_result = await session.execute(
            select(ApiKeyModel.provider_model_id).where(ApiKeyModel.api_key_id == api_key_id)
        )
        pm_ids = [row[0] for row in pm_result.fetchall()]
        if not pm_ids:
            return None

        provider_model_result = await session.execute(
            select(ProviderModel.provider_id, ProviderModel.model_id, ProviderModel.model_name_override)
            .where(ProviderModel.id.in_(pm_ids))
        )
        pm_rows = provider_model_result.fetchall()

        model_id_to_name: dict[int, str] = {}
        model_ids = {row[1] for row in pm_rows}
        if model_ids:
            name_result = await session.execute(
                select(Model.id, Model.name).where(Model.id.in_(model_ids))
            )
            model_id_to_name = {row[0]: row[1] for row in name_result.fetchall()}

        allowed: set[str] = set()
        for row in pm_rows:
            provider_id, model_id, override = row
            provider_name = _get_provider_name_by_id(provider_id)
            if not provider_name:
                continue
            model_name = override or model_id_to_name.get(model_id, "")
            if model_name:
                allowed.add(f"{provider_name}/{model_name}")
        return allowed


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


def _billing_number(value) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _billing_int(value) -> int:
    return int(round(_billing_number(value)))


def _build_billing_detail_rows(logs) -> list[dict]:
    buckets: dict[tuple[str, str], dict[str, dict[str, float]]] = {}
    for log in logs:
        tokens = log.tokens if isinstance(getattr(log, "tokens", None), dict) else {}
        billing = tokens.get("billing") if isinstance(tokens.get("billing"), dict) else {}
        if not billing:
            continue
        provider = (
            billing.get("provider_name")
            or _get_provider_name_by_id(getattr(log, "provider_id", None))
            or "-"
        )
        model = billing.get("model_name") or getattr(log, "model", None) or "-"
        bucket = buckets.setdefault(
            (provider, model),
            {
                "输入": {"tokens": 0, "cost_cny": 0.0},
                "输出": {"tokens": 0, "cost_cny": 0.0},
                "缓存输入": {"tokens": 0, "cost_cny": 0.0},
            },
        )
        bucket["输入"]["tokens"] += _billing_int(billing.get("uncached_input_tokens"))
        bucket["输入"]["cost_cny"] += _billing_number(billing.get("input_cost_cny"))
        bucket["输出"]["tokens"] += _billing_int(billing.get("completion_tokens"))
        bucket["输出"]["cost_cny"] += _billing_number(billing.get("output_cost_cny"))
        bucket["缓存输入"]["tokens"] += _billing_int(billing.get("cached_input_tokens"))
        bucket["缓存输入"]["cost_cny"] += _billing_number(
            billing.get("cached_input_cost_cny")
        )

    rows = []
    for (provider, model), type_map in sorted(buckets.items()):
        for token_type in ("输入", "输出", "缓存输入"):
            item = type_map[token_type]
            rows.append(
                {
                    "provider": provider,
                    "model": model,
                    "token_type": token_type,
                    "tokens": int(item["tokens"]),
                    "cost_cny": round(item["cost_cny"], 10),
                }
            )
    return rows


def _billing_rows_to_csv(rows: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["provider", "model", "token_type", "tokens", "cost_cny"],
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def get_cache_bucket(now: datetime) -> str:
    return now.strftime("%Y%m%d%H%M")


def get_hour_cache_bucket(now: datetime) -> str:
    return now.strftime("%Y%m%d%H")


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


def aggregate_model_pricing(provider_model_dicts):
    input_prices = []
    output_prices = []
    cached_prices = []
    tier_samples = []
    for pm in provider_model_dicts or []:
        ip = pm.get("input")
        op = pm.get("output")
        cp = pm.get("cached")
        if ip is not None:
            input_prices.append(ip)
        if op is not None:
            output_prices.append(op)
        cp_eff = cp if cp is not None else ip
        if cp_eff is not None:
            cached_prices.append(cp_eff)
        for tier in pm.get("tiers") or []:
            if not isinstance(tier, dict):
                continue
            tier_samples.append({
                "min_context_tokens": tier.get("min_context_tokens"),
                "max_context_tokens": tier.get("max_context_tokens"),
                "input_price": tier.get("input_price_cny_per_million"),
                "output_price": tier.get("output_price_cny_per_million"),
            })
    tier_samples.sort(key=lambda t: (t["min_context_tokens"] is None, t["min_context_tokens"] or 0))
    return {
        "min_input_price": min(input_prices) if input_prices else None,
        "min_output_price": min(output_prices) if output_prices else None,
        "min_cached_price": min(cached_prices) if cached_prices else None,
        "tier_samples": tier_samples,
    }


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
        try:
            from app.services.audit import write_audit_log
            await write_audit_log(
                request, "create", "user_session", str(key.id),
                f"用户登录 (Key: {key.name})", None, 200,
                username=key.name, user_id=key.id,
            )
        except Exception:
            pass
        return {"success": True, "name": key.name}


@router.post("/user/api/logout")
async def user_logout(request: Request, response: Response, user_session: Optional[str] = Cookie(None)):
    if user_session and user_session in USER_SESSIONS:
        info = USER_SESSIONS.get(user_session, {})
        try:
            from app.services.audit import write_audit_log
            await write_audit_log(
                request, "delete", "user_session", str(info.get("api_key_id", "")),
                "用户登出", None, 200,
                username=info.get("name"), user_id=info.get("api_key_id"),
            )
        except Exception:
            pass
        del USER_SESSIONS[user_session]
    response.delete_cookie("user_session")
    return {"success": True}


@router.post("/user/api/regenerate-key")
async def user_regenerate_key(
    request: Request,
    response: Response,
    api_key_id: int = Depends(get_user_session),
    user_session: Optional[str] = Cookie(None),
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == api_key_id))
        key = result.scalar_one_or_none()
        if not key:
            return translated_error(request, "Not authenticated", 401)
        key.key = generate_api_key()
        await session.commit()
        await session.refresh(key)

        from app.services.auth import load_api_keys
        await load_api_keys()

        old_name = USER_SESSIONS.get(user_session, {}).get("name", "") if user_session else ""
        try:
            from app.services.audit import write_audit_log
            await write_audit_log(
                request, "update", "api_key", str(api_key_id),
                "用户重置 API Key", None, 200,
                username=old_name, user_id=api_key_id,
            )
        except Exception:
            pass

        if user_session and user_session in USER_SESSIONS:
            del USER_SESSIONS[user_session]
        response.delete_cookie("user_session")

        return {"success": True, "key": key.key}

@router.get("/user/api/my-key")
async def get_user_api_key(
    request: Request, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == api_key_id))
        key = result.scalar_one_or_none()
        if not key or not key.is_active:
            return translated_error(request, "Not authenticated", 401)
        return {"key": key.key}


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
                        user_model = user_stats_model_name(
                            log.requested_model, log.model
                        )
                        model_bucket = model_stats.setdefault(
                            user_model,
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

            model_group_expr = user_stats_model_expr(
                RequestLog.model, RequestLog.requested_model
            )
            model_stats_result = await session.execute(
                select(
                    model_group_expr.label("model_name"),
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
                .group_by(model_group_expr)
            )
            model_stats_rows = model_stats_result.fetchall()
            model_stats = {
                row.model_name: {
                    "requests": row.count,
                    "tokens": row.tokens or 0,
                    "errors": row.errors or 0,
                }
                for row in model_stats_rows
                if row.model_name
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
                func.sum(
                    case((RequestLog.status.notin_(IN_FLIGHT_STATUSES), 1), else_=0)
                ).label(
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
                        (RequestLog.status.notin_(IN_FLIGHT_STATUSES), RequestLog.latency_ms),
                        else_=None,
                    )
                ).label("avg_latency_ms"),
                func.sum(
                    case((RequestLog.status.in_(IN_FLIGHT_STATUSES), 1), else_=0)
                ).label(
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

        cost_result = await session.execute(
            select(func.sum(RequestLog.tokens["billing"]["total_cost_cny"].as_float())).where(
                RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start
            )
        )
        estimated_cost = cost_result.scalar() or 0.0

        prompt_tokens_result = await session.execute(
            select(func.sum(RequestLog.tokens["prompt_tokens"].as_integer())).where(
                RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start
            )
        )
        total_prompt_tokens = prompt_tokens_result.scalar() or 0

        completion_tokens_result = await session.execute(
            select(func.sum(RequestLog.tokens["completion_tokens"].as_integer())).where(
                RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start
            )
        )
        total_completion_tokens = completion_tokens_result.scalar() or 0

        payload = {
            "name": key.name,
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
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


@router.get("/user/api/billing/usage")
async def get_user_billing_usage(
    request: Request, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)
    from app.services.billing_rules import get_daily_usage_summary

    return await get_daily_usage_summary(api_key_id)


@router.get("/user/api/cost-trend")
async def get_user_cost_trend(
    request: Request, api_key_id: int = Depends(get_user_session), days: int = 30
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    days = max(1, min(days, 90))
    now = get_local_now()
    today_start = get_day_start(now)
    start = today_start - timedelta(days=days - 1)
    start_str = start.strftime("%Y-%m-%d")
    today_str = today_start.strftime("%Y-%m-%d")

    daily: dict[str, dict] = {}
    async with async_session_maker() as session:
        agg_result = await session.execute(
            select(
                ApiKeyDailyStat.date,
                func.coalesce(func.sum(ApiKeyDailyStat.cost_cny), 0).label("cost"),
                func.coalesce(func.sum(ApiKeyDailyStat.tokens), 0).label("tokens"),
            )
            .where(
                ApiKeyDailyStat.api_key_id == api_key_id,
                ApiKeyDailyStat.date >= start_str,
                ApiKeyDailyStat.date < today_str,
            )
            .group_by(ApiKeyDailyStat.date)
        )
        for row in agg_result.fetchall():
            daily[row.date] = {
                "cost": float(row.cost or 0),
                "tokens": int(row.tokens or 0),
            }

        today_result = await session.execute(
            select(RequestLog.tokens, RequestLog.status).where(
                RequestLog.api_key_id == api_key_id,
                RequestLog.created_at >= today_start,
                RequestLog.status.notin_(IN_FLIGHT_STATUSES),
            )
        )
        today_cost = 0.0
        today_tokens = 0
        for tokens, status in today_result.fetchall():
            payload = tokens if isinstance(tokens, dict) else {}
            billing = payload.get("billing")
            today_cost += _billing_number(
                billing.get("total_cost_cny") if isinstance(billing, dict) else None
            )
            if status not in ("rate_limited", "local_rate_limited"):
                today_tokens += get_token_count(payload)
        daily[today_str] = {"cost": today_cost, "tokens": today_tokens}

        total_result = await session.execute(
            select(func.coalesce(func.sum(ApiKeyDailyStat.cost_cny), 0)).where(
                ApiKeyDailyStat.api_key_id == api_key_id
            )
        )
        all_time_cost = float(total_result.scalar() or 0) + today_cost

    dates = []
    cost_series = []
    token_series = []
    current = start
    while current <= today_start:
        key = current.strftime("%Y-%m-%d")
        dates.append(key)
        point = daily.get(key) or {"cost": 0.0, "tokens": 0}
        cost_series.append(round(point["cost"], 6))
        token_series.append(point["tokens"])
        current += timedelta(days=1)

    return {
        "days": days,
        "total_cost": round(all_time_cost, 6),
        "window_cost": round(sum(cost_series), 6),
        "dates": dates,
        "cost": cost_series,
        "tokens": token_series,
    }


@router.get("/user/api/tag-usage")
async def get_user_tag_usage(
    request: Request, api_key_id: int = Depends(get_user_session), days: int = 30
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    days = max(1, min(days, 90))
    now = get_local_now()
    today_start = get_day_start(now)
    start = today_start - timedelta(days=days - 1)
    start_str = start.strftime("%Y-%m-%d")
    today_str = today_start.strftime("%Y-%m-%d")

    buckets: dict[str, dict] = {}

    async with async_session_maker() as session:
        agg_result = await session.execute(
            select(
                TagDailyStat.tag,
                func.coalesce(func.sum(TagDailyStat.requests), 0).label("requests"),
                func.coalesce(func.sum(TagDailyStat.tokens), 0).label("tokens"),
                func.coalesce(func.sum(TagDailyStat.cost_cny), 0).label("cost"),
            )
            .where(
                TagDailyStat.api_key_id == api_key_id,
                TagDailyStat.date >= start_str,
                TagDailyStat.date < today_str,
            )
            .group_by(TagDailyStat.tag)
        )
        for tag, req, tok, cost in agg_result.fetchall():
            buckets[tag or ""] = {
                "requests": int(req or 0),
                "tokens": int(tok or 0),
                "cost": float(cost or 0),
            }

        current_tags_result = await session.execute(
            select(ApiKeyTag.tag).where(ApiKeyTag.api_key_id == api_key_id)
        )
        current_tags = sorted({row[0] or "" for row in current_tags_result.fetchall()})

        today_result = await session.execute(
            select(RequestLog.tokens, RequestLog.status).where(
                RequestLog.api_key_id == api_key_id,
                RequestLog.created_at >= today_start,
                RequestLog.status.notin_(IN_FLIGHT_STATUSES),
            )
        )
        today_requests = 0
        today_tokens = 0
        today_cost = 0.0
        for tokens, status in today_result.fetchall():
            payload = tokens if isinstance(tokens, dict) else {}
            billing = payload.get("billing")
            today_cost += _billing_number(
                billing.get("total_cost_cny") if isinstance(billing, dict) else None
            )
            today_requests += 1
            if status not in ("rate_limited", "local_rate_limited"):
                today_tokens += get_token_count(payload)

        if today_requests:
            for tag in current_tags or [""]:
                bucket = buckets.setdefault(
                    tag, {"requests": 0, "tokens": 0, "cost": 0.0}
                )
                bucket["requests"] += today_requests
                bucket["tokens"] += today_tokens
                bucket["cost"] = round(bucket["cost"] + today_cost, 6)

    items = [
        {
            "tag": tag,
            "requests": v["requests"],
            "tokens": v["tokens"],
            "cost": round(v["cost"], 6),
        }
        for tag, v in buckets.items()
        if v["requests"] > 0 or v["cost"] > 0
    ]
    items.sort(key=lambda x: (-x["cost"], -x["requests"]))

    return {
        "days": days,
        "items": items,
        "note": "tags reflect the key's tag on each day; a key with multiple tags on the same day is counted under each",
    }


@router.get("/user/api/billing-details.csv")
async def download_user_billing_details(
    request: Request, api_key_id: int = Depends(get_user_session), period: str = "day"
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)
    now = get_local_now()
    start, _, _ = get_user_period_range(now, period)

    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog).where(
                RequestLog.api_key_id == api_key_id,
                RequestLog.created_at >= start,
                RequestLog.status.notin_(IN_FLIGHT_STATUSES),
            )
        )
        logs = result.scalars().all()

    rows = _build_billing_detail_rows(logs)
    csv_text = _billing_rows_to_csv(rows)
    safe_period = period if period in {"day", "week", "month"} else "month"
    filename = f"modelgate_billing_{safe_period}_{now.strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content="\ufeff" + csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    from app.services.notification import get_user_notifications as _get
    return await _get(api_key_id, page=page, page_size=page_size, unread_only=unread)


@router.get("/user/api/notifications/unread-count")
async def get_user_unread_count(
    request: Request, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)
    from app.services.notification import get_user_unread_count as _get
    return {"count": await _get(api_key_id)}


@router.put("/user/api/notifications/{notification_id}/read")
async def mark_user_notification_read(
    request: Request,
    notification_id: int,
    api_key_id: int = Depends(get_user_session),
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)
    from app.services.notification import mark_user_read
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
    from app.services.notification import mark_all_user_read
    count = await mark_all_user_read(api_key_id)
    return {"ok": True, "count": count}


@router.get("/user/api/active")
async def get_user_recent_requests(
    request: Request,
    api_key_id: int = Depends(get_user_session),
    limit: int = 5,
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)
    limit = max(1, min(limit, 100))
    requests = await build_user_recent_requests(api_key_id, limit=limit)
    return {"requests": requests}


async def build_user_recent_requests(
    api_key_id: int, limit: int = 10
) -> list[dict]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(
                RequestLog.model,
                RequestLog.provider_id,
                RequestLog.tokens,
                RequestLog.request_context_tokens,
                RequestLog.request_image_count,
                RequestLog.fallback_tries,
                RequestLog.latency_ms,
                RequestLog.first_chunk_ms,
                RequestLog.wait_ms,
                RequestLog.status,
                RequestLog.error,
                RequestLog.created_at,
            )
            .where(RequestLog.api_key_id == api_key_id)
            .order_by(RequestLog.created_at.desc())
            .limit(limit)
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
            tokens_payload = r.tokens if isinstance(r.tokens, dict) else {}
            input_tokens = _billing_int(
                tokens_payload.get("prompt_tokens")
                or tokens_payload.get("input_tokens")
            )
            output_tokens = _billing_int(
                tokens_payload.get("completion_tokens")
                or tokens_payload.get("output_tokens")
            )
            cached_tokens = 0
            prompt_details = tokens_payload.get("prompt_tokens_details")
            if isinstance(prompt_details, dict):
                cached_tokens = _billing_int(prompt_details.get("cached_tokens"))
            billing = tokens_payload.get("billing")
            if isinstance(billing, dict):
                cost_cny = _billing_number(billing.get("total_cost_cny"))
            else:
                cost_cny = 0.0
            cache_ratio = (
                round(cached_tokens / input_tokens * 100, 1)
                if input_tokens > 0 and cached_tokens > 0
                else 0.0
            )
            requests.append({
                "model": r.model,
                "provider": provider_map.get(r.provider_id, "-"),
                "tokens": token_count,
                "context_tokens": int(r.request_context_tokens or 0),
                "image_count": int(r.request_image_count or 0),
                "fallback_tries": r.fallback_tries if isinstance(r.fallback_tries, list) else [],
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_tokens": cached_tokens,
                "cache_ratio": cache_ratio,
                "cost_cny": round(cost_cny, 6),
                "latency_ms": int(r.latency_ms) if r.latency_ms else None,
                "first_chunk_ms": int(r.first_chunk_ms) if r.first_chunk_ms else None,
                "wait_ms": int(r.wait_ms) if r.wait_ms else None,
                "status": status_text,
                "error": short_error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })

        return requests


def _summarize_request_row(r, provider_map) -> dict:
    token_count = get_token_count(r.tokens) if r.tokens else 0
    status_text = (
        "error"
        if r.status in ("error", "failed")
        else "success"
        if r.status == "success"
        else r.status
    )
    short_error = (
        r.error[:120] if r.error and len(r.error) > 120 else r.error
    )
    tokens_payload = r.tokens if isinstance(r.tokens, dict) else {}
    input_tokens = _billing_int(
        tokens_payload.get("prompt_tokens")
        or tokens_payload.get("input_tokens")
    )
    output_tokens = _billing_int(
        tokens_payload.get("completion_tokens")
        or tokens_payload.get("output_tokens")
    )
    cached_tokens = 0
    prompt_details = tokens_payload.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        cached_tokens = _billing_int(prompt_details.get("cached_tokens"))
    billing = tokens_payload.get("billing")
    cost_cny = (
        _billing_number(billing.get("total_cost_cny"))
        if isinstance(billing, dict)
        else 0.0
    )
    cache_ratio = (
        round(cached_tokens / input_tokens * 100, 1)
        if input_tokens > 0 and cached_tokens > 0
        else 0.0
    )
    return {
        "id": r.id,
        "model": r.model,
        "provider": provider_map.get(r.provider_id, "-"),
        "tokens": token_count,
        "context_tokens": int(r.request_context_tokens or 0),
        "image_count": int(r.request_image_count or 0)
        if r.request_image_count is not None
        else 0,
        "fallback_tries": r.fallback_tries if isinstance(r.fallback_tries, list) else [],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "cache_ratio": cache_ratio,
        "cost_cny": round(cost_cny, 6),
        "latency_ms": int(r.latency_ms) if r.latency_ms else None,
        "first_chunk_ms": int(r.first_chunk_ms) if r.first_chunk_ms else None,
        "wait_ms": int(r.wait_ms) if r.wait_ms else None,
        "status": status_text,
        "error": short_error,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


USER_MY_REQUESTS_EXPORT_MAX_ROWS = 50000


def _user_my_requests_window(time_range: str) -> tuple[datetime, datetime]:
    now = datetime.now()
    if time_range == "all":
        return datetime(2000, 1, 1), now
    deltas = {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
    }
    return now - deltas.get(time_range, timedelta(days=7)), now


def _user_my_requests_filters(
    api_key_id: int,
    model: Optional[str],
    status: Optional[str],
    dt_start: datetime,
    dt_end: datetime,
) -> list:
    filters = [
        RequestLog.api_key_id == api_key_id,
        RequestLog.created_at >= dt_start,
        RequestLog.created_at <= dt_end,
    ]
    if model:
        filters.append(RequestLog.model.ilike(f"%{_escape_user_model(model)}%"))
    if status:
        if status == "error":
            filters.append(RequestLog.status.in_(ERROR_STATUSES))
        elif status == "success":
            filters.append(RequestLog.status == "success")
    return filters


@router.get("/user/api/my-requests")
async def get_user_my_requests(
    request: Request,
    api_key_id: int = Depends(get_user_session),
    model: Optional[str] = None,
    status: Optional[str] = None,
    time_range: str = "1h",
    page: int = 1,
    page_size: int = 20,
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    dt_start, dt_end = _user_my_requests_window(time_range)

    async with async_session_maker() as session:
        filters = _user_my_requests_filters(
            api_key_id, model, status, dt_start, dt_end
        )

        count_q = select(func.count()).select_from(RequestLog).where(*filters)
        total = (await session.execute(count_q)).scalar() or 0

        offset = (page - 1) * page_size
        q = (
            select(
                RequestLog.id,
                RequestLog.model,
                RequestLog.provider_id,
                RequestLog.tokens,
                RequestLog.request_context_tokens,
                RequestLog.request_image_count,
                RequestLog.fallback_tries,
                RequestLog.latency_ms,
                RequestLog.first_chunk_ms,
                RequestLog.wait_ms,
                RequestLog.status,
                RequestLog.error,
                RequestLog.created_at,
            )
            .where(*filters)
            .order_by(RequestLog.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        rows = (await session.execute(q)).fetchall()

        provider_ids = {r.provider_id for r in rows if r.provider_id}
        provider_map = {}
        if provider_ids:
            prov_result = await session.execute(
                select(Provider.id, Provider.name).where(Provider.id.in_(provider_ids))
            )
            provider_map = dict(prov_result.fetchall())

        requests = [_summarize_request_row(r, provider_map) for r in rows]

        model_options_result = await session.execute(
            select(RequestLog.model)
            .where(
                RequestLog.api_key_id == api_key_id,
                RequestLog.created_at >= dt_start,
                RequestLog.created_at <= dt_end,
            )
            .distinct()
            .order_by(RequestLog.model)
        )
        model_options = [m[0] for m in model_options_result.fetchall() if m[0]]

        return {
            "requests": requests,
            "total": total,
            "page": page,
            "page_size": page_size,
            "models": model_options,
        }


def _escape_user_model(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/user/api/my-requests/export")
async def export_user_my_requests(
    request: Request,
    api_key_id: int = Depends(get_user_session),
    model: Optional[str] = None,
    status: Optional[str] = None,
    time_range: str = "1h",
):
    from app.routes.logs import _build_xlsx

    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    dt_start, dt_end = _user_my_requests_window(time_range)
    async with async_session_maker() as session:
        filters = _user_my_requests_filters(
            api_key_id, model, status, dt_start, dt_end
        )
        result = await session.execute(
            select(
                RequestLog.id,
                RequestLog.model,
                RequestLog.provider_id,
                RequestLog.tokens,
                RequestLog.request_context_tokens,
                RequestLog.request_image_count,
                RequestLog.fallback_tries,
                RequestLog.latency_ms,
                RequestLog.first_chunk_ms,
                RequestLog.wait_ms,
                RequestLog.status,
                RequestLog.error,
                RequestLog.created_at,
            )
            .where(*filters)
            .order_by(RequestLog.created_at.desc())
            .limit(USER_MY_REQUESTS_EXPORT_MAX_ROWS)
        )
        rows = result.fetchall()

        xlsx_rows: list[list] = [
            [
                "ID",
                "时间",
                "模型",
                "状态",
                "耗时(ms)",
                "首包(ms)",
                "排队(ms)",
                "上下文Tokens",
                "输入Tokens",
                "输出Tokens",
                "缓存Tokens",
                "缓存率(%)",
                "成本(元)",
                "错误",
            ]
        ]
        for r in rows:
            s = _summarize_request_row(r, {})
            xlsx_rows.append(
                [
                    s["id"],
                    r.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    if r.created_at
                    else "",
                    s["model"] or "",
                    s["status"],
                    s["latency_ms"] if s["latency_ms"] is not None else "",
                    s["first_chunk_ms"] if s["first_chunk_ms"] is not None else "",
                    s["wait_ms"] if s["wait_ms"] is not None else "",
                    s["context_tokens"],
                    s["input_tokens"],
                    s["output_tokens"],
                    s["cached_tokens"],
                    s["cache_ratio"] or "",
                    s["cost_cny"] or "",
                    s["error"] or "",
                ]
            )

    filename = f"my_requests_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=_build_xlsx(xlsx_rows),
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/user/api/system-models")
async def get_system_model_stats(
    request: Request, api_key_id: int = Depends(get_user_session), period: str = "day"
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    now = get_local_now()
    start, intervals, format_func = get_user_period_range(now, period)
    cache_key = (period, get_cache_bucket(now))
    cached_payload = get_cached_payload(SYSTEM_MODEL_STATS_CACHE, cache_key, now)
    if cached_payload is not None:
        return cached_payload

    trend_data = {
        label: {"requests": 0, "tokens": 0, "errors": 0} for label in intervals
    }

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

                trend_result = await session.execute(
                    select(
                        ModelDailyStat.date,
                        func.sum(ModelDailyStat.requests).label("requests"),
                        func.sum(ModelDailyStat.tokens).label("tokens"),
                        func.sum(ModelDailyStat.errors).label("errors"),
                    )
                    .where(
                        ModelDailyStat.date >= start.strftime("%Y-%m-%d"),
                        ModelDailyStat.date < aggregate_end.strftime("%Y-%m-%d"),
                    )
                    .group_by(ModelDailyStat.date)
                    .order_by(ModelDailyStat.date)
                )
                for row in trend_result.fetchall():
                    label = format_func(datetime.strptime(row.date, "%Y-%m-%d"))
                    if label in trend_data:
                        trend_data[label]["requests"] += int(row.requests or 0)
                        trend_data[label]["tokens"] += int(row.tokens or 0)
                        trend_data[label]["errors"] += int(row.errors or 0)

            if raw_start < now:
                result = await session.execute(
                    select(
                        RequestLog.model,
                        RequestLog.actual_model,
                        RequestLog.tokens,
                        RequestLog.created_at,
                        RequestLog.status,
                    ).where(
                        RequestLog.created_at >= raw_start
                    )
                )
                for row in result.fetchall():
                    tokens = get_token_count(row.tokens)
                    out_name = provider_stats_model_name(row.actual_model, row.model)
                    if out_name:
                        bucket = models.setdefault(out_name, {"requests": 0, "tokens": 0})
                        bucket["requests"] += 1
                        bucket["tokens"] += tokens
                    label = format_func(row.created_at)
                    if label in trend_data:
                        trend_data[label]["requests"] += 1
                        trend_data[label]["tokens"] += tokens
                        if row.status in ERROR_STATUSES:
                            trend_data[label]["errors"] += 1
        else:
            user_model_group_expr = provider_stats_model_expr(
                RequestLog.model, RequestLog.actual_model
            )
            result = await session.execute(
                select(
                    user_model_group_expr.label("model_name"),
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
                .group_by(user_model_group_expr)
            )
            rows = result.fetchall()
            models = {
                row.model_name: {"requests": row.count or 0, "tokens": row.tokens or 0}
                for row in rows
                if row.model_name
            }

            trend_result = await session.execute(
                select(
                    RequestLog.tokens,
                    RequestLog.created_at,
                    RequestLog.status,
                ).where(RequestLog.created_at >= start)
            )
            for row in trend_result.fetchall():
                label = format_func(row.created_at)
                if label in trend_data:
                    trend_data[label]["requests"] += 1
                    trend_data[label]["tokens"] += get_token_count(row.tokens)
                    if row.status in ERROR_STATUSES:
                        trend_data[label]["errors"] += 1

    total_tokens = sum(v["tokens"] for v in models.values())

    async with async_session_maker() as session:
        prompt_result = await session.execute(
            select(func.sum(RequestLog.tokens["prompt_tokens"].as_integer())).where(
                RequestLog.created_at >= start
            )
        )
        total_prompt_tokens = prompt_result.scalar() or 0
        completion_result = await session.execute(
            select(func.sum(RequestLog.tokens["completion_tokens"].as_integer())).where(
                RequestLog.created_at >= start
            )
        )
        total_completion_tokens = completion_result.scalar() or 0

    payload = {
        "period": period,
        "total_requests": sum(v["requests"] for v in models.values()),
        "total_tokens": total_tokens,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "models": models,
        "trend": trend_data,
    }

    set_cached_payload(SYSTEM_MODEL_STATS_CACHE, cache_key, payload, now)
    return payload


@router.get("/user/api/system-active")
async def get_system_active_sessions(
    request: Request, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    # Real-time source shared with the admin dashboard: in-flight requests are
    # registered in memory the moment they start and removed when they finish,
    # so no DB polling window or pending-status lag here.
    await prune_stale_active_requests()
    async with active_requests_lock:
        live_entries = list(active_requests.values())

    grouped: dict[int | None, dict] = {}
    for entry in live_entries:
        key = entry.get("api_key_id")
        if key not in grouped:
            grouped[key] = {"requests": 0, "models": {}, "last_activity": None}
        grouped[key]["requests"] += 1
        started_at = entry.get("started_at")
        if started_at is not None:
            stamp = started_at.isoformat()
            if grouped[key]["last_activity"] is None or stamp > grouped[key]["last_activity"]:
                grouped[key]["last_activity"] = stamp
        model = entry.get("display_model") or entry.get("model")
        if model:
            grouped[key]["models"][model] = grouped[key]["models"].get(model, 0) + 1

    other_key_ids = {
        key for key in grouped if key is not None and key != api_key_id
    }
    api_key_names: dict[int, str] = {}
    if other_key_ids:
        async with async_session_maker() as session:
            key_result = await session.execute(
                select(ApiKey.id, ApiKey.name).where(ApiKey.id.in_(other_key_ids))
            )
            api_key_names = {row.id: row.name for row in key_result.fetchall()}

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

    def _session_sort_key(item):
        if item["last_activity"]:
            ts = -datetime.fromisoformat(item["last_activity"]).timestamp()
        else:
            ts = 0
        return (ts, not item["is_self"], -item["requests"], item["name"])

    sessions.sort(key=_session_sort_key)
    return {
        "active_count": len(sessions),
        "request_count": sum(item["requests"] for item in sessions),
        "sessions": sessions,
        "busyness": dict(busyness_state) if busyness_state else None,
    }


@router.websocket("/user/api/live")
async def user_live_stats_websocket(websocket: WebSocket):
    token = websocket.cookies.get("user_session")
    session_data = USER_SESSIONS.get(token) if token else None
    if not session_data or datetime.now() > session_data["expires"]:
        await websocket.close(code=4401)
        return

    api_key_id = session_data.get("api_key_id")
    await websocket.accept()
    await add_user_live_stats_subscriber(api_key_id, websocket)

    try:
        snapshot = await build_user_live_stats_snapshot()
        snapshot["my_requests"] = await build_user_my_requests_rows(api_key_id)
        snapshot.update(await build_user_sessions_payload(api_key_id))
        await websocket.send_json(snapshot)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await remove_user_live_stats_subscriber(api_key_id, websocket)


@router.get("/user/api/provider-status")
async def get_user_provider_status(
    request: Request, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    from app.services.provider_limiter import get_disabled_providers_status

    return await get_disabled_providers_status()


@router.get("/user/api/catalog")
async def get_user_catalog(
    request: Request, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    from app.core.database import (
        ApiKeyModel,
        ApiKeyModelAccess,
        AutoModelRoute,
        Model,
        Provider,
        ProviderModel,
    )

    async with async_session_maker() as session:
        key_result = await session.execute(
            select(ApiKey).where(ApiKey.id == api_key_id)
        )
        api_key = key_result.scalar_one_or_none()
        if not api_key:
            return translated_error(request, "API Key not found", 404)

        providers_result = await session.execute(
            select(Provider)
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
        key_model_access_result = await session.execute(
            select(ApiKeyModelAccess).where(ApiKeyModelAccess.api_key_id == api_key_id)
        )
        auto_routes_result = await session.execute(
            select(AutoModelRoute).where(AutoModelRoute.enabled == True)  # noqa: E712
        )

        providers = providers_result.scalars().all()
        models = models_result.scalars().all()
        provider_models = provider_models_result.scalars().all()
        key_models = key_models_result.scalars().all()
        key_model_access = key_model_access_result.scalars().all()
        auto_routes = auto_routes_result.scalars().all()

    provider_map = {provider.id: provider for provider in providers}
    model_map = {model.id: model for model in models}
    active_provider_models = [
        pm
        for pm in provider_models
        if pm.provider_id in provider_map and pm.model_id in model_map
    ]

    allowed_pm_ids = {item.provider_model_id for item in key_models}
    allowed_model_ids = {item.model_id for item in key_model_access}
    full_access = len(allowed_pm_ids) == 0 and len(allowed_model_ids) == 0
    owned_provider_models = (
        active_provider_models
        if full_access
        else [
            pm
            for pm in active_provider_models
            if pm.id in allowed_pm_ids or pm.model_id in allowed_model_ids
        ]
    )

    bypass_busyness = _api_key_bypasses_busyness(api_key_id)

    def _is_provider_model_available(provider_model: ProviderModel) -> bool:
        provider = provider_map.get(provider_model.provider_id)
        model = model_map.get(provider_model.model_id)
        if not provider or not model:
            return False
        if not provider.is_active:
            return False
        provider_name = provider.name
        model_name = model.name
        pconf = providers_cache.get(provider_name)
        if not pconf:
            return False
        if pconf.get("disabled_reason"):
            return False
        for m in pconf.get("models", []):
            if m.get("model_id") == model.id or m.get("actual_model_name") == model_name:
                max_level = m.get("max_busyness_level")
                if max_level is not None:
                    current_level = busyness_state.get("level", 6)
                    if current_level > max_level:
                        if bypass_busyness:
                            return True
                        return False
                return True
        return False

    active_auto_virtual_model_ids = {
        route.virtual_model_id
        for route in auto_routes
        if route.virtual_model_id in model_map
        and model_map[route.virtual_model_id].is_active
        and (route.model_ids or route.provider_model_ids)
    }

    def serialize_virtual_models(model_ids: set[int]) -> list[dict]:
        items = []
        for model_id in sorted(model_ids, key=lambda mid: model_map[mid].name):
            model = model_map[model_id]
            items.append(
                {
                    "id": model.id,
                    "name": model.name,
                    "model_name": model.name,
                    "display_name": model.display_name or model.name,
                    "context": model.context_length or 0,
                    "output": model.max_tokens or 0,
                    "is_multimodal": bool(model.is_multimodal),
                    "has_override": False,
                    "providers": ["virtual"],
                    "is_virtual": True,
                }
            )
        return items

    def serialize_provider_models(items: list[ProviderModel], virtual_model_ids: set[int] | None = None) -> list[dict]:
        models_by_id: dict[int, dict] = {}
        for provider_model in items:
            model = model_map[provider_model.model_id]
            model_name = model.name
            display_name = model.display_name or model_name

            is_pm_available = _is_provider_model_available(provider_model)

            existing = models_by_id.get(model.id)
            provider_names = set(existing.get("providers", [])) if existing else set()
            if is_pm_available:
                provider_names.add(provider_map[provider_model.provider_id].name)
            pm_prices = existing.get("_pm_prices", []) if existing else []
            pm_prices.append({
                "input": provider_model.input_price_cny_per_million,
                "output": provider_model.output_price_cny_per_million,
                "cached": provider_model.cached_input_price_cny_per_million,
                "tiers": provider_model.pricing_tiers or [],
            })
            prev_available = existing.get("is_available", False) if existing else False
            models_by_id[model.id] = {
                "id": model.id,
                "name": model_name,
                "model_name": model_name,
                "display_name": display_name,
                "context": model.context_length or 0,
                "output": model.max_tokens or 0,
                "is_multimodal": bool(model.is_multimodal),
                "has_override": bool(
                    getattr(provider_model, "upstream_model_name", None)
                    or provider_model.model_name_override
                ),
                "providers": sorted(provider_names),
                "is_available": prev_available or is_pm_available,
                "_pm_prices": pm_prices,
            }

        for virtual_model in serialize_virtual_models(virtual_model_ids or set()):
            virtual_model["is_available"] = True
            models_by_id[virtual_model["id"]] = virtual_model

        for model_entry in models_by_id.values():
            pricing = aggregate_model_pricing(model_entry.pop("_pm_prices", []))
            model_entry["min_input_price"] = pricing["min_input_price"]
            model_entry["min_output_price"] = pricing["min_output_price"]
            model_entry["min_cached_price"] = pricing["min_cached_price"]
            model_entry["tier_samples"] = pricing["tier_samples"]

        models_data = sorted(models_by_id.values(), key=lambda item: item["model_name"])
        if not models_data:
            return []
        return [
            {
                "name": "ModelGate",
                "models": models_data,
                "model_count": len(models_data),
            }
        ]

    owned_virtual_model_ids = (
        active_auto_virtual_model_ids
        if full_access
        else active_auto_virtual_model_ids & allowed_model_ids
    )
    platform_providers = serialize_provider_models(
        active_provider_models,
        active_auto_virtual_model_ids,
    )
    owned_providers = serialize_provider_models(
        owned_provider_models,
        owned_virtual_model_ids,
    )

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


@router.get("/user/stats-v2", response_class=HTMLResponse)
async def user_stats_v2(request: Request, api_key_id: int = Depends(get_user_session)):
    if not api_key_id:
        return RedirectResponse(url=build_app_url(request, "/user/login"))

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == api_key_id))
        key = result.scalar_one_or_none()
        if not key:
            return RedirectResponse(url=build_app_url(request, "/user/login"))

        html = render(
            request, "user/stats_v2.html", name=key.name, api_key_id=api_key_id
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
    from app.services.documents import get_document

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
    from app.services.documents import list_documents, list_categories

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
    from app.services.documents import get_document

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
    from app.services.documents import get_document
    from app.services.document_files import list_files

    doc = await get_document(doc_id)
    if not doc or (not doc.get("is_published") and not is_admin):
        return translated_error(request, "Document not found", 404)

    files = await list_files(doc_id)
    result = []
    for f in files:
        url = ""
        if f.get("object_name"):
            from app.services.storage import get_presigned_url

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
    from app.services.documents import get_document
    from app.services.document_files import get_file
    from app.services.storage import get_presigned_url

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

