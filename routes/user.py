import json
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select

from core.config import logger, providers_cache
from core.database import (
    async_session_maker,
    ApiKey,
    RequestLogRead as RequestLog,
    ApiKeyDailyStat,
    ApiKeyModelDailyStat,
    ModelDailyStat,
)
from core.i18n import get_locale, render, translate
from services.message import preprocess_messages
from services.provider import get_model_config
from services.proxy import OUTBOUND_USER_AGENT

router = APIRouter(tags=["user"])
ERROR_STATUSES = ("error", "timeout")
ACTIVE_WINDOW_SECONDS = 30
USER_STATS_CACHE_TTL_SECONDS = 60
USER_RECOMMENDATION_REASON_TTL_SECONDS = 3600
SYSTEM_HEALTH_WINDOW_MINUTES = 20

USER_SESSIONS: dict[str, dict] = {}
USER_SESSION_EXPIRE_HOURS = 24
USER_STATS_CACHE: dict[tuple[int, str, str], dict] = {}
SYSTEM_MODEL_STATS_CACHE: dict[tuple[str, str], dict] = {}
USER_RECOMMENDATIONS_CACHE: dict[tuple[int, str, str], dict] = {}
USER_RECOMMENDATION_REASONS_CACHE: dict[tuple[int, str, str, str, str], dict] = {}
AGGREGATED_USER_PERIODS = {"month"}


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


def build_rule_based_recommendation_reason(request: Request, item: dict) -> str:
    error_rate = float(item.get("error_rate") or 0.0)
    avg_latency_ms = float(item.get("avg_latency_ms") or 0.0)
    requests_count = int(item.get("requests") or 0)

    if error_rate <= 0 and avg_latency_ms > 0 and avg_latency_ms <= 2500 and requests_count >= 10:
        return translate(
            request, "No recent errors, fast responses, and enough usage samples"
        )
    if error_rate <= 0.02 and requests_count >= 10:
        return translate(request, "Low error rate and stable recent performance")
    if avg_latency_ms > 0 and avg_latency_ms <= 2500:
        return translate(request, "Fast recent responses and smooth overall performance")
    if requests_count >= 15:
        return translate(request, "Frequently used recently with relatively stable quality")
    return translate(request, "Balanced recent stability, speed, and sample size")


def format_hour_range(hour_values: list[int]) -> list[str]:
    if not hour_values:
        return []

    sorted_hours = sorted(set(hour_values))
    ranges: list[str] = []
    start = sorted_hours[0]
    end = start
    for hour in sorted_hours[1:]:
        if hour == end + 1:
            end = hour
            continue
        ranges.append(f"{start:02d}:00-{(end + 1) % 24:02d}:00")
        start = hour
        end = hour
    ranges.append(f"{start:02d}:00-{(end + 1) % 24:02d}:00")
    return ranges


def build_rule_based_timing_advice(request: Request, hourly_stats: list[dict]) -> str:
    populated_hours = [item for item in hourly_stats if int(item.get("requests") or 0) > 0]
    if not populated_hours:
        return translate(
            request, "Recent data is limited. Try quieter periods and check system health first"
        )

    total_requests = sum(int(item.get("requests") or 0) for item in populated_hours)
    if total_requests < 10:
        return translate(
            request, "Recent data is limited. Try quieter periods and check system health first"
        )

    scored_hours: list[tuple[float, int]] = []
    for item in populated_hours:
        hour = int(item.get("hour") or 0)
        requests_count = float(item.get("requests") or 0)
        errors_count = float(item.get("errors") or 0)
        avg_latency_ms = float(item.get("avg_latency_ms") or 0)
        error_rate = (errors_count / requests_count) if requests_count > 0 else 0.0
        request_score = get_score_by_threshold(requests_count, 6.0, 60.0)
        error_score = get_score_by_threshold(error_rate, 0.01, 0.18)
        latency_score = (
            get_score_by_threshold(avg_latency_ms, 1800.0, 12000.0)
            if avg_latency_ms > 0
            else 0.7
        )
        score = (request_score * 0.35) + (error_score * 0.40) + (latency_score * 0.25)
        scored_hours.append((score, hour))

    best_hours = [hour for _, hour in sorted(scored_hours, reverse=True)[:3]]
    time_ranges = format_hour_range(best_hours)[:2]
    if not time_ranges:
        return translate(
            request, "Recent data is limited. Try quieter periods and check system health first"
        )

    if len(time_ranges) == 1:
        return translate(
            request,
            "Based on recent daily patterns, {ranges} tends to be smoother with lower errors and faster responses",
            ranges=time_ranges[0],
        )
    return translate(
        request,
        "Based on recent daily patterns, {ranges} tend to be smoother with lower errors and faster responses",
        ranges=" / ".join(time_ranges),
    )


def extract_text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def extract_json_payload(text: str) -> str:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return raw


async def generate_recommendation_insights(
    request: Request, recommendations: list[dict], hourly_stats: list[dict], period: str
) -> dict[str, object]:
    if not recommendations:
        return {
            "reasons": {},
            "timing_advice": build_rule_based_timing_advice(request, hourly_stats),
        }

    fallback_map = {
        item["model"]: build_rule_based_recommendation_reason(request, item)
        for item in recommendations
    }
    fallback_timing_advice = build_rule_based_timing_advice(request, hourly_stats)

    analyzer = recommendations[0]
    provider_name = analyzer.get("provider")
    actual_model_name = analyzer.get("actual_model_name")
    if not provider_name or not actual_model_name:
        return {"reasons": fallback_map, "timing_advice": fallback_timing_advice}

    provider_config = providers_cache.get(provider_name)
    if not provider_config or not provider_config.get("base_url"):
        return {"reasons": fallback_map, "timing_advice": fallback_timing_advice}

    locale = get_locale(request)
    language_name = "Chinese" if locale == "zh" else "English"
    candidates = [
        {
            "model": item["model"],
            "requests": item["requests"],
            "errors": item["errors"],
            "error_rate": item["error_rate"],
            "avg_latency_ms": item["avg_latency_ms"],
            "score": item["score"],
        }
        for item in recommendations
    ]
    hourly_candidates = [
        {
            "hour": int(item.get("hour") or 0),
            "requests": int(item.get("requests") or 0),
            "errors": int(item.get("errors") or 0),
            "error_rate": round(
                (float(item.get("errors") or 0) / float(item.get("requests") or 1))
                if float(item.get("requests") or 0) > 0
                else 0.0,
                4,
            ),
            "avg_latency_ms": round(float(item.get("avg_latency_ms") or 0), 2),
        }
        for item in hourly_stats
        if int(item.get("requests") or 0) > 0
    ]
    prompt = {
        "period": period,
        "language": language_name,
        "instruction": (
            "For each candidate, write one short recommendation reason based only on "
            "stability, error rate, response speed, and sample size. "
            "Also summarize which daily time windows are usually smoother to use based on the hourly stats. "
            "Return strict JSON in the form "
            '{"reasons":[{"model":"provider/model","reason":"..."}],"timing_advice":"..."}. '
            "Keep each reason concise and keep timing_advice to one short sentence."
        ),
        "candidates": candidates,
        "hourly_stats": hourly_candidates,
    }
    body_json = {
        "model": actual_model_name,
        "temperature": 0.2,
        "max_tokens": 220,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You summarize operational metrics for a dashboard. "
                    "Do not invent data. Reply with JSON only."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=False),
            },
        ],
    }

    merge_messages = provider_config.get("merge_consecutive_messages", False)
    model_config = get_model_config(provider_config, actual_model_name)
    is_multimodal = (
        model_config.get("is_multimodal", False) if model_config else False
    )
    body_json = preprocess_messages(body_json, merge_messages, is_multimodal)
    if provider_name == "minimax" and merge_messages:
        body_json.pop("thinking", None)
        body_json.pop("stream_options", None)
        body_json["reasoning_split"] = True

    headers = {
        "content-type": "application/json",
        "accept": "application/json",
        "user-agent": OUTBOUND_USER_AGENT,
    }
    if provider_config.get("api_key"):
        headers["authorization"] = f"Bearer {provider_config['api_key']}"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{provider_config['base_url']}/chat/completions",
                headers=headers,
                content=json.dumps(body_json).encode("utf-8"),
            )
        if response.status_code >= 400:
            logger.warning(
                "[USER] Recommendation reason generation failed for %s/%s with status %s",
                provider_name,
                actual_model_name,
                response.status_code,
            )
            return {"reasons": fallback_map, "timing_advice": fallback_timing_advice}

        payload = response.json()
        content = extract_text_content(
            (((payload.get("choices") or [{}])[0]).get("message") or {}).get("content")
        )
        raw_json = extract_json_payload(content)
        parsed = json.loads(raw_json) if raw_json else {}
        reasons = parsed.get("reasons") if isinstance(parsed, dict) else None
        timing_advice = parsed.get("timing_advice") if isinstance(parsed, dict) else None
        if not isinstance(reasons, list):
            return {"reasons": fallback_map, "timing_advice": fallback_timing_advice}

        reason_map = dict(fallback_map)
        allowed_models = {item["model"] for item in recommendations}
        for item in reasons:
            if not isinstance(item, dict):
                continue
            model_name = item.get("model")
            reason = item.get("reason")
            if (
                isinstance(model_name, str)
                and model_name in allowed_models
                and isinstance(reason, str)
                and reason.strip()
            ):
                reason_map[model_name] = reason.strip()
        return {
            "reasons": reason_map,
            "timing_advice": (
                timing_advice.strip()
                if isinstance(timing_advice, str) and timing_advice.strip()
                else fallback_timing_advice
            ),
        }
    except Exception as exc:
        logger.warning("[USER] Failed to generate recommendation reasons: %s", exc)
        return {"reasons": fallback_map, "timing_advice": fallback_timing_advice}


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
        "avg_latency_ms": round(float(avg_latency_ms or 0), 2) if avg_latency_ms else None,
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
            hour=0 if now.hour < 12 else 12,
            minute=0,
            second=0,
            microsecond=0,
        )
        start = current_bucket_start - timedelta(hours=12 * 13)
        intervals = [
            ((start + timedelta(hours=12 * i)).strftime("%m/%d %H:%M"))
            for i in range(14)
        ]
        def format_func(d: datetime) -> str:
            bucket_index = max(
                0,
                min(
                    int((d - start).total_seconds() // (12 * 3600)),
                    len(intervals) - 1,
                ),
            )
            return intervals[bucket_index]
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30)
        intervals = [
            ((start + timedelta(days=i)).strftime("%m/%d"))
            for i in range(31)
        ]
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
                .where(RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start)
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
                func.count(func.distinct(RequestLog.api_key_id)).label("active_api_keys"),
                func.sum(case((RequestLog.status.in_(ERROR_STATUSES), 1), else_=0)).label(
                    "error_count"
                ),
                func.avg(
                    case((RequestLog.status != "pending", RequestLog.latency_ms), else_=None)
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

        payload = {
            "name": key.name,
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "models": model_stats,
            "trend": trend_data,
            "system_health": system_health,
        }
        set_cached_payload(USER_STATS_CACHE, cache_key, payload, now)
        return payload


@router.get("/user/api/active")
async def get_user_active_sessions(
    request: Request, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    cutoff = get_local_now() - timedelta(seconds=ACTIVE_WINDOW_SECONDS)
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog)
            .where(
                RequestLog.api_key_id == api_key_id,
                or_(
                    RequestLog.status == "pending",
                    RequestLog.created_at >= cutoff,
                ),
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
                    bucket = models.setdefault(
                        row.model, {"requests": 0, "tokens": 0}
                    )
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
    set_cached_payload(SYSTEM_MODEL_STATS_CACHE, cache_key, payload, now)
    return payload


@router.get("/user/api/recommendations")
async def get_user_recommendations(
    request: Request, api_key_id: int = Depends(get_user_session), period: str = "day"
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    from core.database import ApiKeyModel, Model, Provider, ProviderModel

    now = get_local_now()
    start, _, _ = get_user_period_range(now, period)
    cache_key = (api_key_id, period, "v3", get_cache_bucket(now))
    cached_payload = get_cached_payload(USER_RECOMMENDATIONS_CACHE, cache_key, now)
    if cached_payload is not None:
        return cached_payload

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
        models_result = await session.execute(select(Model).where(Model.is_active == True))
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
        accessible_provider_models = (
            active_provider_models
            if full_access
            else [pm for pm in active_provider_models if pm.id in allowed_pm_ids]
        )

        accessible_model_meta: dict[tuple[int, str], dict] = {}
        accessible_provider_ids: set[int] = set()
        accessible_model_names: set[str] = set()
        for provider_model in accessible_provider_models:
            provider = provider_map[provider_model.provider_id]
            model = model_map[provider_model.model_id]
            full_name = f"{provider.name}/{model.name}"
            accessible_model_meta[(provider.id, model.name)] = {
                "provider": provider.name,
                "model_name": model.name,
                "display_name": model.display_name or model.name,
                "full_name": full_name,
            }
            accessible_provider_ids.add(provider.id)
            accessible_model_names.add(model.name)

        if not accessible_model_meta:
            payload = {
                "period": period,
                "generated_at": now.isoformat(),
                "items": [],
            }
            set_cached_payload(USER_RECOMMENDATIONS_CACHE, cache_key, payload, now)
            return payload

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
                RequestLog.provider_id.in_(list(accessible_provider_ids)),
                RequestLog.model.in_(list(accessible_model_names)),
                RequestLog.status != "pending",
            )
            .group_by(RequestLog.provider_id, RequestLog.model)
        )
        rows = rows_result.fetchall()

        hourly_rows_result = await session.execute(
            select(
                func.extract("hour", RequestLog.created_at).label("hour_of_day"),
                func.count(RequestLog.id).label("requests"),
                func.avg(RequestLog.latency_ms).label("avg_latency_ms"),
                func.sum(
                    case((RequestLog.status.in_(ERROR_STATUSES), 1), else_=0)
                ).label("errors"),
            )
            .where(
                RequestLog.created_at >= start,
                RequestLog.provider_id.in_(list(accessible_provider_ids)),
                RequestLog.model.in_(list(accessible_model_names)),
                RequestLog.status != "pending",
            )
            .group_by(func.extract("hour", RequestLog.created_at))
            .order_by(func.extract("hour", RequestLog.created_at))
        )
        hourly_rows = hourly_rows_result.fetchall()

    recommendations = []
    for row in rows:
        if not row.model:
            continue

        meta = accessible_model_meta.get((row.provider_id, row.model))
        if not meta:
            continue

        requests_count = int(row.requests or 0)
        errors_count = int(row.errors or 0)
        if requests_count <= 0:
            continue

        avg_latency_ms = float(row.avg_latency_ms or 0)
        error_rate = errors_count / requests_count if requests_count else 1.0
        reliability_score = max(0.0, 1.0 - (error_rate * 1.5))
        latency_score = 1 / (1 + (avg_latency_ms / 2500.0)) if avg_latency_ms > 0 else 0.0
        sample_score = min(requests_count / 20.0, 1.0)
        score = (reliability_score * 0.55) + (latency_score * 0.30) + (sample_score * 0.15)

        recommendations.append(
            {
                "model": meta["full_name"],
                "display_name": meta["display_name"],
                "provider": meta["provider"],
                "actual_model_name": meta["model_name"],
                "requests": requests_count,
                "errors": errors_count,
                "error_rate": round(error_rate, 4),
                "avg_latency_ms": round(avg_latency_ms, 2),
                "score": round(score, 4),
            }
        )

    recommendations.sort(
        key=lambda item: (
            -item["score"],
            item["error_rate"],
            item["avg_latency_ms"],
            -item["requests"],
            item["model"],
        )
    )

    for index, item in enumerate(recommendations, start=1):
        item["rank"] = index

    top_recommendations = recommendations[:5]
    reason_cache_key = (
        api_key_id,
        period,
        get_locale(request),
        "insights-v1",
        get_hour_cache_bucket(now),
    )
    hourly_stats = [
        {
            "hour": int(row.hour_of_day or 0),
            "requests": int(row.requests or 0),
            "errors": int(row.errors or 0),
            "avg_latency_ms": round(float(row.avg_latency_ms or 0), 2)
            if row.avg_latency_ms is not None
            else None,
        }
        for row in hourly_rows
    ]
    insight_payload = get_cached_payload(
        USER_RECOMMENDATION_REASONS_CACHE,
        reason_cache_key,
        now,
        ttl_seconds=USER_RECOMMENDATION_REASON_TTL_SECONDS,
    )
    if insight_payload is None:
        insight_payload = await generate_recommendation_insights(
            request, top_recommendations, hourly_stats, period
        )
        set_cached_payload(
            USER_RECOMMENDATION_REASONS_CACHE, reason_cache_key, insight_payload, now
        )

    reason_map = insight_payload.get("reasons") if isinstance(insight_payload, dict) else {}
    if not isinstance(reason_map, dict):
        reason_map = {}
    timing_advice = (
        insight_payload.get("timing_advice")
        if isinstance(insight_payload, dict)
        else None
    )
    if not isinstance(timing_advice, str) or not timing_advice.strip():
        timing_advice = build_rule_based_timing_advice(request, hourly_stats)

    for item in top_recommendations:
        item["reason"] = reason_map.get(item["model"]) or build_rule_based_recommendation_reason(
            request, item
        )

    payload = {
        "period": period,
        "generated_at": now.isoformat(),
        "items": top_recommendations,
        "timing_advice": timing_advice,
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
async def get_user_catalog(request: Request, api_key_id: int = Depends(get_user_session)):
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

    def serialize_provider_models(items: list[ProviderModel]) -> list[dict]:
        grouped: dict[str, dict] = {}
        for provider_model in items:
            provider = provider_map[provider_model.provider_id]
            model = model_map[provider_model.model_id]
            provider_name = provider.name
            model_name = model.name
            display_name = model.display_name or model_name

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
        return RedirectResponse(url="/user/login")

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == api_key_id))
        key = result.scalar_one_or_none()
        if not key:
            return RedirectResponse(url="/user/login")

        html = render(
            request, "user/dashboard.html", name=key.name, api_key_id=api_key_id
        )
        return HTMLResponse(content=html)


@router.get("/user/api/opencode-config")
async def get_user_opencode_config(
    request: Request, api_key_id: int = Depends(get_user_session)
):
    if not api_key_id:
        return translated_error(request, "Not authenticated", 401)

    from core.database import Provider, Model, ProviderModel, ApiKeyModel

    async with async_session_maker() as session:
        key_result = await session.execute(
            select(ApiKey).where(ApiKey.id == api_key_id)
        )
        api_key = key_result.scalar_one_or_none()
        if not api_key:
            return translated_error(request, "API Key not found", 404)

        models_result = await session.execute(
            select(ApiKeyModel).where(ApiKeyModel.api_key_id == api_key_id)
        )
        key_models = models_result.scalars().all()

        allowed_pm_ids = [km.provider_model_id for km in key_models]

        if allowed_pm_ids:
            pm_result = await session.execute(
                select(ProviderModel).where(ProviderModel.id.in_(allowed_pm_ids))
            )
        else:
            pm_result = await session.execute(select(ProviderModel))

        provider_models = pm_result.scalars().all()

        models_data = []
        models_config = {}

        for pm in provider_models:
            provider_result = await session.execute(
                select(Provider).where(Provider.id == pm.provider_id)
            )
            provider = provider_result.scalar_one_or_none()
            if not provider:
                continue

            model_result = await session.execute(
                select(Model).where(Model.id == pm.model_id)
            )
            model = model_result.scalar_one_or_none()
            if not model:
                continue

            model_key = f"{provider.name}/{model.name}"
            display_name = model.display_name or model.name

            max_output = model.max_tokens or 16384
            context_window = model.context_length or (max_output * 8)

            models_config[model_key] = {
                "name": f"{provider.name}/{display_name}",
                "modalities": {"input": ["text"], "output": ["text"]},
                "limit": {"context": context_window, "output": max_output},
            }
            if model.thinking_enabled:
                models_config[model_key]["options"] = {
                    "thinking": {
                        "type": "enabled",
                    }
                }

            models_data.append(
                {"name": model_key, "context": context_window, "output": max_output}
            )

        config = {
            "$schema": "https://opencode.ai/config.json",
            "provider": {
                "model-token-plan": {
                    "name": "Model Token Plan",
                    "options": {
                        "baseURL": "BASEURL_PLACEHOLDER",
                        "apiKey": api_key.key,
                    },
                    "models": models_config,
                }
            },
        }

        return {"config": config, "models": models_data}
