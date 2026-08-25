"""Daily spending quota + peak/off-peak billing multipliers.

Charges are based on the per-request cost computed by
``app.services.pricing.enrich_tokens_with_billing`` (upstream cost, CNY)
multiplied by a period multiplier: peak hours cost faster, off-peak hours
cost slower. When a key's accumulated daily charge reaches its quota the
gateway rejects further requests with 429 + Retry-Until-Midnight.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import text

from app.core.config import logger
from app.core.database import async_session_maker
from app.services.system_config import get_setting

BILLING_CATEGORY = "billing"

BILLING_DEFAULTS = {
    "peak_windows": "09:00-12:00,14:00-18:00",
    "weekend_offpeak": "true",
    "peak_multiplier": "1.5",
    "offpeak_multiplier": "0.8",
    "default_daily_quota_cny": "",
}

_WINDOW_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")

QUOTA_NOTIFICATION_TITLE = "API Key 每日额度已用尽"


@dataclass
class BillingRules:
    peak_windows: list[tuple[int, int]]  # (start_min, end_min) minutes-of-day
    weekend_offpeak: bool
    peak_multiplier: float
    offpeak_multiplier: float
    default_daily_quota_cny: float | None  # None = unlimited


def parse_peak_windows(raw: str) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        m = _WINDOW_RE.match(part)
        if not m:
            raise ValueError(f"invalid peak window: {part!r}")
        h1, m1, h2, m2 = (int(g) for g in m.groups())
        if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
            raise ValueError(f"invalid peak window time: {part!r}")
        start = h1 * 60 + m1
        end = h2 * 60 + m2
        if start == end:
            raise ValueError(f"empty peak window: {part!r}")
        windows.append((start, end))
    return windows


def _to_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_quota(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None  # 0/negative = unlimited


async def load_billing_rules() -> BillingRules:
    raw_windows = await get_setting(
        BILLING_CATEGORY, "peak_windows", BILLING_DEFAULTS["peak_windows"]
    )
    try:
        windows = parse_peak_windows(raw_windows)
    except ValueError as exc:
        logger.warning("[BILLING] %s; treating all day as off-peak", exc)
        windows = []

    weekend_raw = await get_setting(
        BILLING_CATEGORY, "weekend_offpeak", "true"
    )
    weekend_offpeak = str(weekend_raw).lower() not in ("false", "0", "no", "off")

    peak_mult = _to_float(
        await get_setting(BILLING_CATEGORY, "peak_multiplier", "1.5"), 1.5
    )
    offpeak_mult = _to_float(
        await get_setting(BILLING_CATEGORY, "offpeak_multiplier", "0.8"), 0.8
    )
    if peak_mult <= 0:
        peak_mult = 1.0
    if offpeak_mult <= 0:
        offpeak_mult = 1.0

    default_quota = _parse_quota(
        await get_setting(BILLING_CATEGORY, "default_daily_quota_cny", "")
    )

    return BillingRules(
        peak_windows=windows,
        weekend_offpeak=weekend_offpeak,
        peak_multiplier=peak_mult,
        offpeak_multiplier=offpeak_mult,
        default_daily_quota_cny=default_quota,
    )


def get_period_multiplier(rules: BillingRules, now: datetime) -> tuple[str, float]:
    """Return ("peak"|"offpeak", multiplier) for a given local timestamp."""
    if rules.weekend_offpeak and now.weekday() >= 5:
        return "offpeak", rules.offpeak_multiplier
    minutes = now.hour * 60 + now.minute
    for start, end in rules.peak_windows:
        if start < end:
            if start <= minutes < end:
                return "peak", rules.peak_multiplier
        else:  # cross-midnight window
            if minutes >= start or minutes < end:
                return "peak", rules.peak_multiplier
    return "offpeak", rules.offpeak_multiplier


def seconds_until_midnight(now: datetime) -> int:
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(int((tomorrow - now).total_seconds()), 1)


def _today_str(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m-%d")


async def resolve_key_quota(api_key_id: int) -> float | None:
    """Effective daily quota for a key: its own value or the global default.

    None = unlimited (key value 0/negative, or no key value and no default).
    """
    from app.core.database import ApiKey

    async with async_session_maker() as session:
        row = await session.get(ApiKey, api_key_id)
    raw = row.daily_quota_cny if row is not None else None
    if raw is not None:
        return raw if raw > 0 else None
    rules = await load_billing_rules()
    return rules.default_daily_quota_cny


async def get_daily_charged(api_key_id: int, day: str | None = None) -> float:
    day = day or _today_str()
    async with async_session_maker() as session:
        result = await session.execute(
            text(
                "SELECT charged_cny FROM api_key_daily_usage "
                "WHERE api_key_id = :key_id AND date = :day"
            ),
            {"key_id": api_key_id, "day": day},
        )
        row = result.first()
    return float(row[0] or 0) if row else 0.0


async def check_daily_quota(
    api_key_id: int,
) -> dict | None:
    """Return quota-exceeded info dict, or None if the request may proceed."""
    try:
        quota = await resolve_key_quota(api_key_id)
        if quota is None:
            return None
        charged = await get_daily_charged(api_key_id)
        if charged < quota:
            return None
        now = datetime.now()
        return {
            "charged_cny": round(charged, 4),
            "quota_cny": quota,
            "retry_after": seconds_until_midnight(now),
            "reset_at": _today_str(now) + " 24:00",
        }
    except Exception:
        logger.exception("[BILLING] quota check failed for key %s; allowing", api_key_id)
        return None


async def charge_daily_usage(api_key_id: int, cost_cny: float) -> dict | None:
    """Apply the period multiplier to a completed request's cost and book it.

    Returns audit fields for the request log, or None when charging is
    not applicable (no key, zero cost, or booking failure — best effort).
    """
    if not api_key_id or not cost_cny or cost_cny <= 0:
        return None
    try:
        rules = await load_billing_rules()
        period, multiplier = get_period_multiplier(rules, datetime.now())
        charge = round(cost_cny * multiplier, 10)
        day = _today_str()
        async with async_session_maker() as session:
            await session.execute(
                text(
                    "INSERT INTO api_key_daily_usage "
                    "(api_key_id, date, charged_cny, requests_charged) "
                    "VALUES (:key_id, :day, :charge, 1) "
                    "ON CONFLICT (api_key_id, date) DO UPDATE SET "
                    "charged_cny = api_key_daily_usage.charged_cny + :charge, "
                    "requests_charged = api_key_daily_usage.requests_charged + 1, "
                    "updated_at = now()"
                ),
                {"key_id": api_key_id, "day": day, "charge": charge},
            )
            await session.commit()
            daily_total = await get_daily_charged(api_key_id, day)

        quota = await resolve_key_quota(api_key_id)
        if quota is not None and daily_total >= quota > (daily_total - charge):
            await _notify_quota_reached(api_key_id, quota, daily_total)

        return {
            "billing_period": period,
            "billing_multiplier": multiplier,
            "daily_charged_cny": charge,
            "daily_total_cny": round(daily_total, 4),
        }
    except Exception:
        logger.exception(
            "[BILLING] failed to record usage for key %s (cost=%s)",
            api_key_id,
            cost_cny,
        )
        return None


async def _notify_quota_reached(api_key_id: int, quota: float, total: float) -> None:
    from app.services.notification import create_notification

    title = f"{QUOTA_NOTIFICATION_TITLE} (key #{api_key_id})"
    today = _today_str()
    try:
        from app.core.database import Notification

        async with async_session_maker() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(Notification.id)
                .where(Notification.type == "system")
                .where(Notification.title == title)
                .where(Notification.created_at >= today)
                .limit(1)
            )
            if result.first():
                return
    except Exception:
        pass
    await create_notification(
        "system",
        "warning",
        title,
        f"API Key #{api_key_id} 今日已扣费 {total:.2f} 元，达到每日额度 {quota:.2f} 元，"
        f"后续请求将被拒绝直至次日零点（{today} 24:00）。",
        target_api_key_id=api_key_id,
    )


async def get_daily_usage_summary(api_key_id: int) -> dict:
    """Dashboard payload: today's charge, quota, and current period info."""
    rules = await load_billing_rules()
    period, multiplier = get_period_multiplier(rules, datetime.now())
    quota = await resolve_key_quota(api_key_id)
    charged = await get_daily_charged(api_key_id)
    return {
        "date": _today_str(),
        "daily_charged_cny": round(charged, 4),
        "daily_quota_cny": quota,
        "billing_period": period,
        "billing_multiplier": multiplier,
    }
