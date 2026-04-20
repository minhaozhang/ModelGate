import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.config import admin_logger, validate_session
from core.database import async_session_maker, Provider, ProviderKey, Model, ProviderModel
from services.provider import load_providers

router = APIRouter(prefix="/admin/api", tags=["provider-models"])


def require_admin(session: Optional[str] = Cookie(None)):
    if not validate_session(session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


class ProviderModelCreate(BaseModel):
    model_id: int
    model_name_override: Optional[str] = None
    max_concurrent: Optional[int] = None
    is_active: bool = True


class ProviderModelUpdate(BaseModel):
    model_name_override: Optional[str] = None
    max_concurrent: Optional[int] = None
    is_active: Optional[bool] = None


@router.get("/providers/{provider_id}/models")
async def list_provider_models(provider_id: int, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderModel).where(ProviderModel.provider_id == provider_id)
        )
        pms = result.scalars().all()
        models_data = []
        for pm in pms:
            model_result = await session.execute(
                select(Model).where(Model.id == pm.model_id)
            )
            model = model_result.scalar_one_or_none()
            if model:
                models_data.append(
                    {
                        "id": pm.id,
                        "model_id": model.id,
                        "model_name": model.name,
                        "display_name": model.display_name,
                        "model_name_override": pm.model_name_override,
                        "max_concurrent": pm.max_concurrent,
                        "is_active": pm.is_active,
                    }
                )
        return {"models": models_data}


@router.post("/providers/{provider_id}/models")
async def add_provider_model(
    provider_id: int, data: ProviderModelCreate, _: bool = Depends(require_admin)
):
    async with async_session_maker() as session:
        pm = ProviderModel(
            provider_id=provider_id,
            model_id=data.model_id,
            model_name_override=data.model_name_override,
            max_concurrent=data.max_concurrent,
            is_active=data.is_active,
        )
        session.add(pm)
        await session.commit()
        await load_providers()
        return {"id": pm.id}


@router.put("/providers/{provider_id}/models/{pm_id}")
async def update_provider_model(
    provider_id: int,
    pm_id: int,
    data: ProviderModelUpdate,
    _: bool = Depends(require_admin),
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderModel).where(
                ProviderModel.id == pm_id, ProviderModel.provider_id == provider_id
            )
        )
        pm = result.scalar_one_or_none()
        if not pm:
            return JSONResponse({"error": "ProviderModel not found"}, status_code=404)
        if data.model_name_override is not None:
            pm.model_name_override = data.model_name_override
        if data.max_concurrent is not None:
            pm.max_concurrent = data.max_concurrent
        if data.is_active is not None:
            pm.is_active = data.is_active
        await session.commit()
        await load_providers()
        return {"id": pm.id}


@router.delete("/providers/{provider_id}/models/{pm_id}")
async def remove_provider_model(
    provider_id: int, pm_id: int, _: bool = Depends(require_admin)
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderModel).where(
                ProviderModel.id == pm_id, ProviderModel.provider_id == provider_id
            )
        )
        pm = result.scalar_one_or_none()
        if not pm:
            return JSONResponse({"error": "ProviderModel not found"}, status_code=404)
        try:
            await session.delete(pm)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return JSONResponse(
                {"error": "Cannot delete: model is bound to API keys. Remove API key bindings first."},
                status_code=409,
            )
        await load_providers()
        return {"deleted": True}


@router.post("/providers/{provider_id}/sync-models")
async def sync_provider_models(provider_id: int, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        result = await session.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        provider = result.scalar_one_or_none()
        if not provider:
            return JSONResponse({"error": "Provider not found"}, status_code=404)

        headers = {"Accept": "application/json"}
        pk_result = await session.execute(
            select(ProviderKey)
            .where(
                ProviderKey.provider_id == provider_id,
                ProviderKey.is_active == True,  # noqa: E712
            )
            .limit(1)
        )
        active_key = pk_result.scalar_one_or_none()
        sync_api_key = active_key.api_key if active_key else (provider.api_key or "")
        if sync_api_key:
            headers["Authorization"] = f"Bearer {sync_api_key}"

        synced = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(f"{provider.base_url}/models", headers=headers)
                if resp.status_code != 200:
                    return JSONResponse(
                        {"error": f"Failed to fetch models: {resp.status_code}"},
                        status_code=500,
                    )
                data = resp.json()
                models = data.get("data", data.get("models", []))
                if isinstance(models, dict):
                    models = list(models.values())

                context_length_map = {
                    "glm-4.5": 131072,
                    "glm-4.5-air": 131072,
                    "glm-4.6": 131072,
                    "glm-4.6v": 131072,
                    "glm-4.6v-flash": 131072,
                    "glm-4.6v-flashx": 131072,
                    "glm-4.7": 131072,
                    "glm-4.1v-thinking-flashx": 131072,
                    "glm-4.1v-thinking-flash": 131072,
                    "glm-4.1-mini": 131072,
                    "glm-4.1-mini-flash": 131072,
                    "glm-4": 128 * 1024,
                    "glm-4-flash-250414": 128 * 1024,
                    "glm-4-air-250414": 128 * 1024,
                    "glm-4-plus": 128 * 1024,
                    "glm-4-air": 128 * 1024,
                    "glm-4-airx": 128 * 1024,
                    "glm-4-flash": 128 * 1024,
                    "glm-4-flashx": 128 * 1024,
                    "glm-4v-plus-0111": 128 * 1024,
                    "glm-4v-flash": 128 * 1024,
                    "glm-5": 131072,
                    "glm-5-turbo": 131072,
                    "glm-5.1": 131072,
                    "glm-5.1-flash": 131072,
                    "glm-4.5-x": 131072,
                    "glm-4.5-flash": 131072,
                }

                for model_info in models:
                    if isinstance(model_info, str):
                        model_name = model_info
                        max_tokens = 16384
                        context_length = 131072
                    else:
                        model_name = model_info.get("id", model_info.get("name", ""))
                        max_tokens = model_info.get("max_tokens", 16384)
                        if isinstance(max_tokens, str):
                            try:
                                max_tokens = int(max_tokens)
                            except ValueError:
                                max_tokens = 16384
                        context_length = context_length_map.get(model_name, 131072)

                    if not model_name:
                        continue

                    model_result = await session.execute(
                        select(Model).where(Model.name == model_name)
                    )
                    model = model_result.scalar_one_or_none()
                    if not model:
                        model = Model(
                            name=model_name,
                            display_name=model_name,
                            max_tokens=max_tokens,
                            context_length=context_length,
                            is_active=True,
                        )
                        session.add(model)
                        await session.flush()
                    else:
                        if model.max_tokens != max_tokens:
                            model.max_tokens = max_tokens
                        if model.display_name != model_name:
                            model.display_name = model_name
                        if model.context_length != context_length:
                            model.context_length = context_length

                    pm_result = await session.execute(
                        select(ProviderModel).where(
                            ProviderModel.provider_id == provider_id,
                            ProviderModel.model_id == model.id,
                        )
                    )
                    pm = pm_result.scalar_one_or_none()
                    if not pm:
                        pm = ProviderModel(
                            provider_id=provider_id,
                            model_id=model.id,
                            is_active=True,
                        )
                        session.add(pm)

                    synced.append(model_name)

                await session.commit()
                await load_providers()
                return {"synced": synced, "total": len(synced)}
            except Exception as e:
                admin_logger.error(f"[SYNC MODELS ERROR] {e}")
                return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/provider-models")
async def list_all_provider_models(_: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderModel).where(ProviderModel.is_active == True)
        )
        pms = result.scalars().all()
        models_data = []
        for pm in pms:
            provider_result = await session.execute(
                select(Provider).where(Provider.id == pm.provider_id)
            )
            provider = provider_result.scalar_one_or_none()
            model_result = await session.execute(
                select(Model).where(Model.id == pm.model_id)
            )
            model = model_result.scalar_one_or_none()
            if provider and model:
                models_data.append(
                    {
                        "id": pm.id,
                        "provider_id": provider.id,
                        "provider_name": provider.name,
                        "model_id": model.id,
                        "model_name": model.name,
                        "display_name": f"{provider.name} - {model.display_name or model.name}",
                    }
                )
        return {"provider_models": models_data}
