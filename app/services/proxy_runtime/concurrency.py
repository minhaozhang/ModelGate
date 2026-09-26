import asyncio
import os
from datetime import datetime

from app.core.config import (
    provider_key_model_semaphores,
    provider_key_semaphores,
    standard_model_semaphores,
    user_api_key_semaphores,
    user_model_semaphores,
)

DEFAULT_PROVIDER_KEY_MAX_CONCURRENCY = 3
DEFAULT_USER_API_KEY_MAX_CONCURRENCY = 1
DEFAULT_USER_MODEL_CONCURRENCY = 2
SEMAPHORE_RETRY_AFTER_SECONDS = 5


def _env_timeout(default: float) -> float:
    try:
        return float(os.getenv("MODELGATE_SEMAPHORE_ACQUIRE_TIMEOUT", "") or default)
    except ValueError:
        return default


# Queue behind in-flight streams instead of fast-failing: thinking-model
# streams hold concurrency slots for minutes, so a short acquire timeout
# rejects (and eventually kills) agent retries that would otherwise just wait.
USER_PROVIDER_MODEL_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS = _env_timeout(10.0)
SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS = USER_PROVIDER_MODEL_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS
# Cap how many requests may sit in a semaphore queue: once waiters exceed
# limit * FACTOR, extra requests fail fast instead of piling up connections.
SEMAPHORE_MAX_WAITERS_FACTOR = 2
RATE_LIMITED_STATUS = "rate_limited"
LOCAL_RATE_LIMITED_STATUS = "local_rate_limited"
RATE_LIMITED_STATUSES = {RATE_LIMITED_STATUS, LOCAL_RATE_LIMITED_STATUS}
SCOPED_SEMAPHORE_LIMIT_ATTR = "_modelgate_scoped_limit"


class _ScopedSemaphore(asyncio.Semaphore):
    def release(self) -> None:
        super().release()
        target_limit = getattr(self, SCOPED_SEMAPHORE_LIMIT_ATTR, None)
        if target_limit is not None and getattr(self, "_value", 0) > target_limit:
            self._value = target_limit


async def acquire_scoped_semaphore(semaphore: asyncio.Semaphore, timeout: float) -> None:
    """Acquire with timeout; raise asyncio.TimeoutError on timeout OR when the
    queue is already saturated, so callers reuse their existing 429 path."""
    if getattr(semaphore, SCOPED_SEMAPHORE_LIMIT_ATTR, None) == 0:
        # Explicit zero concurrency: reject immediately instead of queueing
        # behind a slot that can never open.
        raise asyncio.TimeoutError
    waiters = getattr(semaphore, "_waiters", None)
    if waiters:
        limit = getattr(semaphore, SCOPED_SEMAPHORE_LIMIT_ATTR, 0) or 0
        max_waiters = max(limit, 1) * SEMAPHORE_MAX_WAITERS_FACTOR
        if len(waiters) >= max_waiters:
            raise asyncio.TimeoutError
    await asyncio.wait_for(semaphore.acquire(), timeout=timeout)


def _get_or_create_scoped_semaphore(
    semaphore_store: dict[str, asyncio.Semaphore],
    sem_key: str,
    target_limit: int,
) -> tuple[str, asyncio.Semaphore]:
    if target_limit < 0:
        target_limit = 0
    semaphore = semaphore_store.get(sem_key)
    if semaphore is None:
        semaphore = _ScopedSemaphore(target_limit)
        setattr(semaphore, SCOPED_SEMAPHORE_LIMIT_ATTR, target_limit)
        semaphore_store[sem_key] = semaphore
        return sem_key, semaphore
    current_limit = getattr(semaphore, SCOPED_SEMAPHORE_LIMIT_ATTR, target_limit)
    if current_limit == target_limit:
        return sem_key, semaphore
    available = getattr(semaphore, "_value", current_limit)
    in_flight = max(current_limit - available, 0)
    waiters = getattr(semaphore, "_waiters", None)
    has_waiters = bool(waiters)
    if in_flight == 0 and not has_waiters:
        semaphore = _ScopedSemaphore(target_limit)
        setattr(semaphore, SCOPED_SEMAPHORE_LIMIT_ATTR, target_limit)
        semaphore_store[sem_key] = semaphore
        return sem_key, semaphore
    setattr(semaphore, SCOPED_SEMAPHORE_LIMIT_ATTR, target_limit)
    semaphore._value = max(target_limit - in_flight, 0)
    return sem_key, semaphore


def _get_user_provider_model_limit(bypass_busyness: bool = False) -> int:
    if bypass_busyness:
        return 9999
    from app.core.config import busyness_state
    level = busyness_state.get("level", 6)
    if level >= 5:
        target_limit = 3
    elif level == 4:
        target_limit = 2
    else:
        target_limit = 1
    return max(target_limit, 1)


def _get_user_api_key_limit(
    bypass_busyness: bool = False, stored_limit: int | None = None
) -> int:
    if bypass_busyness:
        return 9999
    try:
        parsed = int(stored_limit)
    except (TypeError, ValueError):
        return DEFAULT_USER_API_KEY_MAX_CONCURRENCY
    if parsed < 0:
        # Negative values are meaningless; treat like unset.
        return DEFAULT_USER_API_KEY_MAX_CONCURRENCY
    # NULL/invalid -> default; explicit 0 -> zero concurrency (key disabled
    # for new requests).
    return parsed


def _get_provider_key_limit(
    provider_config: dict, provider_key_id: int | None = None
) -> int:
    target_limit = None
    if provider_key_id is not None:
        for provider_key in provider_config.get("api_keys") or []:
            if provider_key.get("id") == provider_key_id:
                target_limit = provider_key.get("max_concurrent")
                break
    try:
        parsed = int(target_limit)
    except (TypeError, ValueError):
        return DEFAULT_PROVIDER_KEY_MAX_CONCURRENCY
    if parsed < 0:
        # Negative values are meaningless; treat like unset.
        return DEFAULT_PROVIDER_KEY_MAX_CONCURRENCY
    # NULL/invalid -> default; explicit 0 -> zero concurrency (key disabled
    # for new requests).
    return parsed


def _get_or_create_user_api_key_semaphore(
    api_key_id: int, target_limit: int
) -> tuple[str, asyncio.Semaphore]:
    sem_key = f"user:{api_key_id}"
    return _get_or_create_scoped_semaphore(
        user_api_key_semaphores, sem_key, target_limit
    )


def _get_or_create_user_model_semaphore(
    api_key_id: int, model: str, target_limit: int
) -> tuple[str, asyncio.Semaphore]:
    sem_key = f"usermodel:{api_key_id}:{model}"
    return _get_or_create_scoped_semaphore(
        user_model_semaphores, sem_key, target_limit
    )


def _model_gauge_cap(model: str) -> int:
    """Per-user-per-model cap derived from the model's total
    concurrency gauge (stdmodel semaphore): how many slots a single
    user key may take while the model still has headroom."""
    sem = standard_model_semaphores.get(f"stdmodel:{model}")
    if sem is None:
        # Model has no total concurrency cap — treat as idle.
        return DEFAULT_USER_MODEL_CONCURRENCY
    limit = getattr(sem, SCOPED_SEMAPHORE_LIMIT_ATTR, 0) or 0
    if limit <= 0:
        return DEFAULT_USER_MODEL_CONCURRENCY
    available = getattr(sem, "_value", 0) or 0
    waiters = getattr(sem, "_waiters", None)
    if waiters or available <= 0:
        return 1
    if available / limit >= 0.5:
        return 2
    return 1


def _time_cap(now: datetime | None = None) -> int:
    """Time-window cap: off-peak hours (default 20:00-11:00) are tighter —
    background hammering off-hours is abnormal."""
    import app.core.config as config

    def _int(key: str, default: int) -> int:
        try:
            return int(config.system_settings.get(key) or default)
        except (TypeError, ValueError):
            return default

    start = _int("concurrency.offpeak_start_hour", 20)
    end = _int("concurrency.offpeak_end_hour", 11)
    peak = _int("concurrency.peak_user_model_limit", 2)
    off = _int("concurrency.offpeak_user_model_limit", 1)
    hour = (now or datetime.now()).hour
    if start == end:
        return peak
    offpeak = hour >= start or hour < end
    return off if offpeak else peak


def _get_user_model_limit(
    bypass_busyness: bool,
    model: str,
    now: datetime | None = None,
    model_cfg=None,
) -> int:
    if bypass_busyness:
        return 9999
    # 1) Model-level fixed cap (per_key_concurrency: 0 disables, >=1 cap).
    if model_cfg is not None:
        try:
            return max(int(model_cfg), 0)
        except (TypeError, ValueError):
            pass
    # 2) Dynamic: model gauge headroom x time window.
    return max(min(_model_gauge_cap(model), _time_cap(now)), 0)


def _get_or_create_user_provider_model_semaphore(
    api_key_id: int, provider_key_id: int, provider_model_key: str, target_limit: int
) -> tuple[str, asyncio.Semaphore]:
    sem_key = f"user:{api_key_id}:pk:{provider_key_id}:model:{provider_model_key}"
    return _get_or_create_scoped_semaphore(
        provider_key_model_semaphores, sem_key, target_limit
    )


def _get_or_create_standard_model_semaphore(
    model_name: str, target_limit: int
) -> tuple[str, asyncio.Semaphore]:
    sem_key = f"stdmodel:{model_name}"
    return _get_or_create_scoped_semaphore(
        standard_model_semaphores, sem_key, target_limit
    )


def _get_or_create_provider_key_semaphore(
    provider_key_id: int, provider_name: str, target_limit: int
) -> tuple[str, asyncio.Semaphore]:
    sem_key = f"{provider_key_id}:{provider_name}"
    return _get_or_create_scoped_semaphore(
        provider_key_semaphores, sem_key, target_limit
    )
