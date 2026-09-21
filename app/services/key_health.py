import time
import asyncio
import threading
from dataclasses import dataclass


@dataclass
class KeyEvent:
    timestamp: float
    event_type: str
    status_code: int = 0


_key_events: dict[int, list[KeyEvent]] = {}
_health_disable_inflight: set[int] = set()
_lock = threading.Lock()

FAILURE_EVENT_TYPES = ("error_429", "error_5xx", "error_4xx", "timeout", "connect_error")
HEALTH_DISABLE_REASON = "健康分归零：5分钟内连续失败，自动禁用"
HEALTH_AUTO_RECOVER_MINUTES = 65

WINDOW_SECONDS = 300
BASE_SCORE = 100
DEDUCT_RATE_LIMIT = 5
DEDUCT_SERVER_ERROR = 10
DEDUCT_CLIENT_ERROR = 5
DEDUCT_TIMEOUT = 10
DEDUCT_CONNECT_ERROR = 10
BONUS_SUCCESS_PER = 10
BONUS_SUCCESS_POINTS = 5
REENABLE_SCORE = 60
RATE_LIMIT_FLOOR = 20


def record_key_event(key_id: int, event_type: str, status_code: int = 0) -> None:
    with _lock:
        if key_id not in _key_events:
            _key_events[key_id] = []
        _key_events[key_id].append(
            KeyEvent(timestamp=time.monotonic(), event_type=event_type, status_code=status_code)
        )
    if event_type in FAILURE_EVENT_TYPES:
        _maybe_schedule_health_disable(key_id)


def _maybe_schedule_health_disable(key_id: int) -> None:
    """When a key's score drops to 0, auto-disable it (fire-and-forget task)."""
    try:
        if compute_health_score(key_id) > 0:
            return
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_auto_disable_unhealthy_key(key_id))


async def _auto_disable_unhealthy_key(key_id: int) -> None:
    if key_id in _health_disable_inflight:
        return
    _health_disable_inflight.add(key_id)
    try:
        from datetime import datetime, timedelta

        from app.core.config import providers_cache, proxy_logger
        from app.services.provider_limiter import disable_provider_key

        for provider_name, provider_config in (providers_cache or {}).items():
            keys = (provider_config or {}).get("api_keys") or []
            if not any(k.get("id") == key_id for k in keys):
                continue
            recover_at = datetime.now() + timedelta(
                minutes=HEALTH_AUTO_RECOVER_MINUTES
            )
            reason = (
                f"{HEALTH_DISABLE_REASON}"
                f"（预计 {recover_at:%Y-%m-%d %H:%M:%S} 自动恢复）"
            )
            proxy_logger.warning(
                "[KEY HEALTH] key id=%s score hit 0, auto-disabling (provider=%s)",
                key_id,
                provider_name,
            )
            await disable_provider_key(provider_name, provider_config, key_id, reason)
            return
    except Exception:
        try:
            from app.core.config import proxy_logger

            proxy_logger.exception(
                "[KEY HEALTH] auto-disable failed for key id=%s", key_id
            )
        except Exception:
            pass
    finally:
        _health_disable_inflight.discard(key_id)


def compute_health_score(key_id: int, is_active: bool = True) -> int:
    if not is_active:
        return 0

    with _lock:
        events = _key_events.get(key_id, [])
        now = time.monotonic()
        cutoff = now - WINDOW_SECONDS
        recent = [e for e in events if e.timestamp >= cutoff]
        _key_events[key_id] = recent

    disabled_count = 0
    rate_limited_count = 0
    server_error_count = 0
    client_error_count = 0
    timeout_count = 0
    connect_error_count = 0
    success_count = 0

    for e in recent:
        if e.event_type == "disabled":
            disabled_count += 1
        elif e.event_type == "error_429":
            rate_limited_count += 1
        elif e.event_type == "error_5xx":
            server_error_count += 1
        elif e.event_type == "error_4xx":
            client_error_count += 1
        elif e.event_type == "timeout":
            timeout_count += 1
        elif e.event_type == "connect_error":
            connect_error_count += 1
        elif e.event_type == "success":
            success_count += 1

    if disabled_count > 0:
        return 0

    other_deductions = (
        server_error_count * DEDUCT_SERVER_ERROR
        + client_error_count * DEDUCT_CLIENT_ERROR
        + timeout_count * DEDUCT_TIMEOUT
        + connect_error_count * DEDUCT_CONNECT_ERROR
    )
    bonus = (success_count // BONUS_SUCCESS_PER) * BONUS_SUCCESS_POINTS
    score_before_429 = max(0, min(BASE_SCORE, BASE_SCORE - other_deductions + bonus))
    rate_deduction = min(
        rate_limited_count * DEDUCT_RATE_LIMIT,
        max(0, score_before_429 - RATE_LIMIT_FLOOR),
    )
    return max(0, min(BASE_SCORE, score_before_429 - rate_deduction))


def get_health_level(score: int) -> str:
    if score >= 90:
        return "excellent"
    if score >= 60:
        return "good"
    if score >= 30:
        return "warning"
    if score > 0:
        return "critical"
    return "unavailable"


def get_events_5m(key_id: int) -> dict[str, int]:
    with _lock:
        events = _key_events.get(key_id, [])
        now = time.monotonic()
        cutoff = now - WINDOW_SECONDS
        recent = [e for e in events if e.timestamp >= cutoff]

    counts = {
        "success": 0,
        "rate_limited": 0,
        "server_error": 0,
        "client_error": 0,
        "timeout": 0,
        "connect_error": 0,
    }
    for e in recent:
        if e.event_type == "success":
            counts["success"] += 1
        elif e.event_type == "error_429":
            counts["rate_limited"] += 1
        elif e.event_type == "error_5xx":
            counts["server_error"] += 1
        elif e.event_type == "error_4xx":
            counts["client_error"] += 1
        elif e.event_type == "timeout":
            counts["timeout"] += 1
        elif e.event_type == "connect_error":
            counts["connect_error"] += 1
    return counts


def on_key_reenabled(key_id: int) -> None:
    with _lock:
        events = _key_events.get(key_id, [])
        now = time.monotonic()
        _key_events[key_id] = [e for e in events if e.event_type != "disabled" and e.timestamp >= now - WINDOW_SECONDS]


def clear_all() -> None:
    with _lock:
        _key_events.clear()
