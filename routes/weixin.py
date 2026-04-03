import asyncio
import contextlib
import contextvars
import io
import json

from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from sqlalchemy import select, update
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from core.config import api_keys_cache, logger
from core.database import WeixinAccount, WeixinMessage, async_session_maker
from services.weixin import (
    ILinkClient,
    get_active_account,
    get_context_token,
    get_pending_messages,
    get_qr_code,
    mark_message_replied,
    poll_qr_status,
    save_login,
    save_message,
    start_polling,
)

mcp = FastMCP("weixin-bot")

_session_manager = StreamableHTTPSessionManager(app=mcp._mcp_server)
_exit_stack: contextlib.AsyncExitStack | None = None

_current_api_key_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "_current_api_key_id", default=None
)


@mcp.tool()
async def wechat_login() -> str:
    """Trigger WeChat QR code login. Returns QR code for scanning."""
    api_key_id = _current_api_key_id.get()
    try:
        data = await get_qr_code()
        qrcode_key = data.get("qrcode", "")
        qrcode_url = data.get("qrcode_img_content", "")
        if not qrcode_key:
            return "Failed to get QR code from iLink API"

        import qrcode as qr_lib

        qr = qr_lib.QRCode(border=1)
        qr.add_data(qrcode_url)
        qr.make(fit=True)
        buf = io.StringIO()
        qr.print_ascii(invert=True, out=buf)
        qr_ascii = buf.getvalue()

        asyncio.create_task(_wait_for_scan(qrcode_key, api_key_id))
        return f"Scan this QR code in WeChat:\n\n{qr_ascii}\n\nWaiting for scan..."
    except Exception as e:
        return f"Login failed: {e}"


async def _wait_for_scan(qrcode_key: str, api_key_id: int | None = None):
    for _ in range(60):
        try:
            status = await poll_qr_status(qrcode_key)
            st = status.get("status", "")
            if st == "confirmed":
                bot_token = status.get("bot_token", "")
                ilink_bot_id = status.get("ilink_bot_id", "")
                ilink_user_id = status.get("ilink_user_id", "")
                if bot_token:
                    await save_login(bot_token, ilink_bot_id, ilink_user_id, api_key_id)
                    await start_polling()
                    logger.info("[weixin] Login successful, polling started")
                return
            elif st == "expired":
                logger.info("[weixin] QR code expired")
                return
        except Exception:
            pass
        await asyncio.sleep(5)


@mcp.tool()
async def wechat_status() -> str:
    """Check WeChat login status and unread message count."""
    api_key_id = _current_api_key_id.get()
    account = await get_active_account(api_key_id)
    if not account:
        return "No active WeChat account. Run wechat_login first."

    pending = await get_pending_messages(account.id, limit=100)
    return json.dumps(
        {
            "logged_in": True,
            "ilink_bot_id": account.ilink_bot_id,
            "reply_mode": account.reply_mode,
            "model": account.model_name,
            "unread_count": len(pending),
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def wechat_check_messages(limit: int = 10) -> str:
    """Fetch unread WeChat messages. Returns list of pending messages."""
    api_key_id = _current_api_key_id.get()
    account = await get_active_account(api_key_id)
    if not account:
        return "No active WeChat account. Run wechat_login first."

    messages = await get_pending_messages(account.id, limit=limit)
    if not messages:
        return "No unread messages."

    result = []
    for msg in messages:
        result.append(
            {
                "id": msg.id,
                "from": msg.from_user,
                "text": msg.text,
                "time": str(msg.created_at),
            }
        )
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def wechat_reply(message_id: int, text: str) -> str:
    """Reply to a WeChat message by its ID."""
    api_key_id = _current_api_key_id.get()
    account = await get_active_account(api_key_id)
    if not account:
        return "No active WeChat account."

    async with async_session_maker() as session:
        result = await session.execute(
            select(WeixinMessage).where(
                WeixinMessage.id == message_id,
                WeixinMessage.account_id == account.id,
                WeixinMessage.direction == "in",
            )
        )
        msg = result.scalar_one_or_none()
        if not msg:
            return f"Message {message_id} not found."

    client = ILinkClient(account.bot_token)
    try:
        ctx = msg.context_token or await get_context_token(account.id, msg.from_user)
        await client.send_message(msg.from_user, text, ctx)
        await save_message(
            account_id=account.id,
            direction="out",
            from_user=account.ilink_bot_id or "",
            to_user=msg.from_user,
            text=text,
            context_token=ctx,
            status="replied",
        )
        await mark_message_replied(message_id)
        return f"Reply sent to {msg.from_user}"
    finally:
        await client.close()


@mcp.tool()
async def wechat_send(to: str, text: str) -> str:
    """Proactively send a WeChat message to a user."""
    api_key_id = _current_api_key_id.get()
    account = await get_active_account(api_key_id)
    if not account:
        return "No active WeChat account."

    client = ILinkClient(account.bot_token)
    try:
        ctx = await get_context_token(account.id, to)
        if not ctx:
            return f"No context_token for {to}. User must message you first."
        await client.send_message(to, text, ctx)
        await save_message(
            account_id=account.id,
            direction="out",
            from_user=account.ilink_bot_id or "",
            to_user=to,
            text=text,
            context_token=ctx,
            status="replied",
        )
        return f"Message sent to {to}"
    finally:
        await client.close()


@mcp.tool()
async def wechat_set_mode(mode: str) -> str:
    """Set reply mode: 'auto' (LLM auto-replies) or 'manual' (you control via tools)."""
    if mode not in ("auto", "manual"):
        return "Mode must be 'auto' or 'manual'."

    api_key_id = _current_api_key_id.get()
    account = await get_active_account(api_key_id)
    if not account:
        return "No active WeChat account."

    async with async_session_maker() as session:
        await session.execute(
            update(WeixinAccount)
            .where(WeixinAccount.id == account.id)
            .values(reply_mode=mode)
        )
        await session.commit()
    return f"Reply mode set to '{mode}'"


class _ApiKeyAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            request = Request(scope, receive)
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                key = auth[7:]
            else:
                key = auth
            if not key or key not in api_keys_cache:
                response = JSONResponse({"error": "Unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
            scope["api_key_id"] = api_keys_cache[key]["id"]
        await self.app(scope, receive, send)


async def _mcp_handler(scope: Scope, receive: Receive, send: Send):
    api_key_id = scope.get("api_key_id")
    _current_api_key_id.set(api_key_id)
    await _session_manager.handle_request(scope, receive, send)


async def start_mcp():
    global _exit_stack
    _exit_stack = contextlib.AsyncExitStack()
    await _exit_stack.enter_async_context(_session_manager.run())
    logger.info("[weixin] MCP session manager started")


async def stop_mcp():
    global _exit_stack
    if _exit_stack:
        await _exit_stack.aclose()
        _exit_stack = None
        logger.info("[weixin] MCP session manager stopped")


def get_mcp_asgi_app():
    return _ApiKeyAuthMiddleware(_mcp_handler)
