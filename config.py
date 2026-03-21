import os
import sys
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

os.makedirs("logs", exist_ok=True)

proxy_logger = logging.getLogger("proxy")
proxy_logger.setLevel(logging.DEBUG)
proxy_file_handler = RotatingFileHandler(
    "logs/proxy.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
proxy_file_handler.setLevel(logging.DEBUG)
proxy_file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
proxy_logger.addHandler(proxy_file_handler)

admin_logger = logging.getLogger("admin")
admin_logger.setLevel(logging.DEBUG)
admin_file_handler = RotatingFileHandler(
    "logs/admin.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
admin_file_handler.setLevel(logging.DEBUG)
admin_file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
admin_logger.addHandler(admin_file_handler)

error_logger = logging.getLogger("error")
error_logger.setLevel(logging.DEBUG)
error_file_handler = RotatingFileHandler(
    "logs/error.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
error_file_handler.setLevel(logging.DEBUG)
error_file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
error_logger.addHandler(error_file_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
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
    "admin_password": os.getenv("ADMIN_PASSWORD", "admin123"),
}

providers_cache: dict[str, dict] = {}
providers_cache_time: Optional[datetime] = None
PROVIDERS_CACHE_TTL_MINUTES = 10
api_keys_cache: dict[str, dict] = {}
sessions: dict[str, datetime] = {}
provider_semaphores: dict[str, "asyncio.Semaphore"] = {}

stats = {
    "total_requests": 0,
    "total_tokens": 0,
    "providers": defaultdict(lambda: {"requests": 0, "tokens": 0, "errors": 0}),
    "models": defaultdict(lambda: {"requests": 0, "tokens": 0}),
    "api_keys": defaultdict(
        lambda: {
            "requests": 0,
            "tokens": 0,
            "errors": 0,
            "models": defaultdict(lambda: {"requests": 0, "tokens": 0}),
        }
    ),
    "requests_per_minute": [],
}


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
):
    stats["total_requests"] += 1
    stats["total_tokens"] += tokens
    stats["providers"][provider]["requests"] += 1
    stats["providers"][provider]["tokens"] += tokens
    if is_error:
        stats["providers"][provider]["errors"] += 1
    stats["models"][model]["requests"] += 1
    stats["models"][model]["tokens"] += tokens

    if api_key_id:
        stats["api_keys"][api_key_id]["requests"] += 1
        stats["api_keys"][api_key_id]["tokens"] += tokens
        if is_error:
            stats["api_keys"][api_key_id]["errors"] += 1
        stats["api_keys"][api_key_id]["models"][model]["requests"] += 1
        stats["api_keys"][api_key_id]["models"][model]["tokens"] += tokens

    now = datetime.now()
    minute_key = now.strftime("%Y%m%d_%H%M")
    stats["requests_per_minute"].append(minute_key)
    stats["requests_per_minute"] = stats["requests_per_minute"][-1000:]
