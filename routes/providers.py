from fastapi import APIRouter, Depends, Cookie, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.database import async_session_maker, Provider, ProviderKey
from services.provider import load_providers
from core.config import validate_session

router = APIRouter(prefix="/admin/api", tags=["providers"])


def require_admin(session: Optional[str] = Cookie(None)):
    if not validate_session(session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


class ProviderCreate(BaseModel):
    name: str
    base_url: str
    api_key: Optional[str] = None
    protocol: Optional[str] = "openai"
    merge_consecutive_messages: Optional[bool] = False


class ProviderUpdate(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    is_active: Optional[bool] = None
    protocol: Optional[str] = None
    merge_consecutive_messages: Optional[bool] = None


@router.get("/providers")
async def list_providers(_: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        result = await session.execute(select(Provider))
        providers = result.scalars().all()
        return {
            "providers": [
                {
                    "id": p.id,
                    "name": p.name,
                    "base_url": p.base_url,
                    "protocol": p.protocol or "openai",
                    "is_active": p.is_active,
                    "merge_consecutive_messages": p.merge_consecutive_messages or False,
                    "disabled_reason": p.disabled_reason,
                }
                for p in providers
            ]
        }


@router.post("/providers")
async def create_provider(data: ProviderCreate, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        provider = Provider(
            name=data.name,
            base_url=data.base_url,
            api_key=data.api_key,
            protocol=data.protocol or "openai",
            merge_consecutive_messages=data.merge_consecutive_messages or False,
        )
        session.add(provider)
        await session.commit()
        await load_providers()
        return {"id": provider.id, "name": provider.name}


@router.put("/providers/{provider_id}")
async def update_provider(
    provider_id: int, data: ProviderUpdate, _: bool = Depends(require_admin)
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        provider = result.scalar_one_or_none()
        if not provider:
            return JSONResponse({"error": "Provider not found"}, status_code=404)
        if data.base_url is not None:
            provider.base_url = data.base_url
        if data.api_key is not None:
            provider.api_key = data.api_key
        if data.is_active is not None:
            provider.is_active = data.is_active
            if data.is_active:
                provider.disabled_reason = None
        if data.merge_consecutive_messages is not None:
            provider.merge_consecutive_messages = data.merge_consecutive_messages
        if data.protocol is not None:
            provider.protocol = data.protocol
        await session.commit()
        await load_providers()
        return {"id": provider.id}


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: int, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        result = await session.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        provider = result.scalar_one_or_none()
        if not provider:
            return JSONResponse({"error": "Provider not found"}, status_code=404)
        try:
            await session.delete(provider)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return JSONResponse(
                {"error": "Cannot delete: provider has bound models. Remove all model bindings first."},
                status_code=409,
            )
        await load_providers()
        return {"deleted": True}


class ProviderKeyCreate(BaseModel):
    api_key: str
    label: Optional[str] = None
    max_concurrent: Optional[int] = None


class ProviderKeyUpdate(BaseModel):
    api_key: Optional[str] = None
    label: Optional[str] = None
    max_concurrent: Optional[int] = None
    is_active: Optional[bool] = None


@router.get("/providers/{provider_id}/keys")
async def list_provider_keys(provider_id: int, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderKey)
            .where(ProviderKey.provider_id == provider_id)
            .order_by(ProviderKey.id)
        )
        keys = result.scalars().all()
        return {
            "keys": [
                {
                    "id": k.id,
                    "api_key": k.api_key[:8] + "..." + k.api_key[-4:] if len(k.api_key) > 12 else k.api_key,
                    "label": k.label or "",
                    "max_concurrent": k.max_concurrent,
                    "is_active": k.is_active,
                    "disabled_reason": k.disabled_reason,
                }
                for k in keys
            ]
        }


@router.post("/providers/{provider_id}/keys")
async def create_provider_key(
    provider_id: int, data: ProviderKeyCreate, _: bool = Depends(require_admin)
):
    async with async_session_maker() as session:
        provider_result = await session.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        if not provider_result.scalar_one_or_none():
            return JSONResponse({"error": "Provider not found"}, status_code=404)
        pk = ProviderKey(
            provider_id=provider_id,
            api_key=data.api_key,
            label=data.label,
            max_concurrent=data.max_concurrent,
        )
        session.add(pk)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return JSONResponse(
                {"error": "该 API Key 已存在"}, status_code=409
            )
        await load_providers()
        return {"id": pk.id}


@router.put("/providers/{provider_id}/keys/{key_id}")
async def update_provider_key(
    provider_id: int,
    key_id: int,
    data: ProviderKeyUpdate,
    _: bool = Depends(require_admin),
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderKey).where(
                ProviderKey.id == key_id,
                ProviderKey.provider_id == provider_id,
            )
        )
        pk = result.scalar_one_or_none()
        if not pk:
            return JSONResponse({"error": "Key not found"}, status_code=404)
        if "api_key" in data.model_fields_set and data.api_key is not None:
            pk.api_key = data.api_key
        if "label" in data.model_fields_set:
            pk.label = data.label
        if "max_concurrent" in data.model_fields_set:
            pk.max_concurrent = data.max_concurrent
        if "is_active" in data.model_fields_set and data.is_active is not None:
            pk.is_active = data.is_active
            if data.is_active:
                pk.disabled_reason = None
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return JSONResponse(
                {"error": "该 API Key 已存在"}, status_code=409
            )
        await load_providers()
        return {"id": pk.id}


@router.delete("/providers/{provider_id}/keys/{key_id}")
async def delete_provider_key(
    provider_id: int, key_id: int, _: bool = Depends(require_admin)
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderKey).where(
                ProviderKey.id == key_id,
                ProviderKey.provider_id == provider_id,
            )
        )
        pk = result.scalar_one_or_none()
        if not pk:
            return JSONResponse({"error": "Key not found"}, status_code=404)
        await session.delete(pk)
        await session.commit()
        await load_providers()
        return {"deleted": True}
