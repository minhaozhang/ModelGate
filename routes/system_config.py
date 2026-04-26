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
    return {
        "ua_override": config.OUTBOUND_USER_AGENT,
        "api_key_model_max_concurrency": int(
            config.system_config.get("api_key_model_max_concurrency") or 1
        ),
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


@router.get("/api/notifications")
async def get_notifications(
    page: int = 1,
    page_size: int = 20,
    unread: bool = False,
    _: bool = Depends(require_admin),
):
    from services.notification import get_admin_notifications
    return await get_admin_notifications(page=page, page_size=page_size, unread_only=unread)


@router.get("/api/notifications/unread-count")
async def get_unread_count(_: bool = Depends(require_admin)):
    from services.notification import get_admin_unread_count
    return {"count": await get_admin_unread_count()}


@router.put("/api/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: int, _: bool = Depends(require_admin)):
    from services.notification import mark_admin_read
    ok = await mark_admin_read(notification_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.put("/api/notifications/read-all")
async def mark_all_notifications_read(_: bool = Depends(require_admin)):
    from services.notification import mark_all_admin_read
    count = await mark_all_admin_read()
    return {"ok": True, "count": count}


@router.get("/notifications")
async def notifications_page(request: Request, _: bool = Depends(require_admin)):
    return HTMLResponse(
        content=render(request, "admin/notifications.html", active_page="notifications")
    )


@router.get("/scheduler-tasks")
async def scheduler_tasks_page(request: Request, _: bool = Depends(require_admin)):
    return HTMLResponse(
        content=render(request, "admin/scheduler_tasks.html", active_page="scheduler-tasks")
    )


@router.get("/api/scheduler/tasks")
async def get_scheduler_tasks(_: bool = Depends(require_admin)):
    from services.scheduler import scheduler, TASK_REGISTRY
    from core.database import SchedulerTask as ST

    jobs = {j.id: j for j in scheduler.get_jobs()}
    async with async_session_maker() as session:
        result = await session.execute(select(ST).order_by(ST.id))
        tasks = result.scalars().all()

    items = []
    for t in tasks:
        job = jobs.get(t.task_id)
        items.append({
            "task_id": t.task_id,
            "name": t.name,
            "description": t.description,
            "cron_expression": t.cron_expression,
            "default_cron": t.default_cron,
            "is_paused": t.is_paused,
            "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
            "last_duration_ms": t.last_duration_ms,
            "last_status": t.last_status,
            "last_error": t.last_error,
            "next_run_at": job.next_run_time.isoformat() if job and job.next_run_time else None,
        })
    return {"items": items}


@router.post("/api/scheduler/tasks/{task_id}/trigger")
async def trigger_scheduler_task(task_id: str, _: bool = Depends(require_admin)):
    from services.scheduler import TASK_HANDLERS

    handler = TASK_HANDLERS.get(task_id)
    if not handler:
        raise HTTPException(status_code=404, detail="Task not found")
    import asyncio
    asyncio.create_task(handler())
    return {"ok": True, "message": f"Task {task_id} triggered"}


@router.put("/api/scheduler/tasks/{task_id}")
async def update_scheduler_task(task_id: str, body: dict, _: bool = Depends(require_admin)):
    from services.scheduler import scheduler, cron_to_trigger, TASK_HANDLERS
    from core.database import SchedulerTask as ST

    async with async_session_maker() as session:
        result = await session.execute(select(ST).where(ST.task_id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        if "cron_expression" in body:
            cron = body["cron_expression"].strip()
            try:
                cron_to_trigger(cron)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid cron expression")
            task.cron_expression = cron
            if not task.is_paused:
                handler = TASK_HANDLERS.get(task_id)
                if handler:
                    scheduler.remove_job(task_id)
                    scheduler.add_job(handler, cron_to_trigger(cron), id=task_id, replace_existing=True)

        if "is_paused" in body:
            paused = bool(body["is_paused"])
            task.is_paused = paused
            if paused:
                scheduler.remove_job(task_id)
            else:
                handler = TASK_HANDLERS.get(task_id)
                if handler:
                    scheduler.add_job(handler, cron_to_trigger(task.cron_expression), id=task_id, replace_existing=True)

        await session.commit()

    return {"ok": True}


@router.get("/api/scheduler/tasks/{task_id}/logs")
async def get_scheduler_task_logs(
    task_id: str, _: bool = Depends(require_admin), page: int = 1, page_size: int = 20
):
    from core.database import SchedulerTaskLog as STL

    async with async_session_maker() as session:
        from sqlalchemy import func as sa_func
        count_result = await session.execute(
            select(sa_func.count(STL.id)).where(STL.task_id == task_id)
        )
        total = count_result.scalar() or 0

        result = await session.execute(
            select(STL)
            .where(STL.task_id == task_id)
            .order_by(STL.started_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        logs = result.scalars().all()

        return {
            "items": [
                {
                    "id": l.id,
                    "status": l.status,
                    "started_at": l.started_at.isoformat() if l.started_at else None,
                    "finished_at": l.finished_at.isoformat() if l.finished_at else None,
                    "duration_ms": l.duration_ms,
                    "error": l.error,
                    "result_summary": l.result_summary,
                }
                for l in logs
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/api/scheduler/logs")
async def get_all_scheduler_logs(
    _: bool = Depends(require_admin),
    task_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
):
    from core.database import SchedulerTaskLog as STL, SchedulerTask as ST

    async with async_session_maker() as session:
        from sqlalchemy import func as sa_func

        query = select(STL)
        count_query = select(sa_func.count(STL.id))
        if task_id:
            query = query.where(STL.task_id == task_id)
            count_query = count_query.where(STL.task_id == task_id)

        total = (await session.execute(count_query)).scalar() or 0

        result = await session.execute(
            query.order_by(STL.started_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        logs = result.scalars().all()

        task_names = {}
        task_result = await session.execute(select(ST.task_id, ST.name))
        for tid, tname in task_result.fetchall():
            task_names[tid] = tname

        return {
            "items": [
                {
                    "id": l.id,
                    "task_id": l.task_id,
                    "task_name": task_names.get(l.task_id, l.task_id),
                    "status": l.status,
                    "started_at": l.started_at.isoformat() if l.started_at else None,
                    "finished_at": l.finished_at.isoformat() if l.finished_at else None,
                    "duration_ms": l.duration_ms,
                    "error": l.error,
                    "result_summary": l.result_summary,
                }
                for l in logs
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/system-config", response_class=HTMLResponse)
async def system_config_page(request: Request, _: bool = Depends(require_admin)):
    return HTMLResponse(
        content=render(request, "admin/system_config.html", active_page="system-config")
    )
