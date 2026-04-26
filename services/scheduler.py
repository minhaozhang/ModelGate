from __future__ import annotations

import time
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update

from core.config import proxy_logger
from core.database import SchedulerTask, SchedulerTaskLog, async_session_maker
from services.provider_limiter import auto_reenable_disabled_keys_and_providers
from services.stats_aggregator import (
    aggregate_yesterday_stats,
    backfill_historical_stats,
    cleanup_stale_pending_requests,
    archive_old_request_logs,
    aggregate_mcp_yesterday_stats,
)
from services.busyness import compute_busyness_level, LEVEL_LABELS

logger = proxy_logger
scheduler = AsyncIOScheduler()

TASK_REGISTRY = {
    "aggregate_daily_stats": {
        "name": "每日统计聚合",
        "description": "聚合昨日的请求、Token、错误等统计数据到日统计表",
        "default_cron": "5 0 * * *",
        "func": aggregate_yesterday_stats,
    },
    "aggregate_mcp_daily_stats": {
        "name": "MCP每日统计聚合",
        "description": "聚合昨日MCP调用的统计数据",
        "default_cron": "10 0 * * *",
        "func": aggregate_mcp_yesterday_stats,
    },
    "archive_old_request_logs": {
        "name": "日志归档",
        "description": "将30天前的请求日志从主表归档到历史表",
        "default_cron": "20 0 * * *",
        "func": archive_old_request_logs,
    },
    "cleanup_stale_pending": {
        "name": "清理过期请求",
        "description": "清理长时间处于pending状态的请求记录",
        "default_cron": "*/10 * * * *",
        "func": cleanup_stale_pending_requests,
    },
    "auto_reenable_disabled": {
        "name": "自动恢复禁用",
        "description": "自动重新启用被禁用的供应商密钥和供应商",
        "default_cron": "*/30 * * * *",
        "func": auto_reenable_disabled_keys_and_providers,
    },
    "compute_busyness_level": {
        "name": "繁忙程度计算",
        "description": "计算系统繁忙级别（1-6）并更新缓存",
        "default_cron": "*/10 * * * *",
        "func": compute_busyness_level,
    },
    "daily_recommendation_analysis": {
        "name": "每日推荐分析",
        "description": "基于7天使用统计计算模型推荐排行并缓存到数据库",
        "default_cron": "0 8 * * *",
        "func": None,
    },
}


async def _ensure_task_records():
    async with async_session_maker() as session:
        for task_id, reg in TASK_REGISTRY.items():
            result = await session.execute(
                select(SchedulerTask).where(SchedulerTask.task_id == task_id)
            )
            existing = result.scalar_one_or_none()
            if not existing:
                session.add(SchedulerTask(
                    task_id=task_id,
                    name=reg["name"],
                    description=reg.get("description", ""),
                    cron_expression=reg["default_cron"],
                    default_cron=reg["default_cron"],
                ))
        await session.commit()


async def _get_task_cron(task_id: str) -> str:
    async with async_session_maker() as session:
        result = await session.execute(
            select(SchedulerTask).where(SchedulerTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()
        if task and task.cron_expression:
            return task.cron_expression
    return TASK_REGISTRY[task_id]["default_cron"]


async def _is_task_paused(task_id: str) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(SchedulerTask.is_paused).where(SchedulerTask.task_id == task_id)
        )
        row = result.scalar_one_or_none()
        return bool(row) if row is not None else False


def cron_to_trigger(cron_expr: str):
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {cron_expr}")
    return CronTrigger(
        minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4]
    )


async def _run_task_with_logging(task_id: str, func, summary: str | None = None):
    if await _is_task_paused(task_id):
        logger.debug("[SCHEDULER] Task %s is paused, skipping", task_id)
        return

    start = time.time()
    started_at = datetime.utcnow()
    error = None
    status = "running"

    async with async_session_maker() as session:
        session.add(SchedulerTaskLog(
            task_id=task_id, status=status, started_at=started_at,
        ))
        await session.commit()

    try:
        if func:
            await func()
        status = "success"
    except Exception as exc:
        status = "failed"
        error = str(exc)[:1000]
        logger.error("[SCHEDULER] Task %s failed: %s", task_id, exc)
    finally:
        duration_ms = int((time.time() - start) * 1000)
        finished_at = datetime.utcnow()

        async with async_session_maker() as session:
            await session.execute(
                update(SchedulerTask)
                .where(SchedulerTask.task_id == task_id)
                .values(
                    last_run_at=started_at,
                    last_duration_ms=duration_ms,
                    last_status=status,
                    last_error=error,
                )
            )
            log_result = await session.execute(
                select(SchedulerTaskLog)
                .where(SchedulerTaskLog.task_id == task_id)
                .order_by(SchedulerTaskLog.id.desc())
                .limit(1)
            )
            log_entry = log_result.scalar_one_or_none()
            if log_entry:
                log_entry.status = status
                log_entry.finished_at = finished_at
                log_entry.duration_ms = duration_ms
                log_entry.error = error
                log_entry.result_summary = summary
            await session.commit()

    logger.info("[SCHEDULER] Task %s %s in %dms", task_id, status, duration_ms)


async def _task_aggregate_daily():
    await _run_task_with_logging("aggregate_daily_stats", TASK_REGISTRY["aggregate_daily_stats"]["func"])

async def _task_aggregate_mcp():
    await _run_task_with_logging("aggregate_mcp_daily_stats", TASK_REGISTRY["aggregate_mcp_daily_stats"]["func"])

async def _task_archive():
    await _run_task_with_logging("archive_old_request_logs", TASK_REGISTRY["archive_old_request_logs"]["func"])

async def _task_cleanup():
    await _run_task_with_logging("cleanup_stale_pending", TASK_REGISTRY["cleanup_stale_pending"]["func"])

async def _task_auto_reenable():
    await _run_task_with_logging("auto_reenable_disabled", TASK_REGISTRY["auto_reenable_disabled"]["func"])

async def _task_busyness():
    from core.config import busyness_state

    result = await compute_busyness_level()
    old_level = busyness_state.get("level")
    new_level = result["level"]
    busyness_state.update(result)
    summary = f"level={new_level} ({LEVEL_LABELS.get(new_level, '?')}), disabled={result.get('disabled_providers',0)}, users={result.get('active_users_10min',0)}, 429={result.get('rate_429_ratio',0)*100:.1f}%"

    if old_level is not None and old_level != new_level:
        logger.info("[BUSYNESS] Level changed: %s -> %s", old_level, new_level)
        should_notify = old_level == 2 and new_level == 1
        if should_notify:
            try:
                from services.notification import create_notification
                await create_notification(
                    "system",
                    "warning" if new_level <= 3 else "info",
                    f"系统繁忙程度变更：{LEVEL_LABELS.get(old_level, '?')} → {LEVEL_LABELS.get(new_level, '?')}",
                    f"当前级别：{new_level}（{LEVEL_LABELS.get(new_level, '?')}）",
                )
            except Exception as e:
                logger.warning("[BUSYNESS] Failed to create notification: %s", e)

    await _run_task_with_logging("compute_busyness_level", None, summary)


async def _task_recommendation():
    from routes.user import scheduled_daily_recommendation_analysis
    await _run_task_with_logging("daily_recommendation_analysis", scheduled_daily_recommendation_analysis)


TASK_HANDLERS = {
    "aggregate_daily_stats": _task_aggregate_daily,
    "aggregate_mcp_daily_stats": _task_aggregate_mcp,
    "archive_old_request_logs": _task_archive,
    "cleanup_stale_pending": _task_cleanup,
    "auto_reenable_disabled": _task_auto_reenable,
    "compute_busyness_level": _task_busyness,
    "daily_recommendation_analysis": _task_recommendation,
}


async def startup_scheduler():
    await _ensure_task_records()

    for task_id, handler in TASK_HANDLERS.items():
        cron = await _get_task_cron(task_id)
        try:
            scheduler.add_job(
                handler,
                cron_to_trigger(cron),
                id=task_id,
                replace_existing=True,
            )
        except Exception as e:
            logger.error("[SCHEDULER] Failed to add job %s with cron '%s': %s", task_id, cron, e)

    scheduler.start()
    logger.info("[SCHEDULER] Scheduler started with %d tasks from DB config", len(TASK_HANDLERS))

    import asyncio
    asyncio.create_task(run_backfill())


async def run_backfill():
    import asyncio
    await asyncio.sleep(5)
    logger.info("[SCHEDULER] Running backfill for missing dates...")
    await _run_task_with_logging("aggregate_daily_stats", backfill_historical_stats, "backfill")
    await _run_task_with_logging("archive_old_request_logs", archive_old_request_logs, "backfill")


def shutdown_scheduler():
    scheduler.shutdown()
    logger.info("[SCHEDULER] Scheduler shutdown")
