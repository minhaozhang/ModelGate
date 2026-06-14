import json

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from app.core.database import (
    async_session_maker,
    Model,
    ApiKey,
    ApiKeyModel,
    ApiKeyModelAccess,
    ProviderModel,
    Provider,
)
from app.core.permissions import permission_required
from app.services.auth import load_api_keys

router = APIRouter(prefix="/admin/api", tags=["models"])


class ModelCreate(BaseModel):
    name: str
    display_name: Optional[str] = None
    max_tokens: int = 131072
    context_length: int = 204800
    thinking_enabled: bool = True
    thinking_budget: int = 8192
    is_multimodal: bool = False
    is_active: bool = True
    tags: Optional[str] = None


class ModelUpdate(BaseModel):
    display_name: Optional[str] = None
    max_tokens: Optional[int] = None
    context_length: Optional[int] = None
    thinking_enabled: Optional[bool] = None
    thinking_budget: Optional[int] = None
    is_multimodal: Optional[bool] = None
    is_active: Optional[bool] = None
    estimated_price: Optional[float] = None
    tags: Optional[str] = None


class AutoModelConfigUpdate(BaseModel):
    enabled: bool = False
    model_ids: list[int] = Field(default_factory=list)
    provider_model_ids: list[int] = Field(default_factory=list)


def _normalize_auto_model_config(data: dict | None) -> dict:
    data = data or {}
    return {
        "enabled": bool(data.get("enabled")),
        "model_ids": [int(v) for v in data.get("model_ids", []) if str(v).isdigit()],
        "provider_model_ids": [
            int(v) for v in data.get("provider_model_ids", []) if str(v).isdigit()
        ],
    }


@router.get("/routing/auto-model")
async def get_auto_model_config(_: bool = Depends(permission_required("page.models"))):
    from app.services.system_config import get_setting

    raw = await get_setting("routing", "auto_model", "{}")
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        data = {}
    return _normalize_auto_model_config(data)


@router.put("/routing/auto-model")
async def update_auto_model_config(
    data: AutoModelConfigUpdate,
    _: bool = Depends(permission_required("model.update")),
):
    from app.services.system_config import save_setting

    payload = _normalize_auto_model_config(data.model_dump())
    await save_setting(
        "routing",
        "auto_model",
        json.dumps(payload, ensure_ascii=False),
        "Virtual auto model routing configuration",
    )
    return payload


@router.get("/models")
async def list_all_models(_: bool = Depends(permission_required("page.models"))):
    async with async_session_maker() as session:
        result = await session.execute(select(Model).order_by(Model.name))
        models = result.scalars().all()

        model_ids = [m.id for m in models]
        pm_result = await session.execute(
            select(ProviderModel.model_id, ProviderModel.id).where(
                ProviderModel.model_id.in_(model_ids)
            )
        )
        model_pm_map: dict[int, list[int]] = {m.id: [] for m in models}
        pm_model_map: dict[int, int] = {}
        for row in pm_result.fetchall():
            model_pm_map[row[0]].append(row[1])
            pm_model_map[row[1]] = row[0]

        all_pm_ids = [pm_id for ids in model_pm_map.values() for pm_id in ids]
        model_key_ids: dict[int, set[int]] = {m.id: set() for m in models}
        if all_pm_ids:
            ak_count_result = await session.execute(
                select(ApiKeyModel.provider_model_id, ApiKeyModel.api_key_id).where(
                    ApiKeyModel.provider_model_id.in_(all_pm_ids)
                )
            )
            for row in ak_count_result.fetchall():
                model_id = pm_model_map.get(row[0])
                if model_id:
                    model_key_ids.setdefault(model_id, set()).add(row[1])

        if model_ids:
            model_access_result = await session.execute(
                select(ApiKeyModelAccess.model_id, ApiKeyModelAccess.api_key_id).where(
                    ApiKeyModelAccess.model_id.in_(model_ids)
                )
            )
            for row in model_access_result.fetchall():
                model_key_ids.setdefault(row[0], set()).add(row[1])

        return {
            "models": [
                {
                    "id": m.id,
                    "name": m.name,
                    "display_name": m.display_name,
                    "max_tokens": m.max_tokens,
                    "context_length": m.context_length,
                    "thinking_enabled": m.thinking_enabled,
                    "thinking_budget": m.thinking_budget,
                    "is_multimodal": m.is_multimodal,
                    "is_active": m.is_active,
                    "tags": m.tags,
                    "bound_key_count": len(model_key_ids.get(m.id, set())),
                }
                for m in models
            ]
        }


@router.post("/models")
async def create_model(data: ModelCreate, _: bool = Depends(permission_required("model.create"))):
    async with async_session_maker() as session:
        model = Model(**data.model_dump())
        session.add(model)
        await session.commit()
        return {"id": model.id, "name": model.name}


@router.put("/models/{model_id}")
async def update_model(
    model_id: int, data: ModelUpdate, _: bool = Depends(permission_required("model.update"))
):
    async with async_session_maker() as session:
        result = await session.execute(select(Model).where(Model.id == model_id))
        model = result.scalar_one_or_none()
        if not model:
            return JSONResponse({"error": "Model not found"}, status_code=404)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(model, k, v)
        await session.commit()
        return {"id": model.id}


@router.delete("/models/{model_id}")
async def delete_model(model_id: int, _: bool = Depends(permission_required("model.delete"))):
    async with async_session_maker() as session:
        result = await session.execute(select(Model).where(Model.id == model_id))
        model = result.scalar_one_or_none()
        if not model:
            return JSONResponse({"error": "Model not found"}, status_code=404)
        try:
            await session.delete(model)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return JSONResponse(
                {"error": "Cannot delete: model has provider bindings. Remove all provider bindings first."},
                status_code=409,
            )
        return {"deleted": True}


@router.get("/models/{model_id}/api-keys")
async def get_model_api_keys(model_id: int, _: bool = Depends(permission_required("page.models"))):
    async with async_session_maker() as session:
        pm_result = await session.execute(
            select(ProviderModel, Provider.name).join(
                Provider, ProviderModel.provider_id == Provider.id
            ).where(ProviderModel.model_id == model_id)
        )
        pm_rows = pm_result.fetchall()
        pm_ids = []
        pm_labels = {}
        for row in pm_rows:
            pm = row[0]
            pm_ids.append(pm.id)
            pm_labels[pm.id] = f"{row[1]}/{pm.model_name_override or ''}"

        if not pm_ids:
            return {"api_keys": [], "provider_models": [], "bound_keys": {}}

        ak_result = await session.execute(
            select(ApiKeyModel.provider_model_id, ApiKey.id, ApiKey.name).join(
                ApiKey, ApiKeyModel.api_key_id == ApiKey.id
            ).where(
                ApiKeyModel.provider_model_id.in_(pm_ids)
            )
        )
        bound_keys = {}
        for row in ak_result.fetchall():
            pm_id = row[0]
            bound_keys.setdefault(pm_id, []).append({"id": row[1], "name": row[2]})

        from app.core.database import ApiKeyTag

        all_keys_result = await session.execute(
            select(ApiKey).where(ApiKey.is_active == True)  # noqa: E712
        )
        all_keys_raw = all_keys_result.scalars().all()
        all_key_ids = [k.id for k in all_keys_raw]

        tags_result = await session.execute(
            select(ApiKeyTag.api_key_id, ApiKeyTag.tag).where(
                ApiKeyTag.api_key_id.in_(all_key_ids)
            )
        )
        tags_map: dict[int, list[str]] = {}
        all_tags_set: set[str] = set()
        for row in tags_result.fetchall():
            tags_map.setdefault(row[0], []).append(row[1])
            all_tags_set.add(row[1])

        all_keys = [
            {"id": k.id, "name": k.name, "tags": tags_map.get(k.id, [])}
            for k in all_keys_raw
        ]

        return {
            "api_keys": all_keys,
            "all_tags": sorted(all_tags_set),
            "provider_models": [{"id": k, "label": v} for k, v in pm_labels.items()],
            "bound_keys": bound_keys,
        }


class ModelApiKeysUpdate(BaseModel):
    provider_model_id: int
    api_key_ids: list[int]


@router.put("/models/{model_id}/api-keys")
async def update_model_api_keys(
    model_id: int, data: ModelApiKeysUpdate, _: bool = Depends(permission_required("model.update"))
):
    async with async_session_maker() as session:
        pm_result = await session.execute(
            select(ProviderModel).where(
                ProviderModel.id == data.provider_model_id,
                ProviderModel.model_id == model_id,
            )
        )
        if not pm_result.scalar_one_or_none():
            return JSONResponse({"error": "Provider model not found"}, status_code=404)

        old_result = await session.execute(
            select(ApiKeyModel.api_key_id).where(
                ApiKeyModel.provider_model_id == data.provider_model_id
            )
        )
        old_key_ids = set(row[0] for row in old_result.fetchall())
        new_key_ids = set(data.api_key_ids)

        await session.execute(
            delete(ApiKeyModel).where(
                ApiKeyModel.provider_model_id == data.provider_model_id
            )
        )
        for ak_id in data.api_key_ids:
            session.add(ApiKeyModel(
                api_key_id=ak_id,
                provider_model_id=data.provider_model_id,
            ))

        model_result = await session.execute(select(Model).where(Model.id == model_id))
        model = model_result.scalar_one_or_none()
        model_display = model.display_name or model.name if model else str(model_id)

        added_key_ids = new_key_ids - old_key_ids
        removed_key_ids = old_key_ids - new_key_ids
        if added_key_ids or removed_key_ids:
            from app.services.notification import notify_model_changes_async
            keys_result = await session.execute(
                select(ApiKey.id, ApiKey.name).where(ApiKey.id.in_(added_key_ids | removed_key_ids))
            )
            key_map = {row[0]: row[1] for row in keys_result.fetchall()}
            for ak_id in added_key_ids:
                notify_model_changes_async(ak_id, key_map.get(ak_id, ""), [model_display], [])
            for ak_id in removed_key_ids:
                notify_model_changes_async(ak_id, key_map.get(ak_id, ""), [], [model_display])

        await session.commit()

    await load_api_keys()
    return {"updated": True}


@router.get("/models/resolve")
async def resolve_model(name: str, _: bool = Depends(permission_required("page.models"))):
    from app.services.provider import explain_provider_model_candidates

    explanation = await explain_provider_model_candidates(name)
    results = [
        {
            "provider": item["provider"],
            "actual_model": item["upstream_model_name"],
            "model_name": item["model_name"],
            "health": item["health"],
            "priority": item["effective_priority"],
            "tags": "",
        }
        for item in explanation.get("ordered", [])
    ]
    selected = results[0]["provider"] if results else None
    return {"model": name, "providers": results, "selected": selected}
