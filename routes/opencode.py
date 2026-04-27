import json
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
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
from routes.user import get_user_session

router = APIRouter(tags=["docs"])


def build_opencode_base_url(request: Request) -> str:
    base_url = str(request.base_url).rstrip("/")
    app_base_path = get_app_base_path(request)
    if app_base_path and base_url.endswith(app_base_path):
        return f"{base_url}/v1"
    return f"{base_url}{app_base_path}/v1"


async def build_opencode_config(
    session, base_url: str, api_key: str = None, api_key_id: int = None
):
    if api_key:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key == api_key, ApiKey.is_active == True)
        )
    elif api_key_id:
        result = await session.execute(
            select(ApiKey).where(ApiKey.id == api_key_id, ApiKey.is_active == True)
        )
    else:
        return None
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
            "modelgate": {
                "name": "ModelGate",
                "options": {
                    "baseURL": base_url,
                    "apiKey": key.key,
                },
                "models": models_config,
            }
        },
    }


def build_setup_markdown(config: dict) -> str:
    provider_config = config["provider"]["modelgate"]
    model_names = sorted(provider_config.get("models", {}).keys())
    model_list = "\n".join(f"- `{model_name}`" for model_name in model_names)
    if not model_list:
        model_list = "- No models are currently available for this API key."

    return f"""# OpenCode Setup Instructions

Please update the OpenCode configuration for this machine.

Requirements:
- Preferred global config file: `~/.config/opencode/opencode.json`
- If `~/.config/opencode/opencode.json` does not exist, create it first.
- You can also place `opencode.json` in the root of the current project if you prefer a project-specific config.
- Keep existing providers and other settings unchanged.
- Only add or update the `modelgate` provider shown below.
- If the `modelgate` provider already exists in the config, replace its entire content with the JSON below.
- If OpenCode is not installed yet, download it from `https://opencode.ai/`.

Models included in this provider:
{model_list}

Use this provider config:

```json
{json.dumps(config, ensure_ascii=False)}
```

After the config is updated:
1. Save the file.
2. **Restart OpenCode** for the changes to take effect.
3. Verify that the models above are available in OpenCode."""


@router.get("/opencode/setup.md")
async def get_opencode_setup_markdown(
    request: Request,
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    if not api_key and not api_key_id:
        return PlainTextResponse("# Error\n\nAPI Key is required", status_code=400)

    async with async_session_maker() as session:
        base_url = build_opencode_base_url(request)
        config = await build_opencode_config(
            session, base_url, api_key=api_key, api_key_id=api_key_id
        )
        if not config:
            return PlainTextResponse("# Error\n\nInvalid API Key", status_code=401)

        md = build_setup_markdown(config)
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")


class MergeRequest(BaseModel):
    config: dict


@router.post("/opencode/merge")
async def merge_opencode_config(
    request: Request,
    body: MergeRequest,
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    if not api_key and not api_key_id:
        return JSONResponse({"error": "API Key is required"}, status_code=400)

    async with async_session_maker() as session:
        base_url = build_opencode_base_url(request)
        modelgate_config = await build_opencode_config(
            session, base_url, api_key=api_key, api_key_id=api_key_id
        )
        if not modelgate_config:
            return JSONResponse({"error": "Invalid API Key"}, status_code=401)

        user_config = body.config
        if not isinstance(user_config, dict):
            user_config = {}

        providers = user_config.get("provider", {})
        if not isinstance(providers, dict):
            providers = {}
        providers["modelgate"] = modelgate_config["provider"]["modelgate"]
        user_config["provider"] = providers

        return JSONResponse(user_config)
