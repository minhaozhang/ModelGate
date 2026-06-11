from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.core.config import providers_cache


LEVEL_NAMES = {
    1: "extremely_busy",
    2: "very_busy",
    3: "busy",
    4: "normal",
    5: "idle",
    6: "quiet",
}

LEVEL_LABELS = {
    1: "过载",
    2: "拥挤",
    3: "活跃",
    4: "流畅",
    5: "平静",
    6: "寂静",
}

LEVEL_COLORS = {
    1: "red",
    2: "orange",
    3: "yellow",
    4: "green",
    5: "blue",
    6: "slate",
}


async def _count_disabled_providers(session=None) -> int:
    from app.core.database import async_session_maker, Provider
    from sqlalchemy import select, func

    async def _query(s):
        return (await s.execute(
            select(func.count()).select_from(Provider).where(
                Provider.disabled_reason.isnot(None),
                Provider.disabled_reason != "",
            )
        )).scalar() or 0

    if session:
        return await _query(session)
    async with async_session_maker() as s:
        return await _query(s)


async def compute_busyness_level() -> dict[str, Any]:
    from app.core.database import async_session_maker, RequestLog
    from sqlalchemy import select, func, distinct
    from app.services.system_config import get_int_setting, get_float_setting

    now = datetime.now()
    current_10min_slot = now.replace(minute=(now.minute // 10) * 10, second=0, microsecond=0)
    cutoff_10min = current_10min_slot - timedelta(minutes=10)
    end_10min = current_10min_slot
    cutoff_1hour = current_10min_slot - timedelta(hours=1)

    async with async_session_maker() as session:
        active_users = (await session.execute(
            select(func.count(distinct(RequestLog.api_key_id)))
            .where(RequestLog.created_at >= cutoff_10min, RequestLog.created_at < end_10min, RequestLog.api_key_id.isnot(None))
        )).scalar() or 0
        total_10min = (await session.execute(
            select(func.count()).where(RequestLog.created_at >= cutoff_10min, RequestLog.created_at < end_10min)
        )).scalar() or 0
        rate_limited_10min = (await session.execute(
            select(func.count()).where(RequestLog.created_at >= cutoff_10min, RequestLog.created_at < end_10min, RequestLog.downstream_status_code == 429)
        )).scalar() or 0
        has_1hour = (await session.execute(
            select(func.count()).where(RequestLog.created_at >= cutoff_1hour).limit(1)
        )).scalar() or 0

        disabled_providers = await _count_disabled_providers(session)
    ratio_429 = rate_limited_10min / total_10min if total_10min > 0 else 0.0

    active_threshold_1 = await get_int_setting("busyness", "level1_active_users_threshold", 10)
    rate_threshold_1 = await get_float_setting("busyness", "level1_rate_429_threshold", 0.5)
    disabled_critical_1 = await get_int_setting("busyness", "level1_disabled_providers", 2)
    active_threshold_2 = await get_int_setting("busyness", "level2_active_users_threshold", 8)
    rate_threshold_2 = await get_float_setting("busyness", "level2_rate_429_threshold", 0.3)
    disabled_critical_2 = await get_int_setting("busyness", "level2_disabled_providers", 1)
    active_threshold_3 = await get_int_setting("busyness", "level3_active_users_threshold", 5)
    rate_threshold_3 = await get_float_setting("busyness", "level3_rate_429_threshold", 0.1)
    active_threshold_4 = await get_int_setting("busyness", "level4_active_users_threshold", 1)

    if active_users > active_threshold_1 and ratio_429 > rate_threshold_1 and disabled_providers >= disabled_critical_1:
        level = 1
    elif active_users > active_threshold_2 and ratio_429 > rate_threshold_2 and disabled_providers >= disabled_critical_2:
        level = 2
    elif active_users > active_threshold_3 and ratio_429 > rate_threshold_3:
        level = 3
    elif active_users > active_threshold_4 and total_10min > 0:
        level = 4
    elif total_10min > 0 or has_1hour > 0:
        level = 5
    else:
        level = 6

    return {
        "level": level,
        "name": LEVEL_NAMES[level],
        "label": LEVEL_LABELS[level],
        "color": LEVEL_COLORS[level],
        "disabled_providers": disabled_providers,
        "active_users_10min": active_users,
        "rate_429_ratio": round(ratio_429, 4),
        "computed_at": now.isoformat(),
    }
