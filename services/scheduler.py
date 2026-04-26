from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core.config import proxy_logger
from services.provider_limiter import auto_reenable_disabled_keys_and_providers
from services.busyness import compute_busyness_level, LEVEL_LABELS
from services.stats_aggregator import (
    aggregate_yesterday_stats,
    backfill_historical_stats,
    cleanup_stale_pending_requests,
    archive_old_request_logs,
    aggregate_mcp_yesterday_stats,
)

logger = proxy_logger
scheduler = AsyncIOScheduler()


async def startup_scheduler():
    scheduler.add_job(
        _compute_busyness,
        CronTrigger(minute="*/5"),
        id="compute_busyness_level",
        replace_existing=True,
    )
    scheduler.add_job(
        aggregate_yesterday_stats,
        CronTrigger(hour=0, minute=5),
        id="aggregate_daily_stats",
        replace_existing=True,
    )
    scheduler.add_job(
        cleanup_stale_pending_requests,
        CronTrigger(minute="*/10"),
        id="cleanup_stale_pending",
        replace_existing=True,
    )
    scheduler.add_job(
        auto_reenable_disabled_keys_and_providers,
        CronTrigger(minute="*/30"),
        id="auto_reenable_disabled",
        replace_existing=True,
    )
    scheduler.add_job(
        archive_old_request_logs,
        CronTrigger(hour=0, minute=20),
        id="archive_old_request_logs",
        replace_existing=True,
    )
    scheduler.add_job(
        aggregate_mcp_yesterday_stats,
        CronTrigger(hour=0, minute=10),
        id="aggregate_mcp_daily_stats",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_daily_recommendation_analysis,
        CronTrigger(hour=8, minute=0),
        id="daily_recommendation_analysis",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "[SCHEDULER] Scheduler started: aggregate at 00:05, MCP stats at 00:10, archive at 00:20, cleanup pending every 10 min, auto re-enable every 30 min, busyness every 5 min, recommendation analysis at 08:00"
    )

    import asyncio

    asyncio.create_task(run_backfill())


def _compute_busyness_sync():
    from core.config import busyness_state
    result = compute_busyness_level()
    busyness_state.update(result)
    logger.info("[BUSYNESS] Initial level: %s (%s)", result["level"], LEVEL_LABELS.get(result["level"], "?"))


async def _compute_busyness():
    from core.config import busyness_state

    result = compute_busyness_level()
    old_level = busyness_state.get("level")
    new_level = result["level"]
    busyness_state.update(result)
    if old_level is not None and old_level != new_level:
        logger.info(
            "[BUSYNESS] Level changed: %s (%s) -> %s (%s)",
            old_level, LEVEL_LABELS.get(old_level, "?"),
            new_level, LEVEL_LABELS.get(new_level, "?"),
        )
        try:
            from services.notification import create_notification
            await create_notification(
                "system",
                "warning" if new_level <= 3 else "info",
                f"系统繁忙程度变更：{LEVEL_LABELS.get(old_level, '?')} → {LEVEL_LABELS.get(new_level, '?')}",
                f"当前级别：{new_level}（{LEVEL_LABELS.get(new_level, '?')}），限流供应商：{result.get('disabled_providers', 0)}，活跃用户：{result.get('active_users_10min', 0)}，429占比：{result.get('rate_429_ratio', 0) * 100:.1f}%",
            )
        except Exception as e:
            logger.warning("[BUSYNESS] Failed to create notification: %s", e)
    else:
        logger.debug("[BUSYNESS] Level: %s (%s)", new_level, LEVEL_LABELS.get(new_level, "?"))


async def _run_daily_recommendation_analysis():
    from routes.user import scheduled_daily_recommendation_analysis

    logger.info("[SCHEDULER] Starting daily recommendation analysis...")
    try:
        await scheduled_daily_recommendation_analysis()
    except Exception as exc:
        logger.error("[SCHEDULER] Daily recommendation analysis failed: %s", exc)
    else:
        logger.info("[SCHEDULER] Daily recommendation analysis completed")


async def run_backfill():
    import asyncio

    await asyncio.sleep(5)
    logger.info("[SCHEDULER] Running backfill for missing dates...")
    await backfill_historical_stats()
    await archive_old_request_logs()
    _compute_busyness_sync()


def shutdown_scheduler():
    scheduler.shutdown()
    logger.info("[SCHEDULER] Scheduler shutdown")
