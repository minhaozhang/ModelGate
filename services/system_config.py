from datetime import date, datetime
from sqlalchemy import select, func

import core.config as config
from core.database import async_session_maker, RequestLog


async def init_system_config():
    async with async_session_maker() as session:
        today_start = datetime.combine(date.today(), datetime.min.time())
        result = await session.execute(
            select(RequestLog.user_agent, func.count(RequestLog.id).label("cnt"))
            .where(
                RequestLog.user_agent.isnot(None),
                RequestLog.created_at >= today_start,
            )
            .group_by(RequestLog.user_agent)
            .order_by(func.count(RequestLog.id).desc())
            .limit(1)
        )
        row = result.first()
        if row:
            config.OUTBOUND_USER_AGENT = row[0]
        else:
            config.OUTBOUND_USER_AGENT = config.DEFAULT_OUTBOUND_USER_AGENT
        config.system_config["ua_override"] = config.OUTBOUND_USER_AGENT
        config.system_config.setdefault("api_key_model_max_concurrency", 1)
