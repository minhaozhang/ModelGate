import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select

from core.database import (
    AnalysisArtifact,
    AnalysisRecord,
    AnalysisSubtask,
    async_session_maker,
)

ANALYSIS_STATUS_PENDING = "pending"
ANALYSIS_STATUS_RUNNING = "running"
ANALYSIS_STATUS_SUCCESS = "success"
ANALYSIS_STATUS_FAILED = "failed"
ANALYSIS_STATUS_RETRYING = "retrying"

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


async def get_analysis_record_by_id(record_id: int) -> Optional[AnalysisRecord]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisRecord).where(AnalysisRecord.id == record_id)
        )
        return result.scalar_one_or_none()


async def upsert_analysis_record(
    analysis_type: str,
    scope_key: str,
    *,
    status: str,
    language: Optional[str] = None,
    model_used: Optional[str] = None,
    template_id: Optional[str] = None,
    template_version: Optional[str] = None,
    params_json: Optional[dict[str, Any]] = None,
    content: Optional[str] = None,
    error: Optional[str] = None,
    progress: Optional[str] = None,
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
        if model_used is not None:
            record.model_used = model_used
        if template_id is not None:
            record.template_id = template_id
        if template_version is not None:
            record.template_version = template_version
        if params_json is not None:
            record.params_json = params_json
        if content is not None:
            record.content = content
        if error is not None:
            record.error = error
        if progress is not None:
            record.progress = progress
        record.expires_at = expires_at
        record.updated_at = datetime.now()
        await session.commit()
        await session.refresh(record)
        return record


async def replace_analysis_subtasks(
    analysis_record_id: int, steps: list[dict[str, Any]]
) -> list[AnalysisSubtask]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisSubtask).where(
                AnalysisSubtask.analysis_record_id == analysis_record_id
            )
        )
        existing = {row.step_key: row for row in result.scalars().all()}
        records: list[AnalysisSubtask] = []
        for index, step in enumerate(steps):
            step_key = step["key"]
            record = existing.get(step_key)
            if record is None:
                record = AnalysisSubtask(
                    analysis_record_id=analysis_record_id,
                    step_key=step_key,
                )
                session.add(record)
            record.step_label = step["label"]
            record.sort_order = index
            record.max_attempts = int(step.get("max_attempts", 1) or 1)
            if not record.status:
                record.status = ANALYSIS_STATUS_PENDING
            records.append(record)
        await session.commit()
        for record in records:
            await session.refresh(record)
        return records


async def set_analysis_subtask_status(
    analysis_record_id: int,
    step_key: str,
    *,
    status: str,
    error: Optional[str] = None,
    output: Optional[dict[str, Any]] = None,
    increment_attempt: bool = False,
) -> Optional[AnalysisSubtask]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisSubtask).where(
                AnalysisSubtask.analysis_record_id == analysis_record_id,
                AnalysisSubtask.step_key == step_key,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None

        record.status = status
        if increment_attempt:
            record.attempt_count = int(record.attempt_count or 0) + 1
        if output is not None:
            record.output = output
        if error is not None:
            record.error = error
        if status in {ANALYSIS_STATUS_RUNNING, ANALYSIS_STATUS_RETRYING}:
            record.started_at = record.started_at or datetime.now()
            record.finished_at = None
        elif status in {ANALYSIS_STATUS_SUCCESS, ANALYSIS_STATUS_FAILED}:
            record.finished_at = datetime.now()
        record.updated_at = datetime.now()
        await session.commit()
        await session.refresh(record)
        return record


async def list_analysis_subtasks(analysis_record_id: int) -> list[AnalysisSubtask]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisSubtask)
            .where(AnalysisSubtask.analysis_record_id == analysis_record_id)
            .order_by(AnalysisSubtask.sort_order.asc(), AnalysisSubtask.id.asc())
        )
        return result.scalars().all()


async def upsert_analysis_artifact(
    analysis_record_id: int,
    artifact_key: str,
    *,
    artifact_type: str,
    title: Optional[str] = None,
    path: Optional[str] = None,
    status: str = ANALYSIS_STATUS_SUCCESS,
    meta: Optional[dict[str, Any]] = None,
    subtask_id: Optional[int] = None,
) -> AnalysisArtifact:
    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisArtifact).where(
                AnalysisArtifact.analysis_record_id == analysis_record_id,
                AnalysisArtifact.artifact_key == artifact_key,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            record = AnalysisArtifact(
                analysis_record_id=analysis_record_id,
                artifact_key=artifact_key,
            )
            session.add(record)

        record.subtask_id = subtask_id
        record.artifact_type = artifact_type
        record.title = title
        record.path = path
        record.status = status
        if meta is not None:
            record.meta = meta
        record.updated_at = datetime.now()
        await session.commit()
        await session.refresh(record)
        return record


async def list_analysis_artifacts(analysis_record_id: int) -> list[AnalysisArtifact]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisArtifact)
            .where(AnalysisArtifact.analysis_record_id == analysis_record_id)
            .order_by(AnalysisArtifact.id.asc())
        )
        return result.scalars().all()


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
