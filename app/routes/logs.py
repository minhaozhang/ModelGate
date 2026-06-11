from collections import Counter
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Cookie, Depends, HTTPException
from sqlalchemy import select, func, cast, Numeric

from app.core.config import validate_session
from app.core.database import (
    async_session_maker,
    RequestLogRead as RequestLog,
    RequestContent,
    Provider,
    ApiKey,
    McpCallLog,
    McpServer,
)

router = APIRouter(prefix="/admin/api", tags=["logs"])
ERROR_STATUSES = ("error", "timeout")
ERROR_REPORT_LOG_LIMIT = 200


def require_admin(session: Optional[str] = Cookie(None)):
    if not validate_session(session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


def get_token_count(tokens_payload) -> int:
    return (
        (tokens_payload or {}).get("total_tokens")
        or (tokens_payload or {}).get("estimated")
        or 0
    )


async def _get_maps(
    session, logs: list[RequestLog]
) -> tuple[dict[int, str], dict[int, str]]:
    provider_ids = {log.provider_id for log in logs if log.provider_id is not None}
    api_key_ids = {log.api_key_id for log in logs if log.api_key_id is not None}

    provider_map: dict[int, str] = {}
    if provider_ids:
        provider_result = await session.execute(
            select(Provider).where(Provider.id.in_(provider_ids))
        )
        provider_map = {
            provider.id: provider.name for provider in provider_result.scalars()
        }

    api_key_map: dict[int, str] = {}
    if api_key_ids:
        api_key_result = await session.execute(
            select(ApiKey).where(ApiKey.id.in_(api_key_ids))
        )
        api_key_map = {api_key.id: api_key.name for api_key in api_key_result.scalars()}

    return provider_map, api_key_map


def _serialize_error_log(
    log: RequestLog,
    provider_map: dict[int, str],
    api_key_map: dict[int, str],
) -> dict:
    return {
        "id": log.id,
        "provider": provider_map.get(log.provider_id, "-")
        if log.provider_id is not None
        else "-",
        "api_key": api_key_map.get(log.api_key_id, f"Key-{log.api_key_id}")
        if log.api_key_id is not None
        else "-",
        "model": log.model,
        "status": log.status,
        "upstream_status_code": log.upstream_status_code,
        "downstream_status_code": log.downstream_status_code,
        "latency_ms": log.latency_ms,
        "request_context_tokens": log.request_context_tokens,
        "tokens": log.tokens,
        "client_ip": log.client_ip,
        "user_agent": log.user_agent,
        "inbound_protocol": log.inbound_protocol,
                    "intent": log.intent,
                    "requested_model": log.requested_model,
                    "actual_model": log.actual_model,
                    "provider_key_id": log.provider_key_id,
                    "provider_key_label": log.provider_key_label,
        "response": log.response,
        "error": log.error,
        "created_at": log.created_at.isoformat(),
    }


def _build_error_summary(logs: list[dict]) -> dict:
    total = len(logs)
    total_timeouts = sum(1 for log in logs if log.get("status") == "timeout")
    total_errors = total - total_timeouts

    provider_counter = Counter(log.get("provider") or "-" for log in logs)
    model_counter = Counter(log.get("model") or "-" for log in logs)
    status_code_counter = Counter(
        str(log.get("upstream_status_code"))
        for log in logs
        if log.get("upstream_status_code") is not None
    )
    context_values = [
        int(log.get("request_context_tokens") or 0)
        for log in logs
        if int(log.get("request_context_tokens") or 0) > 0
    ]
    timeout_context_values = [
        int(log.get("request_context_tokens") or 0)
        for log in logs
        if log.get("status") == "timeout"
        and int(log.get("request_context_tokens") or 0) > 0
    ]

    return {
        "total_logs": total,
        "total_errors": total_errors,
        "total_timeouts": total_timeouts,
        "top_providers": provider_counter.most_common(5),
        "top_models": model_counter.most_common(5),
        "top_status_codes": status_code_counter.most_common(5),
        "avg_context_tokens": round(sum(context_values) / len(context_values), 1)
        if context_values
        else None,
        "max_context_tokens": max(context_values) if context_values else None,
        "avg_timeout_context_tokens": round(
            sum(timeout_context_values) / len(timeout_context_values), 1
        )
        if timeout_context_values
        else None,
    }


async def _load_today_error_logs(
    session, limit: int = ERROR_REPORT_LOG_LIMIT
) -> tuple[list[RequestLog], list[dict], dict]:
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(RequestLog)
        .where(
            RequestLog.created_at >= today_start,
            RequestLog.status.in_(ERROR_STATUSES),
        )
        .order_by(RequestLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    provider_map, api_key_map = await _get_maps(session, logs)
    serialized_logs = [
        _serialize_error_log(log, provider_map, api_key_map) for log in logs
    ]
    return logs, serialized_logs, _build_error_summary(serialized_logs)



@router.get("/logs/all")
async def get_all_logs(limit: int = 100, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        count_result = await session.execute(select(func.count(RequestLog.id)))
        total = count_result.scalar() or 0

        result = await session.execute(
            select(RequestLog).order_by(RequestLog.created_at.desc()).limit(limit)
        )
        logs = result.scalars().all()
        return {
            "logs": [
                {
                    "id": log.id,
                    "model": log.model,
                    "status": log.status,
                    "upstream_status_code": log.upstream_status_code,
                    "downstream_status_code": log.downstream_status_code,
                    "latency_ms": log.latency_ms,
                    "request_context_tokens": log.request_context_tokens,
                    "tokens": log.tokens,
                    "client_ip": log.client_ip,
                    "user_agent": log.user_agent,
                    "inbound_protocol": log.inbound_protocol,
                    "intent": log.intent,
                    "requested_model": log.requested_model,
                    "actual_model": log.actual_model,
                    "provider_key_id": log.provider_key_id,
                    "provider_key_label": log.provider_key_label,
                    "created_at": log.created_at.isoformat(),
                    "response": log.response,
                    "error": log.error,
                }
                for log in logs
            ],
            "total": total,
        }


def _escape_ilike(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/logs/query")
async def query_logs(
    key_name: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[int] = None,
    status: Optional[str] = None,
    time_range: str = "1h",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    _: bool = Depends(require_admin),
):
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    now = datetime.now()

    if start_time or end_time:
        try:
            dt_start = (
                datetime.fromisoformat(start_time)
                if start_time
                else now - timedelta(days=7)
            )
            dt_end = datetime.fromisoformat(end_time) if end_time else now
        except ValueError:
            return {"logs": [], "total": 0, "page": page, "page_size": page_size}
    else:
        deltas = {
            "1h": timedelta(hours=1),
            "6h": timedelta(hours=6),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
        }
        dt_start = now - deltas.get(time_range, timedelta(hours=1))
        dt_end = now

    async with async_session_maker() as session:
        api_key_id_filter = None
        if key_name:
            safe_key = _escape_ilike(key_name)
            key_result = await session.execute(
                select(ApiKey).where(ApiKey.name == key_name)
            )
            key = key_result.scalar_one_or_none()
            if key:
                api_key_id_filter = key.id
            else:
                key_result = await session.execute(
                    select(ApiKey).where(ApiKey.name.ilike(f"%{safe_key}%"))
                )
                keys = key_result.scalars().all()
                if keys:
                    api_key_id_filter = [k.id for k in keys]
                else:
                    return {
                        "logs": [],
                        "total": 0,
                        "page": page,
                        "page_size": page_size,
                    }

        q = select(RequestLog).where(
            RequestLog.created_at >= dt_start,
            RequestLog.created_at <= dt_end,
        )
        count_q = select(func.count(RequestLog.id)).where(
            RequestLog.created_at >= dt_start,
            RequestLog.created_at <= dt_end,
        )

        if api_key_id_filter is not None:
            if isinstance(api_key_id_filter, list):
                q = q.where(RequestLog.api_key_id.in_(api_key_id_filter))
                count_q = count_q.where(RequestLog.api_key_id.in_(api_key_id_filter))
            else:
                q = q.where(RequestLog.api_key_id == api_key_id_filter)
                count_q = count_q.where(RequestLog.api_key_id == api_key_id_filter)
        if provider:
            q = q.where(RequestLog.provider_id == provider)
            count_q = count_q.where(RequestLog.provider_id == provider)
        if model:
            safe_model = _escape_ilike(model)
            q = q.where(RequestLog.model.ilike(f"%{safe_model}%"))
            count_q = count_q.where(RequestLog.model.ilike(f"%{safe_model}%"))
        if status:
            q = q.where(RequestLog.status == status)
            count_q = count_q.where(RequestLog.status == status)

        total_result = await session.execute(count_q)
        total = total_result.scalar() or 0

        offset = (page - 1) * page_size
        q = q.order_by(RequestLog.created_at.desc()).offset(offset).limit(page_size)
        result = await session.execute(q)
        logs = result.scalars().all()

        provider_map, api_key_map = await _get_maps(session, logs)

        return {
            "logs": [
                _serialize_error_log(log, provider_map, api_key_map) for log in logs
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/logs/aggregate")
async def aggregate_logs(
    provider: Optional[int] = None,
    status: Optional[str] = None,
    time_range: str = "24h",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    group_by: str = "provider_model",
    key_name: Optional[str] = None,
    client_ip: Optional[str] = None,
    _: bool = Depends(require_admin),
):
    now = datetime.now()

    if start_time or end_time:
        try:
            dt_start = (
                datetime.fromisoformat(start_time)
                if start_time
                else now - timedelta(days=7)
            )
            dt_end = datetime.fromisoformat(end_time) if end_time else now
        except ValueError:
            return {"rows": []}
    else:
        deltas = {
            "1h": timedelta(hours=1),
            "6h": timedelta(hours=6),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
        }
        dt_start = now - deltas.get(time_range, timedelta(hours=24))
        dt_end = now

    async with async_session_maker() as session:
        base_where = [
            RequestLog.created_at >= dt_start,
            RequestLog.created_at <= dt_end,
            RequestLog.latency_ms.is_not(None),
        ]
        if status:
            base_where.append(RequestLog.status == status)
        else:
            base_where.append(RequestLog.status == "success")

        if provider:
            base_where.append(RequestLog.provider_id == provider)

        if client_ip:
            base_where.append(RequestLog.client_ip == client_ip)

        api_key_ids = None
        if key_name:
            k_result = await session.execute(
                select(ApiKey.id).where(ApiKey.name.ilike(f"%{key_name}%"))
            )
            api_key_ids = [r[0] for r in k_result.all()]
            if not api_key_ids:
                return {"group_by": group_by, "rows": []}
            base_where.append(RequestLog.api_key_id.in_(api_key_ids))

        token_expr = func.coalesce(RequestLog.tokens["prompt_tokens"].as_integer(), 0) + func.coalesce(RequestLog.tokens["completion_tokens"].as_integer(), 0)
        common_metrics = [
            func.count(RequestLog.id).label("request_count"),
            func.round(cast(func.avg(RequestLog.latency_ms), Numeric), 2).label("avg_latency_ms"),
            func.sum(token_expr).label("total_tokens"),
        ]

        if group_by == "user":
            q = (
                select(
                    RequestLog.api_key_id,
                    *common_metrics,
                )
                .where(*base_where)
                .group_by(RequestLog.api_key_id)
                .order_by(func.count(RequestLog.id).desc())
            )
            result = await session.execute(q)
            rows = result.fetchall()

            key_ids = {r.api_key_id for r in rows if r.api_key_id}
            key_map = {}
            if key_ids:
                k_result = await session.execute(
                    select(ApiKey.id, ApiKey.name).where(ApiKey.id.in_(key_ids))
                )
                key_map = {k[0]: k[1] for k in k_result.all()}

            return {
                "group_by": "user",
                "rows": [
                    {
                        "api_key_id": r.api_key_id,
                        "api_key_name": key_map.get(r.api_key_id, "-"),
                        "request_count": r.request_count,
                        "avg_latency_ms": float(r.avg_latency_ms) if r.avg_latency_ms else 0,
                        "total_tokens": int(r.total_tokens) if r.total_tokens else 0,
                    }
                    for r in rows
                ],
            }

        elif group_by == "ip":
            q = (
                select(
                    RequestLog.client_ip,
                    *common_metrics,
                )
                .where(*base_where)
                .group_by(RequestLog.client_ip)
                .order_by(func.count(RequestLog.id).desc())
            )
            result = await session.execute(q)
            rows = result.fetchall()
            return {
                "group_by": "ip",
                "rows": [
                    {
                        "client_ip": r.client_ip or "-",
                        "request_count": r.request_count,
                        "avg_latency_ms": float(r.avg_latency_ms) if r.avg_latency_ms else 0,
                        "total_tokens": int(r.total_tokens) if r.total_tokens else 0,
                    }
                    for r in rows
                ],
            }

        elif group_by == "user_ip":
            q = (
                select(
                    RequestLog.api_key_id,
                    RequestLog.client_ip,
                    *common_metrics,
                )
                .where(*base_where)
                .group_by(RequestLog.api_key_id, RequestLog.client_ip)
                .order_by(func.count(RequestLog.id).desc())
            )
            result = await session.execute(q)
            rows = result.fetchall()

            key_ids = {r.api_key_id for r in rows if r.api_key_id}
            key_map = {}
            if key_ids:
                k_result = await session.execute(
                    select(ApiKey.id, ApiKey.name).where(ApiKey.id.in_(key_ids))
                )
                key_map = {k[0]: k[1] for k in k_result.all()}

            return {
                "group_by": "user_ip",
                "rows": [
                    {
                        "api_key_id": r.api_key_id,
                        "api_key_name": key_map.get(r.api_key_id, "-"),
                        "client_ip": r.client_ip or "-",
                        "request_count": r.request_count,
                        "avg_latency_ms": float(r.avg_latency_ms) if r.avg_latency_ms else 0,
                        "total_tokens": int(r.total_tokens) if r.total_tokens else 0,
                    }
                    for r in rows
                ],
            }

        else:
            q = (
                select(
                    RequestLog.provider_id,
                    RequestLog.model,
                    func.count(RequestLog.id).label("request_count"),
                    func.round(cast(func.avg(RequestLog.latency_ms), Numeric), 2).label("avg_latency_ms"),
                    func.round(cast(func.max(RequestLog.latency_ms), Numeric), 2).label("max_latency_ms"),
                    func.round(cast(func.min(RequestLog.latency_ms), Numeric), 2).label("min_latency_ms"),
                    func.round(
                        cast(
                            func.avg(token_expr),
                            Numeric,
                        ),
                        1,
                    ).label("avg_tokens"),
                    func.sum(token_expr).label("total_tokens"),
                )
                .where(*base_where)
                .group_by(RequestLog.provider_id, RequestLog.model)
                .order_by(func.count(RequestLog.id).desc())
            )

            result = await session.execute(q)
            rows = result.fetchall()

            provider_ids = {r.provider_id for r in rows if r.provider_id}
            provider_map = {}
            if provider_ids:
                p_result = await session.execute(
                    select(Provider.id, Provider.name).where(Provider.id.in_(provider_ids))
                )
                provider_map = {p[0]: p[1] for p in p_result.all()}

            return {
                "group_by": "provider_model",
                "rows": [
                    {
                        "provider_id": r.provider_id,
                        "provider_name": provider_map.get(r.provider_id, "-"),
                        "model": r.model,
                        "request_count": r.request_count,
                        "avg_latency_ms": float(r.avg_latency_ms) if r.avg_latency_ms else 0,
                        "max_latency_ms": float(r.max_latency_ms) if r.max_latency_ms else 0,
                        "min_latency_ms": float(r.min_latency_ms) if r.min_latency_ms else 0,
                        "avg_tokens": float(r.avg_tokens) if r.avg_tokens else 0,
                        "total_tokens": int(r.total_tokens) if r.total_tokens else 0,
                    }
                    for r in rows
                ],
            }


@router.get("/mcp-logs/query")
async def query_mcp_logs(
    tool_name: Optional[str] = None,
    status: Optional[str] = None,
    time_range: str = "24h",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    _: bool = Depends(require_admin),
):
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    now = datetime.now()

    if start_time or end_time:
        try:
            dt_start = (
                datetime.fromisoformat(start_time)
                if start_time
                else now - timedelta(days=7)
            )
            dt_end = datetime.fromisoformat(end_time) if end_time else now
        except ValueError:
            return {"logs": [], "total": 0, "page": page, "page_size": page_size}
    else:
        deltas = {
            "1h": timedelta(hours=1),
            "6h": timedelta(hours=6),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
        }
        dt_start = now - deltas.get(time_range, timedelta(hours=24))
        dt_end = now

    async with async_session_maker() as session:
        q = select(McpCallLog).where(
            McpCallLog.created_at >= dt_start,
            McpCallLog.created_at <= dt_end,
        )
        count_q = select(func.count(McpCallLog.id)).where(
            McpCallLog.created_at >= dt_start,
            McpCallLog.created_at <= dt_end,
        )

        if tool_name:
            safe_tool = _escape_ilike(tool_name)
            q = q.where(McpCallLog.tool_name.ilike(f"%{safe_tool}%"))
            count_q = count_q.where(McpCallLog.tool_name.ilike(f"%{safe_tool}%"))
        if status == "error":
            q = q.where(McpCallLog.is_error == True)  # noqa: E712
            count_q = count_q.where(McpCallLog.is_error == True)  # noqa: E712
        elif status == "success":
            q = q.where(McpCallLog.is_error == False)  # noqa: E712
            count_q = count_q.where(McpCallLog.is_error == False)  # noqa: E712

        total_result = await session.execute(count_q)
        total = total_result.scalar() or 0

        offset = (page - 1) * page_size
        q = q.order_by(McpCallLog.created_at.desc()).offset(offset).limit(page_size)
        result = await session.execute(q)
        logs = result.scalars().all()

        server_ids = {log.mcp_server_id for log in logs if log.mcp_server_id}
        server_map = {}
        if server_ids:
            srv_result = await session.execute(
                select(McpServer).where(McpServer.id.in_(server_ids))
            )
            server_map = {s.id: s.name for s in srv_result.scalars()}

        return {
            "logs": [
                {
                    "id": log.id,
                    "mcp_server_id": log.mcp_server_id,
                    "server_name": server_map.get(log.mcp_server_id, "-")
                    if log.mcp_server_id
                    else "-",
                    "tool_name": log.tool_name,
                    "arguments": log.arguments,
                    "is_error": log.is_error,
                    "latency_ms": log.latency_ms,
                    "client_ip": log.client_ip,
                    "error": log.error,
                    "created_at": log.created_at.isoformat(),
                }
                for log in logs
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/logs/{log_id}/content")
async def get_log_content(log_id: int, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestContent).where(RequestContent.log_id == log_id)
        )
        content = result.scalar_one_or_none()
        if not content:
            return {"log_id": log_id, "request_messages": None, "response_content": None,
                    "response_tool_calls": None, "response_thinking": None, "response_raw": None}
        return {
            "log_id": log_id,
            "request_messages": content.request_messages,
            "response_content": content.response_content,
            "response_tool_calls": content.response_tool_calls,
            "response_thinking": content.response_thinking,
            "response_raw": content.response_raw,
        }
