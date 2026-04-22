import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select, update

from core.config import proxy_logger
from core.database import (
    McpServer,
    McpCallLog,
    ApiKeyMcpServer,
    async_session_maker,
)

logger = proxy_logger

_proxy_tools: dict[int, list[dict]] = {}
_session_pool: dict[int, dict] = {}

TOOL_SYNC_TIMEOUT = 30.0
TOOL_CALL_TIMEOUT = 300.0


def _build_auth_headers(server: McpServer) -> dict[str, str]:
    headers: dict[str, str] = {}
    if server.auth_type == "bearer" and server.auth_token:
        headers["Authorization"] = f"Bearer {server.auth_token}"
    elif server.auth_type == "custom" and server.auth_token and server.auth_header:
        headers[server.auth_header] = server.auth_token
    return headers


async def _get_session(server: McpServer) -> ClientSession:
    pool_entry = _session_pool.get(server.id)
    if pool_entry:
        try:
            session = pool_entry["session"]
            if not session._read_stream._closed:
                return session
        except Exception:
            pass
        await _close_pool_entry(server.id)

    http_client = httpx.AsyncClient(
        headers=_build_auth_headers(server),
        timeout=httpx.Timeout(TOOL_CALL_TIMEOUT),
    )
    cm = streamable_http_client(url=server.url, http_client=http_client)
    read_stream, write_stream, _ = await cm.__aenter__()
    session = ClientSession(read_stream, write_stream)
    await session.__aenter__()
    await session.initialize()

    _session_pool[server.id] = {
        "session": session,
        "cm": cm,
        "http_client": http_client,
    }
    return session


async def _close_pool_entry(server_id: int) -> None:
    entry = _session_pool.pop(server_id, None)
    if not entry:
        return
    try:
        await entry["session"].__aexit__(None, None, None)
    except Exception:
        pass
    try:
        await entry["cm"].__aexit__(None, None, None)
    except Exception:
        pass
    try:
        await entry["http_client"].aclose()
    except Exception:
        pass



async def close_all_sessions() -> None:
    for sid in list(_session_pool.keys()):
        await _close_pool_entry(sid)


async def sync_server_tools(server: McpServer) -> list[dict]:
    try:
        async with httpx.AsyncClient(
            headers=_build_auth_headers(server),
            timeout=httpx.Timeout(TOOL_SYNC_TIMEOUT),
        ) as http_client:
            async with streamable_http_client(
                url=server.url,
                http_client=http_client,
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
                            .values(last_sync_error=None, last_sync_at=datetime.now(timezone.utc))
                        )
                        await db.commit()

        logger.info(
            "[MCP] Synced %d tools from server '%s' (id=%d)",
            len(tools),
            server.name,
            server.id,
        )
        return tools
    except BaseException as exc:
        if hasattr(exc, "exceptions"):
            sub = [f"{type(e).__name__}: {e}" for e in exc.exceptions]
            error_msg = f"{type(exc).__name__}: {'; '.join(sub)}"
        else:
            error_msg = f"{type(exc).__name__}: {exc}"
        async with async_session_maker() as db:
            await db.execute(
                update(McpServer)
                .where(McpServer.id == server.id)
                .values(last_sync_error=error_msg)
            )
            await db.commit()
        _proxy_tools.pop(server.id, None)
        await _close_pool_entry(server.id)
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

    async def _sync_one(server):
        try:
            await sync_server_tools(server)
        except BaseException as exc:
            if hasattr(exc, "exceptions"):
                details = "; ".join(f"{type(e).__name__}: {e}" for e in exc.exceptions)
            else:
                details = f"{type(exc).__name__}: {exc}"
            logger.error("[MCP] sync_all: server '%s' failed: %s", server.name, details)

    await asyncio.gather(*[_sync_one(s) for s in servers])
    logger.info("[MCP] Synced tools from %d active servers", len(servers))


async def call_tool(
    server: McpServer,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
    api_key_id: int | None = None,
) -> str:
    start = time.monotonic()
    error_msg = None
    result_text = ""
    is_error = False

    try:
        session = await _get_session(server)
        result = await session.call_tool(tool_name, arguments or {})
        parts = []
        for content in result.content:
            if hasattr(content, "text"):
                parts.append(content.text)
            else:
                parts.append(str(content))
        result_text = "\n".join(parts)
        is_error = result.isError or False
    except BaseException as exc:
        if hasattr(exc, "exceptions"):
            sub = [f"{type(e).__name__}: {e}" for e in exc.exceptions]
            error_msg = f"{type(exc).__name__}: {'; '.join(sub)}"
        else:
            error_msg = f"{type(exc).__name__}: {exc}"
        is_error = True
        await _close_pool_entry(server.id)

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


async def get_servers_by_api_key(api_key_id: int) -> list[McpServer]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(McpServer)
            .join(ApiKeyMcpServer, ApiKeyMcpServer.mcp_server_id == McpServer.id)
            .where(
                ApiKeyMcpServer.api_key_id == api_key_id,
                McpServer.is_active == True,  # noqa: E712
            )
        )
        return list(result.scalars().all())


def get_cached_tools(server_id: int) -> list[dict]:
    return _proxy_tools.get(server_id, [])


def remove_cached_tools(server_id: int) -> None:
    _proxy_tools.pop(server_id, None)


def get_server_tool_names(server: McpServer, tools: list[dict]) -> list[str]:
    prefix = server.tool_prefix or ""
    names: list[str] = []
    for tool in tools:
        base_name = tool.get("name")
        if not base_name:
            continue
        names.append(f"{prefix}{base_name}" if prefix else base_name)
    return names
