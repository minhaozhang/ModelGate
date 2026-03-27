import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import case, func, select

from core.database import async_session_maker, ApiKey, RequestLog
from core.config import logger

router = APIRouter(tags=["user"])

USER_SESSIONS: dict[str, dict] = {}
USER_SESSION_EXPIRE_HOURS = 24


from templates.user.login import USER_LOGIN_HTML
from templates.user.dashboard import USER_DASHBOARD_HTML


class UserLoginRequest(BaseModel):
    api_key: str


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


def get_user_period_range(
    now: datetime, period: str
) -> tuple[datetime, list[str], Callable[[datetime], str]]:
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        intervals = [((start + timedelta(hours=i)).strftime("%H:00")) for i in range(24)]
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
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days_in_month = (
            now.replace(month=now.month % 12 + 1, day=1) - timedelta(days=1)
        ).day
        intervals = [
            ((start + timedelta(days=i)).strftime("%m/%d"))
            for i in range(days_in_month)
        ]
        format_func = lambda d: d.strftime("%m/%d")

    return start, intervals, format_func


@router.get("/user/login", response_class=HTMLResponse)
async def user_login_page():
    return HTMLResponse(content=USER_LOGIN_HTML)


@router.post("/user/api/login")
async def user_login(data: UserLoginRequest, response: Response):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key == data.api_key, ApiKey.is_active == True)
        )
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "Invalid API Key"}, status_code=401)

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
    api_key_id: int = Depends(get_user_session), period: str = "day"
):
    if not api_key_id:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    from datetime import datetime, timedelta

    async with async_session_maker() as db_session:
        now_result = await db_session.execute(select(func.now()))
        now = now_result.scalar()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    start, intervals, format_func = get_user_period_range(now, period)

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == api_key_id))
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "API key not found"}, status_code=404)

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
            ).where(RequestLog.api_key_id == api_key_id, RequestLog.created_at >= start)
        )
        total_tokens = tokens_result.scalar() or 0

        errors_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.api_key_id == api_key_id,
                RequestLog.status == "error",
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
                func.sum(case((RequestLog.status == "error", 1), else_=0)).label(
                    "errors"
                ),
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

        trend_data = {label: {"requests": 0, "tokens": 0, "errors": 0} for label in intervals}
        for log in trend_logs:
            label = format_func(log.created_at)
            if label in trend_data:
                trend_data[label]["requests"] += 1
                tokens = (
                    (log.tokens or {}).get("total_tokens")
                    or (log.tokens or {}).get("estimated")
                    or 0
                )
                trend_data[label]["tokens"] += tokens
                if log.status == "error":
                    trend_data[label]["errors"] += 1

        return {
            "name": key.name,
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "models": model_stats,
            "trend": trend_data,
        }


@router.get("/user/api/active")
async def get_user_active_sessions(api_key_id: int = Depends(get_user_session)):
    if not api_key_id:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog).where(
                RequestLog.api_key_id == api_key_id,
                RequestLog.created_at >= func.now() - timedelta(minutes=1),
            )
        )
        logs = result.scalars().all()

        model_sessions = {}
        for log in logs:
            if not log.model:
                continue

            model = log.model
            if model not in model_sessions:
                model_sessions[model] = {"requests": 0}

            model_sessions[model]["requests"] += 1

        return {
            "active_count": len(model_sessions),
            "sessions": model_sessions,
        }


@router.get("/user/api/system-models")
async def get_system_model_stats(
    api_key_id: int = Depends(get_user_session), period: str = "day"
):
    if not api_key_id:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    async with async_session_maker() as db_session:
        now_result = await db_session.execute(select(func.now()))
        now = now_result.scalar()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)

    start, _, _ = get_user_period_range(now, period)

    async with async_session_maker() as session:
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
    return {
        "period": period,
        "total_requests": sum(v["requests"] for v in models.values()),
        "total_tokens": sum(v["tokens"] for v in models.values()),
        "models": models,
    }


@router.get("/user/api/system-active")
async def get_system_active_sessions(api_key_id: int = Depends(get_user_session)):
    if not api_key_id:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog).where(RequestLog.created_at >= func.now() - timedelta(minutes=1))
        )
        logs = result.scalars().all()

    grouped: dict[int | None, dict] = {}
    for log in logs:
        key = log.api_key_id
        if key not in grouped:
            grouped[key] = {"requests": 0, "models": {}}
        grouped[key]["requests"] += 1
        if log.model:
            grouped[key]["models"][log.model] = grouped[key]["models"].get(log.model, 0) + 1

    other_index = 1
    sessions = []
    for key in sorted(grouped.keys(), key=lambda value: (value != api_key_id, value or 0)):
        stats = grouped[key]
        if key == api_key_id:
            display_name = "Yourself"
            is_self = True
        elif key is None:
            display_name = "Anonymous"
            is_self = False
        else:
            display_name = f"Other {other_index}"
            other_index += 1
            is_self = False

        sessions.append(
            {
                "name": display_name,
                "is_self": is_self,
                "requests": stats["requests"],
                "models": stats["models"],
            }
        )

    sessions.sort(key=lambda item: (not item["is_self"], -item["requests"], item["name"]))
    return {
        "active_count": len(sessions),
        "request_count": sum(item["requests"] for item in sessions),
        "sessions": sessions,
    }


@router.get("/user/dashboard", response_class=HTMLResponse)
async def user_dashboard(api_key_id: int = Depends(get_user_session)):
    if not api_key_id:
        return RedirectResponse(url="/user/login")

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == api_key_id))
        key = result.scalar_one_or_none()
        if not key:
            return RedirectResponse(url="/user/login")

        html = USER_DASHBOARD_HTML.format(name=key.name, api_key_id=api_key_id)
        return HTMLResponse(content=html)


@router.get("/user/api/opencode-config")
async def get_user_opencode_config(api_key_id: int = Depends(get_user_session)):
    if not api_key_id:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    from core.database import Provider, Model, ProviderModel, ApiKeyModel

    async with async_session_maker() as session:
        key_result = await session.execute(
            select(ApiKey).where(ApiKey.id == api_key_id)
        )
        api_key = key_result.scalar_one_or_none()
        if not api_key:
            return JSONResponse({"error": "API Key not found"}, status_code=404)

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
                "options": {"thinking": {"type": "enabled", "budgetTokens": 8192}},
                "limit": {"context": context_window, "output": max_output},
            }

            models_data.append(
                {"name": model_key, "context": context_window, "output": max_output}
            )

        config = {
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
