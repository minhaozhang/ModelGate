from datetime import date, datetime, time
from typing import Any, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.core.database import (
    ProviderModel,
    ProviderModelRoutingRule,
    ProviderKey,
    ProviderKeyStrategyTemplate,
    async_session_maker,
)
from app.core.permissions import permission_required
from app.services.provider import (
    explain_provider_key_candidates,
    explain_provider_model_candidates,
    get_provider_and_model,
    load_providers,
)
from app.services.tokens import estimate_request_context_tokens

router = APIRouter(prefix="/admin/api/routing", tags=["routing"])


class StrategyTemplatePayload(BaseModel):
    name: str
    template_key: str
    description: Optional[str] = None
    is_active: bool = True
    config_schema: dict[str, Any] = {}
    rule_blueprint: dict[str, Any] = {}


class RoutingResolvePayload(BaseModel):
    model: str
    api_key_id: Optional[int] = None
    messages: list[dict[str, Any]] = []
    context_tokens: Optional[int] = None
    now: Optional[datetime] = None
    preferred_tags: Optional[str] = None


class ProviderModelRoutingRulePayload(BaseModel):
    name: Optional[str] = None
    rule_type: Optional[str] = "custom"
    enabled: bool = True
    priority: Optional[int] = 0
    start_time: Optional[Any] = None
    end_time: Optional[Any] = None
    start_date: Optional[Any] = None
    end_date: Optional[Any] = None
    weekdays: Optional[str] = None
    min_context_tokens: Optional[int] = None
    max_context_tokens: Optional[int] = None
    provider_key_ids: list[int] = []
    action: str = "prefer"


def _serialize_template(template: ProviderKeyStrategyTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "template_key": template.template_key,
        "description": template.description or "",
        "is_builtin": template.is_builtin,
        "is_active": template.is_active,
        "config_schema": template.config_schema or {},
        "rule_blueprint": template.rule_blueprint or {},
    }


def _coerce_time(value: Any) -> time | None:
    if value is None or isinstance(value, time):
        return value
    if isinstance(value, str) and value:
        try:
            hour, minute, *rest = value.split(":")
            second = int(rest[0]) if rest else 0
            return time(int(hour), int(minute), second)
        except (TypeError, ValueError):
            return None
    return None


def _coerce_date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _normalize_provider_key_ids(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    ids: list[int] = []
    seen: set[int] = set()
    for item in value:
        try:
            key_id = int(item)
        except (TypeError, ValueError):
            continue
        if key_id in seen:
            continue
        seen.add(key_id)
        ids.append(key_id)
    return ids


async def _valid_provider_key_ids(
    session,
    provider_model_id: int,
    provider_key_ids: list[int],
) -> list[int]:
    normalized_ids = _normalize_provider_key_ids(provider_key_ids)
    if not normalized_ids:
        return []
    pm_result = await session.execute(
        select(ProviderModel).where(ProviderModel.id == provider_model_id)
    )
    pm = pm_result.scalar_one_or_none()
    if not pm:
        return []
    key_result = await session.execute(
        select(ProviderKey.id).where(
            ProviderKey.provider_id == pm.provider_id,
            ProviderKey.id.in_(normalized_ids),
        )
    )
    valid_ids = {key_id for (key_id,) in key_result.all()}
    return [key_id for key_id in normalized_ids if key_id in valid_ids]


def _provider_model_rule_from_payload(
    provider_model_id: int,
    data: ProviderModelRoutingRulePayload,
    provider_key_ids: list[int] | None = None,
) -> ProviderModelRoutingRule:
    rule = ProviderModelRoutingRule(provider_model_id=provider_model_id)
    _apply_provider_model_rule_payload(rule, data, provider_key_ids=provider_key_ids)
    return rule


def _apply_provider_model_rule_payload(
    rule: ProviderModelRoutingRule,
    data: ProviderModelRoutingRulePayload,
    provider_key_ids: list[int] | None = None,
) -> None:
    rule.name = data.name or None
    rule.rule_type = data.rule_type or "custom"
    rule.enabled = data.enabled
    rule.priority = int(data.priority or 0)
    rule.start_time = _coerce_time(data.start_time)
    rule.end_time = _coerce_time(data.end_time)
    rule.start_date = _coerce_date(data.start_date)
    rule.end_date = _coerce_date(data.end_date)
    rule.weekdays = data.weekdays
    rule.min_context_tokens = data.min_context_tokens
    rule.max_context_tokens = data.max_context_tokens
    rule.provider_key_ids = provider_key_ids if provider_key_ids is not None else []
    rule.action = data.action or "prefer"


def _serialize_provider_model_rule(rule: ProviderModelRoutingRule) -> dict[str, Any]:
    return {
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


@router.get("/strategy-templates")
async def list_strategy_templates(
    _: bool = Depends(permission_required("page.providers")),
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderKeyStrategyTemplate).order_by(
                ProviderKeyStrategyTemplate.is_builtin.desc(),
                ProviderKeyStrategyTemplate.id,
            )
        )
        templates = result.scalars().all()
        return {"templates": [_serialize_template(t) for t in templates]}


@router.post("/strategy-templates")
async def create_strategy_template(
    data: StrategyTemplatePayload,
    _: bool = Depends(permission_required("provider.update_key")),
):
    async with async_session_maker() as session:
        template = ProviderKeyStrategyTemplate(
            name=data.name,
            template_key=data.template_key,
            description=data.description,
            is_builtin=False,
            is_active=data.is_active,
            config_schema=data.config_schema,
            rule_blueprint=data.rule_blueprint,
        )
        session.add(template)
        await session.commit()
        return {"id": template.id}


@router.put("/strategy-templates/{template_id}")
async def update_strategy_template(
    template_id: int,
    data: StrategyTemplatePayload,
    _: bool = Depends(permission_required("provider.update_key")),
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderKeyStrategyTemplate).where(
                ProviderKeyStrategyTemplate.id == template_id
            )
        )
        template = result.scalar_one_or_none()
        if not template:
            return JSONResponse({"error": "Template not found"}, status_code=404)
        if template.is_builtin:
            template.description = data.description
            template.is_active = data.is_active
        else:
            template.name = data.name
            template.template_key = data.template_key
            template.description = data.description
            template.is_active = data.is_active
            template.config_schema = data.config_schema
            template.rule_blueprint = data.rule_blueprint
        await session.commit()
        return {"id": template.id}


@router.get("/provider-models/{provider_model_id}/rules")
async def list_provider_model_rules(
    provider_model_id: int,
    _: bool = Depends(permission_required("page.provider_models")),
):
    async with async_session_maker() as session:
        pm_result = await session.execute(
            select(ProviderModel).where(ProviderModel.id == provider_model_id)
        )
        if not pm_result.scalar_one_or_none():
            return JSONResponse({"error": "Provider model not found"}, status_code=404)
        rules_result = await session.execute(
            select(ProviderModelRoutingRule)
            .where(ProviderModelRoutingRule.provider_model_id == provider_model_id)
            .order_by(ProviderModelRoutingRule.id)
        )
        return {
            "rules": [
                _serialize_provider_model_rule(rule)
                for rule in rules_result.scalars().all()
            ]
        }


@router.post("/provider-models/{provider_model_id}/rules")
async def create_provider_model_rule(
    provider_model_id: int,
    data: ProviderModelRoutingRulePayload,
    _: bool = Depends(permission_required("provider_model.update")),
):
    async with async_session_maker() as session:
        pm_result = await session.execute(
            select(ProviderModel).where(ProviderModel.id == provider_model_id)
        )
        if not pm_result.scalar_one_or_none():
            return JSONResponse({"error": "Provider model not found"}, status_code=404)
        provider_key_ids = await _valid_provider_key_ids(
            session,
            provider_model_id,
            data.provider_key_ids,
        )
        rule = _provider_model_rule_from_payload(
            provider_model_id,
            data,
            provider_key_ids=provider_key_ids,
        )
        session.add(rule)
        await session.flush()
        rule_id = rule.id
        await session.commit()
        await load_providers()
        return {"id": rule_id}


@router.put("/provider-model-rules/{rule_id}")
async def update_provider_model_rule(
    rule_id: int,
    data: ProviderModelRoutingRulePayload,
    _: bool = Depends(permission_required("provider_model.update")),
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderModelRoutingRule).where(ProviderModelRoutingRule.id == rule_id)
        )
        rule = result.scalar_one_or_none()
        if not rule:
            return JSONResponse({"error": "Rule not found"}, status_code=404)
        provider_key_ids = await _valid_provider_key_ids(
            session,
            rule.provider_model_id,
            data.provider_key_ids,
        )
        _apply_provider_model_rule_payload(
            rule,
            data,
            provider_key_ids=provider_key_ids,
        )
        await session.commit()
        await load_providers()
        return {"id": rule_id}


@router.delete("/provider-model-rules/{rule_id}")
async def delete_provider_model_rule(
    rule_id: int,
    _: bool = Depends(permission_required("provider_model.update")),
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProviderModelRoutingRule).where(ProviderModelRoutingRule.id == rule_id)
        )
        rule = result.scalar_one_or_none()
        if not rule:
            return JSONResponse({"error": "Rule not found"}, status_code=404)
        await session.delete(rule)
        await session.commit()
        await load_providers()
        return {"deleted": True}


@router.post("/resolve")
async def resolve_routing(
    data: RoutingResolvePayload,
    _: bool = Depends(permission_required("page.providers")),
):
    context_tokens = data.context_tokens
    if context_tokens is None:
        context_tokens = estimate_request_context_tokens({"messages": data.messages})
    now = data.now or datetime.now()
    route = await get_provider_and_model(
        data.model,
        messages=data.messages,
        preferred_tags=data.preferred_tags,
        context_tokens=context_tokens,
        now=now,
    )
    model_explanation = await explain_provider_model_candidates(
        data.model,
        messages=data.messages,
        preferred_tags=data.preferred_tags,
        context_tokens=context_tokens,
        now=now,
    )
    if not route.provider_config:
        return {
            "selected_provider": None,
            "selected_provider_model_id": None,
            "selected_provider_key_id": None,
            "context_tokens": context_tokens,
            "model_candidates": model_explanation.get("ordered", []),
            "model_filtered": model_explanation.get("filtered", []),
            "key_candidates": [],
            "key_filtered": [],
        }
    key_explanation = explain_provider_key_candidates(
        route.provider_config,
        api_key_id=data.api_key_id,
        provider_name=route.provider_name,
        context_tokens=context_tokens,
        now=now,
    )
    keys = key_explanation["ordered"]
    return {
        "selected_provider": route.provider_name,
        "selected_provider_model_id": route.provider_model_id,
        "selected_provider_key_id": keys[0]["key_id"] if keys else None,
        "context_tokens": context_tokens,
        "model_candidates": model_explanation.get("ordered", []),
        "model_filtered": model_explanation.get("filtered", []),
        "key_candidates": [
            {
                "provider": route.provider_name,
                "provider_model_id": route.provider_model_id,
                "provider_key_id": item["key_id"],
                "label": item.get("label") or "",
                "priority": item.get("priority", 0),
                "policy_priority": item.get("policy_priority", 0),
                "health": item.get("health", 100),
                "standby": item.get("standby", False),
                "matched_rules": item.get("matched_rules", []),
                "filtered_reasons": item.get("filtered_reasons", []),
                "selected": index == 0,
            }
            for index, item in enumerate(keys)
        ],
        "key_filtered": key_explanation.get("filtered", []),
    }
