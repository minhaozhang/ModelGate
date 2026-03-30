from typing import Optional
from sqlalchemy import select

from core.config import api_keys_cache
from core.database import async_session_maker, ApiKey, ApiKeyModel
from services.provider import parse_model, get_provider_config


async def load_api_keys():
    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.is_active == True))
        keys = result.scalars().all()

        api_keys_cache.clear()
        for k in keys:
            models_result = await session.execute(
                select(ApiKeyModel.provider_model_id).where(
                    ApiKeyModel.api_key_id == k.id
                )
            )
            model_ids = [row[0] for row in models_result.fetchall()]
            api_keys_cache[k.key] = {
                "id": k.id,
                "name": k.name,
                "allowed_provider_model_ids": model_ids,
            }


async def validate_api_key(
    auth_header: str, model: str
) -> tuple[Optional[int], Optional[str]]:
    if not auth_header:
        return None, "Missing API key"

    if auth_header.startswith("Bearer "):
        key = auth_header[7:]
    else:
        key = auth_header

    key_info = api_keys_cache.get(key)
    if not key_info:
        return None, "Invalid API key"

    allowed_models = key_info.get("allowed_provider_model_ids", [])

    if allowed_models:
        provider_name, actual_model = parse_model(model)

        if not provider_name:
            return key_info["id"], None

        provider_config = await get_provider_config(provider_name)
        if not provider_config:
            return None, f"Provider '{provider_name}' not found"

        provider_model_id = None
        for pm in provider_config.get("models", []):
            pm_model_name = pm.get("model_name")
            if (
                pm_model_name == actual_model
                or pm_model_name == actual_model.split("/")[-1]
            ):
                provider_model_id = pm["id"]
                break

        if provider_model_id is None:
            return (
                None,
                f"Model '{actual_model}' not found in provider '{provider_name}'",
            )

        if provider_model_id not in allowed_models:
            return None, f"API key not authorized for model '{model}'"

    return key_info["id"], None
