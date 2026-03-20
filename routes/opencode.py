from typing import Optional
from fastapi import APIRouter, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select

from config import validate_session
from database import (
    async_session_maker,
    ApiKey,
    Provider,
    Model,
    ProviderModel,
    ApiKeyModel,
)

router = APIRouter(tags=["docs"])


@router.get("/opencode", response_class=HTMLResponse)
async def opencode_page(session: Optional[str] = Cookie(None)):
    if not validate_session(session):
        return RedirectResponse(url="/login")
    from templates.opencode import OPENCODE_PAGE_HTML

    return HTMLResponse(content=OPENCODE_PAGE_HTML)


@router.get("/opencode/config")
async def get_opencode_config(api_key: Optional[str] = None):
    if not api_key:
        return JSONResponse({"error": "API Key is required"}, status_code=400)

    async with async_session_maker() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key == api_key, ApiKey.is_active == True)
        )
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "Invalid API Key"}, status_code=401)

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

        models_data = []
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
            context_window = max_output * 8

            models_config[model_key] = {
                "name": f"{provider.name}/{display_name}",
                "modalities": {"input": ["text"], "output": ["text"]},
                "options": {"thinking": {"type": "enabled", "budgetTokens": 8192}},
                "limit": {"context": context_window, "output": max_output},
            }

            models_data.append(
                {"name": model_key, "context": context_window, "output": max_output}
            )

        config = {
            "$schema": "https://opencode.ai/config.json",
            "provider": {
                "proxy-coding-plan": {
                    "name": "API Proxy",
                    "options": {
                        "baseURL": "http://127.0.0.1:8765/v1",
                        "apiKey": "YOUR-API-KEY",
                    },
                    "models": models_config,
                }
            },
        }

        return {"config": config, "models": models_data}
