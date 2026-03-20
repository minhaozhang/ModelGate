from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select, func, delete

from database import (
    async_session_maker,
    ApiKey,
    ApiKeyModel,
    RequestLog,
    generate_api_key,
)
from services.proxy import load_api_keys

router = APIRouter(tags=["api-keys"])


class ApiKeyCreate(BaseModel):
    name: str
    allowed_provider_model_ids: list[int] = []


class ApiKeyUpdate(BaseModel):
    name: Optional[str] = None
    allowed_provider_model_ids: Optional[list[int]] = None
    is_active: Optional[bool] = None


@router.get("/api/keys")
async def list_api_keys():
    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey))
        keys = result.scalars().all()
        api_keys = []
        for k in keys:
            models_result = await session.execute(
                select(ApiKeyModel.provider_model_id).where(
                    ApiKeyModel.api_key_id == k.id
                )
            )
            model_ids = [row[0] for row in models_result.fetchall()]
            api_keys.append(
                {
                    "id": k.id,
                    "name": k.name,
                    "key": k.key,
                    "allowed_provider_model_ids": model_ids,
                    "is_active": k.is_active,
                }
            )
        return {"api_keys": api_keys}


@router.post("/api/keys")
async def create_api_key(data: ApiKeyCreate):
    async with async_session_maker() as session:
        new_key = ApiKey(name=data.name, key=generate_api_key())
        session.add(new_key)
        await session.commit()
        await session.refresh(new_key)

        for pm_id in data.allowed_provider_model_ids:
            assoc = ApiKeyModel(api_key_id=new_key.id, provider_model_id=pm_id)
            session.add(assoc)
        await session.commit()
        await load_api_keys()
        return {"id": new_key.id, "name": new_key.name, "key": new_key.key}


@router.put("/api/keys/{key_id}")
async def update_api_key(key_id: int, data: ApiKeyUpdate):
    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "API key not found"}, status_code=404)
        if data.name is not None:
            key.name = data.name
        if data.is_active is not None:
            key.is_active = data.is_active
        if data.allowed_provider_model_ids is not None:
            await session.execute(
                delete(ApiKeyModel).where(ApiKeyModel.api_key_id == key_id)
            )
            for pm_id in data.allowed_provider_model_ids:
                assoc = ApiKeyModel(api_key_id=key_id, provider_model_id=pm_id)
                session.add(assoc)
        await session.commit()
        await load_api_keys()
        return {"id": key.id}


@router.delete("/api/keys/{key_id}")
async def delete_api_key(key_id: int):
    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "API key not found"}, status_code=404)
        await session.execute(
            delete(ApiKeyModel).where(ApiKeyModel.api_key_id == key_id)
        )
        await session.delete(key)
        await session.commit()
        await load_api_keys()
        return {"deleted": True}


@router.get("/api-keys/{key_id}/stats")
async def get_api_key_stats(key_id: int):
    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
        key = result.scalar_one_or_none()
        if not key:
            return JSONResponse({"error": "API key not found"}, status_code=404)

        total_result = await session.execute(
            select(func.count(RequestLog.id)).where(RequestLog.api_key_id == key_id)
        )
        total_requests = total_result.scalar() or 0

        tokens_result = await session.execute(
            select(func.sum(RequestLog.tokens["total_tokens"].as_integer())).where(
                RequestLog.api_key_id == key_id
            )
        )
        total_tokens = tokens_result.scalar() or 0

        errors_result = await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.api_key_id == key_id, RequestLog.status == "error"
            )
        )
        total_errors = errors_result.scalar() or 0

        model_stats_result = await session.execute(
            select(
                RequestLog.model,
                func.count(RequestLog.id).label("count"),
                func.sum(RequestLog.tokens["total_tokens"].as_integer()).label(
                    "tokens"
                ),
            )
            .where(RequestLog.api_key_id == key_id)
            .group_by(RequestLog.model)
        )
        model_stats = {
            row.model: {"requests": row.count, "tokens": row.tokens or 0}
            for row in model_stats_result
        }

        return {
            "name": key.name,
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "models": model_stats,
        }


@router.get("/api-keys/{key_id}/logs")
async def get_api_key_logs(key_id: int, limit: int = 100):
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog)
            .where(RequestLog.api_key_id == key_id)
            .order_by(RequestLog.created_at.desc())
            .limit(limit)
        )
        logs = result.scalars().all()
        return {
            "logs": [
                {
                    "id": log.id,
                    "model": log.model,
                    "status": log.status,
                    "latency_ms": log.latency_ms,
                    "tokens": log.tokens,
                    "created_at": log.created_at.isoformat(),
                    "response": log.response,
                    "error": log.error,
                }
                for log in logs
            ]
        }
