"""Hourly streaming-speed (tokens/s) aggregation into model_speed_stats.

Every run aggregates complete one-hour windows from request_logs:
- only successful streaming requests with a first-chunk time count
- stream duration = latency_ms - first_chunk_ms  ("from first token to end")
- output tokens come from tokens.completion_tokens (fallback output_tokens)
- rate = (sum(output_tokens) - requests) / sum(duration): industry-standard
  decode throughput, excluding each request's first (prefill) token

Three dimensions are stored per window with '' sentinels (see ModelSpeedStat):
provider rollup, provider+model, and model across providers (user-view name).
The task catches up missed windows automatically (max SPEED_BACKFILL_WINDOWS)
and purges rows older than SPEED_RETENTION_DAYS.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import text

from app.core.config import logger
from app.core.database import async_session_maker, ModelSpeedStat
from app.services.model_naming import (
    provider_stats_model_name,
    user_stats_model_name,
)

SPEED_RETENTION_DAYS = 30
SPEED_BACKFILL_WINDOWS = 48

_FETCH_WINDOW_SQL = text(
    """
    SELECT
        COALESCE(p.name, '') AS provider_name,
        rl.requested_model AS requested_model,
        rl.model AS model,
        rl.actual_model AS actual_model,
        GREATEST(COALESCE((rl.tokens->>'completion_tokens')::bigint,
                          (rl.tokens->>'output_tokens')::bigint, 0), 0) AS output_tokens,
        (rl.latency_ms - rl.first_chunk_ms) AS stream_ms
    FROM request_logs rl
    LEFT JOIN providers p ON p.id = rl.provider_id
    WHERE rl.created_at >= :start
      AND rl.created_at < :end
      AND rl.status = 'success'
      AND rl.first_chunk_ms IS NOT NULL
      AND rl.latency_ms IS NOT NULL
      AND rl.latency_ms > rl.first_chunk_ms
      AND GREATEST(COALESCE((rl.tokens->>'completion_tokens')::bigint,
                            (rl.tokens->>'output_tokens')::bigint, 0), 0) > 0
    """
)


def group_speed_rows(rows) -> dict[tuple[str, str], dict]:
    """Group fetched window rows into the three dimensions.

    Returns {(provider_name, model_name): {requests, output_tokens, stream_ms}}.
    """
    grouped: dict[tuple[str, str], dict] = {}

    def _bump(provider: str, model: str, output_tokens: int, stream_ms: float):
        key = (provider, model)
        bucket = grouped.setdefault(
            key, {"requests": 0, "output_tokens": 0, "stream_ms": 0.0}
        )
        bucket["requests"] += 1
        bucket["output_tokens"] += int(output_tokens)
        bucket["stream_ms"] += float(stream_ms or 0)

    for row in rows:
        provider = row.provider_name or ""
        output_tokens = int(row.output_tokens or 0)
        stream_ms = float(row.stream_ms or 0)
        if output_tokens <= 0 or stream_ms <= 0:
            continue
        upstream_model = provider_stats_model_name(row.actual_model, row.model)
        user_model = user_stats_model_name(row.requested_model, row.model)
        if provider and upstream_model:
            _bump(provider, upstream_model, output_tokens, stream_ms)  # provider+model
            _bump(provider, "", output_tokens, stream_ms)  # provider rollup
        if user_model:
            _bump("", user_model, output_tokens, stream_ms)  # model (user view)
    return grouped


def hour_floor(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def missing_windows(last_period: datetime | None, now: datetime) -> list[datetime]:
    """Complete hourly windows still missing, oldest first (bounded)."""
    latest_complete = hour_floor(now) - timedelta(hours=1)
    if last_period is None:
        return [latest_complete - timedelta(hours=i) for i in range(SPEED_BACKFILL_WINDOWS - 1, -1, -1)]
    start = last_period + timedelta(hours=1)
    windows = []
    while start <= latest_complete and len(windows) < SPEED_BACKFILL_WINDOWS:
        windows.append(start)
        start += timedelta(hours=1)
    return windows


async def aggregate_speed_window(period_start: datetime) -> int:
    """Aggregate one hourly window into model_speed_stats. Returns rows written."""
    end = period_start + timedelta(hours=1)
    async with async_session_maker() as session:
        rows = (await session.execute(_FETCH_WINDOW_SQL, {"start": period_start, "end": end})).all()
        grouped = group_speed_rows(rows)
        for (provider, model), bucket in grouped.items():
            await session.execute(
                text(
                    "INSERT INTO model_speed_stats "
                    "(period_start, provider_name, model_name, requests, output_tokens, stream_ms) "
                    "VALUES (:period_start, :provider, :model, :requests, :output_tokens, :stream_ms) "
                    "ON CONFLICT (period_start, provider_name, model_name) DO UPDATE SET "
                    "requests = EXCLUDED.requests, output_tokens = EXCLUDED.output_tokens, "
                    "stream_ms = EXCLUDED.stream_ms"
                ),
                {
                    "period_start": period_start,
                    "provider": provider,
                    "model": model,
                    "requests": bucket["requests"],
                    "output_tokens": bucket["output_tokens"],
                    "stream_ms": bucket["stream_ms"],
                },
            )
        await session.commit()
    return len(grouped)


async def run_speed_stats_aggregation() -> dict:
    """Scheduled entrypoint: catch up missing windows + purge old rows."""
    async with async_session_maker() as session:
        last_result = await session.execute(
            text("SELECT MAX(period_start) FROM model_speed_stats")
        )
        last_period = last_result.scalar()
        purge_result = await session.execute(
            text("DELETE FROM model_speed_stats WHERE period_start < :cutoff"),
            {"cutoff": datetime.now() - timedelta(days=SPEED_RETENTION_DAYS)},
        )
        purged = purge_result.rowcount or 0
        await session.commit()

    windows = missing_windows(last_period, datetime.now())
    total_rows = 0
    for window in windows:
        total_rows += await aggregate_speed_window(window)

    summary = {
        "windows": len(windows),
        "rows": total_rows,
        "purged": purged,
    }
    logger.info(
        "[SPEED STATS] Aggregated %d windows (%d rows), purged %d stale rows",
        len(windows), total_rows, purged,
    )
    return summary


def compute_tokens_per_second(
    output_tokens: int | float,
    stream_ms: int | float,
    requests: int | float = 0,
) -> float | None:
    """Decode tok/s = (output_tokens - requests) / (stream_ms / 1000).

    Industry-standard formula: the window starts at the first token and the
    first (prefill) token of each request is excluded, so the numerator
    subtracts the request count from the summed output tokens.
    """
    if not stream_ms or stream_ms <= 0:
        return None
    decode_tokens = float(output_tokens) - float(requests or 0)
    if decode_tokens <= 0:
        return None
    return round(decode_tokens / (float(stream_ms) / 1000.0), 1)


async def get_speed_report(dimension: str, hours: int = 168) -> dict:
    """Read-side aggregation for admin monitor + user catalog.

    Returns items with 24h/7d(or `hours`) tokens-per-second plus an hourly
    series over the last 24h for the chart.
    """
    from sqlalchemy import case, func, select

    now = datetime.now()
    range_start = hour_floor(now) - timedelta(hours=hours - 1)
    day_start = hour_floor(now) - timedelta(hours=23)

    if dimension == "provider":
        where = (ModelSpeedStat.provider_name != "") & (ModelSpeedStat.model_name == "")
        key_cols = (ModelSpeedStat.provider_name,)
    elif dimension == "provider_model":
        where = (ModelSpeedStat.provider_name != "") & (ModelSpeedStat.model_name != "")
        key_cols = (ModelSpeedStat.provider_name, ModelSpeedStat.model_name)
    else:  # model
        where = (ModelSpeedStat.provider_name == "") & (ModelSpeedStat.model_name != "")
        key_cols = (ModelSpeedStat.model_name,)

    async with async_session_maker() as session:
        total_result = await session.execute(
            select(
                *key_cols,
                func.sum(ModelSpeedStat.requests),
                func.sum(ModelSpeedStat.output_tokens),
                func.sum(ModelSpeedStat.stream_ms),
                func.sum(
                    case((ModelSpeedStat.period_start >= day_start, ModelSpeedStat.requests), else_=0)
                ),
                func.sum(
                    case(
                        (ModelSpeedStat.period_start >= day_start, ModelSpeedStat.output_tokens),
                        else_=0,
                    )
                ),
                func.sum(
                    case((ModelSpeedStat.period_start >= day_start, ModelSpeedStat.stream_ms), else_=0)
                ),
            )
            .where(where & (ModelSpeedStat.period_start >= range_start))
            .group_by(*key_cols)
        )
        totals = total_result.all()

        series_result = await session.execute(
            select(
                ModelSpeedStat.period_start,
                *key_cols,
                ModelSpeedStat.output_tokens,
                ModelSpeedStat.stream_ms,
                ModelSpeedStat.requests,
            )
            .where(where & (ModelSpeedStat.period_start >= day_start))
            .order_by(ModelSpeedStat.period_start.asc())
        )
        series_rows = series_result.all()

    series_map: dict = {}
    for row in series_rows:
        key = row[1] if len(key_cols) == 1 else (row[1], row[2])
        series_map.setdefault(key, []).append(
            {
                "t": row[0].isoformat(),
                "v": compute_tokens_per_second(row[-3], row[-2], row[-1]),
            }
        )

    offset = len(key_cols)
    items = []
    for row in totals:
        key = row[0] if offset == 1 else (row[0], row[1])
        req_total = int(row[offset] or 0)
        out_total = int(row[offset + 1] or 0)
        ms_total = float(row[offset + 2] or 0)
        req_day = int(row[offset + 3] or 0)
        out_day = int(row[offset + 4] or 0)
        ms_day = float(row[offset + 5] or 0)
        items.append(
            {
                "name": _display_name(dimension, row),
                "requests": req_total,
                "tokens_per_s": compute_tokens_per_second(out_total, ms_total, req_total),
                "requests_24h": req_day,
                "tokens_per_s_24h": compute_tokens_per_second(out_day, ms_day, req_day),
                "series": series_map.get(key, []),
            }
        )
    items.sort(key=lambda it: -(it["requests"] or 0))
    return {"dimension": dimension, "hours": hours, "items": items}


def _display_name(dimension: str, row) -> str:
    if dimension == "provider":
        return row[0]
    if dimension == "provider_model":
        return f"{row[0]} / {row[1]}"
    return row[0]


async def get_model_speed_map(days: int = 7) -> dict[str, float]:
    """User-side: model -> tokens/s over the recent window (model dimension)."""
    from sqlalchemy import func, select

    cutoff = hour_floor(datetime.now()) - timedelta(days=days)
    async with async_session_maker() as session:
        result = await session.execute(
            select(
                ModelSpeedStat.model_name,
                func.sum(ModelSpeedStat.output_tokens),
                func.sum(ModelSpeedStat.stream_ms),
                func.sum(ModelSpeedStat.requests),
            )
            .where(
                (ModelSpeedStat.provider_name == "")
                & (ModelSpeedStat.model_name != "")
                & (ModelSpeedStat.period_start >= cutoff)
            )
            .group_by(ModelSpeedStat.model_name)
        )
        rows = result.all()
    speed_map = {}
    for name, output_tokens, stream_ms, requests in rows:
        tps = compute_tokens_per_second(output_tokens or 0, stream_ms or 0, requests or 0)
        if tps:
            speed_map[name] = tps
    return speed_map


if __name__ == "__main__":
    print(asyncio.run(run_speed_stats_aggregation()))
