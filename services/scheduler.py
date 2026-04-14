from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core.config import proxy_logger
from services.stats_aggregator import (
    aggregate_yesterday_stats,
    backfill_historical_stats,
    cleanup_stale_pending_requests,
    archive_old_request_logs,
)

logger = proxy_logger
scheduler = AsyncIOScheduler()


async def startup_scheduler():
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
        archive_old_request_logs,
        CronTrigger(hour=0, minute=20),
        id="archive_old_request_logs",
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
        "[SCHEDULER] Scheduler started: aggregate at 00:05, archive at 00:20, cleanup pending every 10 min, recommendation analysis at 08:00"
    )

    import asyncio

    asyncio.create_task(run_backfill())


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


def shutdown_scheduler():
    scheduler.shutdown()
    logger.info("[SCHEDULER] Scheduler shutdown")
