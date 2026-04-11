import asyncio
import os
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
import sys
from typing import Any, Optional

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


def parse_admin_users() -> dict[str, str]:
    users_env = os.getenv("ADMIN_USERS", "")
    if users_env:
        users = {}
        for pair in users_env.split(","):
            if ":" in pair:
                username, password = pair.strip().split(":", 1)
                users[username] = password
        return users
    return {
        os.getenv("ADMIN_USERNAME", "admin"): os.getenv("ADMIN_PASSWORD", "admin123")
    }


admin_users: dict[str, str] = parse_admin_users()

login_attempts: dict[str, int] = {}
login_lockout: dict[str, datetime] = {}
LOGIN_MAX_ATTEMPTS = 3
LOGIN_LOCKOUT_MINUTES = 5

providers_cache: dict[str, dict] = {}
providers_cache_time: Optional[datetime] = None
PROVIDERS_CACHE_TTL_MINUTES = 10
api_keys_cache: dict[str, dict] = {}
sessions: dict[str, datetime] = {}
provider_semaphores: dict[str, "asyncio.Semaphore"] = {}

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
}

requests_per_second: list[tuple[str, int]] = []
tokens_per_second: list[tuple[str, int]] = []

today_stats_cache: dict = {}
today_stats_cache_time: Optional[datetime] = None
TODAY_STATS_CACHE_TTL_SECONDS = 600
LIVE_REQUEST_STALE_SECONDS = 660
active_requests: dict[str, dict[str, Any]] = {}
active_requests_lock = asyncio.Lock()
live_stats_subscribers: set[Any] = set()
live_stats_subscribers_lock = asyncio.Lock()


def create_session() -> str:
    import secrets

    token = secrets.token_urlsafe(32)
    sessions[token] = datetime.now() + timedelta(hours=24)
    return token


def validate_session(token: Optional[str]) -> bool:
    if not token:
        return False
    expiry = sessions.get(token)
    if not expiry:
        return False
    if datetime.now() > expiry:
        del sessions[token]
        return False
    return True


def clear_session(token: str):
    sessions.pop(token, None)


def update_stats(
    provider: str,
    model: str,
    tokens: int,
    api_key_id: Optional[int] = None,
    is_error: bool = False,
    is_rate_limited: bool = False,
):
    if not is_rate_limited:
        stats["total_requests"] += 1
        stats["total_tokens"] += tokens
        stats["providers"][provider]["requests"] += 1
        stats["providers"][provider]["tokens"] += tokens
        stats["models"][model]["requests"] += 1
        stats["models"][model]["tokens"] += tokens

        if api_key_id:
            stats["api_keys"][api_key_id]["requests"] += 1
            stats["api_keys"][api_key_id]["tokens"] += tokens
            stats["api_keys"][api_key_id]["models"][model]["requests"] += 1
            stats["api_keys"][api_key_id]["models"][model]["tokens"] += tokens

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

    second_key = now.strftime("%Y%m%d_%H%M%S")
    requests_per_second.append((second_key, 1))
    tokens_per_second.append((second_key, tokens))
    cutoff = (now - timedelta(seconds=10)).strftime("%Y%m%d_%H%M%S")
    requests_per_second[:] = [(k, v) for k, v in requests_per_second if k >= cutoff]
    tokens_per_second[:] = [(k, v) for k, v in tokens_per_second if k >= cutoff]


def get_api_key_name(api_key_id: int | None) -> str | None:
    if not api_key_id:
        return None
    for key_data in api_keys_cache.values():
        if key_data["id"] == api_key_id:
            return key_data["name"]
    return None


async def register_active_request(
    request_id: str,
    provider: str,
    model: str,
    api_key_id: int | None,
    client_ip: str | None = None,
) -> None:
    now = datetime.now()
    async with active_requests_lock:
        active_requests[request_id] = {
            "request_id": request_id,
            "provider": provider,
            "model": model,
            "api_key_id": api_key_id,
            "client_ip": client_ip,
            "started_at": now,
        }
    asyncio.create_task(broadcast_live_stats())


async def finish_active_request(request_id: str) -> None:
    removed = False
    async with active_requests_lock:
        removed = active_requests.pop(request_id, None) is not None
    if removed:
        asyncio.create_task(broadcast_live_stats())


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
        grouped_users: dict[str, dict[str, Any]] = {}
        for request_data in active_requests.values():
            key_name = get_api_key_name(request_data.get("api_key_id")) or "Unknown"
            bucket = grouped_users.setdefault(
                key_name,
                {
                    "api_key_id": request_data.get("api_key_id"),
                    "models": {},
                    "requests": 0,
                    "last_activity": request_data["started_at"].isoformat(),
                },
            )
            bucket["requests"] += 1
            bucket["last_activity"] = max(
                bucket["last_activity"],
                request_data["started_at"].isoformat(),
            )
            model_name = request_data.get("model")
            if model_name:
                bucket["models"][model_name] = bucket["models"].get(model_name, 0) + 1

        for key_name, bucket in grouped_users.items():
            api_key_id = bucket.get("api_key_id")
            if api_key_id and api_key_id in stats["api_keys"]:
                bucket["tokens"] = stats["api_keys"][api_key_id].get("tokens", 0)
            else:
                bucket["tokens"] = 0

        now = datetime.now()
        cutoff = (now - timedelta(seconds=10)).strftime("%Y%m%d_%H%M%S")
        t_by_second: dict[str, int] = {}
        for k, v in tokens_per_second:
            if k >= cutoff:
                t_by_second[k] = t_by_second.get(k, 0) + v
        token_active_seconds = max(len([v for v in t_by_second.values() if v > 0]), 1)
        total_tokens = sum(t_by_second.values())

        return {
            "active_requests": len(active_requests),
            "active_users": len(grouped_users),
            "tokens_per_second": round(total_tokens / token_active_seconds, 1),
            "sessions": dict(
                sorted(
                    grouped_users.items(),
                    key=lambda item: item[1]["last_activity"],
                    reverse=True,
                )
            ),
        }


async def add_live_stats_subscriber(subscriber: Any) -> None:
    async with live_stats_subscribers_lock:
        live_stats_subscribers.add(subscriber)


async def remove_live_stats_subscriber(subscriber: Any) -> None:
    async with live_stats_subscribers_lock:
        live_stats_subscribers.discard(subscriber)


async def broadcast_live_stats() -> None:
    snapshot = await build_live_stats_snapshot()
    async with live_stats_subscribers_lock:
        subscribers = list(live_stats_subscribers)
    stale_subscribers = []
    for subscriber in subscribers:
        try:
            await subscriber.send_json(snapshot)
        except Exception:
            stale_subscribers.append(subscriber)
    if stale_subscribers:
        async with live_stats_subscribers_lock:
            for subscriber in stale_subscribers:
                live_stats_subscribers.discard(subscriber)
