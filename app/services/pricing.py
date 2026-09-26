from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select


MILLION_TOKENS = 1_000_000


@dataclass
class PricingConfig:
    input_price_cny_per_million: float | None = None
    output_price_cny_per_million: float | None = None
    cached_input_price_cny_per_million: float | None = None
    default_cache_hit_ratio: float | None = 0
    pricing_tiers: list[dict[str, Any]] = field(default_factory=list)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _global_default_cache_hit_ratio() -> float | None:
    import app.core.config as config

    raw = (config.system_settings or {}).get("pricing.default_cache_hit_ratio")
    if raw is None or raw == "":
        return None
    return _to_float(raw, None)


def _explicit_cached_input_tokens(tokens: dict[str, Any]) -> int | None:
    for key in ("cache_read_input_tokens", "cached_input_tokens"):
        if key in tokens:
            return max(_to_int(tokens.get(key)), 0)
    details = tokens.get("prompt_tokens_details")
    if isinstance(details, dict) and "cached_tokens" in details:
        return max(_to_int(details.get("cached_tokens")), 0)
    return None


def select_pricing_for_context(
    pricing: PricingConfig, request_context_tokens: int | None
) -> PricingConfig:
    context_tokens = _to_int(request_context_tokens)
    for tier in pricing.pricing_tiers or []:
        if not isinstance(tier, dict):
            continue
        min_tokens = tier.get("min_context_tokens")
        max_tokens = tier.get("max_context_tokens")
        if min_tokens is not None and context_tokens < _to_int(min_tokens):
            continue
        if max_tokens is not None and context_tokens > _to_int(max_tokens):
            continue
        return PricingConfig(
            input_price_cny_per_million=_to_float(
                tier.get("input_price_cny_per_million"),
                _to_float(pricing.input_price_cny_per_million),
            ),
            output_price_cny_per_million=_to_float(
                tier.get("output_price_cny_per_million"),
                _to_float(pricing.output_price_cny_per_million),
            ),
            cached_input_price_cny_per_million=_to_float(
                tier.get("cached_input_price_cny_per_million"),
                _to_float(pricing.cached_input_price_cny_per_million),
            ),
            default_cache_hit_ratio=pricing.default_cache_hit_ratio,
            pricing_tiers=pricing.pricing_tiers,
        )
    return pricing


def calculate_model_billing(tokens: dict[str, Any], pricing: PricingConfig) -> dict[str, Any]:
    prompt_tokens = max(_to_int(tokens.get("prompt_tokens") or tokens.get("input_tokens")), 0)
    completion_tokens = max(
        _to_int(tokens.get("completion_tokens") or tokens.get("output_tokens")), 0
    )
    cached_input_tokens = _explicit_cached_input_tokens(tokens)
    if cached_input_tokens is None:
        ratio = min(max(_to_float(pricing.default_cache_hit_ratio), 0.0), 100.0)
        cached_input_tokens = int(round(prompt_tokens * ratio / 100))
    cached_input_tokens = min(cached_input_tokens, prompt_tokens)
    uncached_input_tokens = max(prompt_tokens - cached_input_tokens, 0)

    input_price = _to_float(pricing.input_price_cny_per_million)
    output_price = _to_float(pricing.output_price_cny_per_million)
    cached_price = _to_float(pricing.cached_input_price_cny_per_million, input_price)

    input_cost = uncached_input_tokens * input_price / MILLION_TOKENS
    cached_input_cost = cached_input_tokens * cached_price / MILLION_TOKENS
    output_cost = completion_tokens * output_price / MILLION_TOKENS
    total_cost = input_cost + cached_input_cost + output_cost

    return {
        "currency": "CNY",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": uncached_input_tokens,
        "input_cost_cny": round(input_cost, 10),
        "cached_input_cost_cny": round(cached_input_cost, 10),
        "output_cost_cny": round(output_cost, 10),
        "total_cost_cny": round(total_cost, 10),
        "input_price_cny_per_million": input_price,
        "output_price_cny_per_million": output_price,
        "cached_input_price_cny_per_million": cached_price,
        "default_cache_hit_ratio": _to_float(pricing.default_cache_hit_ratio),
    }


def _has_pricing(pricing: PricingConfig) -> bool:
    return (
        pricing.input_price_cny_per_million is not None
        or pricing.output_price_cny_per_million is not None
        or pricing.cached_input_price_cny_per_million is not None
        or bool(pricing.pricing_tiers)
    )


async def enrich_tokens_with_billing(
    tokens: dict[str, Any],
    *,
    provider_name: str | None = None,
    model: str | None = None,
    provider_model_id: int | None = None,
    request_context_tokens: int | None = None,
    api_key_id: int | None = None,
) -> dict[str, Any]:
    from app.core.database import Model, Provider, ProviderModel, async_session_maker

    if not isinstance(tokens, dict):
        return tokens

    async with async_session_maker() as session:
        stmt = select(ProviderModel, Provider, Model).join(
            Provider, Provider.id == ProviderModel.provider_id
        ).join(Model, Model.id == ProviderModel.model_id)
        if provider_model_id:
            stmt = stmt.where(ProviderModel.id == provider_model_id)
        else:
            filters = []
            if provider_name:
                filters.append(Provider.name == provider_name)
            if model:
                filters.append(
                    or_(
                        ProviderModel.upstream_model_name == model,
                        ProviderModel.model_name_override == model,
                        Model.name == model,
                    )
                )
            if not filters:
                return tokens
            for item in filters:
                stmt = stmt.where(item)
        result = await session.execute(stmt.limit(1))
        row = result.first()
        if not row:
            return tokens
        provider_model, provider, standard_model = row

    pricing = PricingConfig(
        input_price_cny_per_million=provider_model.input_price_cny_per_million,
        output_price_cny_per_million=provider_model.output_price_cny_per_million,
        cached_input_price_cny_per_million=provider_model.cached_input_price_cny_per_million,
        default_cache_hit_ratio=(
            provider_model.default_cache_hit_ratio
            if provider_model.default_cache_hit_ratio is not None
            else _to_float(_global_default_cache_hit_ratio(), 0.0)
        ),
        pricing_tiers=provider_model.pricing_tiers or [],
    )
    if not _has_pricing(pricing):
        return tokens

    selected = select_pricing_for_context(pricing, request_context_tokens)
    billing = calculate_model_billing(tokens, selected)
    billing.update(
        {
            "provider_model_id": provider_model.id,
            "provider_name": provider.name,
            "model_name": standard_model.name,
            "upstream_model_name": provider_model.upstream_model_name
            or provider_model.model_name_override
            or standard_model.name,
        }
    )
    enriched = dict(tokens)
    enriched["billing"] = billing
    if api_key_id:
        from app.services.billing_rules import charge_daily_usage

        usage = await charge_daily_usage(api_key_id, billing.get("total_cost_cny") or 0)
        if usage:
            enriched["daily_usage"] = usage
    return enriched
