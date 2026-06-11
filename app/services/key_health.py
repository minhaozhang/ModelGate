import time
import threading
from dataclasses import dataclass


@dataclass
class KeyEvent:
    timestamp: float
    event_type: str
    status_code: int = 0


_key_events: dict[int, list[KeyEvent]] = {}
_lock = threading.Lock()

WINDOW_SECONDS = 300
BASE_SCORE = 100
DEDUCT_RATE_LIMIT = 15
DEDUCT_SERVER_ERROR = 10
DEDUCT_CLIENT_ERROR = 5
BONUS_SUCCESS_PER = 10
BONUS_SUCCESS_POINTS = 5
REENABLE_SCORE = 60


def record_key_event(key_id: int, event_type: str, status_code: int = 0) -> None:
    with _lock:
        if key_id not in _key_events:
            _key_events[key_id] = []
        _key_events[key_id].append(
            KeyEvent(timestamp=time.monotonic(), event_type=event_type, status_code=status_code)
        )


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
        elif e.event_type == "success":
            success_count += 1

    if disabled_count > 0:
        return 0

    deductions = (
        rate_limited_count * DEDUCT_RATE_LIMIT
        + server_error_count * DEDUCT_SERVER_ERROR
        + client_error_count * DEDUCT_CLIENT_ERROR
    )
    bonus = (success_count // BONUS_SUCCESS_PER) * BONUS_SUCCESS_POINTS
    return max(0, min(BASE_SCORE, BASE_SCORE - deductions + bonus))


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

    counts = {"success": 0, "rate_limited": 0, "server_error": 0, "client_error": 0}
    for e in recent:
        if e.event_type == "success":
            counts["success"] += 1
        elif e.event_type == "error_429":
            counts["rate_limited"] += 1
        elif e.event_type == "error_5xx":
            counts["server_error"] += 1
        elif e.event_type == "error_4xx":
            counts["client_error"] += 1
    return counts


def on_key_reenabled(key_id: int) -> None:
    with _lock:
        events = _key_events.get(key_id, [])
        now = time.monotonic()
        _key_events[key_id] = [e for e in events if e.event_type != "disabled" and e.timestamp >= now - WINDOW_SECONDS]


def clear_all() -> None:
    with _lock:
        _key_events.clear()
