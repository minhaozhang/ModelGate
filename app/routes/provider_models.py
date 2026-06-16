import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import admin_logger
from app.core.database import async_session_maker, Provider, ProviderKey, Model, ProviderModel, ProviderModelRoutingRule
from app.core.permissions import permission_required
from app.services.provider import load_providers

router = APIRouter(prefix="/admin/api", tags=["provider-models"])


class ProviderModelCreate(BaseModel):
    model_id: int
    model_name_override: Optional[str] = None
    upstream_model_name: Optional[str] = None
    alias: Optional[str] = None
    priority: Optional[int] = 0
    is_active: bool = True


class ProviderModelUpdate(BaseModel):
    model_name_override: Optional[str] = None
    upstream_model_name: Optional[str] = None
    alias: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    max_busyness_level: Optional[int] = None
    clear_busyness_level: Optional[bool] = None


@router.get("/providers/{provider_id}/models")
async def list_provider_models(
    provider_id: int,
    _: bool = Depends(permission_required("page.provider_models")),
):
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
                        "upstream_model_name": pm.upstream_model_name
                        if hasattr(pm, "upstream_model_name")
                        else pm.model_name_override,
                        "is_active": pm.is_active,
                        "max_busyness_level": pm.max_busyness_level,
                        "alias": pm.alias if hasattr(pm, "alias") else None,
                        "priority": pm.priority if hasattr(pm, "priority") else 0,
                        "tags": model.tags,
                    }
                )
        return {"models": models_data}


@router.post("/providers/{provider_id}/models")
async def add_provider_model(
    provider_id: int,
    data: ProviderModelCreate,
    _: bool = Depends(permission_required("provider_model.create")),
):
    async with async_session_maker() as session:
        pm = ProviderModel(
            provider_id=provider_id,
            model_id=data.model_id,
            model_name_override=data.model_name_override,
            upstream_model_name=data.upstream_model_name or data.model_name_override,
            alias=data.alias,
            priority=data.priority or 0,
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
    _: bool = Depends(permission_required("provider_model.update")),
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
            if not data.upstream_model_name:
                pm.upstream_model_name = data.model_name_override
        if data.upstream_model_name is not None:
            pm.upstream_model_name = data.upstream_model_name or None
        if data.alias is not None:
            pm.alias = data.alias if data.alias else None
        if data.priority is not None:
            pm.priority = data.priority
        if data.is_active is not None:
            pm.is_active = data.is_active
        if data.clear_busyness_level:
            pm.max_busyness_level = None
        elif data.max_busyness_level is not None:
            pm.max_busyness_level = data.max_busyness_level if data.max_busyness_level > 0 else None
        await session.commit()
        await load_providers()
        return {"id": pm.id}


@router.delete("/providers/{provider_id}/models/{pm_id}")
async def remove_provider_model(
    provider_id: int,
    pm_id: int,
    _: bool = Depends(permission_required("provider_model.delete")),
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
async def sync_provider_models(
    provider_id: int,
    _: bool = Depends(permission_required("provider_model.sync")),
):
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
                        max_tokens = None
                        context_length = None
                    else:
                        model_name = model_info.get("id", model_info.get("name", ""))
                        raw_mt = model_info.get("max_tokens")
                        if isinstance(raw_mt, str):
                            try:
                                raw_mt = int(raw_mt)
                            except ValueError:
                                raw_mt = None
                        max_tokens = raw_mt
                        context_length = context_length_map.get(model_name)

                    if not model_name:
                        continue

                    model_result = await session.execute(
                        select(Model).where(Model.name == model_name)
                    )
                    model = model_result.scalar_one_or_none()
                    if not model:
                        create_kwargs = dict(
                            name=model_name,
                            display_name=model_name,
                            is_active=True,
                        )
                        if max_tokens is not None:
                            create_kwargs["max_tokens"] = max_tokens
                        if context_length is not None:
                            create_kwargs["context_length"] = context_length
                        model = Model(**create_kwargs)
                        session.add(model)
                        await session.flush()
                    else:
                        if max_tokens is not None and model.max_tokens != max_tokens:
                            model.max_tokens = max_tokens
                        if model.display_name != model_name:
                            model.display_name = model_name
                        if context_length is not None and model.context_length != context_length:
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
                            upstream_model_name=model_name,
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
async def list_all_provider_models(_: bool = Depends(permission_required("page.provider_models"))):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderModel).where(ProviderModel.is_active == True)
        )
        pms = result.scalars().all()
        models_data = []
        for pm in pms:
            rules_result = await session.execute(
                select(ProviderModelRoutingRule)
                .where(ProviderModelRoutingRule.provider_model_id == pm.id)
                .order_by(ProviderModelRoutingRule.id)
            )
            routing_rules = [
                {
                    "id": rule.id,
                    "provider_model_id": rule.provider_model_id,
                    "name": rule.name or "",
                    "rule_type": rule.rule_type,
                    "enabled": rule.enabled,
                    "priority": rule.priority or 0,
                    "start_time": rule.start_time.isoformat() if rule.start_time else None,
                    "end_time": rule.end_time.isoformat() if rule.end_time else None,
                    "start_date": rule.start_date.isoformat() if rule.start_date else None,
                    "end_date": rule.end_date.isoformat() if rule.end_date else None,
                    "weekdays": rule.weekdays,
                    "min_context_tokens": rule.min_context_tokens,
                    "max_context_tokens": rule.max_context_tokens,
                    "provider_key_ids": rule.provider_key_ids or [],
                    "action": rule.action,
                }
                for rule in rules_result.scalars().all()
            ]
            provider_result = await session.execute(
                select(Provider).where(Provider.id == pm.provider_id)
            )
            provider = provider_result.scalar_one_or_none()
            model_result = await session.execute(
                select(Model).where(Model.id == pm.model_id)
            )
            model = model_result.scalar_one_or_none()
            if provider and model:
                key_result = await session.execute(
                    select(ProviderKey)
                    .where(ProviderKey.provider_id == provider.id)
                    .order_by(ProviderKey.priority.desc(), ProviderKey.id)
                )
                provider_keys = [
                    {
                        "id": key.id,
                        "label": key.label or f"Key #{key.id}",
                        "priority": key.priority or 0,
                        "is_active": key.is_active,
                    }
                    for key in key_result.scalars().all()
                ]
                models_data.append(
                    {
                        "id": pm.id,
                        "provider_id": provider.id,
                        "provider_name": provider.name,
                        "model_id": model.id,
                        "model_name": model.name,
                        "model_display_name": model.display_name or model.name,
                        "display_name": f"{provider.name} - {model.display_name or model.name}",
                        "upstream_model_name": pm.upstream_model_name or pm.model_name_override or model.name,
                        "priority": pm.priority or 0,
                        "max_busyness_level": pm.max_busyness_level,
                        "tags": model.tags or "",
                        "provider_is_active": provider.is_active,
                        "provider_disabled_reason": provider.disabled_reason,
                        "provider_keys": provider_keys,
                        "routing_rules": routing_rules,
                        "routing_rule_count": len(routing_rules),
                    }
                )
        return {"provider_models": models_data}
