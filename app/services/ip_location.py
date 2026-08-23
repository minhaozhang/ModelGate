"""IP geolocation lookup backed by AMap v3/ip + ipinfo.io with local DB cache.

Lookup order:
1. LAN/loopback/invalid IPs are answered locally (no external call, no cache row).
2. Cached row in ip_locations.
3. Both providers are queried concurrently and merged:
   - AMap: province/city/adcode/rectangle (Chinese, domestic IPv4 only)
   - ipinfo.io: country/city/region/loc/org-ISP (works worldwide)
   Only fields from successful responses are persisted; provider errors
   (QPS limit, daily quota, invalid key, rate limit, ...) are never written
   to the database and are negatively cached in-memory for a short TTL so
   repeated clicks don't burn the quota.
"""

from __future__ import annotations

import asyncio
import ipaddress
import time

import httpx
from sqlalchemy import select

from app.core.config import logger
from app.core.database import IpLocation, async_session_maker
from app.services.system_config import get_setting

AMAP_IP_API = "https://restapi.amap.com/v3/ip"
IPINFO_IP_API = "https://ipinfo.io"
DEFAULT_AMAP_KEY = "d595bc8feb6202d679ebf73ef7e395a7"
AMAP_SUCCESS_INFOCODE = "10000"
AMAP_LAN_PROVINCE = "局域网"
HTTP_TIMEOUT_SECONDS = 8.0
FAILURE_CACHE_TTL_SECONDS = 120.0

# AMap infocodes worth surfacing to the admin UI as "retry later".
_RETRYABLE_INFOCODES = {
    "10021": "CUQPS_HAS_EXCEEDED_THE_LIMIT",
    "10044": "DAILY_QUERY_OVER_LIMIT",
    "10019": "CQPS_HAS_EXCEEDED_THE_LIMIT",
}

_failure_cache: dict[str, tuple[float, dict]] = {}
_lookup_locks: dict[str, asyncio.Lock] = {}


def _classify_local_ip(ip: str) -> str | None:
    """Return a human label for IPs geolocation APIs can never resolve, else None."""
    if not ip or ip in ("-", "unknown", "internal"):
        return "unknown"
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "unknown"
    if addr.version == 6:
        return "ipv6"
    if not addr.is_global:
        return "lan"
    return None


def _clean_str(value) -> str | None:
    """AMap/ipinfo may return [] or missing keys instead of strings."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _rectangle_center(rectangle: str | None) -> str | None:
    """AMap 'x1,y1;x2,y2' -> center 'cx,cy'."""
    if not rectangle or ";" not in rectangle:
        return None
    try:
        (x1, y1), (x2, y2) = (
            tuple(float(v) for v in part.split(",")[:2])
            for part in rectangle.split(";")[:2]
        )
        return f"{(x1 + x2) / 2:.6f},{(y1 + y2) / 2:.6f}"
    except (ValueError, TypeError, IndexError):
        return None


async def _fetch_from_amap(ip: str) -> tuple[dict | None, dict | None]:
    """Return (fields, error). fields is None when AMap yielded nothing usable."""
    key = (await get_setting("ip_location", "amap_key", DEFAULT_AMAP_KEY)).strip()
    if not key:
        key = DEFAULT_AMAP_KEY

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.get(AMAP_IP_API, params={"key": key, "ip": ip})
            payload = resp.json()
    except Exception as exc:
        logger.warning("[IP LOCATION] AMap request failed for %s: %s", ip, exc)
        return None, {"reason": "amap_unreachable", "message": f"高德接口请求失败: {exc}"}

    status = str(payload.get("status", "0"))
    infocode = str(payload.get("infocode", ""))
    info = str(payload.get("info", ""))

    if status != "1" or infocode != AMAP_SUCCESS_INFOCODE:
        retryable = infocode in _RETRYABLE_INFOCODES
        logger.warning(
            "[IP LOCATION] AMap rejected %s: status=%s infocode=%s info=%s",
            ip, status, infocode, info,
        )
        return None, {
            "reason": "amap_error",
            "retryable": retryable,
            "infocode": infocode,
            "message": f"高德接口返回错误: {info} ({infocode})",
        }

    province = _clean_str(payload.get("province"))
    if not province or province == AMAP_LAN_PROVINCE:
        # LAN or foreign/unresolvable IP: nothing usable from AMap.
        return None, None

    rectangle = _clean_str(payload.get("rectangle"))
    return (
        {
            "province": province,
            "city": _clean_str(payload.get("city")) or "",
            "adcode": _clean_str(payload.get("adcode")) or "",
            "rectangle": rectangle or "",
            "loc": _rectangle_center(rectangle) or "",
        },
        None,
    )


def _normalize_isp(org: str | None) -> str | None:
    """'AS4837 CHINA UNICOM China169 Backbone' -> 'CHINA UNICOM China169 Backbone'."""
    if not org:
        return None
    parts = org.split(" ", 1)
    if len(parts) == 2 and parts[0].upper().startswith("AS") and parts[0][2:].isdigit():
        return parts[1].strip() or org
    return org


async def _fetch_from_ipinfo(ip: str) -> tuple[dict | None, dict | None]:
    """Return (fields, error). fields is None when ipinfo yielded nothing usable."""
    token = (await get_setting("ip_location", "ipinfo_token", "")).strip()

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{IPINFO_IP_API}/{ip}/json",
                params={"token": token} if token else None,
            )
            if resp.status_code == 429:
                return None, {"reason": "ipinfo_rate_limited", "message": "ipinfo.io 请求频率超限 (429)"}
            payload = resp.json()
    except Exception as exc:
        logger.warning("[IP LOCATION] ipinfo request failed for %s: %s", ip, exc)
        return None, {"reason": "ipinfo_unreachable", "message": f"ipinfo.io 请求失败: {exc}"}

    if not isinstance(payload, dict) or payload.get("bogon"):
        return None, None

    country = _clean_str(payload.get("country"))
    isp = _normalize_isp(_clean_str(payload.get("org")))
    city = _clean_str(payload.get("city"))
    region = _clean_str(payload.get("region"))
    loc = _clean_str(payload.get("loc"))
    if loc and "," in loc:
        # ipinfo returns "lat,lon"; normalize to AMap-style "lon,lat".
        lat, _, lon = loc.partition(",")
        try:
            loc = f"{float(lon):.6f},{float(lat):.6f}"
        except ValueError:
            loc = None

    if not any((country, isp, city, region, loc)):
        return None, None

    return (
        {
            "country": country or "",
            "isp": isp or "",
            "city": city or "",
            "province": region or "",
            "loc": loc or "",
        },
        None,
    )


def _cache_hit_fields(row: IpLocation) -> dict:
    return {
        "ip": row.ip,
        "cached": True,
        "ok": True,
        "province": row.province or "",
        "city": row.city or "",
        "adcode": row.adcode or "",
        "rectangle": row.rectangle or "",
        "loc": row.loc or "",
        "country": row.country or "",
        "isp": row.isp or "",
        "message": "",
    }


_PERSIST_FIELDS = ("province", "city", "adcode", "rectangle", "loc", "country", "isp")


def _merge_fields(amap: dict | None, ipinfo: dict | None) -> dict:
    merged = {k: "" for k in _PERSIST_FIELDS}
    for src in (amap, ipinfo):  # AMap wins for overlapping fields (Chinese, more precise)
        if src:
            for k, v in src.items():
                if v and not merged[k]:
                    merged[k] = v
    return merged


async def _persist(ip: str, fields: dict, source: str) -> None:
    try:
        async with async_session_maker() as session:
            existing = (
                await session.execute(select(IpLocation).where(IpLocation.ip == ip))
            ).scalar_one_or_none()
            if existing is None:
                session.add(IpLocation(ip=ip, source=source, **fields))
            else:
                for k, v in fields.items():
                    if v:
                        setattr(existing, k, v)
                existing.source = source
            await session.commit()
        logger.info("[IP LOCATION] Saved %s (%s) -> %s %s %s", ip, source, fields.get("province"), fields.get("city"), fields.get("isp"))
    except Exception as exc:
        logger.warning("[IP LOCATION] Failed to persist %s: %s", ip, exc)


async def _query_providers(ip: str) -> dict:
    (amap_fields, amap_err), (ipinfo_fields, ipinfo_err) = await asyncio.gather(
        _fetch_from_amap(ip), _fetch_from_ipinfo(ip)
    )

    merged = _merge_fields(amap_fields, ipinfo_fields)
    # Meaningful only if we got real geo/ISP data (not an empty shell).
    if merged.get("province") or merged.get("isp") or merged.get("country"):
        sources = "+".join(
            name for name, fields in (("amap", amap_fields), ("ipinfo", ipinfo_fields)) if fields
        ) or "amap"
        await _persist(ip, merged, sources)
        return {"ip": ip, "cached": False, "ok": True, **merged, "message": ""}

    # Nothing usable: build a helpful message from provider errors.
    messages = [e["message"] for e in (amap_err, ipinfo_err) if e]
    retryable = any(e.get("retryable") for e in (amap_err, ipinfo_err) if e)
    if messages:
        return {
            "ip": ip,
            "cached": False,
            "ok": False,
            "reason": "provider_error",
            "retryable": retryable,
            "message": "；".join(messages),
        }
    return {
        "ip": ip,
        "cached": False,
        "ok": False,
        "reason": "unresolved",
        "message": "两个数据源均无法解析该 IP",
    }


async def lookup_ip_location(ip: str) -> dict:
    ip = (ip or "").strip()

    local_label = _classify_local_ip(ip)
    if local_label is not None:
        messages = {
            "lan": "内网 / 局域网 IP，无需地理定位",
            "ipv6": "IPv6 地址，高德 IP 定位仅支持 IPv4",
            "unknown": "无效或未记录的 IP 地址",
        }
        return {"ip": ip or "-", "cached": False, "ok": False, "reason": local_label, "message": messages[local_label]}

    # In-memory negative cache: don't hammer providers after a failure.
    cached_failure = _failure_cache.get(ip)
    if cached_failure and time.monotonic() - cached_failure[0] < FAILURE_CACHE_TTL_SECONDS:
        result = dict(cached_failure[1])
        result["cached"] = True
        return result

    async with async_session_maker() as session:
        row = (
            await session.execute(select(IpLocation).where(IpLocation.ip == ip))
        ).scalar_one_or_none()
        if row is not None:
            return _cache_hit_fields(row)

    # Serialize concurrent lookups for the same IP.
    lock = _lookup_locks.setdefault(ip, asyncio.Lock())
    async with lock:
        # Re-check DB in case a parallel lookup just filled it.
        async with async_session_maker() as session:
            row = (
                await session.execute(select(IpLocation).where(IpLocation.ip == ip))
            ).scalar_one_or_none()
            if row is not None:
                return _cache_hit_fields(row)

        result = await _query_providers(ip)
        if not result.get("ok") and not result.get("retryable"):
            _failure_cache[ip] = (time.monotonic(), dict(result))
        elif _failure_cache.get(ip):
            _failure_cache.pop(ip, None)
        return result
