from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core.config import proxy_logger
from services.stats_aggregator import (
    aggregate_yesterday_stats,
    backfill_historical_stats,
    cleanup_stale_pending_requests,
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
        CronTrigger(minute=0),
        id="cleanup_stale_pending",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "[SCHEDULER] Scheduler started: aggregate at 00:05, cleanup pending hourly"
    )

    import asyncio

    asyncio.create_task(run_backfill())


async def run_backfill():
    import asyncio

    await asyncio.sleep(5)
    logger.info("[SCHEDULER] Running backfill for missing dates...")
    await backfill_historical_stats()


def shutdown_scheduler():
    scheduler.shutdown()
    logger.info("[SCHEDULER] Scheduler shutdown")
