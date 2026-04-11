from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from core.config import validate_session
from core.database import AnalysisRecord, async_session_maker
from services.usage_report import (
    get_usage_report_status,
    list_usage_reports,
    start_usage_report,
)

router = APIRouter(prefix="/admin/api", tags=["reports"])


def require_admin(session: Optional[str] = Cookie(None)):
    if not validate_session(session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


class UsageReportRequest(BaseModel):
    start_date: str
    end_date: str
    exclude_api_key_ids: list[int] = []


@router.post("/reports/usage")
async def create_usage_report(
    data: UsageReportRequest,
    _: bool = Depends(require_admin),
):
    started = start_usage_report(
        data.start_date,
        data.end_date,
        exclude_api_key_ids=data.exclude_api_key_ids or None,
    )
    if not started:
        return JSONResponse(
            {"error": "A usage report for this date range is already running"},
            status_code=409,
        )
    status = get_usage_report_status(data.start_date, data.end_date)
    return {"task_id": status["task_id"], "status": status["status"]}


@router.get("/reports/usage/status")
async def get_report_status(
    start_date: str = Query(...),
    end_date: str = Query(...),
    _: bool = Depends(require_admin),
):
    status = get_usage_report_status(start_date, end_date)
    if not status:
        return JSONResponse({"error": "Report not found"}, status_code=404)
    return status


@router.get("/reports/usage/{task_id}/download")
async def download_usage_report(
    task_id: str,
    _: bool = Depends(require_admin),
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisRecord).where(
                AnalysisRecord.id == int(task_id),
                AnalysisRecord.analysis_type == "usage_report",
            )
        )
        record = result.scalar_one_or_none()

    if not record or record.status != "success" or not record.content:
        return JSONResponse({"error": "Report not found"}, status_code=404)

    file_path = Path(record.content)
    if not file_path.is_absolute():
        file_path = Path.cwd() / file_path

    if not file_path.exists():
        return JSONResponse({"error": "Report file not found"}, status_code=404)

    filename = f"usage_report_{record.scope_key.replace('/', '_')}.docx"
    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


@router.get("/reports/usage/history")
async def get_report_history(
    limit: int = Query(10, ge=1, le=100),
    _: bool = Depends(require_admin),
):
    reports = list_usage_reports(limit)
    return {"reports": reports}
