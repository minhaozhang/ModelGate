import asyncio
import os
import time
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
import sys
from typing import Any, Optional

from sqlalchemy import select

os.makedirs("logs", exist_ok=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, LOG_LEVEL, logging.INFO)

proxy_logger = logging.getLogger("proxy")
proxy_logger.setLevel(log_level)
proxy_file_handler = RotatingFileHandler(
    "logs/proxy.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
proxy_file_handler.setLevel(log_level)
proxy_file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
proxy_logger.addHandler(proxy_file_handler)

admin_logger = logging.getLogger("admin")
admin_logger.setLevel(log_level)
admin_file_handler = RotatingFileHandler(
    "logs/admin.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
admin_file_handler.setLevel(log_level)
admin_file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
admin_logger.addHandler(admin_file_handler)

error_logger = logging.getLogger("error")
error_logger.setLevel(log_level)
error_file_handler = RotatingFileHandler(
    "logs/error.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
error_file_handler.setLevel(log_level)
error_file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
error_logger.addHandler(error_file_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(log_level)
console_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
)
proxy_logger.addHandler(console_handler)
admin_logger.addHandler(console_handler)
error_logger.addHandler(console_handler)

logger = proxy_logger

logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

CONFIG = {
    "port": int(os.getenv("PORT", 8765)),
}

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "modelgate")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() in ("true", "1", "yes")


login_attempts: dict[str, int] = {}
login_lockout: dict[str, datetime] = {}
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 5

providers_cache: dict[str, dict] = {}
providers_cache_time: Optional[datetime] = None
PROVIDERS_CACHE_TTL_MINUTES = 10
api_keys_cache: dict[str, dict] = {}
provider_key_semaphores: dict[str, "asyncio.Semaphore"] = {}
provider_key_model_semaphores: dict[str, "asyncio.Semaphore"] = {}
user_api_key_semaphores: dict[str, "asyncio.Semaphore"] = {}
standard_model_semaphores: dict[str, "asyncio.Semaphore"] = {}
_model_requests_24h_cache: dict[str, Any] = {"counts": None, "series": None, "recent": None, "at": 0.0}

DEFAULT_OUTBOUND_USER_AGENT = (
    "opencode/local ai-sdk/provider-utils/4.0.23 runtime/node.js/24"
)
OUTBOUND_USER_AGENT = DEFAULT_OUTBOUND_USER_AGENT
system_config: dict[str, Any] = {}
system_settings: dict[str, str] = {}

stats = {
    "total_requests": 0,
    "total_tokens": 0,
    "providers": defaultdict(
        lambda: {"requests": 0, "tokens": 0, "errors": 0, "rate_limited": 0}
    ),
    "models": defaultdict(lambda: {"requests": 0, "tokens": 0}),
    "api_keys": defaultdict(
        lambda: {
            "requests": 0,
            "tokens": 0,
            "errors": 0,
            "rate_limited": 0,
            "models": defaultdict(lambda: {"requests": 0, "tokens": 0}),
        }
    ),
    "requests_per_minute": [],
    "rate_limited_per_minute": [],
}

requests_per_second: list[tuple[str, int]] = []
token_buckets: list[tuple[str, int]] = []
_tokens_per_second_ewma: float | None = None
TOKEN_RATE_WINDOW_SECONDS = 10
TOKEN_RATE_EWMA_ALPHA = 0.3

today_stats_cache: dict = {}
today_stats_cache_time: Optional[datetime] = None
TODAY_STATS_CACHE_TTL_SECONDS = 600
LIVE_REQUEST_STALE_SECONDS = 660
MAX_LIVE_REQUEST_ROWS = 200


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


# User-concurrency slots held longer than this are force-released so a long
# thinking/streaming request does not lock a user with concurrency=1 out of
# new requests entirely.
USER_SLOT_STALE_SECONDS = _env_float("MODELGATE_USER_SLOT_STALE_SECONDS", 60.0)
USER_SLOT_WATCHDOG_INTERVAL_SECONDS = _env_float(
    "MODELGATE_USER_SLOT_WATCHDOG_INTERVAL", 5.0
)
user_slot_released_ids: set[str] = set()
# Wait at most this long for upstream response headers + first SSE line
# before treating the attempt as hung and letting route fallback pick
# another provider/key. Keep above slow-provider first-token latencies.
STREAM_FIRST_CHUNK_TIMEOUT_SECONDS = _env_float(
    "STREAM_FIRST_CHUNK_TIMEOUT_SECONDS", 90.0
)
# After first-chunk timeouts exhaust all routes, only suggest the client
# compacts when the context is actually large.
COMPACT_HINT_MIN_TOKENS = _env_float(
    "MODELGATE_COMPACT_HINT_MIN_TOKENS", 40000.0
)
active_requests: dict[str, dict[str, Any]] = {}
active_requests_lock = asyncio.Lock()
busyness_state: dict[str, Any] = {}
live_stats_subscribers: set[Any] = set()
live_stats_subscribers_lock = asyncio.Lock()
user_live_stats_subscribers: set[Any] = set()
user_live_stats_subscribers_lock = asyncio.Lock()


def validate_session(token: Optional[str]) -> bool:
    if not token:
        return False
    if not token.startswith("ey"):
        return False
    try:
        import jwt as pyjwt

        payload = pyjwt.decode(
            token,
            os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production"),
            algorithms=["HS256"],
        )
        return bool(payload.get("user_id"))
    except Exception:
        return False
def update_stats(
    provider: str,
    model: str,
    tokens: int,
    api_key_id: Optional[int] = None,
    is_error: bool = False,
    is_rate_limited: bool = False,
    upstream_model: Optional[str] = None,
    requested_model: Optional[str] = None,
):
    from app.services.model_naming import user_stats_model_name

    if not is_rate_limited:
        stats["total_requests"] += 1
        stats["total_tokens"] += tokens
        stats["providers"][provider]["requests"] += 1
        stats["providers"][provider]["tokens"] += tokens
        provider_model = upstream_model or model
        stats["models"][provider_model]["requests"] += 1
        stats["models"][provider_model]["tokens"] += tokens

        if api_key_id:
            stats["api_keys"][api_key_id]["requests"] += 1
            stats["api_keys"][api_key_id]["tokens"] += tokens
            user_model = user_stats_model_name(requested_model, model)
            stats["api_keys"][api_key_id]["models"][user_model]["requests"] += 1
            stats["api_keys"][api_key_id]["models"][user_model]["tokens"] += tokens

    if is_error:
        stats["providers"][provider]["errors"] += 1
    if is_rate_limited:
        stats["providers"][provider]["rate_limited"] += 1
    if api_key_id:
        if is_error:
            stats["api_keys"][api_key_id]["errors"] += 1
        if is_rate_limited:
            stats["api_keys"][api_key_id]["rate_limited"] += 1

    now = datetime.now()
    minute_key = now.strftime("%Y%m%d_%H%M")
    stats["requests_per_minute"].append(minute_key)
    stats["requests_per_minute"] = stats["requests_per_minute"][-1000:]
    if is_rate_limited:
        stats.setdefault("rate_limited_per_minute", []).append(minute_key)
        stats["rate_limited_per_minute"] = stats["rate_limited_per_minute"][-1000:]

    second_key = now.strftime("%Y%m%d_%H%M%S")
    requests_per_second.append((second_key, 1))
    cutoff = (now - timedelta(seconds=10)).strftime("%Y%m%d_%H%M%S")
    requests_per_second[:] = [(k, v) for k, v in requests_per_second if k >= cutoff]


def _trim_token_buckets(now: datetime) -> None:
    cutoff = (now - timedelta(seconds=TOKEN_RATE_WINDOW_SECONDS)).strftime(
        "%Y%m%d_%H%M%S"
    )
    token_buckets[:] = [(k, v) for k, v in token_buckets if k >= cutoff]


def record_tokens_second(tokens: int) -> None:
    """按秒累积 tokens（负值用于流式估算校正，桶值不为负）。"""
    if tokens == 0:
        return
    now = datetime.now()
    second_key = now.strftime("%Y%m%d_%H%M%S")
    if token_buckets and token_buckets[-1][0] == second_key:
        token_buckets[-1] = (second_key, max(token_buckets[-1][1] + tokens, 0))
    else:
        token_buckets.append((second_key, max(tokens, 0)))
    _trim_token_buckets(now)


def record_stream_text_delta(text: str) -> None:
    """流式 chunk 增量估算（len/4，与 build_tokens_record 估算口径一致）。"""
    if not text:
        return
    record_tokens_second(len(text) // 4)


def get_total_tokens_per_second() -> float:
    global _tokens_per_second_ewma
    now = datetime.now()
    _trim_token_buckets(now)
    total = sum(v for _, v in token_buckets)
    raw = round(total / TOKEN_RATE_WINDOW_SECONDS, 1)
    if _tokens_per_second_ewma is None:
        _tokens_per_second_ewma = raw
    else:
        _tokens_per_second_ewma = round(
            _tokens_per_second_ewma * (1 - TOKEN_RATE_EWMA_ALPHA)
            + raw * TOKEN_RATE_EWMA_ALPHA,
            1,
        )
    if _tokens_per_second_ewma <= 0.1:
        _tokens_per_second_ewma = 0.0
    return _tokens_per_second_ewma


def get_api_key_name(api_key_id: int | None) -> str | None:
    if not api_key_id:
        return None
    for key_data in api_keys_cache.values():
        if key_data["id"] == api_key_id:
            return key_data["name"]
    return None


def get_api_key_tags(api_key_id: int | None) -> list[str]:
    if not api_key_id:
        return []
    for key_data in api_keys_cache.values():
        if key_data["id"] == api_key_id:
            return list(key_data.get("tags") or [])
    return []


async def register_active_request(
    request_id: str,
    provider: str,
    model: str,
    api_key_id: int | None,
    client_ip: str | None = None,
    prompt_tokens: int = 0,
    requested_model: str | None = None,
    upstream_model: str | None = None,
    user_semaphore: Any = None,
) -> None:
    from app.services.model_naming import user_stats_model_name

    now = datetime.now()
    async with active_requests_lock:
        active_requests[request_id] = {
            "request_id": request_id,
            "provider": provider,
            "model": model,
            "requested_model": requested_model,
            "display_model": user_stats_model_name(requested_model, model),
            "upstream_model": upstream_model,
            "api_key_id": api_key_id,
            "client_ip": client_ip,
            "prompt_tokens": prompt_tokens,
            "started_at": now,
            "user_semaphore": user_semaphore,
        }
    asyncio.create_task(broadcast_live_stats())


async def finish_active_request(request_id: str) -> None:
    entry: dict[str, Any] | None = None
    async with active_requests_lock:
        entry = active_requests.pop(request_id, None)
    if entry is not None:
        if entry.get("user_slot_released"):
            user_slot_released_ids.add(request_id)
        asyncio.create_task(broadcast_live_stats())


async def release_stale_user_slots() -> int:
    """Force-release user-concurrency slots held beyond USER_SLOT_STALE_SECONDS.

    The owning request still runs to completion; it just no longer blocks the
    user's semaphore. Its natural release is skipped via the
    user_slot_released marker so the slot is never released twice.
    """
    now = datetime.now()
    released = 0
    async with active_requests_lock:
        for request_id, request_data in list(active_requests.items()):
            if request_data.get("user_slot_released"):
                continue
            semaphore = request_data.get("user_semaphore")
            started_at = request_data.get("started_at")
            if semaphore is None or started_at is None:
                continue
            age = (now - started_at).total_seconds()
            if age > USER_SLOT_STALE_SECONDS:
                request_data["user_slot_released"] = True
                semaphore.release()
                released += 1
                logger.info(
                    "[USER SLOT] Force-released stale user slot for request %s "
                    "(held %.0fs > %.0fs)",
                    request_id,
                    age,
                    USER_SLOT_STALE_SECONDS,
                )
    return released


def consume_user_slot_released(request_id: str) -> bool:
    """True once if the watchdog already released this request's user slot."""
    if request_id in user_slot_released_ids:
        user_slot_released_ids.discard(request_id)
        return True
    return False


def start_user_slot_watchdog() -> asyncio.Task | None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None

    async def _watchdog_loop() -> None:
        while True:
            await asyncio.sleep(USER_SLOT_WATCHDOG_INTERVAL_SECONDS)
            try:
                await release_stale_user_slots()
            except Exception:
                logger.exception("user slot watchdog iteration failed")

    return loop.create_task(_watchdog_loop())


async def prune_stale_active_requests() -> bool:
    cutoff = datetime.now() - timedelta(seconds=LIVE_REQUEST_STALE_SECONDS)
    removed = False
    async with active_requests_lock:
        stale_ids = [
            request_id
            for request_id, request_data in active_requests.items()
            if request_data.get("started_at") and request_data["started_at"] < cutoff
        ]
        for request_id in stale_ids:
            active_requests.pop(request_id, None)
            removed = True
    if removed:
        asyncio.create_task(broadcast_live_stats())
    return removed


async def build_live_stats_snapshot() -> dict[str, Any]:
    await prune_stale_active_requests()
    async with active_requests_lock:
        snapshot_now = datetime.now()
        grouped_users: dict[str, dict[str, Any]] = {}
        request_rows: list[dict[str, Any]] = []
        for request_data in active_requests.values():
            key_name = get_api_key_name(request_data.get("api_key_id")) or "Unknown"
            bucket = grouped_users.setdefault(
                key_name,
                {
                    "api_key_id": request_data.get("api_key_id"),
                    "tags": get_api_key_tags(request_data.get("api_key_id")),
                    "models": {},
                    "requests": 0,
                    "tokens": 0,
                    "last_activity": request_data["started_at"].isoformat(),
                    "first_activity": request_data["started_at"].isoformat(),
                },
            )
            bucket["requests"] += 1
            bucket["last_activity"] = max(
                bucket["last_activity"],
                request_data["started_at"].isoformat(),
            )
            bucket["first_activity"] = min(
                bucket["first_activity"],
                request_data["started_at"].isoformat(),
            )
            requested = request_data.get("display_model")
            actual = (
                request_data.get("upstream_model") or request_data.get("model")
            )
            provider_name = request_data.get("provider") or ""
            prompt_tokens = request_data.get("prompt_tokens", 0)
            request_rows.append(
                {
                    "id": request_data.get("request_id"),
                    "key": key_name,
                    "tags": bucket["tags"],
                    "model": requested or actual,
                    "provider": provider_name,
                    "actual": actual,
                    "tokens": prompt_tokens,
                    "elapsed_seconds": round(
                        (snapshot_now - request_data["started_at"]).total_seconds(),
                        1,
                    ),
                }
            )
            if not provider_name:
                model_key = requested or actual
            elif not requested or requested == actual:
                model_key = f"{provider_name}/{actual}"
            else:
                model_key = f"{requested} -> {provider_name}/{actual}"
            if model_key:
                entry = bucket["models"].setdefault(
                    model_key,
                    {
                        "count": 0,
                        "tokens": 0,
                        "provider": provider_name,
                        "oldest_started_at": request_data["started_at"],
                    },
                )
                entry["count"] += 1
                entry["tokens"] += prompt_tokens
                if request_data["started_at"] < entry["oldest_started_at"]:
                    entry["oldest_started_at"] = request_data["started_at"]
            bucket["tokens"] += prompt_tokens

        if len(request_rows) > MAX_LIVE_REQUEST_ROWS:
            request_rows = request_rows[-MAX_LIVE_REQUEST_ROWS:]

        for bucket in grouped_users.values():
            for entry in bucket["models"].values():
                oldest = entry.pop("oldest_started_at", None)
                entry["elapsed_seconds"] = (
                    round((snapshot_now - oldest).total_seconds(), 1)
                    if oldest is not None
                    else 0
                )

        disabled_providers = {}
        for pname, pconf in providers_cache.items():
            if pconf.get("disabled_reason"):
                disabled_providers[pname] = pconf["disabled_reason"]

        key_concurrency = {}
        for sem_key, sem in provider_key_semaphores.items():
            limit = (
                getattr(sem, "_modelgate_scoped_limit", getattr(sem, "_value", 0))
                or 0
            )
            available = getattr(sem, "_value", 0)
            key_concurrency[sem_key] = {
                "limit": limit,
                "in_use": max(limit - available, 0),
            }

        return {
            "active_requests": len(active_requests),
            "active_users": len(grouped_users),
            "tokens_per_second": get_total_tokens_per_second(),
            "sessions": dict(sorted(grouped_users.items(), key=lambda item: item[1]["first_activity"])),
            "requests": request_rows,
            "disabled_providers": disabled_providers,
            "key_concurrency": key_concurrency,
        }


async def build_user_live_stats_snapshot() -> dict[str, Any]:
    await prune_stale_active_requests()
    async with active_requests_lock:
        active_requests_count = len(active_requests)
        active_users_count = len(
            {entry.get("api_key_id") for entry in active_requests.values()}
        )
    disabled_providers = {
        pname: pconf.get("disabled_reason")
        for pname, pconf in providers_cache.items()
        if pconf.get("disabled_reason")
    }

    from app.services.provider import _model_max_concurrent_by_name
    from app.services.proxy_runtime.concurrency import (
        DEFAULT_PROVIDER_KEY_MAX_CONCURRENCY,
    )

    model_concurrency = {}
    for model_name, limit in _model_max_concurrent_by_name.items():
        if limit is None:
            continue
        sem = standard_model_semaphores.get(f"stdmodel:{model_name}")
        available = getattr(sem, "_value", None) if sem else None
        in_use = max(limit - available, 0) if available is not None else 0

        capacity = 0
        for pcfg in providers_cache.values():
            if pcfg.get("disabled_reason"):
                continue
            if not any(
                pm.get("model_name") == model_name
                for pm in pcfg.get("models", [])
            ):
                continue
            for k in pcfg.get("api_keys", []):
                klimit = k.get("max_concurrent")
                if klimit is None:
                    capacity += DEFAULT_PROVIDER_KEY_MAX_CONCURRENCY
                else:
                    capacity += klimit

        effective = min(limit, capacity)
        model_concurrency[model_name] = {
            "limit": limit,
            "in_use": in_use,
            "effective": effective,
        }

    model_requests_24h: Optional[dict[str, int]] = None
    model_hourly_24h: Optional[dict[str, list[int]]] = None
    model_rate_per_min: Optional[dict[str, int]] = None
    global _model_requests_24h_cache
    now_ts = time.monotonic()
    if now_ts - _model_requests_24h_cache["at"] > 60:
        try:
            from app.core.database import RequestLog, async_session_maker

            now_dt = datetime.now()
            cutoff = now_dt - timedelta(hours=24)
            async with async_session_maker() as session:
                rows = await session.execute(
                    select(RequestLog.model, RequestLog.created_at).where(
                        RequestLog.created_at >= cutoff
                    )
                )
                counts: dict[str, int] = {}
                series: dict[str, list[int]] = {}
                for name, created_at in rows.fetchall():
                    if not name:
                        continue
                    counts[name] = counts.get(name, 0) + 1
                    buckets = series.setdefault(name, [0] * 24)
                    idx = int((created_at - cutoff).total_seconds() // 3600)
                    if 0 <= idx < 24:
                        buckets[idx] += 1
                _model_requests_24h_cache["counts"] = counts
                _model_requests_24h_cache["series"] = series

                recent_cutoff = now_dt - timedelta(seconds=60)
                recent_rows = await session.execute(
                    select(RequestLog.model).where(
                        RequestLog.created_at >= recent_cutoff
                    )
                )
                recent: dict[str, int] = {}
                for (name,) in recent_rows.fetchall():
                    if name:
                        recent[name] = recent.get(name, 0) + 1
                _model_requests_24h_cache["recent"] = recent
        except Exception:
            logging.getLogger(__name__).warning(
                "model_requests_24h query failed", exc_info=True
            )
        _model_requests_24h_cache["at"] = now_ts
    if _model_requests_24h_cache["counts"] is not None:
        model_requests_24h = _model_requests_24h_cache["counts"]
        model_hourly_24h = _model_requests_24h_cache.get("series")
        model_rate_per_min = _model_requests_24h_cache.get("recent")

    return {
        "active_requests": active_requests_count,
        "active_users": active_users_count,
        "tokens_per_second": get_total_tokens_per_second(),
        "busyness": dict(busyness_state) if busyness_state else None,
        "disabled_providers": disabled_providers,
        "model_concurrency": model_concurrency,
        "model_requests_24h": model_requests_24h,
        "model_hourly_24h": model_hourly_24h,
        "model_rate_per_min": model_rate_per_min,
    }


async def add_live_stats_subscriber(subscriber: Any) -> None:
    async with live_stats_subscribers_lock:
        live_stats_subscribers.add(subscriber)


async def remove_live_stats_subscriber(subscriber: Any) -> None:
    async with live_stats_subscribers_lock:
        live_stats_subscribers.discard(subscriber)


async def add_user_live_stats_subscriber(subscriber: Any) -> None:
    async with user_live_stats_subscribers_lock:
        user_live_stats_subscribers.add(subscriber)


async def remove_user_live_stats_subscriber(subscriber: Any) -> None:
    async with user_live_stats_subscribers_lock:
        user_live_stats_subscribers.discard(subscriber)


async def _send_payload_to_subscribers(
    subscribers: list[Any], payload: dict[str, Any]
) -> list[Any]:
    stale_subscribers = []
    for subscriber in subscribers:
        try:
            await subscriber.send_json(payload)
        except Exception:
            stale_subscribers.append(subscriber)
    return stale_subscribers


async def _discard_stale_subscribers(
    stale: list[Any], lock: asyncio.Lock, container: set[Any]
) -> None:
    async with lock:
        for subscriber in stale:
            container.discard(subscriber)


async def broadcast_live_stats() -> None:
    snapshot = await build_live_stats_snapshot()
    async with live_stats_subscribers_lock:
        subscribers = list(live_stats_subscribers)
    stale = await _send_payload_to_subscribers(subscribers, snapshot)
    if stale:
        await _discard_stale_subscribers(
            stale, live_stats_subscribers_lock, live_stats_subscribers
        )

    if not user_live_stats_subscribers:
        return
    user_snapshot = await build_user_live_stats_snapshot()
    async with user_live_stats_subscribers_lock:
        user_subscribers = list(user_live_stats_subscribers)
    stale = await _send_payload_to_subscribers(user_subscribers, user_snapshot)
    if stale:
        await _discard_stale_subscribers(
            stale, user_live_stats_subscribers_lock, user_live_stats_subscribers
        )
