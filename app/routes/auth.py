from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Response, Cookie, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.client_ip import get_client_ip
from app.core.config import (
    login_attempts,
    login_lockout,
    LOGIN_MAX_ATTEMPTS,
    LOGIN_LOCKOUT_MINUTES,
    admin_logger,
)

router = APIRouter(prefix="/admin/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


def _check_lockout(client_ip: str):
    if client_ip in login_lockout:
        if datetime.now() < login_lockout[client_ip]:
            remaining = (login_lockout[client_ip] - datetime.now()).seconds // 60 + 1
            return JSONResponse(
                {"error": f"Too many failed attempts. Try again in {remaining} minute(s)."},
                status_code=429,
            )
        else:
            del login_lockout[client_ip]
            login_attempts.pop(client_ip, None)
    return None


def _record_failure(client_ip: str, username: str):
    login_attempts[client_ip] = login_attempts.get(client_ip, 0) + 1
    admin_logger.warning(
        f"[LOGIN] Failed - User: {username or '<empty>'}, IP: {client_ip}, "
        f"Attempts: {login_attempts[client_ip]}"
    )
    if login_attempts[client_ip] >= LOGIN_MAX_ATTEMPTS:
        login_lockout[client_ip] = datetime.now() + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
        return JSONResponse(
            {"error": f"Too many failed attempts. Account locked for {LOGIN_LOCKOUT_MINUTES} minutes."},
            status_code=429,
        )
    remaining = LOGIN_MAX_ATTEMPTS - login_attempts[client_ip]
    return JSONResponse(
        {"error": f"Invalid username or password. {remaining} attempt(s) remaining."},
        status_code=401,
    )


async def _try_rbac_login(username: str, password: str):
    try:
        from app.services.rbac import get_user_by_username
        from app.services.rbac_auth import verify_password, create_access_token
        user = await get_user_by_username(username)
        if not user:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return create_access_token(user.id, user.username)
    except Exception:
        return None


@router.post("/login")
async def login(data: LoginRequest, response: Response, request: Request):
    client_ip = get_client_ip(request) or "unknown"
    username = data.username.strip()

    lockout_resp = _check_lockout(client_ip)
    if lockout_resp:
        return lockout_resp

    token = await _try_rbac_login(username, data.password)

    if token:
        login_attempts.pop(client_ip, None)
        admin_logger.info(f"[LOGIN] Success - User: {username}, IP: {client_ip}")
        try:
            from sqlalchemy import update
            from app.core.database import User, async_session_maker

            async with async_session_maker() as session:
                await session.execute(
                    update(User)
                    .where(User.username == username)
                    .values(last_login=datetime.now(), updated_at=datetime.now())
                )
                await session.commit()
        except Exception:
            pass
        try:
            from app.services.audit import write_audit_log
            await write_audit_log(
                request, "create", "session", None,
                f"登录 系统 (User: {username})", None, 200,
                username=username,
            )
        except Exception:
            pass
        response.set_cookie(
            key="session",
            value=token,
            httponly=True,
            max_age=86400,
            samesite="lax",
            path="/",
        )
        return {"success": True}

    return _record_failure(client_ip, username)


@router.post("/logout")
async def logout(response: Response, request: Request, session: Optional[str] = Cookie(None)):
    logout_username = None
    if session:
        try:
            from app.services.rbac_auth import decode_access_token
            payload = decode_access_token(session)
            if payload:
                logout_username = payload.get("username")
        except Exception:
            pass
        try:
            from app.services.audit import write_audit_log
            await write_audit_log(
                request, "delete", "session", None, "登出 系统", None, 200,
                username=logout_username,
            )
        except Exception:
            pass
    response.delete_cookie("session", path="/")
    return {"success": True}


@router.post("/change-password")
async def change_password(
    request: Request,
    session: Optional[str] = Cookie(None),
):
    if not session:
        return JSONResponse({"error": "未登录"}, status_code=401)
    if not session.startswith("ey"):
        return JSONResponse({"error": "当前会话不支持修改密码"}, status_code=401)

    body = await request.json()
    old_password = body.get("old_password", "")
    new_password = body.get("new_password", "")
    if not old_password or not new_password:
        return JSONResponse({"error": "旧密码和新密码不能为空"}, status_code=400)
    if len(new_password) < 6:
        return JSONResponse({"error": "新密码长度不能少于6位"}, status_code=400)

    try:
        from app.services.rbac import get_user_by_id
        from app.services.rbac_auth import (
            decode_access_token,
            hash_password,
            verify_password,
        )
        from app.core.database import User, async_session_maker

        payload = decode_access_token(session)
        if not payload:
            return JSONResponse({"error": "登录已过期"}, status_code=401)
        user = await get_user_by_id(payload["user_id"])
        if not user:
            return JSONResponse({"error": "用户不存在"}, status_code=404)
        if not verify_password(old_password, user.password_hash):
            return JSONResponse({"error": "旧密码错误"}, status_code=400)

        async with async_session_maker() as db:
            await db.execute(
                sql_update(User)
                .where(User.id == user.id)
                .values(password_hash=hash_password(new_password))
            )
            await db.commit()
        return {"success": True, "message": "密码修改成功"}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/check")
async def check_auth(session: Optional[str] = Cookie(None)):
    if not session:
        return {"authenticated": False}
    username = None
    try:
        from app.services.rbac_auth import decode_access_token

        payload = decode_access_token(session)
        if not payload:
            return {"authenticated": False}
        username = payload.get("username")
    except Exception:
        return {"authenticated": False}
    return {"authenticated": True, "username": username}
