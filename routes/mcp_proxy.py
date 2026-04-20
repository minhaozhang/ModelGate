import contextlib
import contextvars

from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from sqlalchemy import select

from core.config import api_keys_cache, logger
from core.database import McpServer, async_session_maker
from services.mcp_proxy import get_servers_by_api_key, get_cached_tools, call_tool

mcp = FastMCP("ModelGate MCP Proxy")

_session_manager = StreamableHTTPSessionManager(app=mcp._mcp_server)
_exit_stack: contextlib.AsyncExitStack | None = None

_current_api_key_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "_current_mcp_api_key_id", default=None
)

_current_server_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "_current_mcp_server_id", default=None
)


def _register_proxy_tools(server: McpServer, tools: list[dict]) -> None:
    prefix = server.tool_prefix or ""
    for tool_info in tools:
        tool_name = f"{prefix}{tool_info['name']}" if prefix else tool_info["name"]
        description = tool_info.get("description", "")

        try:
            mcp.remove_tool(tool_name)
        except Exception:
            pass

        def _make_handler(tn: str, sn: McpServer):
            async def handler(**kwargs):
                ak_id = _current_api_key_id.get()
                return await call_tool(
                    server=sn,
                    tool_name=tn,
                    arguments=kwargs,
                    api_key_id=ak_id,
                )
            return handler

        fn = _make_handler(tool_info["name"], server)
        fn.__name__ = tool_name
        fn.__doc__ = description

        mcp.add_tool(
            fn,
            name=tool_name,
            description=description,
        )


async def register_all_proxy_tools() -> None:
    for name in list(mcp._tool_manager._tools.keys()):
        try:
            mcp.remove_tool(name)
        except Exception:
            pass

    async with async_session_maker() as session:
        result = await session.execute(
            select(McpServer).where(McpServer.is_active == True)  # noqa: E712
        )
        servers = result.scalars().all()

    for server in servers:
        tools = get_cached_tools(server.id)
        if tools:
            _register_proxy_tools(server, tools)

    logger.info("[MCP Proxy] Registered tools from %d active servers", len(servers))


class _ApiKeyAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            from starlette.requests import Request
            from starlette.responses import JSONResponse

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

            api_key_id = api_keys_cache[key]["id"]
            scope["api_key_id"] = api_key_id

        await self.app(scope, receive, send)


async def _mcp_handler(scope, receive, send):
    api_key_id = scope.get("api_key_id")
    _current_api_key_id.set(api_key_id)

    if api_key_id:
        servers = await get_servers_by_api_key(api_key_id)
        if servers:
            _current_server_id.set(servers[0].id)
        else:
            from starlette.responses import JSONResponse
            response = JSONResponse(
                {"error": "No MCP server bound to this API key"}, status_code=403
            )
            await response(scope, receive, send)
            return
    else:
        _current_server_id.set(None)

    await _session_manager.handle_request(scope, receive, send)


async def start_mcp_proxy():
    global _exit_stack
    _exit_stack = contextlib.AsyncExitStack()
    await _exit_stack.enter_async_context(_session_manager.run())

    from services.mcp_proxy import sync_all_servers

    await sync_all_servers()
    await register_all_proxy_tools()

    logger.info("[MCP Proxy] Session manager started and tools registered")


async def stop_mcp_proxy():
    global _exit_stack
    if _exit_stack:
        await _exit_stack.aclose()
        _exit_stack = None
        logger.info("[MCP Proxy] Session manager stopped")


def get_mcp_proxy_asgi_app():
    return _ApiKeyAuthMiddleware(_mcp_handler)
