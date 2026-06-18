import random
import time
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy import select

import app.core.config as config

from app.core.config import (
    providers_cache,
    PROVIDERS_CACHE_TTL_MINUTES,
    logger,
    provider_key_model_semaphores,
    provider_key_semaphores,
)
from app.core.database import (
    async_session_maker,
    Provider,
    ProviderKey,
    ProviderModelRoutingRule,
    ProviderModel,
    Model,
)
from app.services.key_health import compute_health_score
from app.services.provider_key_routing import (
    RoutingContext,
    evaluate_provider_key_candidates,
    rule_matches,
)
from app.services.auto_model_routes import (
    AUTO_MODEL_NAME,
    get_cached_auto_model_route,
    is_cached_auto_model_enabled,
    load_auto_model_routes_cache,
)

KEY_STICKY_TTL_SECONDS = 1800
_key_sticky_map: dict[tuple[int, str], tuple[int, float]] = {}

_alias_index: dict[str, list[tuple[str, dict, str, int]]] = {}
_model_name_index: dict[str, list[tuple[str, dict, str, int]]] = {}
_model_id_by_name: dict[str, int] = {}


@dataclass
class RouteResult:
    provider_config: Optional[dict]
    upstream_model_name: str
    provider_name: str
    provider_id: int | None = None
    provider_model_id: int | None = None
    model_id: int | None = None
    requested_model_id: int | None = None
    requested_model: str = ""
    model_name: str = ""
    is_forced_provider: bool = False
    provider_key_ids: list[int] | None = None

    def __iter__(self):
        yield self.provider_config
        yield self.upstream_model_name
        yield self.provider_name


def _serialize_provider_model_rule(rule: ProviderModelRoutingRule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name or "",
        "rule_type": rule.rule_type,
        "enabled": rule.enabled,
        "priority": rule.priority or 0,
        "start_time": rule.start_time,
        "end_time": rule.end_time,
        "start_date": rule.start_date,
        "end_date": rule.end_date,
        "weekdays": rule.weekdays,
        "min_context_tokens": rule.min_context_tokens,
        "max_context_tokens": rule.max_context_tokens,
        "provider_key_ids": rule.provider_key_ids or [],
        "action": rule.action,
    }


async def _load_provider_keys(session, provider_id: int) -> tuple[list[dict], list[str], list[dict]]:
    active_result = await session.execute(
        select(ProviderKey).where(
            ProviderKey.provider_id == provider_id,
            ProviderKey.is_active == True,  # noqa: E712
        )
    )
    active_key_rows = active_result.scalars().all()
    active_keys = [
        {
            "id": pk.id,
            "api_key": pk.api_key,
            "label": pk.label or "",
            "max_concurrent": pk.max_concurrent,
            "priority": pk.priority if hasattr(pk, "priority") else 0,
            "cost_role": getattr(pk, "cost_role", None) or "standard",
        }
        for pk in active_key_rows
    ]
    disabled_result = await session.execute(
        select(ProviderKey).where(
            ProviderKey.provider_id == provider_id,
            ProviderKey.is_active == False,  # noqa: E712
            ProviderKey.disabled_reason.isnot(None),
            ProviderKey.disabled_reason != "",
        )
    )
    disabled_key_rows = disabled_result.scalars().all()
    disabled_keys = [
        {
            "id": pk.id,
            "label": pk.label or "",
            "priority": pk.priority if hasattr(pk, "priority") else 0,
            "disabled_reason": pk.disabled_reason or "",
        }
        for pk in disabled_key_rows
        if pk.disabled_reason
    ]
    disabled_keys.sort(key=lambda item: int(item.get("priority") or 0), reverse=True)
    reasons = [item["disabled_reason"] for item in disabled_keys]
    return active_keys, reasons, disabled_keys


def pick_api_key(
    provider_config: dict, api_key_id: int | None, provider_name: str
) -> tuple[str | None, int | None]:
    keys = [
        key
        for key in (provider_config.get("api_keys") or [])
        if key.get("is_active", True)
    ]
    if not keys:
        fallback = provider_config.get("api_key") or ""
        if fallback:
            return fallback, None
        return None, None
    if api_key_id is not None:
        sticky = _key_sticky_map.get((api_key_id, provider_name))
        if sticky:
            key_id, ts = sticky
            if time.monotonic() - ts < KEY_STICKY_TTL_SECONDS:
                for k in keys:
                    if k["id"] == key_id:
                        return k["api_key"], k["id"]
    chosen = random.choice(keys)
    if api_key_id is not None:
        _key_sticky_map[(api_key_id, provider_name)] = (chosen["id"], time.monotonic())
    return chosen["api_key"], chosen["id"]


def pick_api_keys(
    provider_config: dict,
    api_key_id: int | None,
    provider_name: str,
    context_tokens: int = 0,
    now: datetime | None = None,
    standby_open: bool = False,
    allowed_key_ids: list[int] | set[int] | None = None,
) -> list[tuple[str, int | None]]:
    explanation = explain_provider_key_candidates(
        provider_config,
        api_key_id,
        provider_name,
        context_tokens=context_tokens,
        now=now,
        standby_open=standby_open,
        allowed_key_ids=allowed_key_ids,
    )
    return [
        (item["api_key"], item["key_id"])
        for item in explanation["ordered"]
        if item.get("api_key")
    ]


def explain_provider_key_candidates(
    provider_config: dict,
    api_key_id: int | None,
    provider_name: str,
    context_tokens: int = 0,
    now: datetime | None = None,
    standby_open: bool = False,
    allowed_key_ids: list[int] | set[int] | None = None,
) -> dict:
    allowed_key_id_set = {
        int(key_id)
        for key_id in (allowed_key_ids or [])
        if key_id is not None
    }
    scope_filtered = []
    keys = [
        key
        for key in (provider_config.get("api_keys") or [])
        if key.get("is_active", True)
    ]
    if allowed_key_id_set:
        scoped_keys = []
        for key in keys:
            key_id = key.get("id")
            if key_id in allowed_key_id_set:
                scoped_keys.append(key)
                continue
            scope_filtered.append(
                {
                    "key_id": key_id,
                    "label": key.get("label") or f"Key #{key_id}",
                    "priority": int(key.get("priority") or 0),
                    "health": compute_health_score(key_id) if key_id is not None else 100,
                    "policy_priority": 0,
                    "sticky": False,
                    "standby": False,
                    "matched_rules": [],
                    "filtered_reasons": ["route_key_scope"],
                    "api_key": None,
                }
            )
        keys = scoped_keys
    if not keys:
        fallback = provider_config.get("api_key") or ""
        if fallback and not allowed_key_id_set:
            return {
                "ordered": [
                    {
                        "key_id": None,
                        "label": "default",
                        "api_key": fallback,
                        "priority": 0,
                        "health": 100,
                        "policy_priority": 0,
                        "sticky": False,
                        "standby": False,
                        "matched_rules": [],
                        "filtered_reasons": [],
                    }
                ],
                "filtered": scope_filtered,
            }
        return {"ordered": [], "filtered": scope_filtered}
    sticky_key_id = None
    if api_key_id is not None:
        sticky = _key_sticky_map.get((api_key_id, provider_name))
        if sticky:
            key_id, ts = sticky
            if time.monotonic() - ts < KEY_STICKY_TTL_SECONDS:
                sticky_key_id = key_id
    evaluation = evaluate_provider_key_candidates(
        keys,
        RoutingContext(
            now=now or datetime.now(),
            context_tokens=context_tokens,
            sticky_key_id=sticky_key_id,
            standby_open=standby_open,
        ),
    )
    ordered = []
    for candidate in evaluation.ordered:
        item = candidate.to_dict()
        item["api_key"] = candidate.api_key
        ordered.append(item)
    if ordered and api_key_id is not None and ordered[0].get("key_id") is not None:
        _key_sticky_map[(api_key_id, provider_name)] = (
            ordered[0]["key_id"],
            time.monotonic(),
        )
    filtered = []
    for candidate in evaluation.filtered:
        item = candidate.to_dict()
        item["api_key"] = None
        filtered.append(item)
    return {"ordered": ordered, "filtered": scope_filtered + filtered}


async def invalidate_provider_key_sticky_cache(
    provider_name: str,
    provider_key_id: int,
) -> None:
    stale_keys = [
        sticky_key
        for sticky_key, sticky_value in _key_sticky_map.items()
        if sticky_key[1] == provider_name and sticky_value[0] == provider_key_id
    ]
    for sticky_key in stale_keys:
        _key_sticky_map.pop(sticky_key, None)


def parse_model(model: str) -> tuple[str, str]:
    if "/" in model:
        parts = model.split("/", 1)
        return parts[0], parts[1]
    return "", model


def _get_model_aliases(pm: dict) -> set[str]:
    aliases: set[str] = set()
    for value in (
        pm.get("model_name"),
        pm.get("actual_model_name"),
        pm.get("upstream_model_name"),
    ):
        if not value:
            continue
        aliases.add(value)
        aliases.add(value.split("/")[-1])
    return aliases


async def load_providers():
    async with async_session_maker() as session:
        await load_auto_model_routes_cache(session)
        result = await session.execute(
            select(Provider).where(Provider.is_active == True)  # noqa: E712
        )
        providers = result.scalars().all()

        providers_cache.clear()
        _alias_index.clear()
        _model_name_index.clear()
        _model_id_by_name.clear()
        model_id_result = await session.execute(select(Model.id, Model.name))
        for model_id, model_name in model_id_result.fetchall():
            _model_id_by_name[model_name] = model_id
        for p in providers:
            pm_result = await session.execute(
                select(ProviderModel, Model)
                .where(
                    ProviderModel.provider_id == p.id,
                    ProviderModel.is_active == True,
                )
                .join(Model, ProviderModel.model_id == Model.id)
            )
            provider_models_data = []
            pm_rows = pm_result.all()
            pm_ids = [pm.id for pm, _model in pm_rows]
            rules_by_pm: dict[int, list[dict]] = {pm_id: [] for pm_id in pm_ids}
            if pm_ids:
                pm_rules_result = await session.execute(
                    select(ProviderModelRoutingRule).where(
                        ProviderModelRoutingRule.provider_model_id.in_(pm_ids),
                        ProviderModelRoutingRule.enabled == True,  # noqa: E712
                    )
                )
                for rule in pm_rules_result.scalars().all():
                    rules_by_pm.setdefault(rule.provider_model_id, []).append(
                        _serialize_provider_model_rule(rule)
                    )
            for pm, model in pm_rows:
                model_tags = model.tags if model else None
                pm_alias = pm.alias if hasattr(pm, "alias") else None
                pm_priority = pm.priority if hasattr(pm, "priority") else 0
                standard_model_name = model.name if model else None
                upstream_model_name = (
                    getattr(pm, "upstream_model_name", None)
                    or pm.model_name_override
                    or standard_model_name
                )
                provider_models_data.append(
                    {
                        "id": pm.id,
                        "model_id": model.id if model else None,
                        "model_name": standard_model_name,
                        "upstream_model_name": upstream_model_name,
                        "actual_model_name": standard_model_name,
                        "is_multimodal": model.is_multimodal if model else False,
                        "max_tokens": model.max_tokens if model else 131072,
                        "thinking_enabled": model.thinking_enabled if model else False,
                        "thinking_budget": model.thinking_budget if model else 8192,
                        "max_busyness_level": pm.max_busyness_level,
                        "model_tags": model_tags,
                        "alias": pm_alias,
                        "priority": pm_priority or 0,
                        "routing_rules": rules_by_pm.get(pm.id, []),
                    }
                )
                if standard_model_name:
                    if standard_model_name not in _model_name_index:
                        _model_name_index[standard_model_name] = []
                    _model_name_index[standard_model_name].append(
                        (p.name, provider_models_data[-1], model_tags or "", pm_priority or 0)
                    )
                if pm_alias:
                    if pm_alias not in _alias_index:
                        _alias_index[pm_alias] = []
                    _alias_index[pm_alias].append(
                        (p.name, provider_models_data[-1], model_tags or "", pm_priority or 0)
                    )

            active_keys, disabled_reasons, disabled_keys = await _load_provider_keys(session, p.id)
            providers_cache[p.name] = {
                "id": p.id,
                "base_url": p.base_url,
                "api_key": p.api_key or "",
                "protocol": p.protocol or "openai",
                "models": provider_models_data,
                "merge_consecutive_messages": p.merge_consecutive_messages or False,
                "disabled_reason": p.disabled_reason,
                "api_keys": active_keys,
                "disabled_key_reasons": disabled_reasons,
                "disabled_keys": disabled_keys,
            }

        config.providers_cache_time = datetime.now()

    # Drop idle semaphores for removed/deactivated provider keys after cache refresh.
    active_provider_key_prefixes = {
        f"{pk['id']}:{provider_name}"
        for provider_name, provider_config in providers_cache.items()
        for pk in provider_config.get("api_keys", [])
        if pk.get("id") is not None
    }
    for sem_key in list(provider_key_semaphores.keys()):
        if sem_key in active_provider_key_prefixes:
            continue
        semaphore = provider_key_semaphores.get(sem_key)
        if semaphore is None:
            continue
        waiters = getattr(semaphore, "_waiters", None)
        available = getattr(semaphore, "_value", 0)
        current_limit = getattr(semaphore, "_modelgate_scoped_limit", available) or available
        in_flight = max(current_limit - available, 0)
        if in_flight == 0 and not waiters:
            provider_key_semaphores.pop(sem_key, None)
    for sem_key in list(provider_key_model_semaphores.keys()):
        if any(sem_key.startswith(prefix + "/") for prefix in active_provider_key_prefixes):
            continue
        semaphore = provider_key_model_semaphores.get(sem_key)
        if semaphore is None:
            continue
        waiters = getattr(semaphore, "_waiters", None)
        available = getattr(semaphore, "_value", 0)
        current_limit = getattr(semaphore, "_modelgate_scoped_limit", available) or available
        in_flight = max(current_limit - available, 0)
        if in_flight == 0 and not waiters:
            provider_key_model_semaphores.pop(sem_key, None)


async def get_provider_config(provider_name: str) -> Optional[dict]:
    if provider_name in providers_cache:
        return providers_cache.get(provider_name)
    if config.providers_cache_time is None or (
        datetime.now() - config.providers_cache_time
    ) > timedelta(minutes=PROVIDERS_CACHE_TTL_MINUTES):
        await load_providers()
    return providers_cache.get(provider_name)


def get_model_config(provider_config: dict, model_name: str) -> Optional[dict]:
    if not provider_config:
        return None
    requested_names = {model_name, model_name.split("/")[-1]}
    for pm in provider_config.get("models", []):
        if requested_names & _get_model_aliases(pm):
            return pm
    return None


def _parse_id_list(value) -> set[int]:
    if not isinstance(value, list):
        return set()
    ids: set[int] = set()
    for item in value:
        try:
            ids.add(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def get_auto_model_config(model_name: str = AUTO_MODEL_NAME) -> dict:
    return get_cached_auto_model_route(model_name)


def is_auto_model_enabled(model_name: str = AUTO_MODEL_NAME) -> bool:
    return is_cached_auto_model_enabled(model_name)


def _message_part_has_image(value) -> bool:
    if isinstance(value, list):
        return any(_message_part_has_image(item) for item in value)
    if not isinstance(value, dict):
        return False
    part_type = str(value.get("type") or "").lower()
    if part_type in {"image", "image_url", "input_image"}:
        return True
    if any(key in value for key in ("image_url", "image", "input_image")):
        return True
    source = value.get("source")
    if isinstance(source, dict):
        source_type = str(source.get("type") or "").lower()
        media_type = str(source.get("media_type") or "").lower()
        if source_type in {"image", "base64"} and media_type.startswith("image/"):
            return True
    return any(_message_part_has_image(v) for v in value.values())


def request_requires_multimodal(messages: list[dict] | None) -> bool:
    if not messages:
        return False
    return any(_message_part_has_image(message.get("content")) for message in messages)


def get_auto_model_provider_candidates(
    model_name: str = AUTO_MODEL_NAME,
    require_multimodal: bool = False,
) -> list[tuple[str, dict, str, int]]:
    auto_config = get_auto_model_config(model_name)
    if not is_auto_model_enabled(model_name):
        return []
    allowed_model_ids = set(auto_config.get("model_ids") or [])
    allowed_provider_model_ids = set(auto_config.get("provider_model_ids") or [])
    candidates: list[tuple[str, dict, str, int]] = []
    seen: set[int] = set()
    for model_candidates in _model_name_index.values():
        for provider_name, pm_dict, model_tags, priority in model_candidates:
            provider_model_id = pm_dict.get("id")
            if provider_model_id in seen:
                continue
            seen.add(provider_model_id)
            if allowed_model_ids and pm_dict.get("model_id") not in allowed_model_ids:
                continue
            if (
                allowed_provider_model_ids
                and provider_model_id not in allowed_provider_model_ids
            ):
                continue
            if require_multimodal and not pm_dict.get("is_multimodal"):
                continue
            candidates.append((provider_name, pm_dict, model_tags, priority))
    return candidates


def get_cached_model_id(model_name: str) -> int | None:
    if model_name in _model_id_by_name:
        return _model_id_by_name.get(model_name)
    for model_candidates in _model_name_index.values():
        for _provider_name, pm_dict, _model_tags, _priority in model_candidates:
            if pm_dict.get("model_name") == model_name:
                return pm_dict.get("model_id")
    return None


def _route_from_provider_model(
    provider_config: Optional[dict],
    provider_name: str,
    pm: Optional[dict],
    requested_model: str,
    is_forced_provider: bool,
    provider_key_ids: list[int] | None = None,
) -> RouteResult:
    if not provider_config or not pm:
        return RouteResult(
            provider_config=provider_config,
            upstream_model_name=requested_model,
            provider_name=provider_name,
            requested_model=requested_model,
            is_forced_provider=is_forced_provider,
            provider_key_ids=provider_key_ids,
        )
    model_name = pm.get("model_name") or pm.get("actual_model_name") or requested_model
    upstream_model_name = pm.get("upstream_model_name") or model_name
    requested_model_id = (
        get_cached_model_id(requested_model)
        if requested_model == AUTO_MODEL_NAME
        else pm.get("model_id")
    )
    return RouteResult(
        provider_config=provider_config,
        provider_name=provider_name,
        provider_id=provider_config.get("id"),
        provider_model_id=pm.get("id"),
        model_id=pm.get("model_id"),
        requested_model_id=requested_model_id,
        requested_model=requested_model,
        model_name=model_name,
        upstream_model_name=upstream_model_name,
        is_forced_provider=is_forced_provider,
        provider_key_ids=provider_key_ids,
    )


def _apply_provider_model_rules(
    pm_dict: dict,
    ctx: RoutingContext,
) -> tuple[int, list[str], bool, list[str], list[int]]:
    policy_priority = 0
    filtered_reasons: list[str] = []
    is_standby = False
    matched_rules: list[str] = []
    provider_key_ids: set[int] = set()
    rules = [
        rule
        for rule in (pm_dict.get("routing_rules") or [])
        if rule.get("enabled", True)
    ]
    allow_rules = [rule for rule in rules if rule.get("action") == "allow"]
    deny_matched = False

    for rule in rules:
        if not rule_matches(rule, ctx):
            continue
        matched_rules.append(
            str(
                rule.get("name")
                or rule.get("template_key")
                or rule.get("id")
                or rule.get("action")
                or "rule"
            )
        )
        action = rule.get("action")
        rule_priority = int(rule.get("priority") or 0)
        provider_key_ids.update(_parse_id_list(rule.get("provider_key_ids")))
        if action == "deny":
            deny_matched = True
        elif action == "prefer":
            policy_priority += rule_priority
        elif action == "deprioritize":
            policy_priority -= rule_priority
        elif action == "standby":
            is_standby = True
            if ctx.standby_open:
                policy_priority += rule_priority

    if deny_matched:
        filtered_reasons.append("route_denied")
    if allow_rules and not any(rule_matches(rule, ctx) for rule in allow_rules):
        filtered_reasons.append("allow_not_matched")
    return (
        policy_priority,
        filtered_reasons,
        is_standby,
        matched_rules,
        sorted(provider_key_ids),
    )


async def explain_provider_model_candidates(
    model: str,
    messages: list[dict] | None = None,
    preferred_tags: str | None = None,
    context_tokens: int = 0,
    now: datetime | None = None,
) -> dict:
    provider_name, actual_model = parse_model(model)
    routing_ctx = RoutingContext(
        now=now or datetime.now(),
        context_tokens=context_tokens,
    )
    if provider_name:
        provider_config = providers_cache.get(provider_name)
        pm = get_model_config(provider_config, actual_model) if provider_config else None
        return {
            "requested_model": model,
            "forced_provider": True,
            "context_tokens": context_tokens,
            "ordered": [
                {
                    "provider": provider_name,
                    "provider_id": provider_config.get("id") if provider_config else None,
                    "provider_model_id": pm.get("id") if pm else None,
                    "model_id": pm.get("model_id") if pm else None,
                    "model_name": pm.get("model_name") if pm else actual_model,
                    "upstream_model_name": (pm or {}).get("upstream_model_name")
                    or (pm or {}).get("model_name")
                    or actual_model,
                    "tag_match": 0,
                    "priority": int((pm or {}).get("priority") or 0),
                    "policy_priority": 0,
                    "effective_priority": int((pm or {}).get("priority") or 0),
                    "health": 100,
                    "standby": False,
                    "matched_rules": [],
                    "provider_key_ids": [],
                    "filtered_reasons": [] if provider_config else ["provider_not_found"],
                }
            ],
            "filtered": [],
        }

    is_auto_model = is_auto_model_enabled(model)
    requires_multimodal = request_requires_multimodal(messages) if is_auto_model else False
    candidates = (
        get_auto_model_provider_candidates(
            model_name=model,
            require_multimodal=requires_multimodal,
        )
        if is_auto_model
        else (_model_name_index.get(model) or _alias_index.get(model) or [])
    )
    from app.services.key_health import compute_health_score
    from app.services.intent_classifier import classify_intent

    intent = classify_intent(messages) if messages else "chat"
    user_tags = set()
    if preferred_tags:
        user_tags = {t.strip() for t in preferred_tags.split(",") if t.strip()}

    ordered: list[dict] = []
    filtered: list[dict] = []
    for cand_provider_name, pm_dict, model_tags_str, pm_priority in candidates:
        pc = await get_provider_config(cand_provider_name)
        entry = {
            "provider": cand_provider_name,
            "provider_id": pc.get("id") if pc else None,
            "provider_model_id": pm_dict.get("id"),
            "model_id": pm_dict.get("model_id"),
            "model_name": pm_dict.get("model_name") or pm_dict.get("actual_model_name") or model,
            "upstream_model_name": pm_dict.get("upstream_model_name")
            or pm_dict.get("model_name")
            or model,
            "is_auto_model": is_auto_model,
            "requires_multimodal": requires_multimodal,
            "is_multimodal": bool(pm_dict.get("is_multimodal")),
            "tag_match": 0,
            "priority": int(pm_priority or 0),
            "policy_priority": 0,
            "effective_priority": int(pm_priority or 0),
            "health": 100,
            "standby": False,
            "matched_rules": [],
            "provider_key_ids": [],
            "filtered_reasons": [],
        }
        if not pc:
            entry["filtered_reasons"].append("provider_not_found")
            filtered.append(entry)
            continue
        if pc.get("disabled_reason"):
            entry["filtered_reasons"].append("provider_disabled")
        keys = pc.get("api_keys") or []
        active_keys = [k for k in keys if k.get("id") is not None]
        if not active_keys and not pc.get("api_key"):
            entry["filtered_reasons"].append("missing_api_key")
        if active_keys:
            entry["health"] = max(compute_health_score(k["id"]) for k in active_keys)

        model_tags_set = {t.strip() for t in model_tags_str.split(",") if t.strip()}
        if intent in model_tags_set:
            entry["tag_match"] = 1
        if user_tags and user_tags & model_tags_set:
            entry["tag_match"] = 2

        (
            policy_priority,
            rule_filtered_reasons,
            is_standby,
            matched_rules,
            provider_key_ids,
        ) = _apply_provider_model_rules(pm_dict, routing_ctx)
        entry["policy_priority"] = policy_priority
        entry["effective_priority"] = int(pm_priority or 0) + policy_priority
        entry["standby"] = is_standby
        entry["matched_rules"] = matched_rules
        entry["provider_key_ids"] = provider_key_ids
        entry["filtered_reasons"].extend(rule_filtered_reasons)
        if provider_key_ids:
            provider_key_id_set = set(provider_key_ids)
            scoped_active_keys = [
                key for key in active_keys if key.get("id") in provider_key_id_set
            ]
            if scoped_active_keys:
                entry["health"] = max(
                    compute_health_score(key["id"]) for key in scoped_active_keys
                )
            else:
                entry["filtered_reasons"].append("route_key_scope_unavailable")

        if entry["filtered_reasons"]:
            filtered.append(entry)
        else:
            ordered.append(entry)

    ordered.sort(
        key=lambda x: (
            x["tag_match"],
            0 if x["standby"] else 1,
            x["effective_priority"],
            x["health"],
        ),
        reverse=True,
    )
    return {
        "requested_model": model,
        "forced_provider": False,
        "context_tokens": context_tokens,
        "intent": intent,
        "preferred_tags": sorted(user_tags),
        "is_auto_model": is_auto_model,
        "requires_multimodal": requires_multimodal,
        "ordered": ordered,
        "filtered": filtered,
    }


async def get_provider_model_candidates(
    model: str,
    messages: list[dict] | None = None,
    preferred_tags: str | None = None,
    context_tokens: int = 0,
    now: datetime | None = None,
) -> list[RouteResult]:
    provider_name, actual_model = parse_model(model)
    if provider_name:
        provider_config = await get_provider_config(provider_name)
        if not provider_config:
            return [
                _route_from_provider_model(
                    provider_config, provider_name, None, model, True
                )
            ]
        pm = get_model_config(provider_config, actual_model)
        return [
            _route_from_provider_model(
                provider_config, provider_name, pm, model, True
            )
        ]

    is_auto_model = is_auto_model_enabled(model)
    candidates = (
        get_auto_model_provider_candidates(
            model_name=model,
            require_multimodal=request_requires_multimodal(messages)
        )
        if is_auto_model
        else (_model_name_index.get(model) or _alias_index.get(model))
    )
    if candidates:
        explanation = await explain_provider_model_candidates(
            model,
            messages=messages,
            preferred_tags=preferred_tags,
            context_tokens=context_tokens,
            now=now,
        )
        if explanation["ordered"]:
            routes: list[RouteResult] = []
            pm_by_id = {
                pm_dict.get("id"): (cand_provider_name, pm_dict)
                for cand_provider_name, pm_dict, _model_tags_str, _pm_priority in candidates
            }
            for entry in explanation["ordered"]:
                cand_provider_name, pm_dict = pm_by_id.get(
                    entry["provider_model_id"],
                    (entry["provider"], {}),
                )
                pc = await get_provider_config(cand_provider_name)
                route = _route_from_provider_model(
                    pc,
                    cand_provider_name,
                    pm_dict,
                    model,
                    False,
                    provider_key_ids=entry.get("provider_key_ids") or None,
                )
                logger.info(
                    "[ALIAS ROUTE CANDIDATE] model=%s → provider=%s, actual=%s, intent=%s, tag_match=%d, standby=%s, health=%d, priority=%d",
                    model, cand_provider_name, route.upstream_model_name, explanation.get("intent", "chat"), entry["tag_match"], entry["standby"], entry["health"], entry["effective_priority"],
                )
                routes.append(route)
            return routes

    return [
        RouteResult(
            provider_config=None,
            upstream_model_name=model,
            provider_name="",
            model_id=get_cached_model_id(model),
            requested_model_id=get_cached_model_id(model),
            requested_model=model,
            model_name=model,
        )
    ]


async def get_provider_and_model(
    model: str,
    messages: list[dict] | None = None,
    preferred_tags: str | None = None,
    context_tokens: int = 0,
    now: datetime | None = None,
) -> RouteResult:
    routes = await get_provider_model_candidates(
        model,
        messages,
        preferred_tags,
        context_tokens,
        now,
    )
    return routes[0]


async def get_disabled_provider_reason(provider_name: str) -> str | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Provider.disabled_reason).where(
                Provider.name == provider_name,
                Provider.is_active == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()
