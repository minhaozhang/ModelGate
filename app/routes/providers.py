from datetime import datetime

from fastapi import APIRouter, Depends, Cookie, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_maker, Provider, ProviderKey
from app.core.permissions import permission_required, login_required
from app.services.provider import invalidate_provider_sticky_cache, load_providers
from app.services.disable_schedule import normalize_rules, schedule_active
from app.services.key_health import compute_health_score, get_health_level, get_events_5m

router = APIRouter(prefix="/admin/api", tags=["providers"])


class ProviderCreate(BaseModel):
    name: str
    base_url: str
    protocol: Optional[str] = "openai"
    merge_consecutive_messages: Optional[bool] = False

    @field_validator("base_url")
    @classmethod
    def _strip_base_url(cls, v: str) -> str:
        return v.strip()


class ProviderUpdate(BaseModel):
    base_url: Optional[str] = None
    is_active: Optional[bool] = None
    protocol: Optional[str] = None
    merge_consecutive_messages: Optional[bool] = None
    disable_schedule: Optional[list] = None

    @field_validator("base_url")
    @classmethod
    def _strip_base_url(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v is not None else v


@router.get("/provider-status")
async def get_admin_provider_status(_: bool = Depends(login_required)):
    from app.services.provider_limiter import get_disabled_providers_status

    return await get_disabled_providers_status()


@router.get("/providers")
async def list_providers(_: bool = Depends(permission_required("page.providers"))):
    async with async_session_maker() as session:
        result = await session.execute(select(Provider))
        providers = result.scalars().all()
        stats_result = await session.execute(
            select(
                ProviderKey.provider_id,
                func.count(ProviderKey.id).label("total"),
                func.sum(case((ProviderKey.is_active == True, 1), else_=0)).label("active"),  # noqa: E712
            ).group_by(ProviderKey.provider_id)
        )
        key_stats = {
            row.provider_id: (int(row.total), int(row.active or 0))
            for row in stats_result
        }
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
                    "disable_schedule": p.disable_schedule or [],
                    "schedule_active_now": schedule_active(p.disable_schedule),
                    "keys_total": key_stats.get(p.id, (0, 0))[0],
                    "keys_active": key_stats.get(p.id, (0, 0))[1],
                }
                for p in providers
            ]
        }


@router.post("/providers")
async def create_provider(data: ProviderCreate, _: bool = Depends(permission_required("provider.create"))):
    async with async_session_maker() as session:
        provider = Provider(
            name=data.name,
            base_url=data.base_url,
            protocol=data.protocol or "openai",
            merge_consecutive_messages=data.merge_consecutive_messages or False,
        )
        session.add(provider)
        await session.commit()
        await load_providers()
        return {"id": provider.id, "name": provider.name}


@router.put("/providers/{provider_id}")
async def update_provider(
    provider_id: int, data: ProviderUpdate, _: bool = Depends(permission_required("provider.update"))
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
        if data.is_active is not None:
            provider.is_active = data.is_active
            if data.is_active:
                provider.disabled_by = None
                provider.disabled_reason = None
                provider.disabled_at = None
                provider.reset_at = None
            else:
                provider.disabled_by = "manual"
                provider.disabled_at = datetime.now()
        if data.merge_consecutive_messages is not None:
            provider.merge_consecutive_messages = data.merge_consecutive_messages
        if data.protocol is not None:
            provider.protocol = data.protocol
        if "disable_schedule" in data.model_fields_set and data.disable_schedule is not None:
            provider.disable_schedule = normalize_rules(data.disable_schedule)
        await session.commit()
        await load_providers()
        return {"id": provider.id}


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: int, _: bool = Depends(permission_required("provider.delete"))):
    from app.core.database import ProviderModel, Model
    from sqlalchemy import func

    async with async_session_maker() as session:
        result = await session.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        provider = result.scalar_one_or_none()
        if not provider:
            return JSONResponse({"error": "Provider not found"}, status_code=404)

        bound_result = await session.execute(
            select(Model.name)
            .select_from(ProviderModel)
            .join(Model, Model.id == ProviderModel.model_id)
            .where(ProviderModel.provider_id == provider_id)
            .order_by(Model.name)
            .limit(10)
        )
        bound_models = [row[0] for row in bound_result.fetchall()]
        if bound_models:
            total_result = await session.execute(
                select(func.count()).select_from(ProviderModel).where(
                    ProviderModel.provider_id == provider_id
                )
            )
            total = total_result.scalar() or len(bound_models)
            more = f" 等 {total} 个模型" if total > len(bound_models) else ""
            return JSONResponse(
                {
                    "error": (
                        f"无法删除供应商「{provider.name}」：仍有 {total} 个模型绑定"
                        f"（{'、'.join(bound_models)}{more}）。"
                        f"请先在「供应商与模型」中解除这些绑定后再删除。"
                    )
                },
                status_code=409,
            )

        pk_result = await session.execute(
            select(func.count()).select_from(ProviderKey).where(
                ProviderKey.provider_id == provider_id
            )
        )
        pk_count = pk_result.scalar() or 0
        if pk_count > 0:
            return JSONResponse(
                {
                    "error": (
                        f"无法删除供应商「{provider.name}」：名下仍有 {pk_count} 个供应商 Key，"
                        f"删除会连同这些 Key 一起丢失。请先在「供应商 Key」中处理后再删除。"
                    )
                },
                status_code=409,
            )

        try:
            await session.delete(provider)
            await session.commit()
        except IntegrityError:
            try:
                await session.rollback()
            except Exception:
                pass
            return JSONResponse(
                {"error": f"无法删除供应商「{provider.name}」：仍有关联数据引用它，请先解除相关绑定。"},
                status_code=409,
            )
        await load_providers()
        return {"deleted": True}


class ProviderKeyCreate(BaseModel):
    api_key: str
    label: Optional[str] = None
    max_concurrent: Optional[int] = Field(None, ge=0)
    priority: Optional[int] = 0
    cost_role: Optional[str] = "standard"


class ProviderKeyUpdate(BaseModel):
    api_key: Optional[str] = None
    label: Optional[str] = None
    max_concurrent: Optional[int] = Field(None, ge=0)
    priority: Optional[int] = None
    cost_role: Optional[str] = None
    is_active: Optional[bool] = None
    disabled_reason: Optional[str] = None
    disable_schedule: Optional[list] = None


@router.get("/providers/{provider_id}/keys")
async def list_provider_keys(provider_id: int, _: bool = Depends(permission_required("page.providers"))):
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
                    "disabled_by": getattr(k, "disabled_by", None),
                    "disabled_reason": k.disabled_reason,
                    "priority": k.priority if hasattr(k, "priority") else 0,
                    "cost_role": getattr(k, "cost_role", None) or "standard",
                    "disable_schedule": k.disable_schedule or [],
                    "schedule_active_now": schedule_active(k.disable_schedule),
                    "health_score": compute_health_score(k.id, is_active=k.is_active),
                }
                for k in keys
            ]
        }


@router.post("/providers/{provider_id}/keys")
async def create_provider_key(
    provider_id: int, data: ProviderKeyCreate, _: bool = Depends(permission_required("provider.add_key"))
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
            priority=data.priority or 0,
            cost_role=data.cost_role or "standard",
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
    _: bool = Depends(permission_required("provider.update_key")),
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
        if "priority" in data.model_fields_set:
            pk.priority = data.priority or 0
        if "cost_role" in data.model_fields_set:
            pk.cost_role = data.cost_role or "standard"
        if "is_active" in data.model_fields_set and data.is_active is not None:
            pk.is_active = data.is_active
            if data.is_active:
                pk.disabled_by = None
                pk.disabled_reason = None
                pk.disabled_at = None
                pk.reset_at = None
            else:
                pk.disabled_by = "manual"
                pk.disabled_reason = None
                pk.disabled_at = datetime.now()
                pk.reset_at = None
        if "disabled_reason" in data.model_fields_set:
            pk.disabled_reason = data.disabled_reason
        if "disable_schedule" in data.model_fields_set and data.disable_schedule is not None:
            pk.disable_schedule = normalize_rules(data.disable_schedule)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return JSONResponse(
                {"error": "该 API Key 已存在"}, status_code=409
            )
        if "is_active" in data.model_fields_set and data.is_active is not None:
            from app.services.provider_limiter import cancel_reenable_job

            cancel_reenable_job("key", key_id)
        ordering_fields = (
            "priority",
            "max_concurrent",
            "cost_role",
            "is_active",
            "api_key",
            "disable_schedule",
        )
        if any(field in data.model_fields_set for field in ordering_fields):
            name_result = await session.execute(
                select(Provider.name).where(Provider.id == provider_id)
            )
            provider_name = name_result.scalar_one_or_none()
            if provider_name:
                await invalidate_provider_sticky_cache(provider_name)
        await load_providers()
        return {"id": pk.id}


@router.delete("/providers/{provider_id}/keys/{key_id}")
async def delete_provider_key(
    provider_id: int, key_id: int, _: bool = Depends(permission_required("provider.delete_key"))
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


@router.get("/providers/{provider_id}/keys/health")
async def get_provider_keys_health(provider_id: int, _: bool = Depends(permission_required("page.providers"))):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderKey)
            .where(ProviderKey.provider_id == provider_id)
            .order_by(ProviderKey.id)
        )
        keys = result.scalars().all()
        keys_data = []
        for k in keys:
            score = compute_health_score(k.id, is_active=k.is_active)
            level = get_health_level(score)
            events = get_events_5m(k.id)
            keys_data.append({
                "key_id": k.id,
                "label": k.label or "",
                "is_active": k.is_active,
                "health_score": score,
                "health_level": level,
                "events_5m": events,
                "disabled_by": getattr(k, "disabled_by", None),
                "disabled_reason": k.disabled_reason,
            })
        return {"keys": keys_data}
