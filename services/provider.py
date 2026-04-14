import asyncio
from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy import select

import core.config as config

from core.config import (
    providers_cache,
    PROVIDERS_CACHE_TTL_MINUTES,
    logger,
    provider_semaphores,
)
from core.database import (
    async_session_maker,
    RequestLog,
    Provider,
    ProviderModel,
    Model,
)

SEMAPHORE_LIMIT_ATTR = "_modelgate_limit"
SEMAPHORE_PENDING_LIMIT_ATTR = "_modelgate_pending_limit"


def parse_model(model: str) -> tuple[str, str]:
    if "/" in model:
        parts = model.split("/", 1)
        return parts[0], parts[1]
    return "", model


def _build_semaphore(limit: int) -> asyncio.Semaphore:
    semaphore = asyncio.Semaphore(limit)
    setattr(semaphore, SEMAPHORE_LIMIT_ATTR, limit)
    return semaphore


def _get_semaphore_limit(
    semaphore: asyncio.Semaphore, fallback: int | None = None
) -> int | None:
    return getattr(semaphore, SEMAPHORE_LIMIT_ATTR, fallback)


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
            select(Provider).where(Provider.is_active == True)
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
                        "max_concurrent": pm.max_concurrent,
                    }
                )

            providers_cache[p.name] = {
                "id": p.id,
                "base_url": p.base_url,
                "api_key": p.api_key or "",
                "models": provider_models_data,
                "max_concurrent": p.max_concurrent or 3,
                "merge_consecutive_messages": p.merge_consecutive_messages or False,
            }

            provider_default = p.max_concurrent or 3
            for pm_data in provider_models_data:
                model_name = pm_data.get("model_name") or pm_data.get("actual_model_name")
                if not model_name:
                    continue
                sem_key = f"{p.name}/{model_name}"
                model_max = pm_data["max_concurrent"] or provider_default
                existing = provider_semaphores.get(sem_key)
                if existing is None:
                    provider_semaphores[sem_key] = _build_semaphore(model_max)
                    continue
                if _get_semaphore_limit(existing, model_max) == model_max:
                    if hasattr(existing, SEMAPHORE_PENDING_LIMIT_ATTR):
                        delattr(existing, SEMAPHORE_PENDING_LIMIT_ATTR)
                    continue
                waiters = getattr(existing, "_waiters", None)
                has_waiters = bool(waiters)
                current_limit = _get_semaphore_limit(existing, model_max) or model_max
                available = getattr(existing, "_value", current_limit)
                in_flight = max(current_limit - available, 0)
                if in_flight == 0 and not has_waiters:
                    provider_semaphores[sem_key] = _build_semaphore(model_max)
                    continue
                pending_limit = getattr(existing, SEMAPHORE_PENDING_LIMIT_ATTR, None)
                if pending_limit != model_max:
                    setattr(existing, SEMAPHORE_PENDING_LIMIT_ATTR, model_max)
                    logger.info(
                        "[SEMAPHORE] Deferring resize for %s from %s to %s while %s request(s) are active",
                        sem_key,
                        current_limit,
                        model_max,
                        in_flight,
                    )

        config.providers_cache_time = datetime.now()


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


def get_semaphore_key(provider_name: str, actual_model: str, provider_config: dict) -> str:
    model_cfg = get_model_config(provider_config, actual_model)
    model_name = model_cfg.get("model_name") or model_cfg.get("actual_model_name") if model_cfg else None
    if model_name:
        return f"{provider_name}/{model_name}"
    return f"{provider_name}/{actual_model}"


def get_or_create_provider_semaphore(
    provider_name: str, actual_model: str, provider_config: dict
) -> tuple[str, asyncio.Semaphore]:
    sem_key = get_semaphore_key(provider_name, actual_model, provider_config)
    model_cfg = get_model_config(provider_config, actual_model)
    target_limit = (
        model_cfg.get("max_concurrent") if model_cfg else None
    ) or provider_config.get("max_concurrent", 3)
    existing = provider_semaphores.get(sem_key)
    if existing is None:
        semaphore = _build_semaphore(target_limit)
        provider_semaphores[sem_key] = semaphore
        return sem_key, semaphore

    current_limit = _get_semaphore_limit(existing, target_limit) or target_limit
    if current_limit == target_limit:
        if hasattr(existing, SEMAPHORE_PENDING_LIMIT_ATTR):
            delattr(existing, SEMAPHORE_PENDING_LIMIT_ATTR)
        return sem_key, existing

    waiters = getattr(existing, "_waiters", None)
    has_waiters = bool(waiters)
    available = getattr(existing, "_value", current_limit)
    in_flight = max(current_limit - available, 0)
    if in_flight == 0 and not has_waiters:
        semaphore = _build_semaphore(target_limit)
        provider_semaphores[sem_key] = semaphore
        logger.info(
            "[SEMAPHORE] Resized %s from %s to %s",
            sem_key,
            current_limit,
            target_limit,
        )
        return sem_key, semaphore

    pending_limit = getattr(existing, SEMAPHORE_PENDING_LIMIT_ATTR, None)
    if pending_limit != target_limit:
        setattr(existing, SEMAPHORE_PENDING_LIMIT_ATTR, target_limit)
        logger.info(
            "[SEMAPHORE] Deferring resize for %s from %s to %s while %s request(s) are active",
            sem_key,
            current_limit,
            target_limit,
            in_flight,
        )
    return sem_key, existing


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
