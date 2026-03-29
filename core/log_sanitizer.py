import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_LOG_TEXT_LIMIT = 1000

SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "password",
    "proxy-authorization",
    "refresh_token",
    "session",
    "sessionid",
    "set-cookie",
    "token",
    "x-api-key",
}


def _truncate_text(text: str, limit: int = DEFAULT_LOG_TEXT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"


def _redact_key_value_patterns(text: str) -> str:
    redacted = text
    for key in sorted(SENSITIVE_KEYS):
        redacted = re.sub(
            rf'("{re.escape(key)}"\s*:\s*")[^"]*(")',
            rf"\1[REDACTED]\2",
            redacted,
            flags=re.IGNORECASE,
        )
        redacted = re.sub(
            rf"('{re.escape(key)}'\s*:\s*')[^']*(')",
            rf"\1[REDACTED]\2",
            redacted,
            flags=re.IGNORECASE,
        )
    return redacted


def sanitize_text_for_log(
    value: Any, limit: int = DEFAULT_LOG_TEXT_LIMIT, keep_empty: bool = True
) -> str:
    if value is None:
        return "" if keep_empty else "[empty]"
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)

    text = re.sub(r"(?i)\bBearer\s+[^\s'\"\\]+", "Bearer [REDACTED]", text)
    text = _redact_key_value_patterns(text)
    return _truncate_text(text, limit)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if key_str.lower() in SENSITIVE_KEYS:
                sanitized[key_str] = "[REDACTED]"
            else:
                sanitized[key_str] = _sanitize_value(item)
        return sanitized

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_value(item) for item in value]

    if isinstance(value, bytes):
        return sanitize_text_for_log(value, limit=DEFAULT_LOG_TEXT_LIMIT * 2)

    if isinstance(value, str):
        return sanitize_text_for_log(value, limit=DEFAULT_LOG_TEXT_LIMIT * 2)

    return value


def sanitize_payload_for_log(
    payload: Any, limit: int = DEFAULT_LOG_TEXT_LIMIT, fallback: str = ""
) -> str:
    if payload is None:
        return fallback

    if isinstance(payload, (str, bytes, bytearray)):
        return sanitize_text_for_log(payload, limit=limit)

    try:
        sanitized = _sanitize_value(payload)
        return _truncate_text(json.dumps(sanitized, ensure_ascii=False), limit)
    except Exception:
        return sanitize_text_for_log(payload, limit=limit, keep_empty=False)


def sanitize_headers_for_log(headers: Mapping[str, Any] | None) -> dict[str, Any]:
    if not headers:
        return {}
    return {
        str(key): ("[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else _sanitize_value(value))
        for key, value in headers.items()
    }
