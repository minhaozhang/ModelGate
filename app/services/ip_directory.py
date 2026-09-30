"""Admin IP directory: unified list of client IPs with geo location and tags.

Data sources are merged on read:
- request_logs_all view (live + archived)  -> per-IP requests + last seen
- audit_logs                              -> per-IP admin ops + last seen
- ip_locations                            -> cached geo/ISP (written by
  app.services.ip_location.lookup_ip_location)
- ip_tags                                 -> admin-managed labels per IP
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, text

from app.core.config import logger
from app.core.database import IpLocation, IpTag, async_session_maker

# Well-known tags get a fixed color class; anything else falls back to a
# stable palette based on the tag name (Tailwind-ish color keys).
PREDEFINED_TAG_COLORS = {
    "办公室": "blue",
    "家": "green",
    "服务器": "purple",
    "攻击者": "red",
    "可疑": "red",
    "客户": "amber",
    "内网": "slate",
}
_TAG_PALETTE = ["blue", "green", "purple", "amber", "cyan", "pink", "slate"]

MAX_TAG_LENGTH = 50
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def tag_color(tag: str) -> str:
    predefined = PREDEFINED_TAG_COLORS.get(tag)
    if predefined:
        return predefined
    return _TAG_PALETTE[sum(ord(ch) for ch in tag) % len(_TAG_PALETTE)]


def _location_label(country, province, city) -> str:
    parts = []
    if country and country not in ("中国", "China", "CHN"):
        parts.append(country)
    if province:
        parts.append(province)
    if city and city != province:
        parts.append(city)
    return " ".join(parts)


_REQUEST_AGG_SQL = (
    "SELECT client_ip, COUNT(*), MAX(created_at) FROM request_logs_all "
    "WHERE client_ip IS NOT NULL AND client_ip <> '' {ip_filter} "
    "GROUP BY client_ip"
)
_AUDIT_AGG_SQL = (
    "SELECT client_ip, COUNT(*), MAX(created_at) FROM audit_logs "
    "WHERE client_ip IS NOT NULL AND client_ip <> '' {ip_filter} "
    "GROUP BY client_ip"
)


def _merge_agg(merged: dict, rows, *, is_audit: bool) -> None:
    for ip, cnt, last_seen in rows:
        entry = merged.setdefault(ip, {"requests": 0, "admin_ops": 0, "last_seen": None})
        if is_audit:
            entry["admin_ops"] += int(cnt or 0)
        else:
            entry["requests"] += int(cnt or 0)
        if last_seen and (entry["last_seen"] is None or last_seen > entry["last_seen"]):
            entry["last_seen"] = last_seen


async def list_ips(search: str = "", page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> dict:
    """Unified IP directory with geo + tags, newest activity first."""
    search = (search or "").strip()
    page = max(1, page)
    page_size = min(MAX_PAGE_SIZE, max(1, page_size))
    ip_filter = ""
    params: dict = {}
    if search:
        ip_filter = "AND client_ip LIKE :pat"
        params["pat"] = f"%{search}%"

    merged: dict[str, dict] = {}
    async with async_session_maker() as session:
        _merge_agg(
            merged,
            (await session.execute(text(_REQUEST_AGG_SQL.format(ip_filter=ip_filter)), params)).all(),
            is_audit=False,
        )
        _merge_agg(
            merged,
            (await session.execute(text(_AUDIT_AGG_SQL.format(ip_filter=ip_filter)), params)).all(),
            is_audit=True,
        )
        # Search may also match tag names: include those IPs even without log rows.
        if search:
            tag_rows = (
                await session.execute(
                    select(IpTag.ip).where(IpTag.tag.like(f"%{search}%")).distinct()
                )
            ).all()
            for (ip,) in tag_rows:
                merged.setdefault(ip, {"requests": 0, "admin_ops": 0, "last_seen": None})

        items_sorted = sorted(
            merged.items(),
            key=lambda kv: (kv[1]["last_seen"] or datetime.min, kv[1]["requests"]),
            reverse=True,
        )
        total = len(items_sorted)
        page_items = items_sorted[(page - 1) * page_size : page * page_size]
        page_ips = [ip for ip, _ in page_items]
        if not page_ips:
            return {"items": [], "total": total, "page": page, "page_size": page_size}

        loc_rows = (
            await session.execute(
                select(
                    IpLocation.ip,
                    IpLocation.country,
                    IpLocation.province,
                    IpLocation.city,
                    IpLocation.isp,
                ).where(IpLocation.ip.in_(page_ips))
            )
        ).all()
        locations = {
            ip: {"location": _location_label(country, province, city), "isp": isp or ""}
            for ip, country, province, city, isp in loc_rows
        }

        tag_rows = (
            await session.execute(
                select(IpTag.ip, IpTag.tag)
                .where(IpTag.ip.in_(page_ips))
                .order_by(IpTag.created_at.asc(), IpTag.id.asc())
            )
        ).all()
        tags: dict[str, list[str]] = {}
        for ip, tag in tag_rows:
            tags.setdefault(ip, []).append(tag)

    items = []
    for ip, stats in page_items:
        loc = locations.get(ip, {})
        items.append(
            {
                "ip": ip,
                "location": loc.get("location", ""),
                "isp": loc.get("isp", ""),
                "tags": tags.get(ip, []),
                "requests": stats["requests"],
                "admin_ops": stats["admin_ops"],
                "last_seen": stats["last_seen"].isoformat() if stats["last_seen"] else None,
            }
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def add_ip_tag(ip: str, tag: str) -> list[str]:
    """Add a tag to an IP (idempotent). Returns the IP's current tags."""
    tag = (tag or "").strip()
    ip = (ip or "").strip()
    if not ip or not tag:
        raise ValueError("IP 和标签不能为空")
    if len(tag) > MAX_TAG_LENGTH:
        raise ValueError(f"标签最长 {MAX_TAG_LENGTH} 个字符")
    async with async_session_maker() as session:
        await session.execute(
            text(
                "INSERT INTO ip_tags (ip, tag) VALUES (:ip, :tag) "
                "ON CONFLICT (ip, tag) DO NOTHING"
            ),
            {"ip": ip, "tag": tag},
        )
        await session.commit()
    logger.info("[IP DIRECTORY] Tagged %s as '%s'", ip, tag)
    return await get_ip_tags(ip)


async def remove_ip_tag(ip: str, tag: str) -> list[str]:
    async with async_session_maker() as session:
        await session.execute(
            text("DELETE FROM ip_tags WHERE ip = :ip AND tag = :tag"),
            {"ip": (ip or "").strip(), "tag": (tag or "").strip()},
        )
        await session.commit()
    return await get_ip_tags(ip)


async def get_ip_tags(ip: str) -> list[str]:
    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(IpTag.tag)
                .where(IpTag.ip == ip)
                .order_by(IpTag.created_at.asc(), IpTag.id.asc())
            )
        ).all()
    return [tag for (tag,) in rows]
