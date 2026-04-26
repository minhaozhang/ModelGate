from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, and_, or_

from core.config import logger
from core.database import Notification, async_session_maker


def _notification_visible_to_user(notification: Notification, api_key_id: int) -> bool:
    return notification.target_api_key_id in (None, api_key_id)


def _user_visible_notification_clause(api_key_id: int):
    return or_(
        Notification.target_api_key_id == None,
        Notification.target_api_key_id == api_key_id,
    )


async def create_notification(
    type: str,
    level: str,
    title: str,
    body: str | None = None,
    target_api_key_id: int | None = None,
) -> int:
    async with async_session_maker() as session:
        n = Notification(
            type=type,
            level=level,
            title=title,
            body=body,
            target_api_key_id=target_api_key_id,
        )
        session.add(n)
        await session.commit()
        await session.refresh(n)
        logger.info(
            "[NOTIFICATION] Created: type=%s level=%s title=%s target=%s",
            type, level, title[:50], target_api_key_id,
        )
        return n.id


async def create_notifications_batch(
    items: list[dict],
) -> int:
    if not items:
        return 0
    async with async_session_maker() as session:
        objs = []
        for item in items:
            objs.append(Notification(
                type=item.get("type", "user"),
                level=item.get("level", "info"),
                title=item["title"],
                body=item.get("body"),
                target_api_key_id=item.get("target_api_key_id"),
            ))
        session.add_all(objs)
        await session.commit()
        logger.info("[NOTIFICATION] Batch created %d notifications", len(objs))
        return len(objs)


def notify_model_changes_async(
    api_key_id: int,
    api_key_name: str,
    added_models: list[str],
    removed_models: list[str],
) -> None:
    if not added_models and not removed_models:
        return
    title_parts = []
    if added_models:
        title_parts.append(f"新增: {', '.join(added_models)}")
    if removed_models:
        title_parts.append(f"移除: {', '.join(removed_models)}")
    title = f"模型权限变更：{'；'.join(title_parts)}"

    async def _do():
        await create_notifications_batch([{
            "type": "user",
            "level": "info",
            "title": title,
            "target_api_key_id": api_key_id,
        }])

    asyncio.create_task(_do())


async def get_admin_notifications(
    page: int = 1,
    page_size: int = 20,
    unread_only: bool = False,
) -> dict:
    async with async_session_maker() as session:
        base_where = Notification.type == "system"
        if unread_only:
            base_where = and_(base_where, Notification.is_read_by_admin == False)

        count_result = await session.execute(
            select(func.count(Notification.id)).where(base_where)
        )
        total = count_result.scalar() or 0

        result = await session.execute(
            select(Notification)
            .where(base_where)
            .order_by(Notification.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = result.scalars().all()

        return {
            "items": [
                {
                    "id": n.id,
                    "type": n.type,
                    "level": n.level,
                    "title": n.title,
                    "body": n.body,
                    "is_read": n.is_read_by_admin,
                    "created_at": n.created_at.isoformat() if n.created_at else None,
                }
                for n in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


async def get_admin_unread_count() -> int:
    async with async_session_maker() as session:
        result = await session.execute(
            select(func.count(Notification.id)).where(
                and_(
                    Notification.type == "system",
                    Notification.is_read_by_admin == False,
                )
            )
        )
        return result.scalar() or 0


async def mark_admin_read(notification_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Notification).where(
                and_(Notification.id == notification_id, Notification.type == "system")
            )
        )
        n = result.scalar_one_or_none()
        if n:
            n.is_read_by_admin = True
            await session.commit()
            return True
    return False


async def mark_all_admin_read() -> int:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Notification).where(
                and_(
                    Notification.type == "system",
                    Notification.is_read_by_admin == False,
                )
            )
        )
        items = result.scalars().all()
        for n in items:
            n.is_read_by_admin = True
        await session.commit()
        return len(items)


async def get_user_notifications(
    api_key_id: int,
    page: int = 1,
    page_size: int = 20,
    unread_only: bool = False,
) -> dict:
    async with async_session_maker() as session:
        base_where = _user_visible_notification_clause(api_key_id)
        if unread_only:
            base_where = and_(
                base_where,
                ~Notification.read_api_key_ids.contains([api_key_id]),
            )

        count_result = await session.execute(
            select(func.count(Notification.id)).where(base_where)
        )
        total = count_result.scalar() or 0

        result = await session.execute(
            select(Notification)
            .where(base_where)
            .order_by(Notification.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = result.scalars().all()

        return {
            "items": [
                {
                    "id": n.id,
                    "type": n.type,
                    "level": n.level,
                    "title": n.title,
                    "body": n.body,
                    "is_read": api_key_id in (n.read_api_key_ids or []),
                    "created_at": n.created_at.isoformat() if n.created_at else None,
                }
                for n in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


async def get_user_unread_count(api_key_id: int) -> int:
    async with async_session_maker() as session:
        result = await session.execute(
            select(func.count(Notification.id)).where(
                and_(
                    Notification.target_api_key_id == api_key_id,
                    ~Notification.read_api_key_ids.contains([api_key_id]),
                )
            )
        )
        return result.scalar() or 0


async def mark_user_read(notification_id: int, api_key_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Notification).where(
                and_(
                    Notification.id == notification_id,
                    _user_visible_notification_clause(api_key_id),
                )
            )
        )
        n = result.scalar_one_or_none()
        if n:
            read_ids = list(n.read_api_key_ids or [])
            if api_key_id not in read_ids:
                read_ids.append(api_key_id)
                n.read_api_key_ids = read_ids
                await session.commit()
            return True
    return False


async def mark_all_user_read(api_key_id: int) -> int:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Notification).where(
                and_(
                    _user_visible_notification_clause(api_key_id),
                    ~Notification.read_api_key_ids.contains([api_key_id]),
                )
            )
        )
        items = result.scalars().all()
        count = 0
        for n in items:
            read_ids = list(n.read_api_key_ids or [])
            if api_key_id not in read_ids:
                read_ids.append(api_key_id)
                n.read_api_key_ids = read_ids
                count += 1
        await session.commit()
        return count
