import os
import time
from datetime import date, datetime
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select, func

import app.core.config as config
from app.core.config import (
    DEFAULT_OUTBOUND_USER_AGENT,
)
from app.core.database import async_session_maker, RequestLog
from app.core.i18n import render
from app.core.permissions import permission_required, login_required

router = APIRouter(prefix="/admin", tags=["system-config"])


@router.get("/api/system/config")
async def get_config(_: bool = Depends(permission_required("page.system.config"))):
    from app.services.system_config import ALL_DEFAULTS, get_setting

    busyness_settings = {}
    for key in ALL_DEFAULTS.get("busyness", {}):
        busyness_settings[key] = await get_setting("busyness", key)

    ua = await get_setting("proxy", "ua_override", "")

    from app.services.glm_health_check import DEFAULT_HEALTH_CHECK_MODEL

    glm_model = await get_setting("scheduler", "glm_health_check_model", "")

    from app.services.billing_rules import BILLING_DEFAULTS, parse_peak_windows

    billing_settings = {}
    for key, default in BILLING_DEFAULTS.items():
        billing_settings[key] = await get_setting("billing", key, default)
    billing_settings["peak_windows_valid"] = True
    try:
        parse_peak_windows(billing_settings["peak_windows"])
    except ValueError:
        billing_settings["peak_windows_valid"] = False

    daily_report_settings = {}
    for key in ALL_DEFAULTS.get("daily_report", {}):
        daily_report_settings[key] = await get_setting("daily_report", key)

    concurrency_settings = {}
    for key in ALL_DEFAULTS.get("concurrency", {}):
        concurrency_settings[key] = await get_setting("concurrency", key)

    pricing_settings = {}
    for key in ALL_DEFAULTS.get("pricing", {}):
        pricing_settings[key] = await get_setting("pricing", key)

    return {
        "ua_override": ua or DEFAULT_OUTBOUND_USER_AGENT,
        "default_ua": DEFAULT_OUTBOUND_USER_AGENT,
        "busyness": busyness_settings,
        "glm_health_check_model": glm_model,
        "glm_health_check_model_default": DEFAULT_HEALTH_CHECK_MODEL,
        "billing": billing_settings,
        "daily_report": daily_report_settings,
        "concurrency": concurrency_settings,
        "pricing": pricing_settings,
    }


@router.put("/api/system/config")
async def update_config(body: dict, _: bool = Depends(permission_required("system_config.update"))):
    from app.services.system_config import ALL_DEFAULTS, save_setting

    ua = body.get("ua_override", "").strip()
    if ua:
        await save_setting("proxy", "ua_override", ua)
        config.OUTBOUND_USER_AGENT = ua
    else:
        await save_setting("proxy", "ua_override", "")
        config.OUTBOUND_USER_AGENT = DEFAULT_OUTBOUND_USER_AGENT

    if "glm_health_check_model" in body:
        glm_model = str(body.get("glm_health_check_model") or "").strip()
        await save_setting(
            "scheduler",
            "glm_health_check_model",
            glm_model,
            "GLM 健康检查使用的模型（provider/model 全名，留空用默认）",
        )

    billing_updates = body.get("billing", {})
    if billing_updates:
        from app.services.billing_rules import parse_peak_windows

        if "peak_windows" in billing_updates:
            windows_raw = str(billing_updates.get("peak_windows") or "").strip()
            try:
                parse_peak_windows(windows_raw)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            await save_setting(
                "billing",
                "peak_windows",
                windows_raw,
                "高峰时段，逗号分隔 HH:MM-HH:MM，支持跨零点",
            )
        for key in ("peak_multiplier", "offpeak_multiplier", "default_daily_quota_cny"):
            if key in billing_updates:
                await save_setting("billing", key, str(billing_updates.get(key) or "").strip())
        if "weekend_offpeak" in billing_updates:
            await save_setting(
                "billing",
                "weekend_offpeak",
                "true" if billing_updates.get("weekend_offpeak") else "false",
                "周六周日全天按低峰计费",
            )

    busyness_updates = body.get("busyness", {})
    valid_busyness_keys = ALL_DEFAULTS.get("busyness", {})
    for key, value in busyness_updates.items():
        if key in valid_busyness_keys:
            await save_setting("busyness", key, str(value))

    daily_report_updates = body.get("daily_report", {})
    valid_daily_report_keys = ALL_DEFAULTS.get("daily_report", {})
    for key, value in daily_report_updates.items():
        if key in valid_daily_report_keys:
            try:
                float(value)
            except (TypeError, ValueError):
                continue
            await save_setting("daily_report", key, str(value))

    concurrency_updates = body.get("concurrency", {})
    valid_concurrency_keys = ALL_DEFAULTS.get("concurrency", {})
    for key, value in concurrency_updates.items():
        if key not in valid_concurrency_keys:
            continue
        try:
            num = int(value)
        except (TypeError, ValueError):
            continue
        if num < 0 or (num > 23 and key.endswith("_hour")):
            continue
        await save_setting(
            "concurrency", key, str(value), "用户模型并发动态控制参数"
        )

    pricing_updates = body.get("pricing", {})
    valid_pricing_keys = ALL_DEFAULTS.get("pricing", {})
    for key, value in pricing_updates.items():
        if key not in valid_pricing_keys:
            continue
        try:
            num = float(value)
        except (TypeError, ValueError):
            continue
        if num < 0 or num > 100:
            continue
        await save_setting(
            "pricing", key, str(value), "价格全局默认参数"
        )

    return {"ok": True}


@router.get("/api/system/ua-stats")
async def get_ua_stats(limit: int = 10, _: bool = Depends(permission_required("page.system.config"))):
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
    _: bool = Depends(login_required()),
):
    from app.services.notification import get_admin_notifications
    return await get_admin_notifications(page=page, page_size=page_size, unread_only=unread)


@router.post("/api/notifications")
async def publish_notification(
    payload: dict = Body(...),
    _: bool = Depends(permission_required("notification.create")),
):
    """Publish a site-wide announcement broadcast to every user's message center."""
    from app.services.notification import create_notification

    title = str(payload.get("title") or "").strip()
    body = str(payload.get("body") or "").strip() or None
    level = payload.get("level")
    if level not in ("info", "warning"):
        level = "info"
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    notification_id = await create_notification(
        type="user", level=level, title=title, body=body, target_api_key_id=None
    )
    return {"ok": True, "id": notification_id}


@router.get("/api/notifications/unread-count")
async def get_unread_count(_: bool = Depends(login_required())):
    from app.services.notification import get_admin_unread_count
    return {"count": await get_admin_unread_count()}


@router.put("/api/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    _: bool = Depends(permission_required("notification.mark_read")),
):
    from app.services.notification import mark_admin_read
    ok = await mark_admin_read(notification_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.put("/api/notifications/read-all")
async def mark_all_notifications_read(_: bool = Depends(permission_required("notification.mark_read"))):
    from app.services.notification import mark_all_admin_read
    count = await mark_all_admin_read()
    return {"ok": True, "count": count}


@router.get("/notifications")
async def notifications_page(request: Request, _: bool = Depends(login_required())):
    return HTMLResponse(
        content=render(request, "admin/notifications.html", active_page="notifications")
    )


@router.get("/scheduler-tasks")
async def scheduler_tasks_page(request: Request, _: bool = Depends(permission_required("page.system.scheduler"))):
    return HTMLResponse(
        content=render(request, "admin/scheduler_tasks.html", active_page="scheduler-tasks")
    )


@router.get("/api/scheduler/tasks")
async def get_scheduler_tasks(_: bool = Depends(permission_required("page.system.scheduler"))):
    from app.services.scheduler import scheduler, TASK_REGISTRY
    from app.core.database import SchedulerTask as ST

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
async def trigger_scheduler_task(task_id: str, _: bool = Depends(permission_required("scheduler.trigger"))):
    from app.services.scheduler import TASK_HANDLERS

    handler = TASK_HANDLERS.get(task_id)
    if not handler:
        raise HTTPException(status_code=404, detail="Task not found")
    import asyncio
    asyncio.create_task(handler())
    return {"ok": True, "message": f"Task {task_id} triggered"}


@router.put("/api/scheduler/tasks/{task_id}")
async def update_scheduler_task(
    task_id: str,
    body: dict,
    _: bool = Depends(permission_required("scheduler.update")),
):
    from app.services.scheduler import scheduler, cron_to_trigger, TASK_HANDLERS
    from app.core.database import SchedulerTask as ST

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
    task_id: str,
    _: bool = Depends(permission_required("page.system.scheduler")),
    page: int = 1,
    page_size: int = 20,
):
    from app.core.database import SchedulerTaskLog as STL

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
    _: bool = Depends(permission_required("page.system.scheduler")),
    task_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
):
    from app.core.database import SchedulerTaskLog as STL, SchedulerTask as ST

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


import asyncio as _asyncio

from app.core.config import provider_key_semaphores, provider_key_model_semaphores, providers_cache
from app.services.key_health import compute_health_score, get_health_level


@router.get("/api/provider-models-status")
async def provider_models_status(_: bool = Depends(permission_required("page.system.config"))):
    rows = []
    for provider_name, pcfg in providers_cache.items():
        provider_id = pcfg.get("id")
        disabled = pcfg.get("disabled_reason")
        api_keys = pcfg.get("api_keys", [])
        models = pcfg.get("models", [])

        if not api_keys:
            key_entry = {
                "provider": provider_name,
                "provider_disabled": bool(disabled),
                "provider_disabled_reason": disabled or "",
                "key_id": None,
                "key_label": "(default)",
                "key_active": not bool(disabled),
                "health_score": 0 if disabled else 100,
                "health_level": "unavailable" if disabled else "excellent",
                "concurrency_limit": 0,
                "concurrency_in_use": 0,
                "models": [m.get("model_name") or m.get("actual_model_name", "") for m in models],
            }
            rows.append(key_entry)
            continue

        for k in api_keys:
            key_id = k["id"]
            label = k.get("label", "") or f"Key #{key_id}"
            is_active = True
            health = compute_health_score(key_id, is_active)
            level = get_health_level(health)

            sem_key = f"{key_id}:{provider_name}"
            sem = provider_key_semaphores.get(sem_key)
            conc_limit = 0
            conc_in_use = 0
            if sem:
                conc_limit = getattr(sem, "_modelgate_scoped_limit", getattr(sem, "_value", 0)) or 0
                available = getattr(sem, "_value", 0)
                conc_in_use = max(conc_limit - available, 0)

            key_models = []
            for m in models:
                model_name = m.get("model_name") or m.get("actual_model_name", "")
                pkm_sem_key = f"{sem_key}/{model_name}"
                pkm_sem = provider_key_model_semaphores.get(pkm_sem_key)
                pkm_in_use = 0
                if pkm_sem:
                    pkm_limit = getattr(pkm_sem, "_modelgate_scoped_limit", getattr(pkm_sem, "_value", 0)) or 0
                    pkm_avail = getattr(pkm_sem, "_value", 0)
                    pkm_in_use = max(pkm_limit - pkm_avail, 0)
                key_models.append({
                    "name": model_name,
                    "in_use": pkm_in_use,
                })

            rows.append({
                "provider": provider_name,
                "provider_disabled": bool(disabled),
                "provider_disabled_reason": disabled or "",
                "key_id": key_id,
                "key_label": label,
                "key_active": is_active,
                "health_score": health,
                "health_level": level,
                "concurrency_limit": conc_limit,
                "concurrency_in_use": conc_in_use,
                "models": key_models,
            })

    rows.sort(key=lambda r: (r["provider"], r.get("key_label", "")))
    return {"rows": rows}


@router.get("/api/system/info")
async def get_system_info(_: bool = Depends(permission_required("page.stats"))):
    import psutil

    cpu_percent = psutil.cpu_percent(interval=0)
    cpu_freq = psutil.cpu_freq()
    load_avg = None
    try:
        load_avg = tuple(round(x, 2) for x in os.getloadavg())
    except (AttributeError, OSError):
        pass

    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    disk_io = psutil.disk_io_counters()

    host_disk = None
    if os.path.ismount("/host_root"):
        try:
            host_usage = psutil.disk_usage("/host_root")
            host_disk = {
                "total": host_usage.total,
                "used": host_usage.used,
                "free": host_usage.free,
                "percent": host_usage.percent,
            }
        except Exception:
            host_disk = None

    process = psutil.Process(os.getpid())
    process_mem = process.memory_info()
    try:
        fd_count = process.num_fds()
    except AttributeError:
        fd_count = None
    try:
        connection_count = len(process.net_connections())
    except Exception:
        connection_count = None

    network = None
    try:
        net_io = psutil.net_io_counters()
        network = {"bytes_sent": net_io.bytes_sent, "bytes_recv": net_io.bytes_recv}
    except Exception:
        pass

    return {
        "cpu": {
            "percent": cpu_percent,
            "count_logical": psutil.cpu_count(logical=True),
            "count_physical": psutil.cpu_count(logical=False),
            "freq_current": round(cpu_freq.current, 0) if cpu_freq else None,
            "freq_max": round(cpu_freq.max, 0) if cpu_freq else None,
            "load_avg_1m": load_avg[0] if load_avg else None,
            "load_avg_5m": load_avg[1] if load_avg else None,
            "load_avg_15m": load_avg[2] if load_avg else None,
        },
        "memory": {
            "total": mem.total,
            "used": mem.used,
            "available": mem.available,
            "percent": mem.percent,
            "swap_total": swap.total,
            "swap_used": swap.used,
            "swap_percent": swap.percent,
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
            "read_bytes": disk_io.read_bytes if disk_io else None,
            "write_bytes": disk_io.write_bytes if disk_io else None,
        },
        "host_disk": host_disk,
        "network": network,
        "uptime": int(time.time() - psutil.boot_time()),
        "process": {
            "memory_rss": process_mem.rss,
            "memory_vms": process_mem.vms,
            "cpu_percent": process.cpu_percent(interval=0),
            "threads": process.num_threads(),
            "fds": fd_count,
            "connections": connection_count,
        },
    }


@router.get("/api/system/ips")
async def list_ip_directory(
    search: str = "",
    page: int = 1,
    page_size: int = 20,
    _: bool = Depends(permission_required("page.system.config")),
):
    from app.services.ip_directory import list_ips

    return await list_ips(search=search, page=page, page_size=page_size)


@router.post("/api/system/ips/{ip}/lookup")
async def lookup_ip_geo(
    ip: str, _: bool = Depends(permission_required("system_config.update"))
):
    from app.services.ip_location import lookup_ip_location

    return await lookup_ip_location(ip)


@router.post("/api/system/ips/{ip}/tags")
async def add_ip_tag(
    ip: str, body: dict = Body(...), _: bool = Depends(permission_required("system_config.update"))
):
    from app.services.ip_directory import add_ip_tag

    tag = (body.get("tag") or "").strip()
    if not tag:
        raise HTTPException(status_code=422, detail="标签不能为空")
    try:
        tags = await add_ip_tag(ip, tag)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ip": ip, "tags": tags}


@router.delete("/api/system/ips/{ip}/tags/{tag}")
async def delete_ip_tag(
    ip: str, tag: str, _: bool = Depends(permission_required("system_config.update"))
):
    from app.services.ip_directory import remove_ip_tag

    return {"ip": ip, "tags": await remove_ip_tag(ip, tag)}


@router.get("/system-config", response_class=HTMLResponse)
async def system_config_page(request: Request, _: bool = Depends(permission_required("page.system.config"))):
    html = render(request, "admin/system_config.html", active_page="system-config")
    return HTMLResponse(content=html)
