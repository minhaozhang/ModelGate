from datetime import date as date_type
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.database import DailyReport, async_session_maker
from app.core.permissions import permission_required

router = APIRouter(prefix="/admin/api/daily-reports", tags=["daily-reports"])


def _parse_date(value: str) -> date_type:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD")


@router.get("")
async def list_daily_reports(
    limit: int = 60,
    _: bool = Depends(permission_required("page.daily_reports")),
):
    limit = max(1, min(limit, 365))
    async with async_session_maker() as session:
        result = await session.execute(
            select(DailyReport)
            .order_by(DailyReport.date.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
    return {
        "items": [
            {
                "date": r.date,
                "level": r.level,
                "summary": r.summary,
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/{date_str}")
async def get_daily_report(
    date_str: str,
    _: bool = Depends(permission_required("page.daily_reports")),
):
    _parse_date(date_str)
    async with async_session_maker() as session:
        result = await session.execute(
            select(DailyReport).where(DailyReport.date == date_str)
        )
        r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="该日期暂无简报")
    return {
        "date": r.date,
        "level": r.level,
        "summary": r.summary,
        "sections": r.sections or {},
        "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else None,
    }


@router.post("/run")
async def run_daily_report(
    body: dict,
    _: bool = Depends(permission_required("scheduler.trigger")),
):
    date_str = str(body.get("date") or "").strip()
    if not date_str:
        date_str = (date_type.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    target = _parse_date(date_str)
    if target >= date_type.today():
        raise HTTPException(status_code=422, detail="只能生成今天之前的日期")
    from app.services.daily_report import generate_daily_report

    result = await generate_daily_report(date_str)
    return {"ok": True, "date": result["date"], "level": result["level"], "summary": result["summary"]}
