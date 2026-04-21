from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select

from core.database import async_session_maker, McpServer, ApiKey, ApiKeyMcpServer
from core.config import validate_session
from services.mcp_proxy import (
    sync_server_tools,
    get_cached_tools,
    remove_cached_tools,
)
from routes.mcp_proxy import register_all_proxy_tools

router = APIRouter(prefix="/admin/api", tags=["mcp-servers"])


def require_admin(session: Optional[str] = Cookie(None)):
    if not validate_session(session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


class McpServerCreate(BaseModel):
    name: str
    url: str
    auth_type: Optional[str] = "none"
    auth_token: Optional[str] = None
    auth_header: Optional[str] = "Authorization"
    tool_prefix: Optional[str] = None
    is_active: Optional[bool] = True


class McpServerUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    auth_type: Optional[str] = None
    auth_token: Optional[str] = None
    auth_header: Optional[str] = None
    tool_prefix: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/mcp-servers")
async def list_mcp_servers(_: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        result = await session.execute(select(McpServer))
        servers = result.scalars().all()

        server_ids = [s.id for s in servers]
        api_key_map: dict[int, list[str]] = {s.id: [] for s in servers}
        if server_ids:
            ak_result = await session.execute(
                select(ApiKeyMcpServer.mcp_server_id, ApiKey.name)
                .join(ApiKey, ApiKey.id == ApiKeyMcpServer.api_key_id)
                .where(ApiKeyMcpServer.mcp_server_id.in_(server_ids))
            )
            for row in ak_result.fetchall():
                api_key_map[row[0]].append(row[1])

        return {
            "servers": [
                {
                    "id": s.id,
                    "api_key_names": api_key_map.get(s.id, []),
                    "name": s.name,
                    "url": s.url,
                    "auth_type": s.auth_type,
                    "auth_header": s.auth_header,
                    "is_active": s.is_active,
                    "tool_prefix": s.tool_prefix,
                    "last_sync_at": s.last_sync_at.isoformat() if s.last_sync_at else None,
                    "last_sync_error": s.last_sync_error,
                    "tool_count": len(get_cached_tools(s.id)),
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in servers
            ]
        }


@router.post("/mcp-servers")
async def create_mcp_server(data: McpServerCreate, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        server = McpServer(
            name=data.name,
            url=data.url,
            auth_type=data.auth_type or "none",
            auth_token=data.auth_token,
            auth_header=data.auth_header or "Authorization",
            tool_prefix=data.tool_prefix,
            is_active=data.is_active if data.is_active is not None else True,
        )
        session.add(server)
        await session.commit()
        await session.refresh(server)

    if server.is_active:
        try:
            await sync_server_tools(server)
        except Exception:
            pass
    await register_all_proxy_tools()

    return {"id": server.id, "name": server.name}


@router.put("/mcp-servers/{server_id}")
async def update_mcp_server(
    server_id: int, data: McpServerUpdate, _: bool = Depends(require_admin)
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(McpServer).where(McpServer.id == server_id)
        )
        server = result.scalar_one_or_none()
        if not server:
            return JSONResponse({"error": "MCP server not found"}, status_code=404)

        if data.name is not None:
            server.name = data.name
        if data.url is not None:
            server.url = data.url
        if data.auth_type is not None:
            server.auth_type = data.auth_type
        if data.auth_token is not None:
            server.auth_token = data.auth_token
        if data.auth_header is not None:
            server.auth_header = data.auth_header
        if data.tool_prefix is not None:
            server.tool_prefix = data.tool_prefix
        if data.is_active is not None:
            server.is_active = data.is_active

        await session.commit()

    if (
        data.url is not None
        or data.auth_type is not None
        or data.auth_token is not None
        or data.auth_header is not None
        or data.tool_prefix is not None
        or data.is_active is not None
    ):
        if server.is_active:
            try:
                await sync_server_tools(server)
            except Exception:
                pass
        else:
            remove_cached_tools(server.id)
    await register_all_proxy_tools()

    return {"id": server.id}


@router.delete("/mcp-servers/{server_id}")
async def delete_mcp_server(server_id: int, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        result = await session.execute(
            select(McpServer).where(McpServer.id == server_id)
        )
        server = result.scalar_one_or_none()
        if not server:
            return JSONResponse({"error": "MCP server not found"}, status_code=404)
        await session.delete(server)
        await session.commit()

    remove_cached_tools(server_id)
    await register_all_proxy_tools()
    return {"deleted": True}


@router.post("/mcp-servers/{server_id}/sync")
async def sync_mcp_server_tools(server_id: int, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        result = await session.execute(
            select(McpServer).where(McpServer.id == server_id)
        )
        server = result.scalar_one_or_none()
        if not server:
            return JSONResponse({"error": "MCP server not found"}, status_code=404)

    try:
        tools = await sync_server_tools(server)
        await register_all_proxy_tools()
        return {"synced": True, "tool_count": len(tools)}
    except Exception as exc:
        return JSONResponse(
            {"error": f"Sync failed: {exc}"},
            status_code=500,
        )


@router.get("/mcp-servers/{server_id}/tools")
async def get_mcp_server_tools(server_id: int, _: bool = Depends(require_admin)):
    tools = get_cached_tools(server_id)
    return {"tools": tools}
