from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from core.app_paths import build_app_url
from core.config import validate_session
from core.database import AnalysisArtifact, AnalysisRecord, async_session_maker
from services.usage_report import (
    get_usage_report_template,
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


def _attach_app_urls(request: Request, payload):
    if isinstance(payload, dict):
        normalized = {}
        for key, value in payload.items():
            if key == "download_url" and isinstance(value, str) and value.startswith("/"):
                normalized[key] = build_app_url(request, value)
            else:
                normalized[key] = _attach_app_urls(request, value)
        return normalized
    if isinstance(payload, list):
        return [_attach_app_urls(request, item) for item in payload]
    return payload


@router.post("/reports/usage")
async def create_usage_report(
    request: Request,
    data: UsageReportRequest,
    _: bool = Depends(require_admin),
):
    started, task = await start_usage_report(
        data.start_date,
        data.end_date,
        exclude_api_key_ids=data.exclude_api_key_ids or None,
    )
    if not started:
        return JSONResponse(
            {
                "error": "A usage report for this parameter set is already running",
                "task": _attach_app_urls(request, task),
            },
            status_code=409,
        )
    task = _attach_app_urls(request, task)
    return {"task_id": task["id"], "status": task["status"], "task": task}


@router.get("/reports/usage/status")
async def get_report_status(
    request: Request,
    task_id: int = Query(..., ge=1),
    _: bool = Depends(require_admin),
):
    status = await get_usage_report_status(task_id)
    if not status:
        return JSONResponse({"error": "Report not found"}, status_code=404)
    return _attach_app_urls(request, status)


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
        artifact_result = await session.execute(
            select(AnalysisArtifact).where(
                AnalysisArtifact.analysis_record_id == int(task_id),
                AnalysisArtifact.artifact_key == "final_docx",
            )
        )
        final_docx_artifact = artifact_result.scalar_one_or_none()

    if not record or record.status != "success":
        return JSONResponse({"error": "Report not found"}, status_code=404)

    candidate_path = record.content or (final_docx_artifact.path if final_docx_artifact else None)
    if not candidate_path:
        return JSONResponse({"error": "Report file not found"}, status_code=404)

    file_path = Path(candidate_path)
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
    request: Request,
    limit: int = Query(10, ge=1, le=100),
    _: bool = Depends(require_admin),
):
    reports = await list_usage_reports(limit)
    return {"reports": _attach_app_urls(request, reports)}


@router.get("/reports/usage/template")
async def get_report_template(_: bool = Depends(require_admin)):
    return {"template": get_usage_report_template()}
