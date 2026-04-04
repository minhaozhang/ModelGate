import asyncio
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Optional

from sqlalchemy import select

from core.database import AnalysisRecord, async_session_maker

ANALYSIS_STATUS_PENDING = "pending"
ANALYSIS_STATUS_RUNNING = "running"
ANALYSIS_STATUS_SUCCESS = "success"
ANALYSIS_STATUS_FAILED = "failed"

ANALYSIS_TYPE_DAILY_ERROR_REPORT = "daily_error_report"
ANALYSIS_TYPE_USER_RECOMMENDATION = "user_recommendation"

ANALYSIS_REPORT_ROOT = Path("reports") / "analysis"

_analysis_tasks: dict[tuple[str, str], asyncio.Task] = {}


def get_report_root() -> Path:
    ANALYSIS_REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    return ANALYSIS_REPORT_ROOT


def start_analysis_task(
    analysis_type: str,
    scope_key: str,
    task_factory: Callable[[], Awaitable[None]],
) -> bool:
    key = (analysis_type, scope_key)
    existing = _analysis_tasks.get(key)
    if existing and not existing.done():
        return False

    async def runner():
        try:
            await task_factory()
        finally:
            _analysis_tasks.pop(key, None)

    _analysis_tasks[key] = asyncio.create_task(runner())
    return True


async def get_analysis_record(
    analysis_type: str, scope_key: str
) -> Optional[AnalysisRecord]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisRecord).where(
                AnalysisRecord.analysis_type == analysis_type,
                AnalysisRecord.scope_key == scope_key,
            )
        )
        return result.scalar_one_or_none()


async def upsert_analysis_record(
    analysis_type: str,
    scope_key: str,
    *,
    status: str,
    language: Optional[str] = None,
    model_used: Optional[str] = None,
    content: Optional[str] = None,
    error: Optional[str] = None,
    expires_at: Optional[datetime] = None,
) -> AnalysisRecord:
    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisRecord).where(
                AnalysisRecord.analysis_type == analysis_type,
                AnalysisRecord.scope_key == scope_key,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            record = AnalysisRecord(
                analysis_type=analysis_type,
                scope_key=scope_key,
            )
            session.add(record)

        record.status = status
        if language is not None:
            record.language = language
        record.model_used = model_used
        record.content = content
        record.error = error
        record.expires_at = expires_at
        record.updated_at = datetime.now()
        await session.commit()
        await session.refresh(record)
        return record


def read_report_markdown(path_text: Optional[str]) -> Optional[str]:
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def write_report_markdown(path: Path, markdown: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return str(path).replace("\\", "/")
