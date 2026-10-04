"""Gateway-wide hourly peak recorder.

Samples two gateway-wide gauges once per second and keeps per-hour
maxima:

* concurrency — ``len(active_requests)`` read under its lock;
* tokens/s — the raw 10s decaying-window rate summed from
  ``token_buckets`` (deliberately NOT the EWMA the dials display:
  reading raw is side-effect free and the recorded peak is true
  instantaneous throughput, not a smoothed one).

The live-stats tick cannot be used for this: it only runs while
dashboard subscribers exist, and peaks must be recorded 24/7. DB
writes are throttled to one per ``PERSIST_INTERVAL_SECONDS`` and are
forced on hour rollover and shutdown. On startup the current hour's
stored row re-seeds the in-memory maxima so a mid-hour restart does
not silently forget the hour's earlier peak.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.config import (
    TOKEN_RATE_WINDOW_SECONDS,
    _trim_token_buckets,
    active_requests,
    active_requests_lock,
    token_buckets,
)
from app.core.database import HourlyPeakStat, async_session_maker

logger = logging.getLogger(__name__)

SAMPLE_INTERVAL_SECONDS = 1.0
PERSIST_INTERVAL_SECONDS = 30.0

_state: dict[str, Any] = {
    "date": "",
    "hour": -1,
    "max_concurrency": 0,
    "max_tokens_per_second": 0.0,
    "last_persist_at": 0.0,
    "dirty": False,
}
_task: asyncio.Task | None = None


def _hour_bucket(now: datetime) -> tuple[str, int]:
    return now.strftime("%Y-%m-%d"), now.hour


def _raw_tokens_per_second(now: datetime) -> float:
    _trim_token_buckets(now)
    total = sum(value for _, value in token_buckets)
    return round(total / TOKEN_RATE_WINDOW_SECONDS, 1)


async def _persist(now: datetime, *, force: bool) -> None:
    if not _state["dirty"] and not force:
        return
    date, hour = _state["date"], _state["hour"]
    if not date or hour < 0:
        return
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                select(HourlyPeakStat).where(
                    HourlyPeakStat.date == date, HourlyPeakStat.hour == hour
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                session.add(
                    HourlyPeakStat(
                        date=date,
                        hour=hour,
                        max_concurrency=_state["max_concurrency"],
                        max_tokens_per_second=_state["max_tokens_per_second"],
                    )
                )
            else:
                row.max_concurrency = max(
                    row.max_concurrency or 0, _state["max_concurrency"]
                )
                row.max_tokens_per_second = max(
                    row.max_tokens_per_second or 0.0,
                    _state["max_tokens_per_second"],
                )
                row.updated_at = now
            await session.commit()
        _state["dirty"] = False
        _state["last_persist_at"] = now.timestamp()
    except Exception:
        # Recording must never take the gateway down; retry on the next
        # forced persist (rollover/shutdown) or after the throttle window.
        logger.debug("hourly peak persist failed", exc_info=True)


async def observe_peak_sample(now: datetime | None = None) -> None:
    """Take one sample, roll the hour bucket if needed, maybe persist.

    Called by the sampler loop every second and (for live display)
    by ``build_live_stats_snapshot``; both funnel through here so the
    recorded maxima and the displayed ones are the same numbers.
    """
    now = now or datetime.now()
    async with active_requests_lock:
        concurrency = len(active_requests)
    tokens_per_second = _raw_tokens_per_second(now)
    date, hour = _hour_bucket(now)
    if date != _state["date"] or hour != _state["hour"]:
        await _persist(now, force=True)
        _state.update(
            date=date,
            hour=hour,
            max_concurrency=0,
            max_tokens_per_second=0.0,
        )
    changed = False
    if concurrency > _state["max_concurrency"]:
        _state["max_concurrency"] = concurrency
        changed = True
    if tokens_per_second > _state["max_tokens_per_second"]:
        _state["max_tokens_per_second"] = tokens_per_second
        changed = True
    if changed:
        _state["dirty"] = True
        if now.timestamp() - _state["last_persist_at"] >= PERSIST_INTERVAL_SECONDS:
            await _persist(now, force=True)


def peaks_payload() -> dict[str, Any]:
    """Current hour bucket + maxima for the live snapshot."""
    return {
        "date": _state["date"],
        "hour": _state["hour"],
        "max_concurrency": _state["max_concurrency"],
        "max_tokens_per_second": _state["max_tokens_per_second"],
    }


async def _sampler_loop() -> None:
    while True:
        await asyncio.sleep(SAMPLE_INTERVAL_SECONDS)
        try:
            await observe_peak_sample()
        except Exception:
            logger.debug("hourly peak sample failed", exc_info=True)


async def _seed_current_hour() -> None:
    now = datetime.now()
    date, hour = _hour_bucket(now)
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                select(HourlyPeakStat).where(
                    HourlyPeakStat.date == date, HourlyPeakStat.hour == hour
                )
            )
            row = result.scalar_one_or_none()
        if row is not None:
            _state.update(
                date=date,
                hour=hour,
                max_concurrency=row.max_concurrency or 0,
                max_tokens_per_second=row.max_tokens_per_second or 0.0,
            )
    except Exception:
        logger.debug("hourly peak seed failed", exc_info=True)


async def start_peak_sampler() -> None:
    global _task
    if _task is not None:
        return
    await _seed_current_hour()
    _task = asyncio.create_task(_sampler_loop())


async def stop_peak_sampler() -> None:
    global _task
    task = _task
    _task = None
    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    await _persist(datetime.now(), force=True)
