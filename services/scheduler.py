import logging
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from services.stats_aggregator import (
    aggregate_yesterday_stats,
    backfill_historical_stats,
)

logger = logging.getLogger("api_proxy")
scheduler = AsyncIOScheduler()


async def startup_scheduler():
    scheduler.add_job(
        aggregate_yesterday_stats,
        CronTrigger(hour=0, minute=5),
        id="aggregate_daily_stats",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[SCHEDULER] Scheduler started, daily aggregation at 00:05")

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
