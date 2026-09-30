import logging
import os
import re
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select

from app.core.database import (
    ApiKey,
    ApiKeyDailyStat,
    AuditLog,
    DailyReport,
    ModelDailyStat,
    RequestLogRead,
    TagDailyStat,
    async_session_maker,
)

logger = logging.getLogger("modelgate.daily_report")

ERROR_STATUS = "error"
TIMEOUT_STATUS = "timeout"
RATE_LIMITED_STATUSES = {"rate_limited", "local_rate_limited"}
AUTH_FAILED_STATUS = "auth_failed"

# Max IPs whose geo location is actively looked up (amap/ipinfo) per report run.
REPORT_IP_LOOKUP_LIMIT = 15


def _lookup_candidates(
    ip_cities: dict[str, str],
    warning_ips: list[str],
    auth_fail_top: list[str],
    login_fail_top: list[str],
    traffic_ips: list[str],
    limit: int = REPORT_IP_LOOKUP_LIMIT,
) -> list[str]:
    """Problem IPs lacking a known location, worst first, capped per run."""
    candidates: list[str] = []
    for ip in warning_ips + auth_fail_top + login_fail_top + traffic_ips:
        if not ip or ip == "unknown" or ip in ip_cities or ip in candidates:
            continue
        candidates.append(ip)
    return candidates[:limit]


def _city_label_from_lookup(result: dict) -> str:
    parts = []
    country = result.get("country") or ""
    if country and country not in ("中国", "China", "CHN"):
        parts.append(country)
    province = result.get("province") or ""
    if province:
        parts.append(province)
    city = result.get("city") or ""
    if city and city != province:
        parts.append(city)
    return " ".join(parts)


async def _resolve_missing_cities(candidates: list[str], ip_cities: dict[str, str]) -> None:
    """Actively look up locations via the platform service (caches into ip_locations)."""
    import asyncio as _asyncio

    from app.services.ip_location import lookup_ip_location

    if not candidates:
        return
    results = await _asyncio.gather(
        *(lookup_ip_location(ip) for ip in candidates),
        return_exceptions=True,
    )
    for ip, result in zip(candidates, results):
        if isinstance(result, Exception) or not result.get("ok"):
            continue
        label = _city_label_from_lookup(result)
        if label:
            ip_cities[ip] = label

HIGH_RISK_RESOURCES = {"roles", "users", "api_keys", "providers", "provider_keys"}


def _pct(cur: float, prev: float) -> float | None:
    if prev <= 0:
        return None
    return (cur - prev) / prev * 100


def _day_bounds(date_str: str) -> tuple[datetime, datetime]:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return d, d + timedelta(days=1)


async def _thresholds() -> dict:
    from app.services.system_config import get_float_setting

    return {
        "error_rate_warn": await get_float_setting("daily_report", "error_rate_warn", 30.0),
        "auth_fail_warn": await get_float_setting("daily_report", "auth_fail_warn", 100.0),
        "login_fail_warn": await get_float_setting("daily_report", "login_fail_warn", 20.0),
        "rate_limit_warn": await get_float_setting("daily_report", "rate_limit_warn", 500.0),
        "ip_req_warn": await get_float_setting("daily_report", "ip_req_warn", 2000.0),
        "ip_auth_fail_warn": await get_float_setting("daily_report", "ip_auth_fail_warn", 30.0),
        "key_ip_warn": await get_float_setting("daily_report", "key_ip_warn", 3.0),
    }


async def _security_section(session, start_dt: datetime, end_dt: datetime, thresholds: dict) -> dict:
    login_fail_rows = await session.execute(
        select(AuditLog.client_ip, AuditLog.status_code, func.count())
        .where(
            AuditLog.created_at >= start_dt,
            AuditLog.created_at < end_dt,
            AuditLog.resource == "session",
            AuditLog.detail.like("登录失败%"),
        )
        .group_by(AuditLog.client_ip, AuditLog.status_code)
    )
    login_fail_by_ip: dict[str, int] = {}
    login_locked = 0
    for ip, status_code, cnt in login_fail_rows.fetchall():
        login_fail_by_ip[ip or "unknown"] = login_fail_by_ip.get(ip or "unknown", 0) + cnt
        if status_code == 429:
            login_locked += cnt
    login_failures = sum(login_fail_by_ip.values())

    auth_fail_rows = await session.execute(
        select(RequestLogRead.client_ip, RequestLogRead.error, func.count())
        .where(
            RequestLogRead.created_at >= start_dt,
            RequestLogRead.created_at < end_dt,
            RequestLogRead.status == AUTH_FAILED_STATUS,
        )
        .group_by(RequestLogRead.client_ip, RequestLogRead.error)
    )
    auth_fail_by_ip: dict[str, int] = {}
    auth_fail_reasons: dict[str, int] = {}
    for ip, reason, cnt in auth_fail_rows.fetchall():
        auth_fail_by_ip[ip or "unknown"] = auth_fail_by_ip.get(ip or "unknown", 0) + cnt
        auth_fail_reasons[reason or "unknown"] = auth_fail_reasons.get(reason or "unknown", 0) + cnt
    auth_failures = sum(auth_fail_by_ip.values())

    rate_limited_row = await session.execute(
        select(func.count()).select_from(RequestLogRead).where(
            RequestLogRead.created_at >= start_dt,
            RequestLogRead.created_at < end_dt,
            RequestLogRead.status.in_(RATE_LIMITED_STATUSES),
        )
    )
    rate_limited = rate_limited_row.scalar() or 0

    admin_ops_row = await session.execute(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.created_at >= start_dt,
            AuditLog.created_at < end_dt,
        )
    )
    admin_ops = admin_ops_row.scalar() or 0

    high_risk_rows = await session.execute(
        select(AuditLog.username, AuditLog.action, AuditLog.resource, AuditLog.detail)
        .where(
            AuditLog.created_at >= start_dt,
            AuditLog.created_at < end_dt,
            AuditLog.action == "delete",
        )
        .order_by(AuditLog.created_at.desc())
        .limit(10)
    )
    high_risk_ops = [
        {"user": u or "?", "action": a, "resource": r, "detail": (d or "")[:80]}
        for u, a, r, d in high_risk_rows.fetchall()
    ]

    ip_traffic_rows = await session.execute(
        select(
            RequestLogRead.client_ip,
            func.count().label("requests"),
            func.count().filter(
                RequestLogRead.status.in_((ERROR_STATUS, TIMEOUT_STATUS))
            ).label("errors"),
        )
        .where(
            RequestLogRead.created_at >= start_dt,
            RequestLogRead.created_at < end_dt,
            RequestLogRead.api_key_id.isnot(None),
            RequestLogRead.client_ip.isnot(None),
        )
        .group_by(RequestLogRead.client_ip)
    )
    ip_traffic: dict[str, dict] = {}
    for ip, reqs, errs in ip_traffic_rows.fetchall():
        ip_traffic.setdefault(ip, {"requests": 0, "errors": 0, "auth_failures": 0, "login_failures": 0})
        ip_traffic[ip]["requests"] = reqs or 0
        ip_traffic[ip]["errors"] = errs or 0
    for ip, cnt in auth_fail_by_ip.items():
        ip_traffic.setdefault(ip, {"requests": 0, "errors": 0, "auth_failures": 0, "login_failures": 0})
        ip_traffic[ip]["auth_failures"] += cnt
    for ip, cnt in login_fail_by_ip.items():
        ip_traffic.setdefault(ip, {"requests": 0, "errors": 0, "auth_failures": 0, "login_failures": 0})
        ip_traffic[ip]["login_failures"] += cnt

    ip_top = sorted(
        ip_traffic.items(),
        key=lambda kv: (kv[1]["requests"] + kv[1]["auth_failures"] + kv[1]["login_failures"]),
        reverse=True,
    )[:10]

    ip_top_ips = [ip for ip, _ in ip_top]
    ip_cities: dict[str, str] = {}
    if ip_top_ips:
        from app.core.database import IpLocation

        loc_rows = await session.execute(
            select(
                IpLocation.ip,
                IpLocation.country,
                IpLocation.province,
                IpLocation.city,
            ).where(IpLocation.ip.in_(ip_top_ips))
        )
        for ip, country, province, city in loc_rows.fetchall():
            parts = []
            if country and country not in ("中国", "China", "CHN"):
                parts.append(country)
            if province:
                parts.append(province)
            if city and city != province:
                parts.append(city)
            if parts:
                ip_cities[ip] = " ".join(parts)

    login_fail_top = sorted(login_fail_by_ip.items(), key=lambda x: -x[1])[:5]
    auth_fail_top = sorted(auth_fail_by_ip.items(), key=lambda x: -x[1])[:5]
    warning_ips = [
        ip
        for ip, stats in ip_top
        if stats["requests"] >= thresholds["ip_req_warn"]
        or stats["auth_failures"] >= thresholds["ip_auth_fail_warn"]
    ]
    candidates = _lookup_candidates(
        ip_cities,
        warning_ips,
        [ip for ip, _ in auth_fail_top],
        [ip for ip, _ in login_fail_top],
        ip_top_ips,
    )
    await _resolve_missing_cities(candidates, ip_cities)

    ip_top_data = [
        {
            "ip": ip,
            "city": ip_cities.get(ip, ""),
            **stats,
        }
        for ip, stats in ip_top
    ]

    key_ip_rows = await session.execute(
        select(
            RequestLogRead.api_key_id,
            func.count().label("requests"),
            func.count(func.distinct(RequestLogRead.client_ip)).label("ip_count"),
        )
        .where(
            RequestLogRead.created_at >= start_dt,
            RequestLogRead.created_at < end_dt,
            RequestLogRead.api_key_id.isnot(None),
            RequestLogRead.client_ip.isnot(None),
        )
        .group_by(RequestLogRead.api_key_id)
    )
    key_ip_all = sorted(
        [(k, reqs or 0, ips or 0) for k, reqs, ips in key_ip_rows.fetchall()],
        key=lambda r: (-r[2], -r[1]),
    )
    key_ip_top = []
    if key_ip_all:
        top5_ids = [r[0] for r in key_ip_all[:5]]
        name_rows = await session.execute(
            select(ApiKey.id, ApiKey.name).where(ApiKey.id.in_(top5_ids))
        )
        key_names = {i: n or f"Key#{i}" for i, n in name_rows.fetchall()}
        pair_rows = await session.execute(
            select(
                RequestLogRead.api_key_id,
                RequestLogRead.client_ip,
                func.count(),
            )
            .where(
                RequestLogRead.created_at >= start_dt,
                RequestLogRead.created_at < end_dt,
                RequestLogRead.api_key_id.in_(top5_ids),
                RequestLogRead.client_ip.isnot(None),
            )
            .group_by(RequestLogRead.api_key_id, RequestLogRead.client_ip)
        )
        top_ip_by_key: dict[int, tuple[str, int]] = {}
        for kid, ip, cnt in pair_rows.fetchall():
            cur = top_ip_by_key.get(kid)
            if cur is None or (cnt or 0) > cur[1]:
                top_ip_by_key[kid] = (ip or "unknown", cnt or 0)
        for kid, reqs, ips in key_ip_all[:5]:
            top_ip, top_ip_cnt = top_ip_by_key.get(kid, ("", 0))
            key_ip_top.append({
                "key_id": kid,
                "key_name": key_names.get(kid, f"Key#{kid}"),
                "ip_count": ips,
                "requests": reqs,
                "top_ip": top_ip,
                "top_ip_share": round(top_ip_cnt / reqs * 100, 1) if reqs else 0.0,
            })

    flags = []
    if login_failures > thresholds["login_fail_warn"]:
        flags.append(f"登录失败 {login_failures} 次超过阈值 {int(thresholds['login_fail_warn'])}")
    if auth_failures > thresholds["auth_fail_warn"]:
        flags.append(f"Key 认证失败 {auth_failures} 次超过阈值 {int(thresholds['auth_fail_warn'])}")
    if rate_limited > thresholds["rate_limit_warn"]:
        flags.append(f"限流 {rate_limited} 次超过阈值 {int(thresholds['rate_limit_warn'])}")
    for ip, stats in ip_top:
        if stats["requests"] >= thresholds["ip_req_warn"]:
            flags.append(
                f"IP {ip} 请求 {stats['requests']} 次超过阈值 {int(thresholds['ip_req_warn'])}"
                + (f"（{ip_cities.get(ip)}）" if ip_cities.get(ip) else "")
            )
        if stats["auth_failures"] >= thresholds["ip_auth_fail_warn"]:
            flags.append(
                f"IP {ip} 认证失败 {stats['auth_failures']} 次超过阈值 {int(thresholds['ip_auth_fail_warn'])}"
                + (f"（{ip_cities.get(ip)}）" if ip_cities.get(ip) else "")
            )
    for kid, reqs, ips in key_ip_all:
        if ips >= thresholds["key_ip_warn"]:
            name = f"Key#{kid}"
            for item in key_ip_top:
                if item["key_id"] == kid:
                    name = item["key_name"]
                    break
            flags.append(
                f"{name} 从 {ips} 个不同 IP 发起请求（阈值 {int(thresholds['key_ip_warn'])}，疑似共享/泄露）"
            )

    return {
        "login_failures": login_failures,
        "login_locked": login_locked,
        "login_fail_top_ips": [
            {"ip": ip, "count": cnt, "city": ip_cities.get(ip, "")}
            for ip, cnt in login_fail_top
        ],
        "auth_failures": auth_failures,
        "auth_fail_top_ips": [
            {"ip": ip, "count": cnt, "city": ip_cities.get(ip, "")}
            for ip, cnt in auth_fail_top
        ],
        "auth_fail_reasons": sorted(auth_fail_reasons.items(), key=lambda x: -x[1])[:5],
        "rate_limited": rate_limited,
        "admin_ops": admin_ops,
        "high_risk_ops": high_risk_ops,
        "ip_top": ip_top_data,
        "key_ip_top": key_ip_top,
        "flags": flags,
    }


NGINX_LOG_ROOT = "/host_root/var/lib/docker/containers"
NGINX_TAIL_BYTES = 24 * 1024 * 1024

_NGINX_LINE_RE = None


def _parse_nginx_window(log_path: str, start_utc, end_utc) -> list[dict]:
    import json as _json
    import re

    global _NGINX_LINE_RE
    if _NGINX_LINE_RE is None:
        _NGINX_LINE_RE = re.compile(
            r'^(\S+) \S+ \S+ \[[^\]]+\] "(\S+) (\S+)[^"]*" (\d{3}) (\d+|-)'
        )

    entries: list[dict] = []
    size = os.path.getsize(log_path)
    with open(log_path, "rb") as f:
        if size > NGINX_TAIL_BYTES:
            f.seek(size - NGINX_TAIL_BYTES)
            f.readline()
        for raw in f:
            try:
                rec = _json.loads(raw)
            except Exception:
                continue
            ts = rec.get("time", "")
            try:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            if not (start_utc <= t < end_utc):
                continue
            m = _NGINX_LINE_RE.match(rec.get("log", ""))
            if not m:
                continue
            ip, method, path, status, bytes_ = m.groups()
            entries.append({
                "ip": ip,
                "method": method,
                "path": path,
                "status": int(status),
                "bytes": int(bytes_) if bytes_.isdigit() else 0,
            })
    return entries


def _find_nginx_log() -> str | None:
    import json as _json

    if not os.path.isdir(NGINX_LOG_ROOT):
        return None
    for cid in os.listdir(NGINX_LOG_ROOT):
        cfg_path = os.path.join(NGINX_LOG_ROOT, cid, "config.v2.json")
        try:
            with open(cfg_path, "r", encoding="utf-8", errors="ignore") as f:
                cfg = _json.load(f)
            name = (cfg.get("Name") or "").lower()
            image = (cfg.get("Image") or cfg.get("Config", {}).get("Image") or "").lower()
            if "nginx" in name or "nginx" in image:
                log_path = os.path.join(NGINX_LOG_ROOT, cid, f"{cid}-json.log")
                if os.path.exists(log_path):
                    return log_path
        except Exception:
            continue
    return None


async def _nginx_section(start_dt: datetime, end_dt: datetime) -> dict | None:
    import asyncio
    from collections import Counter
    from datetime import timezone

    try:
        log_path = await asyncio.to_thread(_find_nginx_log)
        if not log_path:
            return None
        off = datetime.now().astimezone().utcoffset() or timedelta()
        start_utc = (start_dt - off).replace(tzinfo=timezone.utc)
        end_utc = (end_dt - off).replace(tzinfo=timezone.utc)
        entries = await asyncio.to_thread(_parse_nginx_window, log_path, start_utc, end_utc)
    except Exception as e:
        logger.warning("[DAILY_REPORT] nginx log analysis failed: %s", e)
        return None

    if not entries:
        return {"total": 0}

    status_counter = Counter(e["status"] for e in entries)
    static_hits = sum(1 for e in entries if e["path"].startswith(("/modelgate/static/", "/static/")))
    total_bytes = sum(e["bytes"] for e in entries)

    scan_counter: Counter = Counter()
    scan_ip = {}
    for e in entries:
        if e["status"] >= 400 and not e["path"].startswith(("/modelgate/", "/static/")):
            scan_counter[f"{e['method']} {e['path']}"] += 1
            scan_ip.setdefault(f"{e['method']} {e['path']}", e["ip"])
    top_ips = Counter(e["ip"] for e in entries).most_common(5)

    return {
        "total": len(entries),
        "status_2xx": sum(c for s, c in status_counter.items() if 200 <= s < 300),
        "status_3xx": sum(c for s, c in status_counter.items() if 300 <= s < 400),
        "status_4xx": sum(c for s, c in status_counter.items() if 400 <= s < 500 and s != 499),
        "status_499": status_counter.get(499, 0),
        "status_5xx": sum(c for s, c in status_counter.items() if s >= 500),
        "static_hits": static_hits,
        "total_mb": round(total_bytes / 1024 / 1024, 1),
        "top_ips": [{"ip": ip, "requests": cnt} for ip, cnt in top_ips],
        "scan_paths": [
            {"path": p, "requests": cnt, "sample_ip": scan_ip.get(p, "")}
            for p, cnt in scan_counter.most_common(5)
        ],
    }


UPSTREAM_RATE_LIMITED_STATUS = "rate_limited"
QUOTA_WINDOW_RE = re.compile(
    r"(?:已?达?到?\s*5\s*小时.{0,12}(?:上限|限额|额度)"
    r"|5\s*小时\s*使用上限"
    r"|5-hour(?:ly)?\s+(?:usage\s+)?(?:limit|cap)"
    r"|five.hour.{0,10}limit"
    r"|usage\s+limit\s+(?:reached|exceeded))",
    re.IGNORECASE,
)
RESET_TIME_RE = re.compile(r"(\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2}:\d{2})")


async def _provider_name_map(session, ids: set) -> dict:
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    from app.core.database import Provider

    rows = await session.execute(
        select(Provider.id, Provider.name).where(Provider.id.in_(ids))
    )
    return {i: n or f"Provider#{i}" for i, n in rows.fetchall()}


def _pm_label(name_map: dict, pid, model) -> dict:
    prov = name_map.get(pid) or ("local" if pid is None else f"Provider#{pid}")
    return {"provider": prov, "model": model or "?"}


async def _errors_section(session, start_dt: datetime, end_dt: datetime, date_str: str, thresholds: dict) -> dict:
    status_rows = await session.execute(
        select(RequestLogRead.status, func.count())
        .where(
            RequestLogRead.created_at >= start_dt,
            RequestLogRead.created_at < end_dt,
            RequestLogRead.api_key_id.isnot(None),
        )
        .group_by(RequestLogRead.status)
    )
    status_counts = {s: c for s, c in status_rows.fetchall()}
    total = sum(status_counts.values())
    errors = status_counts.get(ERROR_STATUS, 0)
    timeouts = status_counts.get(TIMEOUT_STATUS, 0)
    rate_limited = sum(status_counts.get(s, 0) for s in RATE_LIMITED_STATUSES)
    local_rate_limited = status_counts.get("local_rate_limited", 0)
    upstream_rate_limited = rate_limited - local_rate_limited
    attempts = total - rate_limited
    error_rate = (errors + timeouts) / attempts * 100 if attempts > 0 else 0.0

    upstream_rl_rows = await session.execute(
        select(
            RequestLogRead.provider_id,
            RequestLogRead.model,
            func.count(),
        )
        .where(
            RequestLogRead.created_at >= start_dt,
            RequestLogRead.created_at < end_dt,
            RequestLogRead.status == UPSTREAM_RATE_LIMITED_STATUS,
        )
        .group_by(RequestLogRead.provider_id, RequestLogRead.model)
    )
    upstream_rl_raw = upstream_rl_rows.fetchall()
    rl_names = await _provider_name_map(session, {r[0] for r in upstream_rl_raw})
    upstream_rl_top = sorted(
        (
            {**_pm_label(rl_names, p, m), "requests": c}
            for p, m, c in upstream_rl_raw
        ),
        key=lambda x: -x["requests"],
    )[:5]

    server_err_rows = await session.execute(
        select(
            RequestLogRead.provider_id,
            RequestLogRead.model,
            func.count(),
            func.count().filter(RequestLogRead.status == TIMEOUT_STATUS),
        )
        .where(
            RequestLogRead.created_at >= start_dt,
            RequestLogRead.created_at < end_dt,
            or_(
                and_(
                    RequestLogRead.status == ERROR_STATUS,
                    RequestLogRead.upstream_status_code.isnot(None),
                ),
                RequestLogRead.status == TIMEOUT_STATUS,
            ),
        )
        .group_by(RequestLogRead.provider_id, RequestLogRead.model)
    )
    server_err_raw = server_err_rows.fetchall()
    se_names = await _provider_name_map(session, {r[0] for r in server_err_raw})
    server_err_all = sorted(
        (
            {**_pm_label(se_names, p, m), "errors": c, "timeouts": t}
            for p, m, c, t in server_err_raw
        ),
        key=lambda x: -(x["errors"] + x["timeouts"]),
    )
    upstream_err_row = await session.execute(
        select(func.count()).select_from(RequestLogRead).where(
            RequestLogRead.created_at >= start_dt,
            RequestLogRead.created_at < end_dt,
            RequestLogRead.status == ERROR_STATUS,
            RequestLogRead.upstream_status_code.isnot(None),
        )
    )
    upstream_errors = upstream_err_row.scalar() or 0
    server_errors = upstream_errors + timeouts
    client_errors = errors - upstream_errors
    server_err_top = server_err_all[:5]

    quota_events: list[dict] = []
    quota_rows = await session.execute(
        select(
            RequestLogRead.provider_id,
            RequestLogRead.model,
            RequestLogRead.error,
            RequestLogRead.created_at,
        )
        .where(
            RequestLogRead.created_at >= start_dt,
            RequestLogRead.created_at < end_dt,
            RequestLogRead.status.in_((ERROR_STATUS, UPSTREAM_RATE_LIMITED_STATUS, TIMEOUT_STATUS)),
            or_(
                RequestLogRead.error.like("%小时%"),
                RequestLogRead.error.like("%上限%"),
                RequestLogRead.error.ilike("%usage limit%"),
                RequestLogRead.error.ilike("%5-hour%"),
            ),
        )
    )
    quota_raw = quota_rows.fetchall()
    q_names = await _provider_name_map(session, {r[0] for r in quota_raw})
    for p, m, err_text, ts in quota_raw:
        text = err_text or ""
        m2 = QUOTA_WINDOW_RE.search(text)
        if not m2:
            continue
        reset_m = RESET_TIME_RE.search(text)
        quota_events.append({
            "provider": q_names.get(p) or ("local" if p is None else f"Provider#{p}"),
            "model": m or "?",
            "created_at": ts,
            "reset_at": reset_m.group(1) if reset_m else "",
        })
    quota_5h = None
    if quota_events:
        reset_candidates = sorted(
            {e["reset_at"] for e in quota_events if e["reset_at"]},
            reverse=True,
        )
        off_peak_events = [
            e for e in quota_events if e["created_at"].hour >= 20 or e["created_at"].hour < 11
        ]
        prov_counts: dict[str, int] = {}
        for e in quota_events:
            k = f"{e['provider']}/{e['model']}"
            prov_counts[k] = prov_counts.get(k, 0) + 1
        quota_5h = {
            "count": len(quota_events),
            "first_at": min(e["created_at"] for e in quota_events).isoformat(),
            "last_at": max(e["created_at"] for e in quota_events).isoformat(),
            "reset_at": reset_candidates[0] if reset_candidates else "",
            "off_peak": bool(off_peak_events),
            "top": sorted(prov_counts.items(), key=lambda x: -x[1])[:3],
        }

    model_rows = await session.execute(
        select(
            ModelDailyStat.model_name,
            ModelDailyStat.provider_name,
            ModelDailyStat.requests,
            ModelDailyStat.errors,
            ModelDailyStat.timeouts,
            ModelDailyStat.rate_limited,
        )
        .where(ModelDailyStat.date == date_str)
    )
    model_buckets = [
        {
            "model": m or "?",
            "provider": p or "?",
            "requests": req,
            "errors": e,
            "timeouts": t,
            "rate_limited": rl,
        }
        for m, p, req, e, t, rl in model_rows.fetchall()
    ]
    top_error_models = sorted(
        model_buckets, key=lambda b: -(b["errors"] + b["timeouts"])
    )[:10]

    provider_agg: dict[str, dict] = {}
    for b in model_buckets:
        prov = b["provider"]
        agg = provider_agg.setdefault(
            prov, {"requests": 0, "errors": 0, "timeouts": 0, "rate_limited": 0}
        )
        agg["requests"] += b["requests"]
        agg["errors"] += b["errors"]
        agg["timeouts"] += b["timeouts"]
        agg["rate_limited"] += b["rate_limited"]
    worst_providers = []
    for prov, agg in provider_agg.items():
        att = agg["requests"] + agg["errors"] + agg["timeouts"]
        rate = (agg["errors"] + agg["timeouts"]) / att * 100 if att > 0 else 0.0
        worst_providers.append({"provider": prov, "error_rate": round(rate, 2), **agg})
    worst_providers = sorted(worst_providers, key=lambda x: -x["error_rate"])[:5]

    upstream_rows = await session.execute(
        select(RequestLogRead.upstream_status_code, func.count())
        .where(
            RequestLogRead.created_at >= start_dt,
            RequestLogRead.created_at < end_dt,
            RequestLogRead.status.in_((ERROR_STATUS, TIMEOUT_STATUS)),
            RequestLogRead.upstream_status_code.isnot(None),
        )
        .group_by(RequestLogRead.upstream_status_code)
    )
    top_upstream = sorted(
        ((str(c), n) for c, n in upstream_rows.fetchall()), key=lambda x: -x[1]
    )[:5]

    flags = []
    if attempts > 0 and error_rate > thresholds["error_rate_warn"]:
        flags.append(f"错误率 {error_rate:.1f}% 超过阈值 {thresholds['error_rate_warn']:.0f}%")
    if upstream_rate_limited > 0:
        top_rl = upstream_rl_top[0] if upstream_rl_top else None
        flags.append(
            f"上游限流 {upstream_rate_limited} 次（服务端限流，异常）"
            + (f"，主要 {top_rl['provider']}/{top_rl['model']} {top_rl['requests']} 次" if top_rl else "")
        )
    if server_errors > 0:
        top_se = server_err_top[0] if server_err_top else None
        flags.append(
            f"服务端错误 {server_errors} 次（含超时，异常）"
            + (f"，主要 {top_se['provider']}/{top_se['model']}" if top_se else "")
        )
    if quota_5h:
        flags.append(
            f"上游 5 小时额度用完 {quota_5h['count']} 次（重置 {quota_5h['reset_at'] or '未知'}）"
            + ("，且发生在非高峰期 20:00-11:00，异常" if quota_5h["off_peak"] else "")
        )

    return {
        "total": total,
        "errors": errors,
        "timeouts": timeouts,
        "rate_limited": rate_limited,
        "local_rate_limited": local_rate_limited,
        "upstream_rate_limited": upstream_rate_limited,
        "upstream_rate_limited_top": upstream_rl_top,
        "server_errors": server_errors,
        "client_errors": client_errors,
        "server_errors_top": server_err_top,
        "quota_5h": quota_5h,
        "error_rate": round(error_rate, 2),
        "top_error_models": top_error_models,
        "worst_providers": worst_providers,
        "top_upstream_status": top_upstream,
        "flags": flags,
    }


async def _usage_section(session, date_str: str) -> dict:
    key_rows = await session.execute(
        select(
            ApiKeyDailyStat.api_key_id,
            func.sum(ApiKeyDailyStat.requests),
            func.sum(ApiKeyDailyStat.tokens),
            func.sum(ApiKeyDailyStat.cost_cny),
        )
        .where(ApiKeyDailyStat.date == date_str)
        .group_by(ApiKeyDailyStat.api_key_id)
    )
    key_buckets = list(key_rows.fetchall())
    requests = sum(r or 0 for _, r, _, _ in key_buckets)
    tokens = sum(t or 0 for _, _, t, _ in key_buckets)
    cost = sum(c or 0 for _, _, _, c in key_buckets)

    prev_date = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    prev_rows = await session.execute(
        select(
            func.sum(ApiKeyDailyStat.requests),
            func.sum(ApiKeyDailyStat.tokens),
            func.sum(ApiKeyDailyStat.cost_cny),
        )
        .where(ApiKeyDailyStat.date == prev_date)
    )
    prev_requests, prev_tokens, prev_cost = prev_rows.fetchone()

    key_ids = [k for k, _, _, _ in key_buckets if k]
    names_map: dict[int, str] = {}
    if key_ids:
        name_rows = await session.execute(
            select(ApiKey.id, ApiKey.name).where(ApiKey.id.in_(key_ids))
        )
        names_map = {i: n for i, n in name_rows.fetchall()}
    top_keys = sorted(
        (
            {
                "key": names_map.get(k, str(k)),
                "requests": r or 0,
                "tokens": t or 0,
                "cost": round(c or 0, 4),
            }
            for k, r, t, c in key_buckets
        ),
        key=lambda x: -x["cost"],
    )[:5]

    tag_rows = await session.execute(
        select(
            TagDailyStat.tag,
            func.sum(TagDailyStat.requests),
            func.sum(TagDailyStat.tokens),
            func.sum(TagDailyStat.cost_cny),
        )
        .where(TagDailyStat.date == date_str)
        .group_by(TagDailyStat.tag)
    )
    top_tags = sorted(
        (
            {"tag": tag or "", "requests": r or 0, "tokens": t or 0, "cost": round(c or 0, 4)}
            for tag, r, t, c in tag_rows.fetchall()
        ),
        key=lambda x: -x["cost"],
    )[:5]
    untagged_cost = next((t["cost"] for t in top_tags if t["tag"] == ""), 0.0)

    return {
        "requests": requests,
        "tokens": tokens,
        "cost": round(cost, 4),
        "prev_requests": prev_requests or 0,
        "prev_tokens": prev_tokens or 0,
        "prev_cost": round(prev_cost or 0, 4),
        "requests_delta_pct": _pct(requests, prev_requests or 0),
        "tokens_delta_pct": _pct(tokens, prev_tokens or 0),
        "cost_delta_pct": _pct(cost, prev_cost or 0),
        "top_keys": top_keys,
        "top_tags": top_tags,
        "untagged_cost": untagged_cost,
    }


def _build_summary(level: str, security: dict, errors: dict, usage: dict) -> str:
    parts = [
        f"请求 {usage['requests']:,}（环比 {_fmt_delta(usage['requests_delta_pct'])}）",
        f"Token {usage['tokens']:,}",
        f"花费 ¥{usage['cost']:.4f}",
        f"错误率 {errors['error_rate']:.1f}%",
    ]
    if errors.get("upstream_rate_limited"):
        parts.append(f"上游限流 {errors['upstream_rate_limited']}")
    if errors.get("server_errors"):
        parts.append(f"服务端错误 {errors['server_errors']}")
    if errors.get("quota_5h"):
        parts.append(
            "5小时额度用完" + ("（非高峰期，异常）" if errors["quota_5h"].get("off_peak") else "")
        )
    parts.extend([
        f"认证失败 {security['auth_failures']}",
        f"登录失败 {security['login_failures']}",
    ])
    prefix = "【简报·警告】" if level == "warning" else "【简报】"
    return prefix + "；".join(parts)


def _fmt_delta(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.1f}%"


async def _ai_analyze(date_str: str, sections: dict, model: str) -> dict:
    import json as _json

    from app.services.proxy import call_internal_model_via_proxy

    payload = {
        "date": date_str,
        "security": {
            k: sections["security"][k]
            for k in (
                "login_failures",
                "login_locked",
                "login_fail_top_ips",
                "auth_failures",
                "auth_fail_top_ips",
                "auth_fail_reasons",
                "rate_limited",
                "admin_ops",
                "ip_top",
                "key_ip_top",
                "nginx",
                "flags",
            )
            if k in sections.get("security", {})
        },
        "errors": {
            k: sections["errors"][k]
            for k in ("total", "errors", "timeouts", "rate_limited",
                      "local_rate_limited", "upstream_rate_limited",
                      "upstream_rate_limited_top", "server_errors",
                      "server_errors_top", "client_errors", "quota_5h", "error_rate",
                      "top_error_models", "worst_providers", "top_upstream_status", "flags")
            if k in sections.get("errors", {})
        },
        "usage": {
            k: sections["usage"][k]
            for k in ("requests", "tokens", "cost", "requests_delta_pct",
                      "tokens_delta_pct", "cost_delta_pct", "top_keys", "top_tags")
            if k in sections.get("usage", {})
        },
    }

    body_json = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 ModelGate API 网关的运维分析师，根据每日运营数据写分析。"
                    "要求：中文；500字以内；先用两三句话总体评估（引用总量数字），"
                    "再逐项指出异常或值得关注的点（引用具体数字、IP、Key），"
                    "最后给2-3条可执行建议；用短句，不要标题，"
                    "不要输出JSON，不要客套。"
                ),
            },
            {
                "role": "user",
                "content": f"以下是 {date_str} 的运营数据JSON：\n"
                + _json.dumps(payload, ensure_ascii=False),
            },
        ],
        "max_tokens": 1200,
        "temperature": 0.3,
        "stream": False,
    }

    try:
        result = await call_internal_model_via_proxy(
            requested_model=model,
            body_json=body_json,
            purpose="daily-report-analysis",
            timeout_seconds=90.0,
        )
        if not result.get("ok"):
            reason = str(result.get("error") or "")[:300]
            logger.warning("[DAILY REPORT] AI analysis failed: %s", reason)
            return {"model": model, "error": reason}
        reply = ""
        try:
            message = result["payload"]["choices"][0]["message"] or {}
            reply = message.get("content") or message.get("reasoning_content") or ""
        except (KeyError, IndexError, TypeError):
            reply = ""
        if not reply:
            return {"model": model, "error": "AI 响应为空"}
        return {"model": model, "text": reply.strip()}
    except Exception as exc:
        logger.warning("[DAILY REPORT] AI analysis error: %s", exc)
        return {"model": model, "error": str(exc)[:300]}


async def generate_daily_report(
    date_str: str, notify: bool = True, ai_model: str | None = None
) -> dict:
    start_dt, end_dt = _day_bounds(date_str)
    thresholds = await _thresholds()

    async with async_session_maker() as session:
        security = await _security_section(session, start_dt, end_dt, thresholds)
        errors = await _errors_section(session, start_dt, end_dt, date_str, thresholds)
        usage = await _usage_section(session, date_str)

    security["nginx"] = await _nginx_section(start_dt, end_dt)

    all_flags = security["flags"] + errors["flags"]
    level = "warning" if all_flags else "info"
    summary = _build_summary(level, security, errors, usage)

    sections = {"security": security, "errors": errors, "usage": usage}

    try:
        if ai_model:
            sections["ai"] = await _ai_analyze(date_str, sections, ai_model)
    except Exception as exc:
        logger.warning("[DAILY REPORT] AI analysis crashed: %s", exc)
        sections["ai"] = {"error": str(exc)[:300]}

    async with async_session_maker() as session:
        await session.execute(delete(DailyReport).where(DailyReport.date == date_str))
        report = DailyReport(
            date=date_str,
            level=level,
            summary=summary,
            sections=sections,
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)

    if notify:
        try:
            from app.services.notification import create_notification

            body_lines = [summary, ""]
            if all_flags:
                body_lines.append("告警事项:")
                body_lines.extend(f"- {f}" for f in all_flags)
                body_lines.append("")
            body_lines.append(f"错误分布: error {errors['errors']} / timeout {errors['timeouts']} / 限流 {errors['rate_limited']}")
            if errors["top_error_models"]:
                m = errors["top_error_models"][0]
                body_lines.append(
                    f"错误最多: {m['provider']}/{m['model']} ({m['errors'] + m['timeouts']} 次)"
                )
            body_lines.append(
                f"用量: Top Key {usage['top_keys'][0]['key']} ¥{usage['top_keys'][0]['cost']:.4f}"
                if usage["top_keys"]
                else "用量: 无请求"
            )
            ai = sections.get("ai") or {}
            if ai.get("text"):
                body_lines.append("")
                body_lines.append(f"AI 分析（{ai.get('model', '?')}）:")
                body_lines.append(ai["text"][:400])
            await create_notification(
                "system",
                level,
                f"每日简报 {date_str}",
                "\n".join(body_lines),
            )
        except Exception:
            logger.exception("[DAILY REPORT] notification failed")

    logger.info("[DAILY REPORT] %s level=%s flags=%s", date_str, level, all_flags)
    return {"date": date_str, "level": level, "summary": summary, "sections": sections}
