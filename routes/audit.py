from typing import Optional

from fastapi import APIRouter, Request, Depends, Cookie
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func, and_
from core.database import AuditLog, async_session_maker
from core.permissions import login_required
from core.config import validate_session
from core.i18n import render

router = APIRouter(prefix="/admin/api/audit", tags=["audit"])


@router.get("/logs")
async def list_audit_logs(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    action: Optional[str] = None,
    resource: Optional[str] = None,
    username: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user=Depends(login_required()),
):
    async with async_session_maker() as session:
        query = select(AuditLog)
        count_query = select(func.count()).select_from(AuditLog)

        conditions = []
        if action:
            conditions.append(AuditLog.action == action)
        if resource:
            conditions.append(AuditLog.resource == resource)
        if username:
            conditions.append(AuditLog.username.ilike(f"%{username}%"))
        if start_date:
            conditions.append(AuditLog.created_at >= start_date + "T00:00:00")
        if end_date:
            conditions.append(AuditLog.created_at <= end_date + "T23:59:59")

        if conditions:
            where = and_(*conditions)
            query = query.where(where)
            count_query = count_query.where(where)

        total = await session.scalar(count_query)

        query = query.order_by(AuditLog.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await session.execute(query)
        logs = result.scalars().all()

        items = []
        for log in logs:
            item = {
                "id": log.id,
                "user_id": log.user_id,
                "username": log.username,
                "action": log.action,
                "resource": log.resource,
                "resource_id": log.resource_id,
                "detail": log.detail,
                "client_ip": log.client_ip,
                "status_code": log.status_code,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            items.append(item)

        return {
            "success": True,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        }


@router.get("/resources")
async def list_audit_resources(
    request: Request,
    user=Depends(login_required()),
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(AuditLog.resource)
            .distinct()
            .order_by(AuditLog.resource)
        )
        resources = [row[0] for row in result.all()]
        return {"success": True, "data": resources}


page_router = APIRouter(prefix="/admin", tags=["audit-pages"])


@page_router.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request, session: Optional[str] = Cookie(None)):
    if not validate_session(session):
        from core.app_paths import build_app_url
        return HTMLResponse(status_code=302, headers={"Location": build_app_url(request, "/admin/login")})
    return HTMLResponse(
        content=render(request, "admin/audit.html", active_page="audit")
    )
