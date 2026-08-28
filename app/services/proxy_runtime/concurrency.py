import asyncio
import os

from app.core.config import (
    provider_key_model_semaphores,
    provider_key_semaphores,
    standard_model_semaphores,
    user_api_key_semaphores,
)

DEFAULT_PROVIDER_KEY_MAX_CONCURRENCY = 3
DEFAULT_USER_API_KEY_MAX_CONCURRENCY = 1
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
