from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Response, Cookie, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.client_ip import get_client_ip
from core.config import (
    admin_users,
    validate_session,
    create_session,
    clear_session,
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
        from services.rbac import get_user_by_username
        from services.rbac_auth import verify_password, create_access_token
        user = await get_user_by_username(username)
        if not user:
            return None
        if not verify_password(password, user.password_hash):
            return None
        token = create_access_token(user.id, user.username)
        return token
    except Exception:
        return None


def _try_config_login(username: str, password: str):
    if username in admin_users and password == admin_users[username]:
        return create_session()
    return None


@router.post("/login")
async def login(data: LoginRequest, response: Response, request: Request):
    client_ip = get_client_ip(request) or "unknown"
    username = data.username.strip()

    if not username and len(admin_users) == 1:
        username = next(iter(admin_users.keys()))

    lockout_resp = _check_lockout(client_ip)
    if lockout_resp:
        return lockout_resp

    token = await _try_rbac_login(username, data.password)
    if not token:
        token = _try_config_login(username, data.password)

    if token:
        login_attempts.pop(client_ip, None)
        admin_logger.info(f"[LOGIN] Success - User: {username}, IP: {client_ip}")
        try:
            from services.audit import write_audit_log
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
        )
        return {"success": True}

    return _record_failure(client_ip, username)


@router.post("/logout")
async def logout(response: Response, request: Request, session: Optional[str] = Cookie(None)):
    logout_username = None
    if session:
        if session.startswith("ey"):
            try:
                from services.rbac_auth import decode_access_token
                payload = decode_access_token(session)
                if payload:
                    logout_username = payload.get("username")
            except Exception:
                pass
        else:
            if validate_session(session):
                for uname in admin_users:
                    logout_username = uname
                    break
        try:
            from services.audit import write_audit_log
            await write_audit_log(
                request, "delete", "session", None, "登出 系统", None, 200,
                username=logout_username,
            )
        except Exception:
            pass
        clear_session(session)
    response.delete_cookie("session")
    return {"success": True}


@router.get("/check")
async def check_auth(session: Optional[str] = Cookie(None)):
    return {"authenticated": validate_session(session)}
