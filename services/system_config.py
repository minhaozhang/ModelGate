import time

from sqlalchemy import select

import core.config as config
from core.database import async_session_maker, SystemSetting

CACHE_TTL_SECONDS = 300

BUSYNESS_DEFAULTS = {
    "active_users_threshold": "10",
    "rate_429_threshold": "0.5",
    "disabled_providers_critical": "2",
    "disabled_providers_busy": "1",
}

ALL_DEFAULTS = {
    "busyness": BUSYNESS_DEFAULTS,
    "proxy": {
        "ua_override": "",
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
