"""报表中心路由

按标签 / 按人（API Key）统计请求数、Token 与花费。
数据来源：tag_daily_stats（标签快照，多标签 Key 在多个标签下重复计入）
与 api_key_daily_stats（按人合计，不重复）。
"""

import csv
import io
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select

from app.core.database import (
    ApiKey,
    ApiKeyDailyStat,
    TagDailyStat,
    async_session_maker,
)
from app.core.permissions import permission_required

router = APIRouter(prefix="/admin/api/report-center", tags=["报表中心"])


def _parse_date(value: str) -> Optional[str]:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _resolve_range(start: Optional[str], end: Optional[str]) -> tuple[str, str]:
    today = datetime.now().date()
    start_date = _parse_date(start) or (today - timedelta(days=29)).strftime("%Y-%m-%d")
    end_date = _parse_date(end) or today.strftime("%Y-%m-%d")
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    return start_date, end_date


async def _query_by_tag(start: str, end: str) -> list[dict]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(
                TagDailyStat.tag,
                func.count(func.distinct(TagDailyStat.api_key_id)).label("key_count"),
                func.coalesce(func.sum(TagDailyStat.requests), 0).label("requests"),
                func.coalesce(func.sum(TagDailyStat.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(TagDailyStat.completion_tokens), 0).label("completion_tokens"),
                func.coalesce(func.sum(TagDailyStat.tokens), 0).label("tokens"),
                func.coalesce(func.sum(TagDailyStat.cost_cny), 0).label("cost"),
            )
            .where(
                TagDailyStat.date >= start,
                TagDailyStat.date <= end,
            )
            .group_by(TagDailyStat.tag)
            .order_by(func.coalesce(func.sum(TagDailyStat.cost_cny), 0).desc())
        )
        rows = result.fetchall()

    return [
        {
            "tag": row.tag or "",
            "key_count": int(row.key_count or 0),
            "requests": int(row.requests or 0),
            "prompt_tokens": int(row.prompt_tokens or 0),
            "completion_tokens": int(row.completion_tokens or 0),
            "tokens": int(row.tokens or 0),
            "cost": round(float(row.cost or 0), 6),
        }
        for row in rows
    ]


async def _query_by_key(start: str, end: str) -> list[dict]:
    from app.core.database import ApiKeyTag

    tag_agg = (
        select(
            ApiKeyTag.api_key_id.label("k_id"),
            func.string_agg(ApiKeyTag.tag, "/").label("tags"),
        )
        .group_by(ApiKeyTag.api_key_id)
        .subquery()
    )
    async with async_session_maker() as session:
        result = await session.execute(
            select(
                ApiKeyDailyStat.api_key_id,
                ApiKey.name.label("key_name"),
                tag_agg.c.tags.label("key_tags"),
                func.coalesce(func.sum(ApiKeyDailyStat.requests), 0).label("requests"),
                func.coalesce(func.sum(ApiKeyDailyStat.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(ApiKeyDailyStat.completion_tokens), 0).label("completion_tokens"),
                func.coalesce(func.sum(ApiKeyDailyStat.tokens), 0).label("tokens"),
                func.coalesce(func.sum(ApiKeyDailyStat.cost_cny), 0).label("cost"),
            )
            .join(ApiKey, ApiKey.id == ApiKeyDailyStat.api_key_id, isouter=True)
            .join(tag_agg, tag_agg.c.k_id == ApiKeyDailyStat.api_key_id, isouter=True)
            .where(
                ApiKeyDailyStat.date >= start,
                ApiKeyDailyStat.date <= end,
            )
            .group_by(ApiKeyDailyStat.api_key_id, ApiKey.name, tag_agg.c.tags)
            .order_by(func.coalesce(func.sum(ApiKeyDailyStat.cost_cny), 0).desc())
        )
        rows = result.fetchall()

    return [
        {
            "key_name": row.key_name or f"(已删除 #{row.api_key_id})",
            "tags": [t for t in (row.key_tags or "").split("/") if t],
            "requests": int(row.requests or 0),
            "prompt_tokens": int(row.prompt_tokens or 0),
            "completion_tokens": int(row.completion_tokens or 0),
            "tokens": int(row.tokens or 0),
            "cost": round(float(row.cost or 0), 6),
        }
        for row in rows
    ]


@router.get("/by-tag")
async def report_by_tag(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    _: bool = Depends(permission_required("page.report_center")),
):
    start_date, end_date = _resolve_range(start, end)
    rows = await _query_by_tag(start_date, end_date)
    return {"start": start_date, "end": end_date, "rows": rows}


@router.get("/by-key")
async def report_by_key(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    _: bool = Depends(permission_required("page.report_center")),
):
    start_date, end_date = _resolve_range(start, end)
    rows = await _query_by_key(start_date, end_date)
    return {"start": start_date, "end": end_date, "rows": rows}


def _rows_to_csv(headers: list[str], rows: list[dict], keys: list[str]) -> str:
    def _cell(row: dict, key: str):
        value = row.get(key, "")
        if isinstance(value, list):
            return "/".join(value)
        return value

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_cell(row, key) for key in keys])
    return buf.getvalue()


_BY_TAG_CSV_KEYS = ["tag", "key_count", "requests", "prompt_tokens", "completion_tokens", "tokens", "cost"]
_BY_KEY_CSV_KEYS = ["tags", "key_name", "requests", "prompt_tokens", "completion_tokens", "tokens", "cost"]


@router.get("/by-tag.csv")
async def report_by_tag_csv(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    _: bool = Depends(permission_required("page.report_center")),
):
    start_date, end_date = _resolve_range(start, end)
    rows = await _query_by_tag(start_date, end_date)
    filename = f"modelgate_report_by_tag_{start_date}_{end_date}.csv"
    return Response(
        content="\ufeff" + _rows_to_csv(["标签", "人数", "请求数", "输入Token", "输出Token", "总Token", "花费(元)"], rows, _BY_TAG_CSV_KEYS),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/by-key.csv")
async def report_by_key_csv(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    _: bool = Depends(permission_required("page.report_center")),
):
    start_date, end_date = _resolve_range(start, end)
    rows = await _query_by_key(start_date, end_date)
    filename = f"modelgate_report_by_key_{start_date}_{end_date}.csv"
    return Response(
        content="\ufeff" + _rows_to_csv(["标签", "Key", "请求数", "输入Token", "输出Token", "总Token", "花费(元)"], rows, _BY_KEY_CSV_KEYS),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
