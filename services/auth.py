import datetime
from typing import Optional

from sqlalchemy import select

from core.config import api_keys_cache
from core.database import async_session_maker, ApiKey, ApiKeyModel, ApiKeyMcpServer, ApiKeyTimeRule
from services.provider import parse_model, get_provider_config


async def load_api_keys():
    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.is_active == True))
        keys = result.scalars().all()

        key_ids = [k.id for k in keys]
        if not key_ids:
            api_keys_cache.clear()
            return

        all_models_result = await session.execute(
            select(ApiKeyModel.api_key_id, ApiKeyModel.provider_model_id).where(
                ApiKeyModel.api_key_id.in_(key_ids)
            )
        )
        key_models_map: dict[int, list[int]] = {k.id: [] for k in keys}
        for row in all_models_result.fetchall():
            key_models_map[row[0]].append(row[1])

        all_rules_result = await session.execute(
            select(ApiKeyTimeRule)
            .where(ApiKeyTimeRule.api_key_id.in_(key_ids))
            .order_by(ApiKeyTimeRule.rule_type, ApiKeyTimeRule.id)
        )
        key_rules_map: dict[int, list] = {k.id: [] for k in keys}
        for r in all_rules_result.scalars().all():
            rule_data = {
                "id": r.id,
                "rule_type": r.rule_type,
                "allowed": r.allowed,
            }
            if r.start_time is not None:
                rule_data["start_time"] = r.start_time.strftime("%H:%M:%S")
            if r.end_time is not None:
                rule_data["end_time"] = r.end_time.strftime("%H:%M:%S")
            if r.start_date is not None:
                rule_data["start_date"] = r.start_date.isoformat()
            if r.end_date is not None:
                rule_data["end_date"] = r.end_date.isoformat()
            if r.weekdays is not None:
                rule_data["weekdays"] = r.weekdays
            key_rules_map[r.api_key_id].append(rule_data)

        all_mcp_result = await session.execute(
            select(ApiKeyMcpServer.api_key_id, ApiKeyMcpServer.mcp_server_id).where(
                ApiKeyMcpServer.api_key_id.in_(key_ids)
            )
        )
        key_mcp_map: dict[int, list[int]] = {k.id: [] for k in keys}
        for row in all_mcp_result.fetchall():
            key_mcp_map[row[0]].append(row[1])

        api_keys_cache.clear()
        for k in keys:
            api_keys_cache[k.key] = {
                "id": k.id,
                "name": k.name,
                "allowed_provider_model_ids": key_models_map[k.id],
                "time_rules": key_rules_map[k.id],
                "mcp_server_ids": key_mcp_map[k.id],
            }


def _parse_rule_time(value: str | None) -> datetime.time | None:
    if not value:
        return None
    parts = [int(part) for part in value.split(":")]
    return datetime.time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0)


def _matches_time_range(
    current_time: datetime.time, start_str: str | None, end_str: str | None
) -> bool:
    start_t = _parse_rule_time(start_str)
    end_t = _parse_rule_time(end_str)
    if start_t is None or end_t is None:
        return False
    if start_t <= end_t:
        return start_t <= current_time <= end_t
    return current_time >= start_t or current_time <= end_t


def _matches_rule(
    rule: dict,
    current_time: datetime.time,
    current_date: datetime.date,
    current_weekday: int,
) -> bool:
    rule_type = rule.get("rule_type")
    if rule_type == "time_range":
        return _matches_time_range(
            current_time,
            rule.get("start_time"),
            rule.get("end_time"),
        )
    if rule_type == "date_range":
        start_str = rule.get("start_date")
        end_str = rule.get("end_date")
        if not start_str or not end_str:
            return False
        start_d = datetime.date.fromisoformat(start_str)
        end_d = datetime.date.fromisoformat(end_str)
        return start_d <= current_date <= end_d
    if rule_type == "weekday":
        weekdays_str = rule.get("weekdays")
        if not weekdays_str:
            return False
        days = [int(day) for day in weekdays_str.split(",") if day.strip()]
        return current_weekday in days
    return False


def _check_time_rules(time_rules: list[dict]) -> bool:
    if not time_rules:
        return True

    now = datetime.datetime.now()
    current_time = now.time()
    current_date = now.date()
    current_weekday = now.weekday()
    grouped_rules: dict[str, list[dict]] = {}
    for rule in time_rules:
        rule_type = rule.get("rule_type")
        if not rule_type:
            continue
        grouped_rules.setdefault(rule_type, []).append(rule)

        if rule_type == "time_range":
            start_str = rule.get("start_time")
            end_str = rule.get("end_time")
            if not start_str or not end_str:
                continue
            parts = [int(p) for p in start_str.split(":")]
            start_t = datetime.time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0)
            parts = [int(p) for p in end_str.split(":")]
            end_t = datetime.time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0)
            if start_t > end_t:
                in_range = current_time >= start_t or current_time <= end_t
            else:
                in_range = start_t <= current_time <= end_t
            if in_range:
                return allowed

    for rules in grouped_rules.values():
        allow_rules = [rule for rule in rules if rule.get("allowed", True)]
        if allow_rules and not any(
            _matches_rule(rule, current_time, current_date, current_weekday)
            for rule in allow_rules
        ):
            return False

    return True


async def validate_api_key(
    auth_header: str, model: str
) -> tuple[Optional[int], Optional[str]]:
    if not auth_header:
        return None, "Missing API key"

    if auth_header.startswith("Bearer "):
        key = auth_header[7:]
    else:
        key = auth_header

    key_info = api_keys_cache.get(key)
    if not key_info:
        return None, "Invalid API key"

    if not _check_time_rules(key_info.get("time_rules", [])):
        return None, "API key not allowed at this time"

    allowed_models = key_info.get("allowed_provider_model_ids", [])

    if allowed_models:
        provider_name, actual_model = parse_model(model)

        if not provider_name:
            return key_info["id"], None

        provider_config = await get_provider_config(provider_name)
        if not provider_config:
            return None, f"Provider '{provider_name}' not found"

        provider_model_id = None
        for pm in provider_config.get("models", []):
            pm_model_name = pm.get("model_name")
            if (
                pm_model_name == actual_model
                or pm_model_name == actual_model.split("/")[-1]
            ):
                provider_model_id = pm["id"]
                break

        if provider_model_id is None:
            return (
                None,
                f"Model '{actual_model}' not found in provider '{provider_name}'",
            )

        if provider_model_id not in allowed_models:
            return None, f"API key not authorized for model '{model}'"

    return key_info["id"], None
