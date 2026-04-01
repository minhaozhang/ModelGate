from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Cookie, Depends, HTTPException
from sqlalchemy import select, func

from core.database import async_session_maker, RequestLog
from core.config import validate_session

router = APIRouter(prefix="/admin/api", tags=["logs"])


def require_admin(session: Optional[str] = Cookie(None)):
    if not validate_session(session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


@router.get("/logs/today")
async def get_today_logs(_: bool = Depends(require_admin)):
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog)
            .where(RequestLog.created_at >= today_start)
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
                    "client_ip": log.client_ip,
                    "user_agent": log.user_agent,
                    "created_at": log.created_at.isoformat(),
                }
                for log in logs
            ]
        }


@router.get("/logs/all")
async def get_all_logs(limit: int = 100, _: bool = Depends(require_admin)):
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
                    "client_ip": log.client_ip,
                    "user_agent": log.user_agent,
                    "created_at": log.created_at.isoformat(),
                    "response": log.response,
                    "error": log.error,
                }
                for log in logs
            ],
            "total": total,
        }
