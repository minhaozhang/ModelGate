import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import admin_logger
from app.core.database import async_session_maker, Provider, ProviderKey, Model, ProviderModel, ProviderModelRoutingRule
from app.core.permissions import permission_required
from app.services.provider import load_providers

router = APIRouter(prefix="/admin/api", tags=["provider-models"])


class SyncModelsRequest(BaseModel):
    models: Optional[List[str]] = None


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


class ProviderModelPricingUpdate(BaseModel):
    input_price_cny_per_million: Optional[float] = None
    output_price_cny_per_million: Optional[float] = None
    cached_input_price_cny_per_million: Optional[float] = None
    default_cache_hit_ratio: Optional[float] = None
    pricing_tiers: Optional[list[dict]] = None


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
                        "input_price_cny_per_million": pm.input_price_cny_per_million,
                        "output_price_cny_per_million": pm.output_price_cny_per_million,
                        "cached_input_price_cny_per_million": pm.cached_input_price_cny_per_million,
                        "default_cache_hit_ratio": pm.default_cache_hit_ratio or 0,
                        "pricing_tiers": pm.pricing_tiers or [],
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


@router.put("/provider-models/{pm_id}/pricing")
async def update_provider_model_pricing(
    pm_id: int,
    data: ProviderModelPricingUpdate,
    _: bool = Depends(permission_required("provider_model.update")),
):
    async with async_session_maker() as session:
        result = await session.execute(select(ProviderModel).where(ProviderModel.id == pm_id))
        pm = result.scalar_one_or_none()
        if not pm:
            return JSONResponse({"error": "ProviderModel not found"}, status_code=404)
        for field in (
            "input_price_cny_per_million",
            "output_price_cny_per_million",
            "cached_input_price_cny_per_million",
            "default_cache_hit_ratio",
            "pricing_tiers",
        ):
            if field in data.model_fields_set:
                setattr(pm, field, getattr(data, field))
        await session.commit()
        return {"id": pm.id}


class ProviderModelBatchPricingUpdate(BaseModel):
    ids: list[int]
    input_price_cny_per_million: Optional[float] = None
    output_price_cny_per_million: Optional[float] = None
    cached_input_price_cny_per_million: Optional[float] = None
    default_cache_hit_ratio: Optional[float] = None


@router.post("/provider-models/batch-pricing")
async def batch_update_provider_model_pricing(
    data: ProviderModelBatchPricingUpdate,
    _: bool = Depends(permission_required("provider_model.update")),
):
    if not data.ids:
        return JSONResponse({"error": "ids is empty"}, status_code=400)
    fields = {}
    for fname in (
        "input_price_cny_per_million",
        "output_price_cny_per_million",
        "cached_input_price_cny_per_million",
        "default_cache_hit_ratio",
    ):
        val = getattr(data, fname)
        if val is not None:
            fields[fname] = val
    if not fields:
        return JSONResponse({"error": "no fields to update"}, status_code=400)
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderModel).where(ProviderModel.id.in_(data.ids))
        )
        pms = result.scalars().all()
        found_ids = {pm.id for pm in pms}
        missing = set(data.ids) - found_ids
        if missing:
            return JSONResponse({"error": f"not found: {sorted(missing)}"}, status_code=404)
        for pm in pms:
            for fname, val in fields.items():
                setattr(pm, fname, val)
        await session.commit()
    return {"updated": sorted(found_ids)}


class CopyPricingPayload(BaseModel):
    target_pm_id: int


@router.post("/provider-models/{pm_id}/copy-pricing")
async def copy_provider_model_pricing(
    pm_id: int,
    data: CopyPricingPayload,
    _: bool = Depends(permission_required("provider_model.update")),
):
    async with async_session_maker() as session:
        src_result = await session.execute(select(ProviderModel).where(ProviderModel.id == pm_id))
        src = src_result.scalar_one_or_none()
        if not src:
            return JSONResponse({"error": "source not found"}, status_code=404)
        tgt_result = await session.execute(
            select(ProviderModel).where(ProviderModel.id == data.target_pm_id)
        )
        tgt = tgt_result.scalar_one_or_none()
        if not tgt:
            return JSONResponse({"error": "target not found"}, status_code=404)
        for fname in (
            "input_price_cny_per_million",
            "output_price_cny_per_million",
            "cached_input_price_cny_per_million",
            "default_cache_hit_ratio",
            "pricing_tiers",
        ):
            setattr(tgt, fname, getattr(src, fname))
        await session.commit()
    return {"copied_from": pm_id, "copied_to": data.target_pm_id}


@router.post("/provider-models/{pm_id}/sync-to-siblings")
async def sync_pricing_to_siblings(
    pm_id: int,
    _: bool = Depends(permission_required("provider_model.update")),
):
    async with async_session_maker() as session:
        base_result = await session.execute(select(ProviderModel).where(ProviderModel.id == pm_id))
        base = base_result.scalar_one_or_none()
        if not base:
            return JSONResponse({"error": "base not found"}, status_code=404)
        siblings_result = await session.execute(
            select(ProviderModel).where(
                ProviderModel.model_id == base.model_id,
                ProviderModel.id != pm_id,
            )
        )
        siblings = siblings_result.scalars().all()
        for sib in siblings:
            for fname in (
                "input_price_cny_per_million",
                "output_price_cny_per_million",
                "cached_input_price_cny_per_million",
                "default_cache_hit_ratio",
                "pricing_tiers",
            ):
                setattr(sib, fname, getattr(base, fname))
        await session.commit()
    return {"synced_to": [sib.id for sib in siblings]}


@router.get("/provider-models/pricing-export.csv")
async def export_provider_model_pricing_csv(
    _: bool = Depends(permission_required("provider_model.view")),
):
    import csv
    import io
    import json
    from fastapi.responses import Response

    async with async_session_maker() as session:
        stmt = (
            select(ProviderModel, Provider, Model)
            .join(Provider, Provider.id == ProviderModel.provider_id)
            .join(Model, Model.id == ProviderModel.model_id)
            .order_by(Model.name, Provider.name)
        )
        result = await session.execute(stmt)
        rows = result.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "provider", "model", "upstream_model",
        "input_price_cny_per_million", "output_price_cny_per_million",
        "cached_input_price_cny_per_million", "default_cache_hit_ratio",
        "tiers_json",
    ])
    for pm, provider, model in rows:
        writer.writerow([
            provider.name, model.name,
            pm.upstream_model_name or pm.model_name_override or model.name,
            pm.input_price_cny_per_million,
            pm.output_price_cny_per_million,
            pm.cached_input_price_cny_per_million,
            pm.default_cache_hit_ratio,
            json.dumps(pm.pricing_tiers or [], ensure_ascii=False),
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=modelgate_pricing.csv"},
    )


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
    from app.core.database import ApiKeyModel, ApiKey, Model

    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderModel).where(
                ProviderModel.id == pm_id, ProviderModel.provider_id == provider_id
            )
        )
        pm = result.scalar_one_or_none()
        if not pm:
            return JSONResponse({"error": "ProviderModel not found"}, status_code=404)

        model_result = await session.execute(
            select(Model.name).where(Model.id == pm.model_id)
        )
        model_name = model_result.scalar() or f"#{pm.model_id}"

        key_result = await session.execute(
            select(ApiKey.name)
            .select_from(ApiKeyModel)
            .join(ApiKey, ApiKey.id == ApiKeyModel.api_key_id)
            .where(ApiKeyModel.provider_model_id == pm_id)
            .order_by(ApiKey.name)
            .limit(10)
        )
        bound_keys = [row[0] for row in key_result.fetchall()]
        if bound_keys:
            from sqlalchemy import func

            total_result = await session.execute(
                select(func.count()).select_from(ApiKeyModel).where(
                    ApiKeyModel.provider_model_id == pm_id
                )
            )
            total = total_result.scalar() or len(bound_keys)
            more = f" 等 {total} 个 Key" if total > len(bound_keys) else ""
            return JSONResponse(
                {
                    "error": (
                        f"无法解除模型「{model_name}」的绑定：该供应商模型仍被 {total} 个 API Key 引用"
                        f"（{'、'.join(bound_keys)}{more}）。"
                        f"请先在这些 API Key 的「允许模型」中移除该模型。"
                    )
                },
                status_code=409,
            )

        try:
            await session.delete(pm)
            await session.commit()
        except IntegrityError:
            try:
                await session.rollback()
            except Exception:
                pass
            return JSONResponse(
                {"error": f"无法解除模型「{model_name}」的绑定：仍有关联数据引用它，请先解除相关配置。"},
                status_code=409,
            )
        await load_providers()
        return {"deleted": True}


@router.post("/providers/{provider_id}/sync-models")
async def sync_provider_models(
    provider_id: int,
    data: Optional[SyncModelsRequest] = None,
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
        models_filter = set(data.models) if data and data.models is not None else None
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
                    if models_filter is not None and model_name not in models_filter:
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


@router.get("/providers/{provider_id}/upstream-models")
async def list_upstream_models(
    provider_id: int,
    _: bool = Depends(permission_required("provider_model.sync")),
):
    """Read-only preview of the provider's upstream /models endpoint."""
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
        api_key = active_key.api_key if active_key else (provider.api_key or "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(f"{provider.base_url}/models", headers=headers)
        except Exception as e:
            admin_logger.error(f"[UPSTREAM MODELS ERROR] provider={provider_id} {e}")
            return JSONResponse({"error": str(e)}, status_code=502)

        if resp.status_code != 200:
            return JSONResponse(
                {"error": f"Failed to fetch models: {resp.status_code}"},
                status_code=502,
            )
        try:
            data = resp.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON from upstream"}, status_code=502)

    models = data.get("data", data.get("models", []))
    if isinstance(models, dict):
        models = list(models.values())
    names = []
    for model_info in models or []:
        if isinstance(model_info, str):
            name = model_info
        elif isinstance(model_info, dict):
            name = model_info.get("id") or model_info.get("name") or ""
        else:
            name = ""
        if name:
            names.append(name)
    return {"models": names, "total": len(names)}


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
                        "input_price_cny_per_million": pm.input_price_cny_per_million,
                        "output_price_cny_per_million": pm.output_price_cny_per_million,
                        "cached_input_price_cny_per_million": pm.cached_input_price_cny_per_million,
                        "default_cache_hit_ratio": pm.default_cache_hit_ratio or 0,
                        "pricing_tiers": pm.pricing_tiers or [],
                    }
                )
        return {"provider_models": models_data}
