from fastapi import HTTPException, Request, status
from typing import List, Optional

from app.core.config import validate_session as _validate_config_session
from app.services.rbac_auth import decode_access_token
from app.services.rbac import has_permission, has_any_permission, get_user_by_id


def _get_session_token(request: Request) -> Optional[str]:
    token = request.cookies.get("session")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    return token


def _is_jwt_token(token: str) -> bool:
    return token.startswith("ey")


async def _resolve_current_user(request: Request):
    token = _get_session_token(request)
    if not token:
        return None

    if _is_jwt_token(token):
        payload = decode_access_token(token)
        if not payload:
            return None
        user = await get_user_by_id(payload["user_id"])
        return user
    else:
        if not _validate_config_session(token):
            return None
        return type("ConfigAdmin", (), {
            "id": 0,
            "username": "admin",
            "is_superuser": True,
            "is_active": True,
        })()


async def require_login(request: Request):
    user = await _resolve_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="\u672a\u767b\u5f55\u6216\u767b\u5f55\u5df2\u8fc7\u671f"
        )
    return user


async def require_permission(request: Request, permission_code: str):
    user = await require_login(request)
    if user.is_superuser:
        return user
    if not await has_permission(user.id, permission_code):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"\u65e0\u6743\u9650\u8bbf\u95ee: {permission_code}"
        )
    return user


async def require_any_permission(request: Request, permission_codes: List[str]):
    user = await require_login(request)
    if user.is_superuser:
        return user
    if not await has_any_permission(user.id, permission_codes):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"\u65e0\u6743\u9650\u8bbf\u95ee\uff0c\u9700\u8981\u4ee5\u4e0b\u4efb\u4e00\u6743\u9650: {', '.join(permission_codes)}"
        )
    return user


def permission_required(permission_code: str):
    async def dependency(request: Request):
        return await require_permission(request, permission_code)
    return dependency


def any_permission_required(permission_codes: List[str]):
    async def dependency(request: Request):
        return await require_any_permission(request, permission_codes)
    return dependency


def login_required():
    async def dependency(request: Request):
        return await require_login(request)
    return dependency
