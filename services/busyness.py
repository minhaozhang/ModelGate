from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from core.config import (
    active_requests,
    providers_cache,
    stats,
)


LEVEL_NAMES = {
    1: "extremely_busy",
    2: "very_busy",
    3: "busy",
    4: "normal",
    5: "idle",
    6: "quiet",
}

LEVEL_LABELS = {
    1: "兵荒马乱",
    2: "焦头烂额",
    3: "人声鼎沸",
    4: "畅通无阻",
    5: "门可罗雀",
    6: "万籁俱寂",
}

LEVEL_COLORS = {
    1: "red",
    2: "orange",
    3: "yellow",
    4: "green",
    5: "blue",
    6: "slate",
}

WINDOW_10MIN = timedelta(minutes=10)
WINDOW_1HOUR = timedelta(hours=1)


def _count_disabled_providers() -> int:
    count = 0
    for pconf in providers_cache.values():
        if pconf.get("disabled_reason"):
            count += 1
    return count


def _count_active_users_10min() -> int:
    cutoff = (datetime.now() - WINDOW_10MIN).strftime("%Y%m%d_%H%M%S")
    user_ids = set()
    for req_data in active_requests.values():
        started_at = req_data.get("started_at")
        if started_at:
            ts = started_at.strftime("%Y%m%d_%H%M%S") if isinstance(started_at, datetime) else str(started_at)[:19].replace("-", "").replace(":", "").replace(" ", "_")
            if ts >= cutoff:
                ak_id = req_data.get("api_key_id")
                if ak_id:
                    user_ids.add(ak_id)
    return len(user_ids)


def _calc_429_ratio_10min() -> float:
    now = datetime.now()
    cutoff = (now - WINDOW_10MIN).strftime("%Y%m%d_%H%M")
    total = sum(1 for key in stats.get("requests_per_minute", []) if key >= cutoff)
    rate_limited = sum(
        1 for key in stats.get("rate_limited_per_minute", []) if key >= cutoff
    )
    if total <= 0:
        return 0.0
    return rate_limited / total


def _has_recent_requests(window: timedelta) -> bool:
    cutoff = (datetime.now() - window).strftime("%Y%m%d_%H%M")
    for key in stats.get("requests_per_minute", []):
        if key >= cutoff:
            return True
    return False


def compute_busyness_level() -> dict[str, Any]:
    now = datetime.now()

    disabled_providers = _count_disabled_providers()
    active_users = _count_active_users_10min()
    ratio_429 = _calc_429_ratio_10min()
    has_active = len(active_requests) > 0
    has_10min = _has_recent_requests(WINDOW_10MIN)
    has_1hour = _has_recent_requests(WINDOW_1HOUR)

    busy_condition = active_users > 10 and ratio_429 > 0.5

    if busy_condition and disabled_providers >= 2:
        level = 1
    elif busy_condition and disabled_providers >= 1:
        level = 2
    elif busy_condition:
        level = 3
    elif has_active or has_10min:
        level = 4
    elif has_1hour:
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
        "has_active_requests": has_active,
        "has_recent_10min": has_10min,
        "has_recent_1hour": has_1hour,
        "computed_at": now.isoformat(),
    }
