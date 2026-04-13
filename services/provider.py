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


def parse_model(model: str) -> tuple[str, str]:
    if "/" in model:
        parts = model.split("/", 1)
        return parts[0], parts[1]
    return "", model


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
                if existing is None or getattr(existing, "_value", None) != model_max:
                    provider_semaphores[sem_key] = asyncio.Semaphore(model_max)

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
    for pm in provider_config.get("models", []):
        pm_model_name = pm.get("model_name")
        if pm_model_name == model_name or pm_model_name == model_name.split("/")[-1]:
            return pm
    return None


def get_semaphore_key(provider_name: str, actual_model: str, provider_config: dict) -> str:
    model_cfg = get_model_config(provider_config, actual_model)
    model_name = model_cfg.get("model_name") or model_cfg.get("actual_model_name") if model_cfg else None
    if model_name:
        return f"{provider_name}/{model_name}"
    return f"{provider_name}/{actual_model}"


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
