from __future__ import annotations

import re
from datetime import datetime

MAX_RULES = 20

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_DATETIME_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M")


def _parse_time(value) -> int | None:
    if not isinstance(value, str):
        return None
    m = _TIME_RE.match(value.strip())
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _parse_datetime(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def normalize_rules(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    rules: list[dict] = []
    for item in raw[:MAX_RULES]:
        if not isinstance(item, dict):
            continue
        rule_type = item.get("type")
        if rule_type == "weekly":
            days_raw = item.get("days")
            if not isinstance(days_raw, list):
                continue
            days = sorted(
                {int(d) for d in days_raw if isinstance(d, int) and 0 <= d <= 6}
            )
            if not days:
                continue
            start = _parse_time(item.get("start"))
            end = _parse_time(item.get("end"))
            if start is None or end is None:
                continue
            rules.append(
                {"type": "weekly", "days": days,
                 "start": f"{start // 60:02d}:{start % 60:02d}",
                 "end": f"{end // 60:02d}:{end % 60:02d}"}
            )
        elif rule_type == "once":
            start = _parse_datetime(item.get("start"))
            end = _parse_datetime(item.get("end"))
            if start is None or end is None or end < start:
                continue
            rules.append(
                {"type": "once",
                 "start": start.strftime("%Y-%m-%d %H:%M"),
                 "end": end.strftime("%Y-%m-%d %H:%M")}
            )
    return rules


def _weekly_span_minutes(start: int, end: int) -> int:
    if end > start:
        return end - start
    if end < start:
        return 24 * 60 - start + end
    return 24 * 60


def schedule_active(rules, now: datetime | None = None) -> bool:
    if not rules:
        return False
    now = now or datetime.now()
    cur_minutes = now.hour * 60 + now.minute
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if rule.get("type") == "weekly":
            start = _parse_time(rule.get("start"))
            end = _parse_time(rule.get("end"))
            days = rule.get("days")
            if start is None or end is None or not isinstance(days, list):
                continue
            span = _weekly_span_minutes(start, end)
            for d in days:
                if not isinstance(d, int) or not 0 <= d <= 6:
                    continue
                delta = (now.weekday() - d) % 7
                if delta == 0:
                    offset = cur_minutes - start
                elif delta == 1:
                    offset = (24 * 60 - start) + cur_minutes
                else:
                    continue
                if 0 <= offset < span:
                    return True
        elif rule.get("type") == "once":
            start = _parse_datetime(rule.get("start"))
            end = _parse_datetime(rule.get("end"))
            if start is None or end is None:
                continue
            if start <= now <= end:
                return True
    return False


def summarize_rules(rules) -> str:
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    if not isinstance(rules, list):
        return ""
    parts = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if rule.get("type") == "weekly":
            days = rule.get("days")
            if not isinstance(days, list) or not days:
                continue
            if sorted(days) == list(range(7)):
                day_text = "每天"
            else:
                day_text = "".join(
                    weekday_names[d] for d in sorted(days) if 0 <= d <= 6
                )
            parts.append(
                f"每周{day_text} {rule.get('start')}→{rule.get('end')}"
            )
        elif rule.get("type") == "once":
            parts.append(f"{rule.get('start')}→{rule.get('end')}")
    return "；".join(parts)
