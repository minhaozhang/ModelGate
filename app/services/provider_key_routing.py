from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from app.services.key_health import compute_health_score


@dataclass
class RoutingContext:
    now: datetime
    context_tokens: int = 0
    sticky_key_id: int | None = None
    health_scores: dict[int, int] = field(default_factory=dict)
    standby_open: bool = False


@dataclass
class ProviderKeyCandidate:
    key: dict[str, Any]
    key_id: int | None
    api_key: str | None
    priority: int = 0
    health: int = 100
    policy_priority: int = 0
    sticky: bool = False
    standby: bool = False
    matched_rules: list[str] = field(default_factory=list)
    filtered_reasons: list[str] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        return not self.filtered_reasons

    def as_key_tuple(self) -> tuple[str, int | None] | None:
        if not self.api_key:
            return None
        return self.api_key, self.key_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "label": self.key.get("label") or "",
            "priority": self.priority,
            "health": self.health,
            "policy_priority": self.policy_priority,
            "sticky": self.sticky,
            "standby": self.standby,
            "matched_rules": self.matched_rules,
            "filtered_reasons": self.filtered_reasons,
        }


@dataclass
class ProviderKeyEvaluation:
    usable: list[ProviderKeyCandidate]
    standby: list[ProviderKeyCandidate]
    filtered: list[ProviderKeyCandidate]

    @property
    def ordered(self) -> list[ProviderKeyCandidate]:
        return [*self.usable, *self.standby]


def _replace_template_value(value: Any, params: dict[str, Any]) -> Any:
    if not isinstance(value, str):
        return value
    if value.startswith("${") and value.endswith("}"):
        return params.get(value[2:-1])
    return value


def materialize_template_rules(
    rule_blueprint: dict[str, Any],
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    rules = rule_blueprint.get("rules") if isinstance(rule_blueprint, dict) else []
    if not isinstance(rules, list):
        return []
    materialized: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        materialized.append(
            {
                key: _replace_template_value(value, params)
                for key, value in rule.items()
                if _replace_template_value(value, params) is not None
            }
        )
    return materialized


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


def _parse_weekdays(value: Any) -> set[int]:
    if value is None or value == "":
        return set()
    if isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = str(value).replace(";", ",").split(",")
    weekdays: set[int] = set()
    for item in raw:
        try:
            weekday = int(str(item).strip())
        except ValueError:
            continue
        if 1 <= weekday <= 7:
            weekdays.add(weekday)
    return weekdays


def _time_matches(rule: dict[str, Any], now: datetime) -> bool:
    start = _coerce_time(rule.get("start_time"))
    end = _coerce_time(rule.get("end_time"))
    if start is None and end is None:
        return True
    current = now.time()
    if start is None:
        return current <= end
    if end is None:
        return current >= start
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def _date_matches(rule: dict[str, Any], now: datetime) -> bool:
    start = _coerce_date(rule.get("start_date"))
    end = _coerce_date(rule.get("end_date"))
    current = now.date()
    if start and current < start:
        return False
    if end and current > end:
        return False
    return True


def _weekday_matches(rule: dict[str, Any], now: datetime) -> bool:
    weekdays = _parse_weekdays(rule.get("weekdays"))
    return not weekdays or now.isoweekday() in weekdays


def _context_matches(rule: dict[str, Any], context_tokens: int) -> bool:
    min_tokens = rule.get("min_context_tokens")
    max_tokens = rule.get("max_context_tokens")
    if min_tokens is not None and context_tokens < int(min_tokens):
        return False
    if max_tokens is not None and context_tokens > int(max_tokens):
        return False
    return True


def rule_matches(rule: dict[str, Any], ctx: RoutingContext) -> bool:
    return (
        _time_matches(rule, ctx.now)
        and _date_matches(rule, ctx.now)
        and _weekday_matches(rule, ctx.now)
        and _context_matches(rule, ctx.context_tokens)
    )


def _rule_label(rule: dict[str, Any]) -> str:
    return str(rule.get("name") or rule.get("template_key") or rule.get("id") or rule.get("action") or "rule")


def _sort_candidate(candidate: ProviderKeyCandidate) -> tuple[int, int, int, int, float]:
    sticky_bonus = 1 if candidate.sticky else 0
    effective_priority = candidate.priority + candidate.policy_priority
    return (
        sticky_bonus,
        effective_priority,
        candidate.priority,
        candidate.health,
        # Fully tied candidates (same priority, same health) would
        # otherwise follow list order forever and pin traffic onto
        # one key; break ties randomly per evaluation.
        random.random(),
    )


def evaluate_provider_key_candidates(
    keys: list[dict[str, Any]],
    ctx: RoutingContext,
) -> ProviderKeyEvaluation:
    usable: list[ProviderKeyCandidate] = []
    standby: list[ProviderKeyCandidate] = []
    filtered: list[ProviderKeyCandidate] = []

    for key in keys:
        key_id = key.get("id")
        health = ctx.health_scores.get(key_id) if key_id is not None else 100
        if health is None:
            health = compute_health_score(key_id) if key_id is not None else 100
        candidate = ProviderKeyCandidate(
            key=key,
            key_id=key_id,
            api_key=key.get("api_key"),
            priority=int(key.get("priority") or 0),
            health=int(health),
            sticky=bool(key_id is not None and key_id == ctx.sticky_key_id),
        )

        if not key.get("is_active", True):
            candidate.filtered_reasons.append("disabled")
        if not candidate.api_key:
            candidate.filtered_reasons.append("missing_api_key")
        if candidate.health <= 0:
            candidate.filtered_reasons.append("health_unavailable")

        rules = [
            rule
            for rule in (key.get("routing_rules") or [])
            if rule.get("enabled", True)
        ]
        allow_rules = [r for r in rules if r.get("action") == "allow"]

        deny_matched = False
        for rule in rules:
            action = rule.get("action")
            if not rule_matches(rule, ctx):
                continue
            candidate.matched_rules.append(_rule_label(rule))
            rule_priority = int(rule.get("priority") or 0)
            if action == "deny":
                deny_matched = True
            elif action == "prefer":
                candidate.policy_priority += rule_priority
            elif action == "deprioritize":
                candidate.policy_priority -= rule_priority
            elif action == "standby":
                candidate.standby = True
                candidate.policy_priority += rule_priority

        if deny_matched:
            candidate.filtered_reasons.append("time_denied")
        if allow_rules and not any(rule_matches(rule, ctx) for rule in allow_rules):
            candidate.filtered_reasons.append("allow_not_matched")
        if candidate.standby and not ctx.standby_open:
            candidate.filtered_reasons.append("standby_closed")

        if candidate.filtered_reasons:
            filtered.append(candidate)
        elif candidate.standby:
            standby.append(candidate)
        else:
            usable.append(candidate)

    usable.sort(key=_sort_candidate, reverse=True)
    standby.sort(key=_sort_candidate, reverse=True)
    return ProviderKeyEvaluation(usable=usable, standby=standby, filtered=filtered)
