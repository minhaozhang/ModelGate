import asyncio

import core.config as config
from core.config import provider_key_model_semaphores, provider_key_semaphores

DEFAULT_PROVIDER_KEY_MAX_CONCURRENCY = 3
DEFAULT_PROVIDER_KEY_MODEL_MAX_CONCURRENCY = 1
SEMAPHORE_RETRY_AFTER_SECONDS = 5
SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS = 1
RATE_LIMITED_STATUS = "rate_limited"
LOCAL_RATE_LIMITED_STATUS = "local_rate_limited"
RATE_LIMITED_STATUSES = {RATE_LIMITED_STATUS, LOCAL_RATE_LIMITED_STATUS}
SCOPED_SEMAPHORE_LIMIT_ATTR = "_modelgate_scoped_limit"


def _get_or_create_scoped_semaphore(
    semaphore_store: dict[str, asyncio.Semaphore],
    sem_key: str,
    target_limit: int,
) -> tuple[str, asyncio.Semaphore]:
    if target_limit < 1:
        target_limit = 1
    semaphore = semaphore_store.get(sem_key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(target_limit)
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
        semaphore = asyncio.Semaphore(target_limit)
        setattr(semaphore, SCOPED_SEMAPHORE_LIMIT_ATTR, target_limit)
        semaphore_store[sem_key] = semaphore
        return sem_key, semaphore
    return sem_key, semaphore


def _get_provider_key_model_limit() -> int:
    try:
        target_limit = int(
            config.system_config.get("api_key_model_max_concurrency")
            or DEFAULT_PROVIDER_KEY_MODEL_MAX_CONCURRENCY
        )
    except (TypeError, ValueError):
        target_limit = DEFAULT_PROVIDER_KEY_MODEL_MAX_CONCURRENCY
    return max(target_limit, 1)


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
        target_limit = int(target_limit or DEFAULT_PROVIDER_KEY_MAX_CONCURRENCY)
    except (TypeError, ValueError):
        target_limit = DEFAULT_PROVIDER_KEY_MAX_CONCURRENCY
    return max(target_limit, 1)


def _get_or_create_provider_key_model_semaphore(
    provider_key_id: int, provider_model_key: str, target_limit: int
) -> tuple[str, asyncio.Semaphore]:
    sem_key = f"{provider_key_id}:{provider_model_key}"
    return _get_or_create_scoped_semaphore(
        provider_key_model_semaphores, sem_key, target_limit
    )


def _get_or_create_provider_key_semaphore(
    provider_key_id: int, provider_name: str, target_limit: int
) -> tuple[str, asyncio.Semaphore]:
    sem_key = f"{provider_key_id}:{provider_name}"
    return _get_or_create_scoped_semaphore(
        provider_key_semaphores, sem_key, target_limit
    )
