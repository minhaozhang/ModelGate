from datetime import datetime
from fastapi import APIRouter
from sqlalchemy import select, func

from database import async_session_maker, RequestLog

router = APIRouter(tags=["logs"])


@router.get("/logs/today")
async def get_today_logs():
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog)
            .where(RequestLog.created_at >= today)
            .order_by(RequestLog.created_at.desc())
            .limit(50)
        )
        logs = result.scalars().all()
        return {
            "logs": [
                {
                    "id": log.id,
                    "model": log.model,
                    "status": log.status,
                    "latency_ms": log.latency_ms,
                    "tokens": log.tokens,
                    "created_at": log.created_at.isoformat(),
                }
                for log in logs
            ]
        }


@router.get("/logs/all")
async def get_all_logs(limit: int = 100):
    async with async_session_maker() as session:
        count_result = await session.execute(select(func.count(RequestLog.id)))
        total = count_result.scalar() or 0

        result = await session.execute(
            select(RequestLog).order_by(RequestLog.created_at.desc()).limit(limit)
        )
        logs = result.scalars().all()
        return {
            "logs": [
                {
                    "id": log.id,
                    "model": log.model,
                    "status": log.status,
                    "latency_ms": log.latency_ms,
                    "tokens": log.tokens,
                    "created_at": log.created_at.isoformat(),
                    "response": log.response,
                    "error": log.error,
                    "messages": log.messages,
                }
                for log in logs
            ],
            "total": total,
        }
