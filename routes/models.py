from fastapi import APIRouter, Depends, Cookie, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from core.database import async_session_maker, Model, ApiKey, ApiKeyModel, ProviderModel, Provider
from core.config import validate_session
from services.auth import load_api_keys

router = APIRouter(prefix="/admin/api", tags=["models"])


def require_admin(session: Optional[str] = Cookie(None)):
    if not validate_session(session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


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


@router.get("/models")
async def list_all_models(_: bool = Depends(require_admin)):
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
        for row in pm_result.fetchall():
            model_pm_map[row[0]].append(row[1])

        all_pm_ids = [pm_id for ids in model_pm_map.values() for pm_id in ids]
        pm_key_counts: dict[int, int] = {}
        if all_pm_ids:
            ak_count_result = await session.execute(
                select(ApiKeyModel.provider_model_id).where(
                    ApiKeyModel.provider_model_id.in_(all_pm_ids)
                )
            )
            for row in ak_count_result.fetchall():
                pm_key_counts[row[0]] = pm_key_counts.get(row[0], 0) + 1

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
                    "bound_key_count": sum(pm_key_counts.get(p, 0) for p in model_pm_map.get(m.id, [])),
                }
                for m in models
            ]
        }


@router.post("/models")
async def create_model(data: ModelCreate, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        model = Model(**data.model_dump())
        session.add(model)
        await session.commit()
        return {"id": model.id, "name": model.name}


@router.put("/models/{model_id}")
async def update_model(
    model_id: int, data: ModelUpdate, _: bool = Depends(require_admin)
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
async def delete_model(model_id: int, _: bool = Depends(require_admin)):
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
async def get_model_api_keys(model_id: int, _: bool = Depends(require_admin)):
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

        from core.database import ApiKeyTag

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
    model_id: int, data: ModelApiKeysUpdate, _: bool = Depends(require_admin)
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
            from services.notification import notify_model_changes_async
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
async def resolve_model(name: str, _: bool = Depends(require_admin)):
    from services.provider import _alias_index
    from services.key_health import compute_health_score

    if name not in _alias_index:
        return {"alias": name, "providers": [], "selected": None}

    candidates = _alias_index[name]
    results = []
    for provider_name, pm_dict, model_tags, priority in candidates:
        from services.provider import get_provider_config
        pc = await get_provider_config(provider_name)
        if not pc:
            continue
        keys = pc.get("api_keys") or []
        best_health = 0
        for k in keys:
            h = compute_health_score(k["id"])
            if h > best_health:
                best_health = h
        results.append({
            "provider": provider_name,
            "actual_model": pm_dict.get("actual_model_name") or name,
            "health": best_health,
            "priority": priority,
            "tags": model_tags,
        })

    results.sort(key=lambda x: (x["health"], x["priority"]), reverse=True)
    selected = results[0]["provider"] if results else None
    return {"alias": name, "providers": results, "selected": selected}
