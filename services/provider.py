import asyncio
from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy import select

from core.config import (
    providers_cache,
    providers_cache_time,
    PROVIDERS_CACHE_TTL_MINUTES,
    logger,
    provider_semaphores,
)
from core.database import async_session_maker, RequestLog, Provider, ProviderModel, Model


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

            max_conc = p.max_concurrent or 3
            existing = provider_semaphores.get(p.name)
            if existing is None or getattr(existing, "_value", None) != max_conc:
                provider_semaphores[p.name] = asyncio.Semaphore(max_conc)

        import core.config as config

        config.providers_cache_time = datetime.now()


async def get_provider_config(provider_name: str) -> Optional[dict]:
    if providers_cache_time is None or (
        datetime.now() - providers_cache_time
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
