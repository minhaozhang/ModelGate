from datetime import datetime, timedelta, time as dt_time, date as dt_date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy import select, func, delete
from collections import defaultdict

from app.core.database import (
    async_session_maker,
    ApiKey,
    ApiKeyModel,
    ApiKeyModelAccess,
    ApiKeyTag,
    ApiKeyTimeRule,
    RequestLog,
    generate_api_key,
    Model,
)
from app.services.auth import load_api_keys
from app.routes.user import get_user_session
from app.core.permissions import permission_required
from app.services.model_naming import user_stats_model_expr

router = APIRouter(prefix="/admin/api", tags=["api-keys"])


class ApiKeyCreate(BaseModel):
    name: str
    email: Optional[str] = None
    expires_at: Optional[datetime] = None
    access_mode: Optional[str] = None
    allowed_model_ids: list[int] = Field(default_factory=list)
    bypass_busyness: bool = False
    max_concurrent: Optional[int] = None
    daily_quota_cny: Optional[float] = None
    tags: list[str] = Field(default_factory=list)


class ApiKeyUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    expires_at: Optional[datetime] = None
    access_mode: Optional[str] = None
    allowed_model_ids: Optional[list[int]] = None
    is_active: Optional[bool] = None
    bypass_busyness: Optional[bool] = None
    max_concurrent: Optional[int] = None
    daily_quota_cny: Optional[float] = None
    tags: Optional[list[str]] = None


def _validate_access_payload(
    access_mode: str | None,
    allowed_model_ids: list[int] | None,
) -> JSONResponse | None:
    if access_mode is None:
        if allowed_model_ids is None:
            return None
        access_mode = "model"
    if access_mode != "model":
        return JSONResponse({"error": "Invalid access mode"}, status_code=400)
    return None


@router.get("/keys")
async def list_api_keys(
    status: str = "active",
    _: bool = Depends(permission_required("page.api_keys")),
):
    async with async_session_maker() as session:
        query = select(ApiKey)
        if status == "inactive":
            query = query.where(ApiKey.is_active == False)  # noqa: E712
        elif status != "all":
            query = query.where(ApiKey.is_active == True)  # noqa: E712
        result = await session.execute(query)
        keys = result.scalars().all()
        key_ids = [k.id for k in keys]
        if not key_ids:
            return {"api_keys": []}

        model_access_map: dict[int, list[int]] = defaultdict(list)
        time_rules_map: dict[int, list[ApiKeyTimeRule]] = defaultdict(list)
        tags_map: dict[int, list[str]] = defaultdict(list)
        model_name_map: dict[int, str] = {}

        model_access_result = await session.execute(
            select(ApiKeyModelAccess.api_key_id, ApiKeyModelAccess.model_id).where(
                ApiKeyModelAccess.api_key_id.in_(key_ids)
            )
        )
        for api_key_id, model_id in model_access_result.fetchall():
            model_access_map[api_key_id].append(model_id)

        model_ids = sorted(
            {model_id for ids in model_access_map.values() for model_id in ids}
        )
        if model_ids:
            model_names_result = await session.execute(
                select(Model.id, Model.display_name, Model.name).where(
                    Model.id.in_(model_ids)
                )
            )
            model_name_map = {
                row[0]: row[1] or row[2] for row in model_names_result.fetchall()
            }

        rules_result = await session.execute(
            select(ApiKeyTimeRule)
            .where(ApiKeyTimeRule.api_key_id.in_(key_ids))
            .order_by(
                ApiKeyTimeRule.api_key_id,
                ApiKeyTimeRule.rule_type,
                ApiKeyTimeRule.id,
            )
        )
        for rule in rules_result.scalars().all():
            time_rules_map[rule.api_key_id].append(rule)

        tags_result = await session.execute(
            select(ApiKeyTag.api_key_id, ApiKeyTag.tag).where(
                ApiKeyTag.api_key_id.in_(key_ids)
            )
        )
        for api_key_id, tag in tags_result.fetchall():
            tags_map[api_key_id].append(tag)

        api_keys = []
        for k in keys:
            rules = time_rules_map[k.id]
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

            api_keys.append(
                {
                    "id": k.id,
                    "name": k.name,
                    "key": k.key,
                    "email": k.email,
                    "expires_at": k.expires_at.isoformat()
                    if k.expires_at
                    else None,
                    "allowed_model_ids": model_access_map[k.id],
                    "allowed_model_names": [
                        model_name_map.get(model_id, f"ID:{model_id}")
                        for model_id in model_access_map[k.id]
                    ],
                    "time_rules": time_rules,
                    "is_active": k.is_active,
                    "bypass_busyness": k.bypass_busyness or False,
                    "max_concurrent": getattr(k, "max_concurrent", None),
                    "daily_quota_cny": k.daily_quota_cny,
                    "tags": tags_map[k.id],
                    "last_used_at": k.last_used_at.isoformat()
                    if k.last_used_at
                    else None,
                }
            )
        return {"api_keys": api_keys}


def _normalize_max_concurrent(value: Optional[int]):
    """-1/None sentinel -> stored NULL (default 2); explicit 0 allowed (disable)."""
    if value is None or value == -1:
        return None
    if value < 0:
        return JSONResponse({"error": "并发上限不能为负数"}, status_code=400)
    return value


@router.post("/keys")
async def create_api_key(data: ApiKeyCreate, _: bool = Depends(permission_required("api_key.create"))):
    access_error = _validate_access_payload(
        data.access_mode,
        data.allowed_model_ids,
    )
    if access_error:
        return access_error
    normalized_max_concurrent = _normalize_max_concurrent(data.max_concurrent)
    if isinstance(normalized_max_concurrent, JSONResponse):
        return normalized_max_concurrent
    async with async_session_maker() as session:
        new_key = ApiKey(
            name=data.name,
            key=generate_api_key(),
            email=(data.email or "").strip() or None,
            expires_at=data.expires_at.replace(tzinfo=None)
            if data.expires_at and data.expires_at.tzinfo
            else (data.expires_at or (datetime.now() + timedelta(days=365))),
            bypass_busyness=data.bypass_busyness,
            max_concurrent=normalized_max_concurrent,
            daily_quota_cny=(
                None
                if data.daily_quota_cny is None or data.daily_quota_cny == -1
                else data.daily_quota_cny
            ),
        )
        session.add(new_key)
        await session.commit()
        await session.refresh(new_key)

        for model_id in data.allowed_model_ids:
            assoc = ApiKeyModelAccess(api_key_id=new_key.id, model_id=model_id)
            session.add(assoc)
        for tag in data.tags:
            t = ApiKeyTag(api_key_id=new_key.id, tag=tag)
            session.add(t)
        await session.commit()
        await load_api_keys()
        return {"id": new_key.id, "name": new_key.name, "key": new_key.key}


@router.put("/keys/{key_id}")
async def update_api_key(
    key_id: int, data: ApiKeyUpdate, _: bool = Depends(permission_required("api_key.update"))
):
    access_error = _validate_access_payload(
        data.access_mode,
        data.allowed_model_ids,
    )
    if access_error:
        return access_error
    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "API key not found"}, status_code=404)
        if data.name is not None:
            key.name = data.name
        if data.email is not None:
            key.email = data.email.strip() or None
        if data.expires_at is not None:
            key.expires_at = data.expires_at.replace(tzinfo=None) if data.expires_at.tzinfo else data.expires_at
        if data.is_active is not None:
            key.is_active = data.is_active
        if data.bypass_busyness is not None:
            key.bypass_busyness = data.bypass_busyness
        if data.max_concurrent is not None:
            normalized = _normalize_max_concurrent(data.max_concurrent)
            if isinstance(normalized, JSONResponse):
                return normalized
            key.max_concurrent = normalized
        if data.daily_quota_cny is not None:
            if data.daily_quota_cny < 0:
                if data.daily_quota_cny == -1:
                    key.daily_quota_cny = None
                else:
                    return JSONResponse(
                        {"error": "每日额度不能为负数"}, status_code=400
                    )
            else:
                key.daily_quota_cny = data.daily_quota_cny
        if data.allowed_model_ids is not None:
            await session.execute(
                delete(ApiKeyModel).where(ApiKeyModel.api_key_id == key_id)
            )
            await session.execute(
                delete(ApiKeyModelAccess).where(ApiKeyModelAccess.api_key_id == key_id)
            )
            for model_id in data.allowed_model_ids:
                assoc = ApiKeyModelAccess(api_key_id=key_id, model_id=model_id)
                session.add(assoc)
        if data.tags is not None:
            await session.execute(
                delete(ApiKeyTag).where(ApiKeyTag.api_key_id == key_id)
            )
            for tag in data.tags:
                t = ApiKeyTag(api_key_id=key_id, tag=tag)
                session.add(t)
        await session.commit()
        await load_api_keys()
        return {"id": key.id}


@router.delete("/keys/{key_id}")
async def delete_api_key(key_id: int, _: bool = Depends(permission_required("api_key.delete"))):
    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "API key not found"}, status_code=404)
        await session.execute(
            delete(ApiKeyModel).where(ApiKeyModel.api_key_id == key_id)
        )
        await session.execute(
            delete(ApiKeyModelAccess).where(ApiKeyModelAccess.api_key_id == key_id)
        )
        await session.delete(key)
        await session.commit()
        await load_api_keys()
        return {"deleted": True}


@router.post("/keys/{key_id}/regenerate")
async def regenerate_api_key(
    request: Request, key_id: int, _: bool = Depends(permission_required("api_key.update"))
):
    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "API key not found"}, status_code=404)
        key.key = generate_api_key()
        await session.commit()
        await session.refresh(key)
        await load_api_keys()

        from app.routes.user import USER_SESSIONS

        purged_sessions = 0
        for token, info in list(USER_SESSIONS.items()):
            if info.get("api_key_id") == key_id:
                del USER_SESSIONS[token]
                purged_sessions += 1
        if purged_sessions:
            try:
                from app.services.audit import write_audit_log

                await write_audit_log(
                    request, "delete", "user_session", str(key_id),
                    f"管理端重置 API Key，清除 {purged_sessions} 个活跃门户会话",
                    None, 200, user_id=key_id,
                )
            except Exception:
                pass

        return {"id": key.id, "key": key.key}


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

        cutoff = datetime.now() - timedelta(days=30)

        total_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.api_key_id == key_id,
                RequestLog.created_at >= cutoff,
            )
        )
        total_requests = total_result.scalar() or 0

        tokens_result = await session.execute(
            select(func.sum(RequestLog.tokens["total_tokens"].as_integer())).where(
                RequestLog.api_key_id == key_id,
                RequestLog.created_at >= cutoff,
            )
        )
        total_tokens = tokens_result.scalar() or 0

        errors_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.api_key_id == key_id,
                RequestLog.status == "error",
                RequestLog.created_at >= cutoff,
            )
        )
        total_errors = errors_result.scalar() or 0

        key_model_group_expr = user_stats_model_expr(
            RequestLog.model, RequestLog.requested_model
        )
        model_stats_result = await session.execute(
            select(
                key_model_group_expr.label("model_name"),
                func.count(RequestLog.id).label("count"),
                func.sum(RequestLog.tokens["total_tokens"].as_integer()).label(
                    "tokens"
                ),
            )
            .where(
                RequestLog.api_key_id == key_id,
                RequestLog.created_at >= cutoff,
            )
            .group_by(key_model_group_expr)
        )
        model_stats = {
            row.model_name: {"requests": row.count, "tokens": row.tokens or 0}
            for row in model_stats_result
            if row.model_name
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
async def list_time_rules(key_id: int, _: bool = Depends(permission_required("page.api_keys"))):
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
    key_id: int,
    data: TimeRuleCreate,
    _: bool = Depends(permission_required("api_key.add_time_rule")),
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
    key_id: int,
    rule_id: int,
    data: TimeRuleUpdate,
    _: bool = Depends(permission_required("api_key.update_time_rule")),
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
async def delete_time_rule(
    key_id: int,
    rule_id: int,
    _: bool = Depends(permission_required("api_key.delete_time_rule")),
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
        await session.delete(rule)
        await session.commit()
        await load_api_keys()
        return {"deleted": True}
