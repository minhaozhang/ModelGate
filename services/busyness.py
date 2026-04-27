from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from core.config import providers_cache


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


def _count_disabled_providers() -> int:
    count = 0
    for pconf in providers_cache.values():
        if pconf.get("disabled_reason"):
            count += 1
    return count


async def compute_busyness_level() -> dict[str, Any]:
    from core.database import async_session_maker, RequestLog
    from sqlalchemy import select, func, distinct
    from services.system_config import get_int_setting, get_float_setting

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

    disabled_providers = _count_disabled_providers()
    ratio_429 = rate_limited_10min / total_10min if total_10min > 0 else 0.0

    active_threshold = await get_int_setting("busyness", "active_users_threshold", 10)
    rate_threshold = await get_float_setting("busyness", "rate_429_threshold", 0.5)
    critical_disabled = await get_int_setting("busyness", "disabled_providers_critical", 2)
    busy_disabled = await get_int_setting("busyness", "disabled_providers_busy", 1)

    busy_condition = active_users > active_threshold and ratio_429 > rate_threshold

    if busy_condition and disabled_providers >= critical_disabled:
        level = 1
    elif busy_condition and disabled_providers >= busy_disabled:
        level = 2
    elif busy_condition:
        level = 3
    elif total_10min > 0:
        level = 4
    elif has_1hour > 0:
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
