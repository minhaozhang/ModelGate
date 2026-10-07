import re
import time

from sqlalchemy import select

import app.core.config as config
from app.core.database import async_session_maker, SystemSetting

CACHE_TTL_SECONDS = 300

BUSYNESS_DEFAULTS = {
    "level1_active_users_threshold": "10",
    "level1_rate_429_threshold": "0.5",
    "level1_disabled_providers": "2",
    "level2_active_users_threshold": "8",
    "level2_rate_429_threshold": "0.3",
    "level2_disabled_providers": "1",
    "level3_active_users_threshold": "5",
    "level3_rate_429_threshold": "0.1",
    "level4_active_users_threshold": "1",
}

ALL_DEFAULTS = {
    "busyness": BUSYNESS_DEFAULTS,
    "proxy": {
        "ua_override": "",
        # "override" = send the fixed UA above; "passthrough" = forward the
        # client's own User-Agent upstream.
        "ua_mode": "override",
        # Persist request context + response bodies in request_contents.
        "record_content": "true",
    },
    "opencode": {
        # Provider id/name written into the generated opencode.jsonc.
        "provider_id": "modelgate",
        "provider_name": "ModelGate",
    },
    "billing": {
        "peak_windows": "09:00-12:00,14:00-18:00",
        "weekend_offpeak": "true",
        "peak_multiplier": "1.5",
        "offpeak_multiplier": "0.8",
        "default_daily_quota_cny": "",
    },
    "daily_report": {
        "error_rate_warn": "30",
        "auth_fail_warn": "100",
        "login_fail_warn": "20",
        "rate_limit_warn": "500",
        "ip_req_warn": "2000",
        "ip_auth_fail_warn": "30",
        "key_ip_warn": "3",
    },
    "concurrency": {
        "offpeak_start_hour": "20",
        "offpeak_end_hour": "11",
        "peak_user_model_limit": "2",
        "offpeak_user_model_limit": "1",
    },
    "pricing": {
        "default_cache_hit_ratio": "0",
    },
}

_settings_cache: dict[str, tuple[str, float]] = {}


def _cache_key(category: str, key: str) -> str:
    return f"{category}.{key}"


async def init_system_config():
    async with async_session_maker() as session:
        result = await session.execute(select(SystemSetting))
        rows = result.scalars().all()

    now = time.time()
    db_settings: dict[str, dict[str, str]] = {}
    for row in rows:
        cat = db_settings.setdefault(row.category, {})
        cat[row.key] = row.value

    for category, defaults in ALL_DEFAULTS.items():
        cat_db = db_settings.get(category, {})
        for key, default_val in defaults.items():
            val = cat_db.get(key) or default_val
            ck = _cache_key(category, key)
            config.system_settings[ck] = val
            _settings_cache[ck] = (val, now)

    ua = config.system_settings.get("proxy.ua_override", "")
    if ua:
        config.OUTBOUND_USER_AGENT = ua
    else:
        config.OUTBOUND_USER_AGENT = config.DEFAULT_OUTBOUND_USER_AGENT


async def _load_from_db(category: str, key: str) -> str | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(SystemSetting).where(
                SystemSetting.category == category,
                SystemSetting.key == key,
            )
        )
        row = result.scalar_one_or_none()
        return row.value if row else None


async def get_setting(category: str, key: str, default: str = "") -> str:
    ck = _cache_key(category, key)
    cached = _settings_cache.get(ck)
    if cached and (time.time() - cached[1]) < CACHE_TTL_SECONDS:
        return cached[0]

    defaults = ALL_DEFAULTS.get(category, {})
    default_val = defaults.get(key, default)

    db_val = await _load_from_db(category, key)
    val = db_val if db_val is not None else default_val

    _settings_cache[ck] = (val, time.time())
    config.system_settings[ck] = val
    return val


async def get_float_setting(category: str, key: str, default: float = 0.0) -> float:
    raw = await get_setting(category, key, str(default))
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


async def get_int_setting(category: str, key: str, default: int = 0) -> int:
    raw = await get_setting(category, key, str(default))
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


async def save_setting(category: str, key: str, value: str, description: str | None = None):
    async with async_session_maker() as session:
        result = await session.execute(
            select(SystemSetting).where(
                SystemSetting.category == category,
                SystemSetting.key == key,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.value = value
            if description is not None:
                row.description = description
        else:
            row = SystemSetting(
                category=category, key=key, value=value, description=description
            )
            session.add(row)
        await session.commit()

    ck = _cache_key(category, key)
    _settings_cache.pop(ck, None)
    config.system_settings[ck] = value


_TRUE_VALUES = ("1", "true", "yes", "on")

_OPENCODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def parse_bool(raw: str | None, default: bool = True) -> bool:
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in _TRUE_VALUES


def normalize_ua_mode(raw: str | None) -> str:
    return "passthrough" if str(raw or "").strip().lower() == "passthrough" else "override"


def valid_opencode_provider_id(value: str) -> bool:
    return bool(_OPENCODE_ID_RE.match(value or ""))


async def get_opencode_identity() -> tuple[str, str]:
    """(provider_id, provider_name) written into generated opencode configs.

    Read from the in-memory settings snapshot (populated by ``init_system_config``
    at startup and refreshed by ``save_setting``), so request handlers never need
    an extra DB round-trip — mirrors how the UA/content-recording toggles are read.
    """
    defaults = ALL_DEFAULTS["opencode"]
    provider_id = str(
        config.system_settings.get("opencode.provider_id") or defaults["provider_id"]
    ).strip()
    provider_name = str(
        config.system_settings.get("opencode.provider_name") or defaults["provider_name"]
    ).strip()
    return provider_id or defaults["provider_id"], provider_name or defaults["provider_name"]
