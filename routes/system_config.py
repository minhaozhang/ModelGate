from datetime import date, datetime
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select, func

import core.config as config
from core.config import (
    validate_session,
    OUTBOUND_USER_AGENT,
    DEFAULT_OUTBOUND_USER_AGENT,
)
from core.database import async_session_maker, RequestLog
from core.i18n import render

router = APIRouter(prefix="/admin", tags=["system-config"])


def require_admin(session: str = Cookie(None)):
    if not validate_session(session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


@router.get("/api/system/config")
async def get_config(_: bool = Depends(require_admin)):
    return {
        "ua_override": config.system_config.get("ua_override")
        or DEFAULT_OUTBOUND_USER_AGENT,
        "default_ua": DEFAULT_OUTBOUND_USER_AGENT,
        "api_key_model_max_concurrency": int(
            config.system_config.get("api_key_model_max_concurrency") or 1
        ),
        "busyness_rules": config.system_config.get("busyness_rules", []),
    }


@router.put("/api/system/config")
async def update_config(body: dict, _: bool = Depends(require_admin)):
    ua = body.get("ua_override", "").strip()
    if ua:
        config.OUTBOUND_USER_AGENT = ua
        config.system_config["ua_override"] = ua
    raw_limit = body.get("api_key_model_max_concurrency")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="api_key_model_max_concurrency must be an integer",
            )
        if limit < 1:
            raise HTTPException(
                status_code=400,
                detail="api_key_model_max_concurrency must be at least 1",
            )
        config.system_config["api_key_model_max_concurrency"] = limit
    raw_rules = body.get("busyness_rules")
    if raw_rules is not None:
        if not isinstance(raw_rules, list):
            raise HTTPException(status_code=400, detail="busyness_rules must be a list")
        for rule in raw_rules:
            if not isinstance(rule, dict):
                raise HTTPException(status_code=400, detail="Each busyness rule must be an object")
            if "min_level" not in rule or "action" not in rule:
                raise HTTPException(status_code=400, detail="Each rule needs min_level and action")
            if rule["action"] not in ("downgrade", "suggest", "block"):
                raise HTTPException(status_code=400, detail="action must be downgrade, suggest, or block")
        config.system_config["busyness_rules"] = raw_rules
    return {
        "ua_override": config.OUTBOUND_USER_AGENT,
        "api_key_model_max_concurrency": int(
            config.system_config.get("api_key_model_max_concurrency") or 1
        ),
        "busyness_rules": config.system_config.get("busyness_rules", []),
    }


@router.get("/api/system/ua-stats")
async def get_ua_stats(limit: int = 10, _: bool = Depends(require_admin)):
    today_start = datetime.combine(date.today(), datetime.min.time())
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog.user_agent, func.count(RequestLog.id).label("cnt"))
            .where(
                RequestLog.user_agent.isnot(None),
                RequestLog.created_at >= today_start,
            )
            .group_by(RequestLog.user_agent)
            .order_by(func.count(RequestLog.id).desc())
            .limit(limit)
        )
        rows = result.all()

    total = sum(r[1] for r in rows)
    items = []
    for ua, cnt in rows:
        items.append(
            {
                "ua": ua,
                "count": cnt,
                "pct": round(cnt / total * 100, 1) if total > 0 else 0,
            }
        )
    return {"items": items, "total": total}


@router.get("/system-config", response_class=HTMLResponse)
async def system_config_page(request: Request, _: bool = Depends(require_admin)):
    return HTMLResponse(
        content=render(request, "admin/system_config.html", active_page="system-config")
    )
