from sqlalchemy import select

from app.core.database import (
    ApiKey,
    ApiKeyModel,
    ApiKeyModelAccess,
    Model,
    Provider,
    ProviderModel,
    async_session_maker,
)


async def resolve_visible_models_for_api_key(api_key: str) -> tuple[set[str] | None, str | None]:
    """Resolve the set of Model.name values an API key may use.

    Mirrors the permission logic of build_opencode_config:
    - ApiKeyModel rows (explicit provider_model grants) take precedence.
    - Otherwise ApiKeyModelAccess rows (model-level grants).
    - Otherwise full access.
    Adds the `auto` virtual model when enabled and requested by the key.

    Returns (model_names, None) on success or (None, error_message).
    """
    if not api_key:
        return None, "Missing API key. Pass it via 'Authorization: Bearer <key>'."

    from app.services.auto_model_routes import AUTO_MODEL_NAME, get_cached_auto_model_route

    async with async_session_maker() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key == api_key, ApiKey.is_active == True)  # noqa: E712
        )
        key = result.scalar_one_or_none()
        if not key:
            return None, "Invalid API key."

        pm_result = await session.execute(
            select(ApiKeyModel.provider_model_id).where(ApiKeyModel.api_key_id == key.id)
        )
        allowed_pm_ids = [row[0] for row in pm_result.fetchall()]

        access_result = await session.execute(
            select(ApiKeyModelAccess.model_id).where(ApiKeyModelAccess.api_key_id == key.id)
        )
        allowed_model_ids = [row[0] for row in access_result.fetchall()]

        full_access = not allowed_pm_ids and not allowed_model_ids

        base_query = (
            select(Model.name.distinct())
            .select_from(ProviderModel)
            .join(Model, Model.id == ProviderModel.model_id)
            .join(Provider, Provider.id == ProviderModel.provider_id)
            .where(Provider.is_active == True, ProviderModel.is_active == True)  # noqa: E712
        )
        if allowed_pm_ids:
            query = base_query.where(ProviderModel.id.in_(allowed_pm_ids))
        elif allowed_model_ids:
            query = base_query.where(ProviderModel.model_id.in_(allowed_model_ids))
        else:
            query = base_query

        names_result = await session.execute(query)
        model_names = {row[0] for row in names_result.fetchall() if row[0]}

    auto_config = get_cached_auto_model_route(AUTO_MODEL_NAME)
    auto_enabled = bool(auto_config.get("enabled")) and bool(
        auto_config.get("model_ids") or auto_config.get("provider_model_ids")
    )
    auto_virtual_model_id = auto_config.get("virtual_model_id")
    if auto_enabled and (
        full_access or (auto_virtual_model_id is not None and auto_virtual_model_id in allowed_model_ids)
    ):
        model_names.add(AUTO_MODEL_NAME)

    return model_names, None
