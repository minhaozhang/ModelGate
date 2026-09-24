from typing import Optional

from fastapi import APIRouter, Request, Depends, Cookie
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func, and_
from app.core.database import (
    AuditLog,
    ApiKey,
    Document,
    Menu,
    Model,
    Notification,
    Permission,
    Provider,
    ProviderKey,
    ProviderModel,
    Role,
    SchedulerTask,
    User,
    async_session_maker,
)
from app.core.permissions import login_required
from app.core.config import validate_session
from app.core.i18n import render

router = APIRouter(prefix="/admin/api/audit", tags=["audit"])

# resource -> (model class, readable-name attribute)
_NAME_RESOLVERS = {
    "api_key": (ApiKey, "name"),
    # user_session audit entries store the portal api key id in resource_id.
    "user_session": (ApiKey, "name"),
    "provider": (Provider, "name"),
    "provider_key": (ProviderKey, "label"),
    "model": (Model, "name"),
    "document": (Document, "title"),
    "notification": (Notification, "title"),
    "scheduler_task": (SchedulerTask, "name"),
    "user": (User, "username"),
    "role": (Role, "name"),
    "menu": (Menu, "name"),
    "permission": (Permission, "name"),
}


async def _resolve_resource_names(logs) -> dict:
    """Batch-resolve {(resource, resource_id): display_name} for one page."""
    ids_by_resource: dict = {}
    for log in logs:
        if not log.resource_id:
            continue
        try:
            rid = int(log.resource_id)
        except (TypeError, ValueError):
            continue
        ids_by_resource.setdefault(log.resource, set()).add(rid)

    if not ids_by_resource:
        return {}

    names: dict = {}
    async with async_session_maker() as session:
        for resource, ids in ids_by_resource.items():
            id_list = list(ids)[:500]
            try:
                resolver = _NAME_RESOLVERS.get(resource)
                if resolver:
                    model_cls, attr = resolver
                    result = await session.execute(
                        select(model_cls.id, getattr(model_cls, attr)).where(
                            model_cls.id.in_(id_list)
                        )
                    )
                    for row_id, value in result.fetchall():
                        if value:
                            names[(resource, str(row_id))] = str(value)
                elif resource == "provider_model":
                    result = await session.execute(
                        select(ProviderModel.id, Model.name)
                        .join(Model, Model.id == ProviderModel.model_id)
                        .where(ProviderModel.id.in_(id_list))
                    )
                    for row_id, value in result.fetchall():
                        if value:
                            names[(resource, str(row_id))] = str(value)
            except Exception:
                continue
    return names


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

        names = await _resolve_resource_names(logs)

        items = []
        for log in logs:
            item = {
                "id": log.id,
                "user_id": log.user_id,
                "username": log.username,
                "action": log.action,
                "resource": log.resource,
                "resource_id": log.resource_id,
                "resource_name": names.get((log.resource, log.resource_id))
                if log.resource_id
                else None,
                "detail": log.detail,
                "request_body": log.request_body,
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
        from app.core.app_paths import build_app_url
        return HTMLResponse(status_code=302, headers={"Location": build_app_url(request, "/admin/login")})
    return HTMLResponse(
        content=render(request, "admin/audit.html", active_page="audit")
    )
