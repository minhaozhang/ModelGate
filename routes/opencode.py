import json
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from core.app_paths import get_app_base_path
from core.database import (
    ApiKey,
    ApiKeyModel,
    Model,
    Provider,
    ProviderModel,
    async_session_maker,
)

router = APIRouter(tags=["docs"])


async def build_opencode_config(session, api_key: str, base_url: str):
    result = await session.execute(
        select(ApiKey).where(ApiKey.key == api_key, ApiKey.is_active == True)
    )
    key = result.scalar_one_or_none()
    if not key:
        return None

    models_result = await session.execute(
        select(ApiKeyModel).where(ApiKeyModel.api_key_id == key.id)
    )
    key_models = models_result.scalars().all()
    allowed_pm_ids = [km.provider_model_id for km in key_models]

    if allowed_pm_ids:
        pm_result = await session.execute(
            select(ProviderModel).where(ProviderModel.id.in_(allowed_pm_ids))
        )
    else:
        pm_result = await session.execute(select(ProviderModel))

    provider_models = pm_result.scalars().all()
    models_config = {}

    for pm in provider_models:
        provider_result = await session.execute(
            select(Provider).where(Provider.id == pm.provider_id)
        )
        provider = provider_result.scalar_one_or_none()
        if not provider:
            continue

        model_result = await session.execute(
            select(Model).where(Model.id == pm.model_id)
        )
        model = model_result.scalar_one_or_none()
        if not model:
            continue

        model_key = f"{provider.name}/{model.name}"
        display_name = model.display_name or model.name
        max_output = model.max_tokens or 16384
        context_window = model.context_length or (max_output * 8)

        input_modalities = ["text"]
        if model.is_multimodal:
            input_modalities.append("image")

        thinking_config = None
        if model.thinking_enabled:
            thinking_config = {
                "type": "enabled",
            }

        model_entry = {
            "name": f"{provider.name}/{display_name}",
            "modalities": {"input": input_modalities, "output": ["text"]},
            "limit": {"context": context_window, "output": max_output},
        }
        if thinking_config:
            model_entry["options"] = {"thinking": thinking_config}

        models_config[model_key] = model_entry

    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "model-token-plan": {
                "name": "Model Token Plan",
                "options": {
                    "baseURL": base_url,
                    "apiKey": api_key,
                },
                "models": models_config,
            }
        }
    }


@router.get("/opencode/setup.md")
async def get_opencode_setup_markdown(request: Request, api_key: Optional[str] = None):
    if not api_key:
        return PlainTextResponse("# Error\n\nAPI Key is required", status_code=400)

    async with async_session_maker() as session:
        base_url = (
            str(request.base_url).rstrip("/") + get_app_base_path(request) + "/v1"
        )
        config = await build_opencode_config(session, api_key, base_url)
        if not config:
            return PlainTextResponse("# Error\n\nInvalid API Key", status_code=401)

        provider_config = config["provider"]["model-token-plan"]
        model_names = sorted(provider_config.get("models", {}).keys())
        model_list = "\n".join(f"- `{model_name}`" for model_name in model_names)
        if not model_list:
            model_list = "- No models are currently available for this API key."

        md = f"""# OpenCode Setup Instructions

Please update the OpenCode configuration for this machine.

Requirements:
- Preferred global config file: `~/.config/opencode/opencode.json`
- If `~/.config/opencode/opencode.json` does not exist, create it first.
- You can also place `opencode.json` in the root of the current project if you prefer a project-specific config.
- Keep existing providers and other settings unchanged.
- Only add or update the `model-token-plan` provider shown below.
- If OpenCode is not installed yet, download it from `https://opencode.ai/`.
- After saving the file, restart OpenCode so the new provider and models are loaded.

Models included in this provider:
{model_list}

Use this provider config:

```json
{json.dumps(config, ensure_ascii=False, indent=2)}
```

After the config is updated:
1. Save the file.
2. Restart OpenCode.
3. Verify that the models above are available in OpenCode.
"""
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")
