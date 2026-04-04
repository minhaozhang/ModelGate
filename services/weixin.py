import asyncio
import base64
import json
import random
import uuid

import httpx
from sqlalchemy import select, update

from core.config import logger
from core.database import (
    WeixinAccount,
    WeixinContextToken,
    WeixinMessage,
    async_session_maker,
)
from services.proxy import (
    INTERNAL_ANALYSIS_API_KEY_ID,
    call_internal_model_via_proxy,
)

ILINK_BASE = "https://ilinkai.weixin.qq.com"
CHANNEL_VERSION = "1.0.3"


class ILinkClient:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.client = httpx.AsyncClient(timeout=40)

    def _headers(self) -> dict:
        uin = base64.b64encode(str(random.randint(0, 0xFFFFFFFF)).encode()).decode()
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self.bot_token}",
            "X-WECHAT-UIN": uin,
        }

    async def _post(self, endpoint: str, body: dict) -> dict:
        body["base_info"] = {"channel_version": CHANNEL_VERSION}
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = self._headers()
        headers["Content-Length"] = str(len(raw))
        resp = await self.client.post(
            f"{ILINK_BASE}/ilink/bot/{endpoint}",
            content=raw,
            headers=headers,
            timeout=35,
        )
        text = resp.text.strip()
        if text and text != "{}":
            return json.loads(text)
        return {"ret": 0}

    async def get_updates(self, cursor: str = "") -> tuple[list[dict], str]:
        result = await self._post("getupdates", {"get_updates_buf": cursor})
        new_cursor = result.get("get_updates_buf", cursor)
        msgs = result.get("msgs", [])
        return msgs, new_cursor

    async def send_message(
        self, to_user_id: str, text: str, context_token: str = ""
    ) -> dict:
        return await self._post(
            "sendmessage",
            {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to_user_id,
                    "client_id": f"mg-{uuid.uuid4().hex[:12]}",
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                }
            },
        )

    async def send_typing(self, to_user_id: str) -> dict:
        return await self._post("sendtyping", {"to_user_id": to_user_id})

    async def close(self):
        await self.client.aclose()


async def get_qr_code() -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{ILINK_BASE}/ilink/bot/get_bot_qrcode?bot_type=3",
            timeout=15,
        )
        return resp.json()


async def poll_qr_status(qrcode_key: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{ILINK_BASE}/ilink/bot/get_qrcode_status?qrcode={qrcode_key}",
            headers={"iLink-App-ClientVersion": "1"},
            timeout=40,
        )
        return resp.json()


async def save_login(
    bot_token: str, ilink_bot_id: str, ilink_user_id: str, api_key_id: int | None = None
) -> int:
    from datetime import datetime

    async with async_session_maker() as session:
        await session.execute(
            update(WeixinAccount)
            .where(WeixinAccount.ilink_user_id == ilink_user_id)
            .values(is_active=False)
        )
        result = await session.execute(
            select(WeixinAccount).where(WeixinAccount.ilink_bot_id == ilink_bot_id)
        )
        account = result.scalar_one_or_none()
        if account:
            account.bot_token = bot_token
            account.ilink_user_id = ilink_user_id
            account.is_active = True
            account.api_key_id = api_key_id
            account.login_at = datetime.utcnow()
        else:
            account = WeixinAccount(
                bot_token=bot_token,
                ilink_bot_id=ilink_bot_id,
                ilink_user_id=ilink_user_id,
                api_key_id=api_key_id,
                is_active=True,
                reply_mode="manual",
                login_at=datetime.utcnow(),
            )
            session.add(account)
        await session.commit()
        await session.refresh(account)
        return account.id


async def save_context_token(account_id: int, user_id: str, token: str):
    async with async_session_maker() as session:
        result = await session.execute(
            select(WeixinContextToken).where(
                WeixinContextToken.account_id == account_id,
                WeixinContextToken.user_id == user_id,
            )
        )
        ctx = result.scalar_one_or_none()
        if ctx:
            ctx.context_token = token
        else:
            ctx = WeixinContextToken(
                account_id=account_id, user_id=user_id, context_token=token
            )
            session.add(ctx)
        await session.commit()


async def get_context_token(account_id: int, user_id: str) -> str:
    async with async_session_maker() as session:
        result = await session.execute(
            select(WeixinContextToken).where(
                WeixinContextToken.account_id == account_id,
                WeixinContextToken.user_id == user_id,
            )
        )
        ctx = result.scalar_one_or_none()
        return ctx.context_token if ctx else ""


async def save_message(
    account_id: int,
    direction: str,
    from_user: str,
    to_user: str,
    text: str,
    context_token: str = "",
    status: str = "pending",
) -> WeixinMessage:
    async with async_session_maker() as session:
        msg = WeixinMessage(
            account_id=account_id,
            direction=direction,
            from_user=from_user,
            to_user=to_user,
            text=text,
            context_token=context_token,
            status=status,
        )
        session.add(msg)
        await session.commit()
        await session.refresh(msg)
        return msg


async def get_pending_messages(account_id: int, limit: int = 10) -> list:
    async with async_session_maker() as session:
        result = await session.execute(
            select(WeixinMessage)
            .where(
                WeixinMessage.account_id == account_id,
                WeixinMessage.direction == "in",
                WeixinMessage.status == "pending",
            )
            .order_by(WeixinMessage.created_at)
            .limit(limit)
        )
        return result.scalars().all()


async def mark_message_replied(message_id: int):
    async with async_session_maker() as session:
        await session.execute(
            update(WeixinMessage)
            .where(WeixinMessage.id == message_id)
            .values(status="replied")
        )
        await session.commit()


async def get_active_account(api_key_id: int | None = None) -> WeixinAccount | None:
    async with async_session_maker() as session:
        stmt = select(WeixinAccount).where(
            WeixinAccount.is_active.is_(True),
            WeixinAccount.bot_token.isnot(None),
        )
        if api_key_id is not None:
            stmt = stmt.where(WeixinAccount.api_key_id == api_key_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def get_all_active_accounts() -> list[WeixinAccount]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(WeixinAccount).where(
                WeixinAccount.is_active.is_(True),
                WeixinAccount.bot_token.isnot(None),
            )
        )
        return list(result.scalars().all())


_poll_task: asyncio.Task | None = None


async def start_polling():
    global _poll_task
    if _poll_task and not _poll_task.done():
        return
    _poll_task = asyncio.create_task(_poll_loop())
    logger.info("[weixin] Background polling started")


async def stop_polling():
    global _poll_task
    if _poll_task and not _poll_task.done():
        _poll_task.cancel()
        try:
            await _poll_task
        except asyncio.CancelledError:
            pass
    _poll_task = None
    logger.info("[weixin] Background polling stopped")


async def _update_account_cursor(account_id: int, cursor: str):
    async with async_session_maker() as session:
        await session.execute(
            update(WeixinAccount)
            .where(WeixinAccount.id == account_id)
            .values(get_updates_buf=cursor)
        )
        await session.commit()


async def _handle_incoming_message(
    account: WeixinAccount,
    client: ILinkClient,
    msg: dict,
):
    from_user = msg.get("from_user_id", "")
    ctx = msg.get("context_token", "")
    text_parts = []
    for item in msg.get("item_list", []):
        if item.get("type") == 1:
            text_parts.append(item.get("text_item", {}).get("text", ""))
    text = "".join(text_parts)
    if not text:
        return

    if ctx:
        await save_context_token(account.id, from_user, ctx)

    inbound_message = await save_message(
        account_id=account.id,
        direction="in",
        from_user=from_user,
        to_user=account.ilink_bot_id or "",
        text=text,
        context_token=ctx,
        status="pending",
    )
    logger.info(f"[weixin] Received from {from_user}: {text[:50]}")

    if account.reply_mode == "auto":
        await _auto_reply(
            account,
            client,
            from_user,
            text,
            ctx,
            inbound_message.id,
        )


async def _poll_loop():
    while True:
        try:
            accounts = await get_all_active_accounts()
            if not accounts:
                await asyncio.sleep(10)
                continue

            for account in accounts:
                try:
                    client = ILinkClient(account.bot_token)
                    try:
                        msgs, new_cursor = await client.get_updates(
                            account.get_updates_buf or ""
                        )
                        for msg in msgs:
                            await _handle_incoming_message(account, client, msg)

                        if new_cursor != account.get_updates_buf:
                            await _update_account_cursor(account.id, new_cursor)
                    finally:
                        await client.close()
                except Exception as e:
                    logger.error(f"[weixin] Poll error for account {account.id}: {e}")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[weixin] Poll loop error: {e}")
        await asyncio.sleep(3)


async def _auto_reply(
    account: WeixinAccount,
    ilink_client: ILinkClient,
    from_user: str,
    text: str,
    context_token: str,
    inbound_message_id: int,
):
    try:
        system_prompt = account.system_prompt or "You are a helpful AI assistant."
        body_json = {
            "model": account.model_name or "zhipu/glm-4-flash",
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": text},
            ],
            "stream": False,
        }
        result = await call_internal_model_via_proxy(
            requested_model=body_json["model"],
            body_json=body_json,
            api_key_id=(
                account.api_key_id
                if account.api_key_id is not None
                else INTERNAL_ANALYSIS_API_KEY_ID
            ),
            purpose="weixin-auto-reply",
            timeout_seconds=60.0,
        )
        if not result.get("ok"):
            logger.warning(
                "[weixin] Auto-reply model call failed for account %s with status %s: %s",
                account.id,
                result.get("status_code"),
                str(result.get("error") or "")[:300],
            )
            return

        data = result.get("payload") or {}
        reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not reply:
            logger.warning("[weixin] Auto-reply returned empty content for account %s", account.id)
            return

        ctx = context_token or await get_context_token(account.id, from_user)
        await ilink_client.send_message(from_user, reply, ctx)
        await save_message(
            account_id=account.id,
            direction="out",
            from_user=account.ilink_bot_id or "",
            to_user=from_user,
            text=reply,
            context_token=ctx,
            status="replied",
        )
        await mark_message_replied(inbound_message_id)
        logger.info(f"[weixin] Auto-reply to {from_user}: {reply[:50]}")
    except Exception as e:
        logger.error(f"[weixin] Auto-reply error: {e}")
