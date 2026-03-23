from typing import Optional
import json
from fastapi import APIRouter, Cookie, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
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


# async def build_opencode_config(session, api_key: str, base_url: str):
#     result = await session.execute(
#         select(ApiKey).where(ApiKey.key == api_key, ApiKey.is_active == True)
#     )
#     key = result.scalar_one_or_none()
#     if not key:
#         return None
#
#     models_result = await session.execute(
#         select(ApiKeyModel).where(ApiKeyModel.api_key_id == key.id)
#     )
#     key_models = models_result.scalars().all()
#     allowed_pm_ids = [km.provider_model_id for km in key_models]
#
#     if allowed_pm_ids:
#         pm_result = await session.execute(
#             select(ProviderModel).where(ProviderModel.id.in_(allowed_pm_ids))
#         )
#     else:
#         pm_result = await session.execute(select(ProviderModel))
#
#     provider_models = pm_result.scalars().all()
#     models_config = {}
#
#     for pm in provider_models:
#         provider_result = await session.execute(
#             select(Provider).where(Provider.id == pm.provider_id)
#         )
#         provider = provider_result.scalar_one_or_none()
#         if not provider:
#             continue
#
#         model_result = await session.execute(
#             select(Model).where(Model.id == pm.model_id)
#         )
#         model = model_result.scalar_one_or_none()
#         if not model:
#             continue
#
#         model_key = f"{provider.name}/{model.name}"
#         display_name = model.display_name or model.name
#         max_output = model.max_tokens or 16384
#         context_window = max_output * 8
#
#         models_config[model_key] = {
#             "name": f"{provider.name}/{display_name}",
#             "modalities": {"input": ["text"], "output": ["text"]},
#             "options": {"thinking": {"type": "enabled", "budgetTokens": 8192}},
#             "limit": {"context": context_window, "output": max_output},
#         }
#
#     return {
#         "provider": {
#             "model-token-plan": {
#                 "name": "Model Token Plan",
#                 "options": {
#                     "baseURL": base_url,
#                     "apiKey": api_key,
#                 },
#                 "models": models_config,
#             }
#         }
#     }


# @router.get("/opencode", response_class=HTMLResponse)
# async def opencode_page(session: Optional[str] = Cookie(None)):
#     if not validate_session(session):
#         return RedirectResponse(url="/login")
#     from templates.opencode import OPENCODE_PAGE_HTML
#
#     return HTMLResponse(content=OPENCODE_PAGE_HTML)


# @router.get("/opencode/config")
# async def get_opencode_config(api_key: Optional[str] = None):
#     if not api_key:
#         return JSONResponse({"error": "API Key is required"}, status_code=400)
#
#     async with async_session_maker() as session:
#         config = await build_opencode_config(session, api_key, "BASEURL_PLACEHOLDER")
#         if not config:
#             return JSONResponse({"error": "Invalid API Key"}, status_code=401)
#         return {"config": config}


# @router.get("/opencode/setup.md")
# async def get_opencode_setup_markdown(request: Request, api_key: Optional[str] = None):
#     if not api_key:
#         return PlainTextResponse("# Error\n\nAPI Key is required", status_code=400)
#
#     async with async_session_maker() as session:
#         base_url = str(request.base_url).rstrip("/") + "/v1"
#         config = await build_opencode_config(session, api_key, base_url)
#         if not config:
#             return PlainTextResponse("# Error\n\nInvalid API Key", status_code=401)
#
#         md = f"""请帮我将以下 provider 配置添加到 `~/.opencode/opencode.json` 中。保留现有的 providers 和其他设置，只添加或更新 `model-token-plan` 这个 provider：
#
# ```json
# {json.dumps(config, ensure_ascii=False, indent=2)}
# ```
# """
#         return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")
