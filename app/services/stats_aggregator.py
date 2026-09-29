from datetime import datetime, timedelta

from sqlalchemy import select, func, and_, delete, update, text, Integer

from app.core.config import proxy_logger
from app.core.database import (
    async_session_maker,
    RequestLog,
    RequestLogRead,
    ProviderDailyStat,
    ProviderKeyDailyStat,
    ApiKeyDailyStat,
    ApiKeyModelDailyStat,
    ModelDailyStat,
    TagDailyStat,
    ApiKey,
    ApiKeyTag,
    Provider,
)
from app.services.model_naming import (
    provider_stats_model_name,
    user_stats_model_name,
)

logger = proxy_logger
ERROR_STATUS = "error"
TIMEOUT_STATUS = "timeout"
RATE_LIMITED_STATUS = "rate_limited"
LOCAL_RATE_LIMITED_STATUS = "local_rate_limited"
RATE_LIMITED_STATUSES = {RATE_LIMITED_STATUS, LOCAL_RATE_LIMITED_STATUS}


async def aggregate_stats_for_date(date_str: str) -> dict:
    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)

    async with async_session_maker() as session:
        logs_query = select(RequestLogRead).where(
            and_(
                RequestLogRead.created_at >= start_dt,
                RequestLogRead.created_at < end_dt,
                RequestLogRead.api_key_id.isnot(None),
            )
        )
        result = await session.execute(logs_query)
        logs = result.scalars().all()

        provider_cache = {}
        provider_stats = {}
        provider_key_stats = {}
        api_key_stats = {}
        api_key_model_stats = {}
        model_stats = {}

        for log in logs:
            provider_name = None
            if log.provider_id:
                if log.provider_id not in provider_cache:
                    prov_result = await session.execute(
                        select(Provider).where(Provider.id == log.provider_id)
                    )
                    prov = prov_result.scalar_one_or_none()
                    provider_cache[log.provider_id] = prov.name if prov else None
                provider_name = provider_cache.get(log.provider_id)

            tokens = (
                (log.tokens or {}).get("total_tokens")
                or (log.tokens or {}).get("estimated")
                or 0
            )
            is_error = log.status == ERROR_STATUS
            is_timeout = log.status == TIMEOUT_STATUS
            is_rate_limited = log.status in RATE_LIMITED_STATUSES
            if is_rate_limited:
                tokens = 0
                prompt_tokens = 0
                completion_tokens = 0
                cost_cny = 0.0
            else:
                prompt_tokens = (log.tokens or {}).get("prompt_tokens") or 0
                completion_tokens = (log.tokens or {}).get("completion_tokens") or 0
                try:
                    cost_cny = float(
                        ((log.tokens or {}).get("billing") or {}).get("total_cost_cny") or 0
                    )
                except (TypeError, ValueError):
                    cost_cny = 0.0

            if provider_name:
                if provider_name not in provider_stats:
                    provider_stats[provider_name] = {
                        "requests": 0,
                        "tokens": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "errors": 0,
                        "timeouts": 0,
                        "rate_limited": 0,
                        "cost_cny": 0.0,
                    }
                if is_rate_limited:
                    provider_stats[provider_name]["rate_limited"] += 1
                else:
                    provider_stats[provider_name]["requests"] += 1
                provider_stats[provider_name]["tokens"] += tokens
                provider_stats[provider_name]["prompt_tokens"] += prompt_tokens
                provider_stats[provider_name]["completion_tokens"] += completion_tokens
                provider_stats[provider_name]["cost_cny"] += cost_cny
                if is_error:
                    provider_stats[provider_name]["errors"] += 1
                if is_timeout:
                    provider_stats[provider_name]["timeouts"] += 1

            if log.provider_key_id is not None:
                key_bucket = provider_key_stats.get(log.provider_key_id)
                if key_bucket is None:
                    key_bucket = provider_key_stats[log.provider_key_id] = {
                        "label": log.provider_key_label,
                        "provider_name": provider_name,
                        "requests": 0,
                        "tokens": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "errors": 0,
                        "timeouts": 0,
                        "rate_limited": 0,
                        "cost_cny": 0.0,
                    }
                if log.provider_key_label:
                    key_bucket["label"] = log.provider_key_label
                if provider_name:
                    key_bucket["provider_name"] = provider_name
                if is_rate_limited:
                    key_bucket["rate_limited"] += 1
                else:
                    key_bucket["requests"] += 1
                key_bucket["tokens"] += tokens
                key_bucket["prompt_tokens"] += prompt_tokens
                key_bucket["completion_tokens"] += completion_tokens
                key_bucket["cost_cny"] += cost_cny
                if is_error:
                    key_bucket["errors"] += 1
                if is_timeout:
                    key_bucket["timeouts"] += 1

            if log.api_key_id:
                if log.api_key_id not in api_key_stats:
                    api_key_stats[log.api_key_id] = {
                        "requests": 0,
                        "tokens": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "errors": 0,
                        "timeouts": 0,
                        "rate_limited": 0,
                        "cost_cny": 0.0,
                    }
                if is_rate_limited:
                    api_key_stats[log.api_key_id]["rate_limited"] += 1
                else:
                    api_key_stats[log.api_key_id]["requests"] += 1
                api_key_stats[log.api_key_id]["tokens"] += tokens
                api_key_stats[log.api_key_id]["prompt_tokens"] += prompt_tokens
                api_key_stats[log.api_key_id]["completion_tokens"] += completion_tokens
                api_key_stats[log.api_key_id]["cost_cny"] += cost_cny
                if is_error:
                    api_key_stats[log.api_key_id]["errors"] += 1
                if is_timeout:
                    api_key_stats[log.api_key_id]["timeouts"] += 1
                if log.model:
                    user_model_name = user_stats_model_name(
                        log.requested_model, log.model
                    )
                    api_key_model_key = (log.api_key_id, user_model_name)
                    if api_key_model_key not in api_key_model_stats:
                        api_key_model_stats[api_key_model_key] = {
                            "requests": 0,
                            "tokens": 0,
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "errors": 0,
                            "timeouts": 0,
                            "rate_limited": 0,
                        }
                    if is_rate_limited:
                        api_key_model_stats[api_key_model_key]["rate_limited"] += 1
                    else:
                        api_key_model_stats[api_key_model_key]["requests"] += 1
                    api_key_model_stats[api_key_model_key]["tokens"] += tokens
                    api_key_model_stats[api_key_model_key]["prompt_tokens"] += prompt_tokens
                    api_key_model_stats[api_key_model_key]["completion_tokens"] += completion_tokens
                    if is_error:
                        api_key_model_stats[api_key_model_key]["errors"] += 1
                    if is_timeout:
                        api_key_model_stats[api_key_model_key]["timeouts"] += 1

            model_key = (provider_stats_model_name(log.actual_model, log.model), provider_name)
            if model_key not in model_stats:
                model_stats[model_key] = {
                    "requests": 0,
                    "tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "errors": 0,
                    "timeouts": 0,
                    "rate_limited": 0,
                }
            if is_rate_limited:
                model_stats[model_key]["rate_limited"] += 1
            else:
                model_stats[model_key]["requests"] += 1
            model_stats[model_key]["tokens"] += tokens
            model_stats[model_key]["prompt_tokens"] += prompt_tokens
            model_stats[model_key]["completion_tokens"] += completion_tokens
            if is_error:
                model_stats[model_key]["errors"] += 1
            if is_timeout:
                model_stats[model_key]["timeouts"] += 1

        await session.execute(
            delete(ProviderDailyStat).where(ProviderDailyStat.date == date_str)
        )
        await session.execute(
            delete(ProviderKeyDailyStat).where(ProviderKeyDailyStat.date == date_str)
        )
        await session.execute(
            delete(ApiKeyDailyStat).where(ApiKeyDailyStat.date == date_str)
        )
        await session.execute(
            delete(ApiKeyModelDailyStat).where(ApiKeyModelDailyStat.date == date_str)
        )
        await session.execute(
            delete(ModelDailyStat).where(ModelDailyStat.date == date_str)
        )

        for provider_name, stats in provider_stats.items():
            stat = ProviderDailyStat(
                provider_name=provider_name,
                date=date_str,
                requests=stats["requests"],
                tokens=stats["tokens"],
                prompt_tokens=stats["prompt_tokens"],
                completion_tokens=stats["completion_tokens"],
                errors=stats["errors"],
                timeouts=stats["timeouts"],
                rate_limited=stats["rate_limited"],
                cost_cny=round(stats["cost_cny"], 10),
            )
            session.add(stat)

        for provider_key_id, stats in provider_key_stats.items():
            stat = ProviderKeyDailyStat(
                provider_key_id=provider_key_id,
                provider_key_label=stats["label"],
                provider_name=stats["provider_name"],
                date=date_str,
                requests=stats["requests"],
                tokens=stats["tokens"],
                prompt_tokens=stats["prompt_tokens"],
                completion_tokens=stats["completion_tokens"],
                errors=stats["errors"],
                timeouts=stats["timeouts"],
                rate_limited=stats["rate_limited"],
                cost_cny=round(stats["cost_cny"], 10),
            )
            session.add(stat)

        for api_key_id, stats in api_key_stats.items():
            stat = ApiKeyDailyStat(
                api_key_id=api_key_id,
                date=date_str,
                requests=stats["requests"],
                tokens=stats["tokens"],
                prompt_tokens=stats["prompt_tokens"],
                completion_tokens=stats["completion_tokens"],
                errors=stats["errors"],
                timeouts=stats["timeouts"],
                rate_limited=stats["rate_limited"],
                cost_cny=round(stats["cost_cny"], 10),
            )
            session.add(stat)

        for (api_key_id, model_name), stats in api_key_model_stats.items():
            stat = ApiKeyModelDailyStat(
                api_key_id=api_key_id,
                model_name=model_name,
                date=date_str,
                requests=stats["requests"],
                tokens=stats["tokens"],
                prompt_tokens=stats["prompt_tokens"],
                completion_tokens=stats["completion_tokens"],
                errors=stats["errors"],
                timeouts=stats["timeouts"],
                rate_limited=stats["rate_limited"],
            )
            session.add(stat)

        for (model_name, provider_name), stats in model_stats.items():
            stat = ModelDailyStat(
                model_name=model_name,
                provider_name=provider_name,
                date=date_str,
                requests=stats["requests"],
                tokens=stats["tokens"],
                prompt_tokens=stats["prompt_tokens"],
                completion_tokens=stats["completion_tokens"],
                errors=stats["errors"],
                timeouts=stats["timeouts"],
                rate_limited=stats["rate_limited"],
            )
            session.add(stat)

        await session.commit()

    total_requests = sum(s["requests"] for s in provider_stats.values())
    logger.info(
        f"[AGGREGATOR] Aggregated stats for {date_str}: {total_requests} requests, {len(provider_stats)} providers, {len(provider_key_stats)} provider_keys, {len(api_key_stats)} api_keys, {len(model_stats)} models"
    )

    return {
        "date": date_str,
        "total_requests": total_requests,
        "providers": len(provider_stats),
        "provider_keys": len(provider_key_stats),
        "api_keys": len(api_key_stats),
        "models": len(model_stats),
    }


async def get_missing_dates() -> list[str]:
    async with async_session_maker() as session:
        # Raw logs older than ~30 days are archived away, so only dates whose
        # detail rows still exist in request_logs can be (re-)aggregated safely.
        result = await session.execute(
            select(func.distinct(func.to_char(RequestLogRead.created_at, "YYYY-MM-DD")))
        )
        log_dates = {row[0] for row in result.fetchall()}
        if not log_dates:
            return []

        result = await session.execute(
            select(
                ProviderDailyStat.date,
                func.count(ProviderDailyStat.id),
                func.count(ProviderDailyStat.cost_cny),
            ).group_by(ProviderDailyStat.date)
        )
        provider_rows = {row[0]: (row[1], row[2]) for row in result.fetchall()}

        result = await session.execute(select(ProviderKeyDailyStat.date).distinct())
        key_stat_dates = {row[0] for row in result.fetchall()}

        today = datetime.now().date().strftime("%Y-%m-%d")
        missing = []
        for date_str in sorted(log_dates):
            if date_str >= today:
                continue  # today is handled by the scheduled task, not backfill
            total_rows, rows_with_cost = provider_rows.get(date_str, (0, 0))
            fully_aggregated = (
                total_rows > 0
                and total_rows == rows_with_cost
                and date_str in key_stat_dates
            )
            if not fully_aggregated:
                missing.append(date_str)

        return missing


async def backfill_historical_stats() -> None:
    missing_dates = await get_missing_dates()
    if not missing_dates:
        return

    logger.info(f"[AGGREGATOR] Backfilling {len(missing_dates)} missing dates")
    for date_str in missing_dates:
        try:
            await aggregate_stats_for_date(date_str)
        except Exception as e:
            logger.error(f"[AGGREGATOR] Error backfilling {date_str}: {e}")


async def aggregate_tag_daily_stats(date_str: str) -> dict:
    """Snapshot per-(tag, api_key) usage for one day into tag_daily_stats.

    Tag attribution is frozen at aggregation time: rows keyed by current
    api_key_tags membership (untagged keys land under tag=''). Multi-tag keys
    produce one row per tag, so per-tag views are complete while per-key
    totals must come from api_key_daily_stats instead.
    """
    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)

    async with async_session_maker() as session:
        key_result = await session.execute(select(ApiKey.id, ApiKey.name))
        key_names = {row.id: row.name for row in key_result.fetchall()}

        tag_result = await session.execute(
            select(ApiKeyTag.api_key_id, ApiKeyTag.tag)
        )
        tags_map: dict[int, list[str]] = {}
        for row in tag_result.fetchall():
            tags_map.setdefault(row.api_key_id, []).append(row.tag)

        result = await session.execute(
            select(RequestLogRead).where(
                and_(
                    RequestLogRead.created_at >= start_dt,
                    RequestLogRead.created_at < end_dt,
                    RequestLogRead.api_key_id.isnot(None),
                )
            )
        )
        logs = result.scalars().all()

        stats: dict[tuple[str, int], dict] = {}
        for log in logs:
            if not log.api_key_id:
                continue
            is_rate_limited = log.status in RATE_LIMITED_STATUSES
            if is_rate_limited:
                tokens = 0
                prompt_tokens = 0
                completion_tokens = 0
                cost_cny = 0.0
            else:
                tokens = (
                    (log.tokens or {}).get("total_tokens")
                    or (log.tokens or {}).get("estimated")
                    or 0
                )
                prompt_tokens = (log.tokens or {}).get("prompt_tokens") or 0
                completion_tokens = (log.tokens or {}).get("completion_tokens") or 0
                try:
                    cost_cny = float(
                        ((log.tokens or {}).get("billing") or {}).get("total_cost_cny") or 0
                    )
                except (TypeError, ValueError):
                    cost_cny = 0.0

            for tag in tags_map.get(log.api_key_id) or [""]:
                bucket_key = (tag, log.api_key_id)
                bucket = stats.setdefault(
                    bucket_key,
                    {
                        "requests": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "tokens": 0,
                        "cost_cny": 0.0,
                    },
                )
                if not is_rate_limited:
                    bucket["requests"] += 1
                bucket["tokens"] += tokens
                bucket["prompt_tokens"] += prompt_tokens
                bucket["completion_tokens"] += completion_tokens
                bucket["cost_cny"] += cost_cny

        await session.execute(
            delete(TagDailyStat).where(TagDailyStat.date == date_str)
        )

        for (tag, api_key_id), bucket in stats.items():
            session.add(
                TagDailyStat(
                    date=date_str,
                    tag=tag,
                    api_key_id=api_key_id,
                    key_name=key_names.get(api_key_id, str(api_key_id)),
                    requests=bucket["requests"],
                    prompt_tokens=bucket["prompt_tokens"],
                    completion_tokens=bucket["completion_tokens"],
                    tokens=bucket["tokens"],
                    cost_cny=round(bucket["cost_cny"], 10),
                )
            )

        await session.commit()

    total_rows = len(stats)
    distinct_keys = len({key_id for _, key_id in stats})
    logger.info(
        f"[AGGREGATOR] Aggregated tag stats for {date_str}: {total_rows} rows, {distinct_keys} api_keys"
    )

    return {
        "date": date_str,
        "rows": total_rows,
        "api_keys": distinct_keys,
    }


async def aggregate_tag_yesterday_stats() -> None:
    async with async_session_maker() as session:
        today_result = await session.execute(select(func.current_date()))
        db_today = today_result.scalar()
    yesterday = (db_today - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        await aggregate_tag_daily_stats(yesterday)
        await backfill_tag_stats()
    except Exception as e:
        logger.error(f"[AGGREGATOR] Error aggregating yesterday tag stats: {e}")


async def backfill_tag_stats() -> None:
    """Fill tag_daily_stats (and refresh api_key_daily_stats cost) for dates
    that already have daily stats but no tag snapshot yet. One-time full
    history pass on first deploy, then a no-op."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderDailyStat.date).distinct()
        )
        stat_dates = {row[0] for row in result.fetchall()}
        result = await session.execute(select(TagDailyStat.date).distinct())
        tag_dates = {row[0] for row in result.fetchall()}

    missing = sorted(stat_dates - tag_dates)
    if not missing:
        return

    logger.info(f"[AGGREGATOR] Backfilling tag stats for {len(missing)} dates")
    for date_str in missing:
        try:
            await aggregate_stats_for_date(date_str)
            await aggregate_tag_daily_stats(date_str)
        except Exception as e:
            logger.error(f"[AGGREGATOR] Error backfilling tag stats {date_str}: {e}")


async def backfill_cost_fix() -> None:
    """One-time full-history re-aggregation after the cost field fix
    (tokens.billing.total_cost_cny instead of the never-populated top-level
    tokens.total_cost_cny). Guarded by a system_settings flag so it runs
    exactly once per deployment."""
    from app.services.system_config import get_setting, save_setting

    if await get_setting("stats", "cost_nested_backfill", "") == "done":
        return

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKeyDailyStat.date).distinct())
        dates = sorted({row[0] for row in result.fetchall()})

    if not dates:
        await save_setting(
            "stats", "cost_nested_backfill", "done", "cost字段嵌套路径修复回填标记"
        )
        return

    logger.info(
        f"[AGGREGATOR] Re-aggregating {len(dates)} dates for cost path fix"
    )
    for date_str in dates:
        try:
            await aggregate_stats_for_date(date_str)
            await aggregate_tag_daily_stats(date_str)
        except Exception as e:
            logger.error(f"[AGGREGATOR] Error re-aggregating {date_str}: {e}")
    await save_setting(
        "stats", "cost_nested_backfill", "done", "cost字段嵌套路径修复回填标记"
    )
    logger.info("[AGGREGATOR] Cost path fix backfill complete")


async def cleanup_stale_pending_requests() -> None:
    async with async_session_maker() as session:
        result = await session.execute(
            update(RequestLog)
            .where(
                RequestLog.status.in_(("waiting", "pending", "sending")),
                RequestLog.created_at < func.now() - timedelta(minutes=10),
            )
            .values(
                status="timeout",
                error="请求超时",
                latency_ms=func.extract("epoch", func.now() - RequestLog.created_at)
                * 1000,
                updated_at=func.now(),
            )
            .returning(RequestLog.id)
        )
        updated_ids = result.scalars().all()
        await session.commit()

        if updated_ids:
            logger.info(
                f"[AGGREGATOR] Marked {len(updated_ids)} stale pending requests as timeout"
            )


async def archive_old_request_logs() -> int:
    cutoff = datetime.now() - timedelta(days=30)

    async with async_session_maker() as session:
        result = await session.execute(
            text(
                """
                WITH moved AS (
                    INSERT INTO request_logs_history (
                        id,
                        api_key_id,
                        provider_id,
                        model,
                        response,
                        tokens,
                        latency_ms,
                        first_chunk_ms,
                        wait_ms,
                        request_context_tokens,
                        status,
                        upstream_status_code,
                        downstream_status_code,
                        client_ip,
                        user_agent,
                        inbound_protocol,
                        error,
                        intent,
                        requested_model,
                        actual_model,
                        provider_key_id,
                        provider_key_label,
                        routing_decision,
                        request_image_count,
                        fallback_tries,
                        created_at,
                        updated_at,
                        archive_month,
                        archived_at
                    )
                    SELECT
                        rl.id,
                        rl.api_key_id,
                        rl.provider_id,
                        rl.model,
                        rl.response,
                        rl.tokens,
                        rl.latency_ms,
                        rl.first_chunk_ms,
                        rl.wait_ms,
                        rl.request_context_tokens,
                        rl.status,
                        rl.upstream_status_code,
                        rl.downstream_status_code,
                        rl.client_ip,
                        rl.user_agent,
                        rl.inbound_protocol,
                        rl.error,
                        rl.intent,
                        rl.requested_model,
                        rl.actual_model,
                        rl.provider_key_id,
                        rl.provider_key_label,
                        rl.routing_decision,
                        rl.request_image_count,
                        rl.fallback_tries,
                        rl.created_at,
                        rl.updated_at,
                        to_char(rl.created_at, 'YYYY-MM'),
                        now()
                    FROM request_logs rl
                    WHERE rl.created_at < :cutoff
                      AND rl.status NOT IN ('rate_limited', 'local_rate_limited')
                      AND EXISTS (
                        SELECT 1
                        FROM model_daily_stats mds
                        WHERE mds.date = to_char(rl.created_at, 'YYYY-MM-DD')
                      )
                    ON CONFLICT (id) DO NOTHING
                    RETURNING id
                )
                DELETE FROM request_logs rl
                WHERE rl.created_at < :cutoff
                  AND EXISTS (
                    SELECT 1
                    FROM model_daily_stats mds
                    WHERE mds.date = to_char(rl.created_at, 'YYYY-MM-DD')
                  )
                  AND (
                    rl.status IN ('rate_limited', 'local_rate_limited')
                    OR EXISTS (
                      SELECT 1
                      FROM request_logs_history rh
                      WHERE rh.id = rl.id
                    )
                  )
                RETURNING id
                """
            ),
            {"cutoff": cutoff},
        )
        archived_ids = result.scalars().all()
        await session.commit()

    if archived_ids:
        logger.info(
            "[AGGREGATOR] Archived %s request logs older than 30 days",
            len(archived_ids),
        )

    notif_cutoff = datetime.now() - timedelta(days=7)
    async with async_session_maker() as session:
        notif_result = await session.execute(
            text(
                "DELETE FROM notifications WHERE "
                "(type = 'system' OR (type = 'user' AND target_api_key_id IS NULL)) "
                "AND created_at < :cutoff"
            ),
            {"cutoff": notif_cutoff},
        )
        deleted_notifs = notif_result.rowcount
        await session.commit()
        if deleted_notifs:
            logger.info(
                "[AGGREGATOR] Cleaned %s stale notifications (system + broadcast "
                "announcements) older than 7 days",
                deleted_notifs,
            )

    return len(archived_ids)


async def aggregate_yesterday_stats() -> None:
    async with async_session_maker() as session:
        today_result = await session.execute(select(func.current_date()))
        db_today = today_result.scalar()
    yesterday = (db_today - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        await aggregate_stats_for_date(yesterday)
        await backfill_historical_stats()
    except Exception as e:
        logger.error(f"[AGGREGATOR] Error aggregating yesterday stats: {e}")


async def backup_request_contents() -> dict:
    import gzip
    import json
    import os

    async with async_session_maker() as session:
        today_result = await session.execute(select(func.current_date()))
        db_today = today_result.scalar()
    target_date = db_today - timedelta(days=1)
    target_date_str = target_date.strftime("%Y-%m-%d")
    dt_start = datetime.combine(target_date, datetime.min.time())
    dt_end = datetime.combine(db_today, datetime.min.time())

    backup_dir = os.path.join(os.getcwd(), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    filename = os.path.join(backup_dir, f"request_contents_{target_date_str}.jsonl.gz")

    if os.path.exists(filename):
        logger.info("[BACKUP] File already exists: %s, skipping export", filename)
        return {"date": target_date_str, "status": "skipped", "reason": "file_exists"}

    exported = 0
    batch_size = 50

    with gzip.open(filename, "wt", encoding="utf-8") as f:
        offset = 0
        while True:
            async with async_session_maker() as session:
                result = await session.execute(
                    text("""
                        SELECT rc.id, rc.log_id, rc.request_messages, rc.response_content,
                               rc.response_tool_calls, rc.response_thinking, rc.response_raw, rc.created_at
                        FROM request_contents rc
                        JOIN request_logs rl ON rl.id = rc.log_id AND rl.status = 'success'
                        WHERE rc.created_at >= :start AND rc.created_at < :end
                        ORDER BY rc.id
                        LIMIT :limit OFFSET :offset
                    """),
                    {
                        "start": dt_start,
                        "end": dt_end,
                        "limit": batch_size,
                        "offset": offset,
                    },
                )
                rows = result.fetchall()

            if not rows:
                break

            for row in rows:
                record = {
                    "id": row[0],
                    "log_id": row[1],
                    "request_messages": row[2],
                    "response_content": row[3],
                    "response_tool_calls": row[4],
                    "response_thinking": row[5],
                    "response_raw": row[6],
                    "created_at": row[7].isoformat() if row[7] else None,
                }
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                exported += 1

            offset += batch_size
            logger.info("[BACKUP] Exported %d rows for %s", exported, target_date_str)

    file_size = os.path.getsize(filename)
    logger.info("[BACKUP] Exported %d rows to %s (%.1f MB)", exported, filename, file_size / 1024 / 1024)

    if exported == 0:
        os.remove(filename)
        logger.info("[BACKUP] No data for %s, removed empty file", target_date_str)
        return {"date": target_date_str, "status": "empty", "exported": 0}

    deleted = 0
    async with async_session_maker() as session:
        result = await session.execute(
            text("""
                DELETE FROM request_contents
                WHERE created_at >= :start AND created_at < :end
            """),
            {
                "start": dt_start,
                "end": dt_end,
            },
        )
        deleted = result.rowcount or 0
        await session.commit()

    logger.info("[BACKUP] Deleted %d rows from request_contents for %s", deleted, target_date_str)
    return {"date": target_date_str, "status": "success", "exported": exported, "deleted": deleted, "file_size_mb": round(file_size / 1024 / 1024, 1)}
