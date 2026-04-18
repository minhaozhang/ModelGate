import time
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select, update

from core.config import proxy_logger
from core.database import (
    McpServer,
    McpCallLog,
    ApiKey,
    async_session_maker,
)

logger = proxy_logger

_proxy_tools: dict[int, list[dict]] = {}

TOOL_SYNC_TIMEOUT = 30.0
TOOL_CALL_TIMEOUT = 300.0


async def sync_server_tools(server: McpServer) -> list[dict]:
    headers = _build_auth_headers(server)
    try:
        async with streamable_http_client(
            url=server.url,
            headers=headers,
            timeout=TOOL_SYNC_TIMEOUT,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()
                tools = []
                for tool in result.tools:
                    tools.append(
                        {
                            "name": tool.name,
                            "description": tool.description or "",
                            "inputSchema": tool.inputSchema or {},
                        }
                    )
                _proxy_tools[server.id] = tools

                async with async_session_maker() as db:
                    await db.execute(
                        update(McpServer)
                        .where(McpServer.id == server.id)
                        .values(
                            last_sync_error=None,
                            last_sync_at=None,
                        )
                    )
                    await db.commit()

                logger.info(
                    "[MCP] Synced %d tools from server '%s' (id=%d)",
                    len(tools),
                    server.name,
                    server.id,
                )
                return tools
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        async with async_session_maker() as db:
            await db.execute(
                update(McpServer)
                .where(McpServer.id == server.id)
                .values(last_sync_error=error_msg)
            )
            await db.commit()
        _proxy_tools.pop(server.id, None)
        logger.error(
            "[MCP] Failed to sync tools from server '%s' (id=%d): %s",
            server.name,
            server.id,
            error_msg,
        )
        raise


async def sync_all_servers() -> None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(McpServer).where(McpServer.is_active == True)  # noqa: E712
        )
        servers = result.scalars().all()

    for server in servers:
        try:
            await sync_server_tools(server)
        except Exception:
            pass

    logger.info("[MCP] Synced tools from %d active servers", len(servers))


async def call_tool(
    server: McpServer,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
    api_key_id: int | None = None,
) -> str:
    headers = _build_auth_headers(server)
    start = time.monotonic()
    error_msg = None
    result_text = ""
    is_error = False

    try:
        async with streamable_http_client(
            url=server.url,
            headers=headers,
            timeout=TOOL_CALL_TIMEOUT,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments or {})
                parts = []
                for content in result.content:
                    if hasattr(content, "text"):
                        parts.append(content.text)
                    else:
                        parts.append(str(content))
                result_text = "\n".join(parts)
                is_error = result.isError or False
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        is_error = True

    latency_ms = (time.monotonic() - start) * 1000

    try:
        async with async_session_maker() as session:
            log = McpCallLog(
                api_key_id=api_key_id,
                mcp_server_id=server.id,
                tool_name=tool_name,
                arguments=arguments,
                result=result_text[:10000] if result_text else None,
                is_error=is_error,
                latency_ms=round(latency_ms, 2),
                client_ip=client_ip,
                user_agent=user_agent,
                error=error_msg[:2000] if error_msg else None,
            )
            session.add(log)
            await session.commit()
    except Exception as log_exc:
        logger.error("[MCP] Failed to write call log: %s", log_exc)

    if is_error:
        raise RuntimeError(error_msg or result_text or "Tool call failed")

    return result_text


async def get_server_by_api_key(api_key_id: int) -> McpServer | None:
    async with async_session_maker() as session:
        ak_result = await session.execute(
            select(ApiKey).where(ApiKey.id == api_key_id)
        )
        ak = ak_result.scalar_one_or_none()
        if not ak or not ak.mcp_server_id:
            return None
        result = await session.execute(
            select(McpServer).where(
                McpServer.id == ak.mcp_server_id,
                McpServer.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()


def get_cached_tools(server_id: int) -> list[dict]:
    return _proxy_tools.get(server_id, [])


def remove_cached_tools(server_id: int) -> None:
    _proxy_tools.pop(server_id, None)


def _build_auth_headers(server: McpServer) -> dict[str, str]:
    headers: dict[str, str] = {}
    if server.auth_type == "bearer" and server.auth_token:
        headers["Authorization"] = f"Bearer {server.auth_token}"
    elif server.auth_type == "custom" and server.auth_token and server.auth_header:
        headers[server.auth_header] = server.auth_token
    return headers
