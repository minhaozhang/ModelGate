from __future__ import annotations

from sqlalchemy import select

from app.core.database import AutoModelRoute, Model, ProviderModel, async_session_maker

AUTO_MODEL_NAME = "auto"

_auto_model_routes_cache: dict[str, dict] = {}


def _parse_id_list(value) -> list[int]:
    if not isinstance(value, list):
        return []
    ids: list[int] = []
    seen: set[int] = set()
    for item in value:
        try:
            item_id = int(item)
        except (TypeError, ValueError):
            continue
        if item_id <= 0 or item_id in seen:
            continue
        ids.append(item_id)
        seen.add(item_id)
    return ids


def normalize_auto_model_route(data: dict | None) -> dict:
    data = data or {}
    return {
        "enabled": bool(data.get("enabled")),
        "model_ids": _parse_id_list(data.get("model_ids")),
        "provider_model_ids": _parse_id_list(data.get("provider_model_ids")),
        "route_policy": data.get("route_policy") if isinstance(data.get("route_policy"), dict) else {},
    }


def auto_model_route_is_active(payload: dict) -> bool:
    return bool(
        payload.get("enabled")
        and (payload.get("model_ids") or payload.get("provider_model_ids"))
    )


async def ensure_auto_virtual_model(session, model_name: str, payload: dict) -> Model:
    result = await session.execute(select(Model).where(Model.name == model_name))
    model = result.scalar_one_or_none()
    active = auto_model_route_is_active(payload)
    if model is None:
        model = Model(
            name=model_name,
            display_name=model_name,
            max_tokens=131072,
            context_length=204800,
            thinking_enabled=True,
            thinking_budget=8192,
            is_multimodal=True,
            is_active=active,
            is_virtual=True,
            tags="virtual,auto",
        )
        session.add(model)
        await session.flush()
    else:
        model.display_name = model_name
        model.is_active = active
        model.is_virtual = True
        if not model.tags:
            model.tags = "virtual,auto"
    return model


def _route_to_payload(model: Model, route: AutoModelRoute | None) -> dict:
    payload = normalize_auto_model_route(
        {
            "enabled": route.enabled if route else False,
            "model_ids": route.model_ids if route else [],
            "provider_model_ids": route.provider_model_ids if route else [],
            "route_policy": route.route_policy if route else {},
        }
    )
    payload["model_name"] = model.name
    payload["virtual_model_id"] = model.id
    payload["display_name"] = getattr(model, "display_name", None) or model.name
    payload["is_multimodal"] = bool(getattr(model, "is_multimodal", False))
    payload["context_length"] = getattr(model, "context_length", None) or 0
    payload["max_tokens"] = getattr(model, "max_tokens", None) or 0
    return payload


async def get_auto_model_route(session, model_name: str = AUTO_MODEL_NAME) -> dict:
    result = await session.execute(
        select(Model, AutoModelRoute)
        .outerjoin(AutoModelRoute, AutoModelRoute.virtual_model_id == Model.id)
        .where(Model.name == model_name, Model.is_virtual == True)  # noqa: E712
    )
    row = result.first()
    if not row:
        return {
            "model_name": model_name,
            "virtual_model_id": None,
            "enabled": False,
            "model_ids": [],
            "provider_model_ids": [],
            "route_policy": {},
        }
    model, route = row
    payload = _route_to_payload(model, route)
    if payload["provider_model_ids"]:
        pm_result = await session.execute(
            select(ProviderModel.model_id).where(
                ProviderModel.id.in_(payload["provider_model_ids"])
            )
        )
        provider_model_model_ids = [
            int(row[0]) for row in pm_result.fetchall() if row[0] is not None
        ]
        payload["model_ids"] = list(
            dict.fromkeys(payload["model_ids"] + provider_model_model_ids)
        )
    return payload


async def update_auto_model_route(
    session,
    payload: dict,
    model_name: str = AUTO_MODEL_NAME,
) -> dict:
    normalized = normalize_auto_model_route(payload)
    model = await ensure_auto_virtual_model(session, model_name, normalized)
    result = await session.execute(
        select(AutoModelRoute).where(AutoModelRoute.virtual_model_id == model.id)
    )
    route = result.scalar_one_or_none()
    if route is None:
        route = AutoModelRoute(virtual_model_id=model.id)
        session.add(route)
    route.enabled = bool(normalized["enabled"])
    route.model_ids = normalized["model_ids"]
    route.provider_model_ids = normalized["provider_model_ids"]
    route.route_policy = normalized["route_policy"]
    payload = _route_to_payload(model, route)
    if payload["provider_model_ids"]:
        pm_result = await session.execute(
            select(ProviderModel.model_id).where(
                ProviderModel.id.in_(payload["provider_model_ids"])
            )
        )
        provider_model_model_ids = [
            int(row[0]) for row in pm_result.fetchall() if row[0] is not None
        ]
        payload["model_ids"] = list(
            dict.fromkeys(payload["model_ids"] + provider_model_model_ids)
        )
    await session.commit()
    return payload


async def load_auto_model_routes_cache(session=None) -> dict[str, dict]:
    owns_session = session is None
    if owns_session:
        session_cm = async_session_maker()
        session = await session_cm.__aenter__()
    else:
        session_cm = None
    try:
        result = await session.execute(
            select(Model, AutoModelRoute)
            .join(AutoModelRoute, AutoModelRoute.virtual_model_id == Model.id)
            .where(Model.is_virtual == True)  # noqa: E712
        )
        routes: dict[str, dict] = {}
        for model, route in result.all():
            payload = _route_to_payload(model, route)
            if model.is_active and auto_model_route_is_active(payload):
                routes[model.name] = payload
        _auto_model_routes_cache.clear()
        _auto_model_routes_cache.update(routes)
        return routes
    finally:
        if owns_session and session_cm is not None:
            await session_cm.__aexit__(None, None, None)


def get_cached_auto_model_route(model_name: str = AUTO_MODEL_NAME) -> dict:
    return _auto_model_routes_cache.get(model_name) or {
        "model_name": model_name,
        "virtual_model_id": None,
        "enabled": False,
        "model_ids": [],
        "provider_model_ids": [],
        "route_policy": {},
    }


def is_cached_auto_model_enabled(model_name: str = AUTO_MODEL_NAME) -> bool:
    return auto_model_route_is_active(get_cached_auto_model_route(model_name))


def get_cached_auto_model_names() -> list[str]:
    return sorted(
        name
        for name, payload in _auto_model_routes_cache.items()
        if auto_model_route_is_active(payload)
    )
