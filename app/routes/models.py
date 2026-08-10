from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from typing import Optional, Union
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from app.core.database import (
    async_session_maker,
    Model,
    ApiKey,
    ApiKeyModelAccess,
    ApiKeyTag,
)
from app.core.permissions import permission_required
from app.services.auth import load_api_keys
from app.services.auto_model_routes import (
    AUTO_MODEL_NAME,
    get_auto_model_route as get_auto_model_route_record,
    normalize_auto_model_route,
    update_auto_model_route as update_auto_model_route_record,
)

router = APIRouter(prefix="/admin/api", tags=["models"])


class ModelCreate(BaseModel):
    name: str
    display_name: Optional[str] = None
    max_tokens: int = 131072
    context_length: int = 204800
    thinking_enabled: bool = True
    thinking_budget: int = 8192
    reasoning_effort: Optional[str] = None
    is_multimodal: bool = False
    is_active: bool = True
    tags: Optional[str] = None


class ModelUpdate(BaseModel):
    display_name: Optional[str] = None
    max_tokens: Optional[int] = None
    context_length: Optional[int] = None
    thinking_enabled: Optional[bool] = None
    thinking_budget: Optional[int] = None
    reasoning_effort: Optional[str] = None
    is_multimodal: Optional[bool] = None
    is_active: Optional[bool] = None
    estimated_price: Optional[float] = None
    tags: Optional[str] = None


class AutoPoolItem(BaseModel):
    id: int
    min_ctx: Optional[int] = None
    max_ctx: Optional[int] = None


class AutoModelConfigUpdate(BaseModel):
    enabled: bool = False
    model_ids: list[int] = Field(default_factory=list)
    provider_model_ids: list[Union[AutoPoolItem, int]] = Field(default_factory=list)


class ModelApiKeysUpdate(BaseModel):
    api_key_ids: list[int] = Field(default_factory=list)


@router.get("/routing/auto-model")
async def get_auto_model_config(_: bool = Depends(permission_required("page.models"))):
    async with async_session_maker() as session:
        return await get_auto_model_route_record(session, AUTO_MODEL_NAME)


@router.put("/routing/auto-model")
async def update_auto_model_config(
    data: AutoModelConfigUpdate,
    _: bool = Depends(permission_required("model.update")),
):
    payload = normalize_auto_model_route(data.model_dump())
    async with async_session_maker() as session:
        payload = await update_auto_model_route_record(session, payload, AUTO_MODEL_NAME)
    from app.services.provider import load_providers

    await load_providers()

    await load_api_keys()
    return payload


@router.get("/models")
async def list_all_models(_: bool = Depends(permission_required("page.models"))):
    async with async_session_maker() as session:
        result = await session.execute(select(Model).order_by(Model.name))
        models = result.scalars().all()

        model_ids = [m.id for m in models]
        model_key_ids: dict[int, set[int]] = {m.id: set() for m in models}
        if model_ids:
            valid_key_ids = {
                r[0] for r in (await session.execute(select(ApiKey.id))).fetchall()
            }
            model_access_result = await session.execute(
                select(ApiKeyModelAccess.model_id, ApiKeyModelAccess.api_key_id).where(
                    ApiKeyModelAccess.model_id.in_(model_ids)
                )
            )
            for row in model_access_result.fetchall():
                if row[1] not in valid_key_ids:
                    continue
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
                    "reasoning_effort": m.reasoning_effort,
                    "is_multimodal": m.is_multimodal,
                    "is_active": m.is_active,
                    "is_virtual": bool(getattr(m, "is_virtual", False)),
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


@router.get("/models/{model_id}/api-keys")
async def get_model_api_keys(
    model_id: int,
    _: bool = Depends(permission_required("model.update")),
):
    async with async_session_maker() as session:
        model_result = await session.execute(select(Model).where(Model.id == model_id))
        if model_result.scalar_one_or_none() is None:
            return JSONResponse({"error": "Model not found"}, status_code=404)

        keys_result = await session.execute(select(ApiKey).order_by(ApiKey.name))
        keys = keys_result.scalars().all()

        tag_rows: list[tuple[int, str]] = []
        if keys:
            tag_result = await session.execute(
                select(ApiKeyTag.api_key_id, ApiKeyTag.tag).where(
                    ApiKeyTag.api_key_id.in_([k.id for k in keys])
                )
            )
            tag_rows = [(int(r[0]), str(r[1])) for r in tag_result.fetchall()]

        tags_by_key: dict[int, list[str]] = {}
        for ak_id, tag in tag_rows:
            tags_by_key.setdefault(ak_id, []).append(tag)

        bound_result = await session.execute(
            select(ApiKeyModelAccess.api_key_id).where(
                ApiKeyModelAccess.model_id == model_id
            )
        )
        bound_ids = [int(r[0]) for r in bound_result.fetchall()]

        now = datetime.now()
        api_keys_out = []
        for k in keys:
            api_keys_out.append({
                "id": k.id,
                "name": k.name,
                "email": k.email,
                "is_active": bool(k.is_active),
                "is_expired": bool(k.expires_at and k.expires_at < now),
                "tags": tags_by_key.get(k.id, []),
            })

        return {
            "model_id": model_id,
            "api_keys": api_keys_out,
            "bound_key_ids": bound_ids,
        }


@router.put("/models/{model_id}/api-keys")
async def update_model_api_keys(
    model_id: int,
    data: ModelApiKeysUpdate,
    _: bool = Depends(permission_required("model.update")),
):
    raw_ids = [int(x) for x in data.api_key_ids]
    if any(x <= 0 for x in raw_ids):
        return JSONResponse(
            {"error": "api_key_ids must be positive integers"},
            status_code=400,
        )
    target_ids = sorted(set(raw_ids))
    async with async_session_maker() as session:
        model_result = await session.execute(select(Model).where(Model.id == model_id))
        if model_result.scalar_one_or_none() is None:
            return JSONResponse({"error": "Model not found"}, status_code=404)

        try:
            if target_ids:
                await session.execute(
                    delete(ApiKeyModelAccess)
                    .where(ApiKeyModelAccess.model_id == model_id)
                    .where(ApiKeyModelAccess.api_key_id.not_in(target_ids))
                )
                existing_result = await session.execute(
                    select(ApiKeyModelAccess.api_key_id).where(
                        ApiKeyModelAccess.model_id == model_id
                    )
                )
                existing_ids = {int(r[0]) for r in existing_result.fetchall()}
                for ak_id in target_ids:
                    if ak_id not in existing_ids:
                        session.add(ApiKeyModelAccess(api_key_id=ak_id, model_id=model_id))
            else:
                await session.execute(
                    delete(ApiKeyModelAccess).where(
                        ApiKeyModelAccess.model_id == model_id
                    )
                )
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return JSONResponse(
                {"error": "One or more api_key_ids do not exist"},
                status_code=400,
            )
    await load_api_keys()
    return {"model_id": model_id, "api_key_ids": target_ids}
