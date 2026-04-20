from fastapi import APIRouter, Depends, Cookie, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.database import async_session_maker, Provider
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
    max_concurrent: Optional[int] = None
    merge_consecutive_messages: Optional[bool] = False


class ProviderUpdate(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    is_active: Optional[bool] = None
    max_concurrent: Optional[int] = None
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
                    "is_active": p.is_active,
                    "max_concurrent": p.max_concurrent or 3,
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
            max_concurrent=data.max_concurrent or 3,
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
        if data.max_concurrent is not None:
            provider.max_concurrent = data.max_concurrent
        if data.merge_consecutive_messages is not None:
            provider.merge_consecutive_messages = data.merge_consecutive_messages
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
