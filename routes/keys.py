from datetime import time as dt_time, date as dt_date

from fastapi import APIRouter, Depends, Cookie, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select, func, delete

from core.database import (
    async_session_maker,
    ApiKey,
    ApiKeyModel,
    ApiKeyMcpServer,
    ApiKeyTimeRule,
    RequestLogRead as RequestLog,
    generate_api_key,
)
from services.auth import load_api_keys
from routes.user import get_user_session
from core.config import validate_session

router = APIRouter(prefix="/admin/api", tags=["api-keys"])


def require_admin(session: Optional[str] = Cookie(None)):
    if not validate_session(session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


class ApiKeyCreate(BaseModel):
    name: str
    allowed_provider_model_ids: list[int] = []
    mcp_server_ids: list[int] = []


class ApiKeyUpdate(BaseModel):
    name: Optional[str] = None
    allowed_provider_model_ids: Optional[list[int]] = None
    is_active: Optional[bool] = None
    mcp_server_ids: Optional[list[int]] = None


@router.get("/keys")
async def list_api_keys(_: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey))
        keys = result.scalars().all()
        api_keys = []
        for k in keys:
            models_result = await session.execute(
                select(ApiKeyModel.provider_model_id).where(
                    ApiKeyModel.api_key_id == k.id
                )
            )
            model_ids = [row[0] for row in models_result.fetchall()]

            rules_result = await session.execute(
                select(ApiKeyTimeRule)
                .where(ApiKeyTimeRule.api_key_id == k.id)
                .order_by(ApiKeyTimeRule.rule_type, ApiKeyTimeRule.id)
            )
            rules = rules_result.scalars().all()
            time_rules = [
                {
                    "id": r.id,
                    "rule_type": r.rule_type,
                    "allowed": r.allowed,
                    "start_time": _serialize_time(r.start_time),
                    "end_time": _serialize_time(r.end_time),
                    "start_date": _serialize_date(r.start_date),
                    "end_date": _serialize_date(r.end_date),
                    "weekdays": r.weekdays,
                }
                for r in rules
            ]

            mcp_result = await session.execute(
                select(ApiKeyMcpServer.mcp_server_id).where(
                    ApiKeyMcpServer.api_key_id == k.id
                )
            )
            mcp_server_ids = [row[0] for row in mcp_result.fetchall()]

            api_keys.append(
                {
                    "id": k.id,
                    "name": k.name,
                    "key": k.key,
                    "allowed_provider_model_ids": model_ids,
                    "time_rules": time_rules,
                    "is_active": k.is_active,
                    "mcp_server_ids": mcp_server_ids,
                    "last_used_at": k.last_used_at.isoformat()
                    if k.last_used_at
                    else None,
                }
            )
        return {"api_keys": api_keys}


@router.post("/keys")
async def create_api_key(data: ApiKeyCreate, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        new_key = ApiKey(name=data.name, key=generate_api_key())
        session.add(new_key)
        await session.commit()
        await session.refresh(new_key)

        for pm_id in data.allowed_provider_model_ids:
            assoc = ApiKeyModel(api_key_id=new_key.id, provider_model_id=pm_id)
            session.add(assoc)
        for sid in data.mcp_server_ids:
            assoc = ApiKeyMcpServer(api_key_id=new_key.id, mcp_server_id=sid)
            session.add(assoc)
        await session.commit()
        await load_api_keys()
        return {"id": new_key.id, "name": new_key.name, "key": new_key.key}


@router.put("/keys/{key_id}")
async def update_api_key(
    key_id: int, data: ApiKeyUpdate, _: bool = Depends(require_admin)
):
    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "API key not found"}, status_code=404)
        if data.name is not None:
            key.name = data.name
        if data.is_active is not None:
            key.is_active = data.is_active
        if data.mcp_server_ids is not None:
            await session.execute(
                delete(ApiKeyMcpServer).where(ApiKeyMcpServer.api_key_id == key_id)
            )
            for sid in data.mcp_server_ids:
                assoc = ApiKeyMcpServer(api_key_id=key_id, mcp_server_id=sid)
                session.add(assoc)
        if data.allowed_provider_model_ids is not None:
            await session.execute(
                delete(ApiKeyModel).where(ApiKeyModel.api_key_id == key_id)
            )
            for pm_id in data.allowed_provider_model_ids:
                assoc = ApiKeyModel(api_key_id=key_id, provider_model_id=pm_id)
                session.add(assoc)
        await session.commit()
        await load_api_keys()
        return {"id": key.id}


@router.delete("/keys/{key_id}")
async def delete_api_key(key_id: int, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "API key not found"}, status_code=404)
        await session.execute(
            delete(ApiKeyModel).where(ApiKeyModel.api_key_id == key_id)
        )
        await session.delete(key)
        await session.commit()
        await load_api_keys()
        return {"deleted": True}


@router.get("/keys/{key_id}/stats")
async def get_api_key_stats(
    key_id: int, user_api_key_id: int = Depends(get_user_session)
):
    if not user_api_key_id:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    if user_api_key_id != key_id:
        return JSONResponse({"error": "Access denied"}, status_code=403)

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "API key not found"}, status_code=404)

        total_result = await session.execute(
            select(func.count(RequestLog.id)).where(RequestLog.api_key_id == key_id)
        )
        total_requests = total_result.scalar() or 0

        tokens_result = await session.execute(
            select(func.sum(RequestLog.tokens["total_tokens"].as_integer())).where(
                RequestLog.api_key_id == key_id
            )
        )
        total_tokens = tokens_result.scalar() or 0

        errors_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.api_key_id == key_id, RequestLog.status == "error"
            )
        )
        total_errors = errors_result.scalar() or 0

        model_stats_result = await session.execute(
            select(
                RequestLog.model,
                func.count(RequestLog.id).label("count"),
                func.sum(RequestLog.tokens["total_tokens"].as_integer()).label(
                    "tokens"
                ),
            )
            .where(RequestLog.api_key_id == key_id)
            .group_by(RequestLog.model)
        )
        model_stats = {
            row.model: {"requests": row.count, "tokens": row.tokens or 0}
            for row in model_stats_result
        }

        return {
            "name": key.name,
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "models": model_stats,
        }


@router.get("/keys/{key_id}/logs")
async def get_api_key_logs(
    key_id: int, limit: int = 100, user_api_key_id: int = Depends(get_user_session)
):
    if not user_api_key_id:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    if user_api_key_id != key_id:
        return JSONResponse({"error": "Access denied"}, status_code=403)

    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog)
            .where(RequestLog.api_key_id == key_id)
            .order_by(RequestLog.created_at.desc())
            .limit(limit)
        )
        logs = result.scalars().all()
        return {
            "logs": [
                {
                    "id": log.id,
                    "model": log.model,
                    "status": log.status,
                    "latency_ms": log.latency_ms,
                    "tokens": log.tokens,
                    "created_at": log.created_at.isoformat(),
                    "response": log.response,
                    "error": log.error,
                }
                for log in logs
            ]
        }


class TimeRuleCreate(BaseModel):
    rule_type: str
    allowed: bool = True
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    weekdays: Optional[str] = None


class TimeRuleUpdate(BaseModel):
    rule_type: Optional[str] = None
    allowed: Optional[bool] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    weekdays: Optional[str] = None
    clear_fields: Optional[list[str]] = []


VALID_RULE_TYPES = {"time_range", "date_range", "weekday"}


def _parse_time(val: str | None) -> dt_time | None:
    if not val:
        return None
    try:
        parts = val.split(":")
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) > 2 else 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
            return None
        return dt_time(hour, minute, second)
    except (ValueError, IndexError):
        return None


def _parse_date(val: str | None) -> dt_date | None:
    if not val:
        return None
    try:
        return dt_date.fromisoformat(val)
    except ValueError:
        return None


def _validate_weekdays(val: str | None) -> str | None:
    if not val:
        return None
    days = [d.strip() for d in val.split(",") if d.strip()]
    for d in days:
        if not d.isdigit():
            return None
        if not (0 <= int(d) <= 6):
            return None
    return ",".join(days)


def _serialize_time(val: dt_time | None) -> str | None:
    return val.strftime("%H:%M:%S") if val else None


def _serialize_date(val: dt_date | None) -> str | None:
    return val.isoformat() if val else None


@router.get("/keys/{key_id}/time-rules")
async def list_time_rules(key_id: int, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ApiKeyTimeRule)
            .where(ApiKeyTimeRule.api_key_id == key_id)
            .order_by(ApiKeyTimeRule.rule_type, ApiKeyTimeRule.id)
        )
        rules = result.scalars().all()
        return {
            "rules": [
                {
                    "id": r.id,
                    "rule_type": r.rule_type,
                    "allowed": r.allowed,
                    "start_time": _serialize_time(r.start_time),
                    "end_time": _serialize_time(r.end_time),
                    "start_date": _serialize_date(r.start_date),
                    "end_date": _serialize_date(r.end_date),
                    "weekdays": r.weekdays,
                }
                for r in rules
            ]
        }


@router.post("/keys/{key_id}/time-rules")
async def create_time_rule(
    key_id: int, data: TimeRuleCreate, _: bool = Depends(require_admin)
):
    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
        if not result.scalar_one_or_none():
            return JSONResponse({"error": "API key not found"}, status_code=404)

        if data.rule_type not in VALID_RULE_TYPES:
            return JSONResponse(
                {
                    "error": f"Invalid rule_type, must be one of: {', '.join(sorted(VALID_RULE_TYPES))}"
                },
                status_code=422,
            )

        if data.weekdays is not None:
            validated_weekdays = _validate_weekdays(data.weekdays)
            if data.weekdays and validated_weekdays is None:
                return JSONResponse(
                    {"error": "Invalid weekdays, must be comma-separated numbers 0-6"},
                    status_code=422,
                )

        parsed_start_time = _parse_time(data.start_time)
        parsed_end_time = _parse_time(data.end_time)
        if data.start_time and parsed_start_time is None:
            return JSONResponse(
                {"error": "Invalid start_time format, expected HH:MM:SS"},
                status_code=422,
            )
        if data.end_time and parsed_end_time is None:
            return JSONResponse(
                {"error": "Invalid end_time format, expected HH:MM:SS"}, status_code=422
            )

        parsed_start_date = _parse_date(data.start_date)
        parsed_end_date = _parse_date(data.end_date)
        if data.start_date and parsed_start_date is None:
            return JSONResponse(
                {"error": "Invalid start_date format, expected YYYY-MM-DD"},
                status_code=422,
            )
        if data.end_date and parsed_end_date is None:
            return JSONResponse(
                {"error": "Invalid end_date format, expected YYYY-MM-DD"},
                status_code=422,
            )

        rule = ApiKeyTimeRule(
            api_key_id=key_id,
            rule_type=data.rule_type,
            allowed=data.allowed,
            start_time=parsed_start_time,
            end_time=parsed_end_time,
            start_date=parsed_start_date,
            end_date=parsed_end_date,
            weekdays=_validate_weekdays(data.weekdays),
        )
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
        await load_api_keys()
        return {
            "id": rule.id,
            "rule_type": rule.rule_type,
            "allowed": rule.allowed,
            "start_time": _serialize_time(rule.start_time),
            "end_time": _serialize_time(rule.end_time),
            "start_date": _serialize_date(rule.start_date),
            "end_date": _serialize_date(rule.end_date),
            "weekdays": rule.weekdays,
        }


@router.put("/keys/{key_id}/time-rules/{rule_id}")
async def update_time_rule(
    key_id: int, rule_id: int, data: TimeRuleUpdate, _: bool = Depends(require_admin)
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ApiKeyTimeRule).where(
                ApiKeyTimeRule.id == rule_id,
                ApiKeyTimeRule.api_key_id == key_id,
            )
        )
        rule = result.scalar_one_or_none()
        if not rule:
            return JSONResponse({"error": "Time rule not found"}, status_code=404)

        CLEARABLE_FIELDS = {
            "start_time",
            "end_time",
            "start_date",
            "end_date",
            "weekdays",
        }

        if data.clear_fields:
            invalid = set(data.clear_fields) - CLEARABLE_FIELDS
            if invalid:
                return JSONResponse(
                    {"error": f"Cannot clear fields: {', '.join(sorted(invalid))}"},
                    status_code=422,
                )
            for field in data.clear_fields:
                setattr(rule, field, None)

        if data.rule_type is not None:
            if data.rule_type not in VALID_RULE_TYPES:
                return JSONResponse(
                    {
                        "error": f"Invalid rule_type, must be one of: {', '.join(sorted(VALID_RULE_TYPES))}"
                    },
                    status_code=422,
                )
            rule.rule_type = data.rule_type
        if data.allowed is not None:
            rule.allowed = data.allowed
        if data.start_time is not None:
            parsed = _parse_time(data.start_time)
            if parsed is None:
                return JSONResponse(
                    {"error": "Invalid start_time format, expected HH:MM:SS"},
                    status_code=422,
                )
            rule.start_time = parsed
        if data.end_time is not None:
            parsed = _parse_time(data.end_time)
            if parsed is None:
                return JSONResponse(
                    {"error": "Invalid end_time format, expected HH:MM:SS"},
                    status_code=422,
                )
            rule.end_time = parsed
        if data.start_date is not None:
            parsed = _parse_date(data.start_date)
            if parsed is None:
                return JSONResponse(
                    {"error": "Invalid start_date format, expected YYYY-MM-DD"},
                    status_code=422,
                )
            rule.start_date = parsed
        if data.end_date is not None:
            parsed = _parse_date(data.end_date)
            if parsed is None:
                return JSONResponse(
                    {"error": "Invalid end_date format, expected YYYY-MM-DD"},
                    status_code=422,
                )
            rule.end_date = parsed
        if data.weekdays is not None:
            validated = _validate_weekdays(data.weekdays)
            if data.weekdays and validated is None:
                return JSONResponse(
                    {"error": "Invalid weekdays, must be comma-separated numbers 0-6"},
                    status_code=422,
                )
            rule.weekdays = validated

        await session.commit()
        await load_api_keys()
        return {"id": rule.id}


@router.delete("/keys/{key_id}/time-rules/{rule_id}")
async def delete_time_rule(key_id: int, rule_id: int, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ApiKeyTimeRule).where(
                ApiKeyTimeRule.id == rule_id,
                ApiKeyTimeRule.api_key_id == key_id,
            )
        )
        rule = result.scalar_one_or_none()
        if not rule:
            return JSONResponse({"error": "Time rule not found"}, status_code=404)
        await session.delete(rule)
        await session.commit()
        await load_api_keys()
        return {"deleted": True}
