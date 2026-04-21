import random
import time
from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy import select

import core.config as config

from core.config import (
    providers_cache,
    PROVIDERS_CACHE_TTL_MINUTES,
    logger,
    provider_key_semaphores,
)
from core.database import (
    async_session_maker,
    Provider,
    ProviderKey,
    ProviderModel,
    Model,
)

KEY_STICKY_TTL_SECONDS = 1800
_key_sticky_map: dict[tuple[int, str], tuple[int, float]] = {}


async def _load_provider_keys(session, provider_id: int) -> list[dict]:
    result = await session.execute(
        select(ProviderKey).where(
            ProviderKey.provider_id == provider_id,
            ProviderKey.is_active == True,  # noqa: E712
        )
    )
    return [
        {
            "id": pk.id,
            "api_key": pk.api_key,
            "label": pk.label or "",
            "max_concurrent": pk.max_concurrent,
        }
        for pk in result.scalars().all()
    ]


def pick_api_key(
    provider_config: dict, api_key_id: int | None, provider_name: str
) -> tuple[str | None, int | None]:
    keys = provider_config.get("api_keys") or []
    if not keys:
        fallback = provider_config.get("api_key") or ""
        if fallback:
            return fallback, None
        return None, None
    if api_key_id is not None:
        sticky = _key_sticky_map.get((api_key_id, provider_name))
        if sticky:
            key_id, ts = sticky
            if time.monotonic() - ts < KEY_STICKY_TTL_SECONDS:
                for k in keys:
                    if k["id"] == key_id:
                        return k["api_key"], k["id"]
    chosen = random.choice(keys)
    if api_key_id is not None:
        _key_sticky_map[(api_key_id, provider_name)] = (chosen["id"], time.monotonic())
    return chosen["api_key"], chosen["id"]


async def invalidate_provider_key_sticky_cache(
    provider_name: str,
    provider_key_id: int,
) -> None:
    stale_keys = [
        sticky_key
        for sticky_key, sticky_value in _key_sticky_map.items()
        if sticky_key[1] == provider_name and sticky_value[0] == provider_key_id
    ]
    for sticky_key in stale_keys:
        _key_sticky_map.pop(sticky_key, None)


def parse_model(model: str) -> tuple[str, str]:
    if "/" in model:
        parts = model.split("/", 1)
        return parts[0], parts[1]
    return "", model


def _get_model_aliases(pm: dict) -> set[str]:
    aliases: set[str] = set()
    for value in (pm.get("model_name"), pm.get("actual_model_name")):
        if not value:
            continue
        aliases.add(value)
        aliases.add(value.split("/")[-1])
    return aliases


async def load_providers():
    async with async_session_maker() as session:
        result = await session.execute(
            select(Provider).where(Provider.is_active == True)  # noqa: E712
        )
        providers = result.scalars().all()

        providers_cache.clear()
        for p in providers:
            pm_result = await session.execute(
                select(ProviderModel, Model)
                .where(
                    ProviderModel.provider_id == p.id,
                    ProviderModel.is_active == True,
                )
                .join(Model, ProviderModel.model_id == Model.id)
            )
            provider_models_data = []
            for pm, model in pm_result.all():
                provider_models_data.append(
                    {
                        "id": pm.id,
                        "model_name": pm.model_name_override
                        or (model.display_name if model else None),
                        "actual_model_name": model.name if model else None,
                        "is_multimodal": model.is_multimodal if model else False,
                        "max_tokens": model.max_tokens if model else 16384,
                        "thinking_enabled": model.thinking_enabled if model else False,
                        "thinking_budget": model.thinking_budget if model else 8192,
                    }
                )

            providers_cache[p.name] = {
                "id": p.id,
                "base_url": p.base_url,
                "api_key": p.api_key or "",
                "models": provider_models_data,
                "merge_consecutive_messages": p.merge_consecutive_messages or False,
                "disabled_reason": p.disabled_reason,
                "api_keys": await _load_provider_keys(session, p.id),
            }

        config.providers_cache_time = datetime.now()

    # Drop idle semaphores for removed/deactivated provider keys after cache refresh.
    active_provider_key_prefixes = {
        f"{pk['id']}:{provider_name}"
        for provider_name, provider_config in providers_cache.items()
        for pk in provider_config.get("api_keys", [])
        if pk.get("id") is not None
    }
    for sem_key in list(provider_key_semaphores.keys()):
        if sem_key in active_provider_key_prefixes:
            continue
        semaphore = provider_key_semaphores.get(sem_key)
        if semaphore is None:
            continue
        waiters = getattr(semaphore, "_waiters", None)
        available = getattr(semaphore, "_value", 0)
        current_limit = getattr(semaphore, "_modelgate_scoped_limit", available) or available
        in_flight = max(current_limit - available, 0)
        if in_flight == 0 and not waiters:
            provider_key_semaphores.pop(sem_key, None)


async def get_provider_config(provider_name: str) -> Optional[dict]:
    if config.providers_cache_time is None or (
        datetime.now() - config.providers_cache_time
    ) > timedelta(minutes=PROVIDERS_CACHE_TTL_MINUTES):
        await load_providers()
    return providers_cache.get(provider_name)


def get_model_config(provider_config: dict, model_name: str) -> Optional[dict]:
    if not provider_config:
        return None
    requested_names = {model_name, model_name.split("/")[-1]}
    for pm in provider_config.get("models", []):
        if requested_names & _get_model_aliases(pm):
            return pm
    return None

async def get_provider_and_model(model: str) -> tuple[Optional[dict], str, str]:
    provider_name, actual_model = parse_model(model)
    if not provider_name:
        if providers_cache:
            provider_name = list(providers_cache.keys())[0]
            logger.debug("[PROXY] No provider prefix, using default: %s", provider_name)
        else:
            return None, model, ""
    config = await get_provider_config(provider_name)
    return config, actual_model, provider_name


async def get_disabled_provider_reason(provider_name: str) -> str | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Provider.disabled_reason).where(
                Provider.name == provider_name,
                Provider.is_active == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()
