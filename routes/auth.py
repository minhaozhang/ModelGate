from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Response, Cookie, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import (
    admin_users, validate_session, create_session, clear_session,
    login_attempts, login_lockout, LOGIN_MAX_ATTEMPTS, LOGIN_LOCKOUT_MINUTES,
    admin_logger
)

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/api/login")
async def login(data: LoginRequest, response: Response, request: Request):
    client_ip = request.client.host if request.client else "unknown"

    if client_ip in login_lockout:
        if datetime.now() < login_lockout[client_ip]:
            remaining = (login_lockout[client_ip] - datetime.now()).seconds // 60 + 1
            return JSONResponse(
                {
                    "error": f"Too many failed attempts. Try again in {remaining} minute(s)."
                },
                status_code=429,
            )
        else:
            del login_lockout[client_ip]
            login_attempts.pop(client_ip, None)

    if data.username in admin_users and data.password == admin_users[data.username]:
        login_attempts.pop(client_ip, None)
        admin_logger.info(f"[LOGIN] Success - User: {data.username}, IP: {client_ip}")
        token = create_session()
        response.set_cookie(
            key="session",
            value=token,
            httponly=True,
            max_age=86400,
            samesite="lax",
        )
        return {"success": True}

    login_attempts[client_ip] = login_attempts.get(client_ip, 0) + 1
    admin_logger.warning(
        f"[LOGIN] Failed - User: {data.username}, IP: {client_ip}, Attempts: {login_attempts[client_ip]}"
    )

    if login_attempts[client_ip] >= LOGIN_MAX_ATTEMPTS:
        login_lockout[client_ip] = datetime.now() + timedelta(
            minutes=LOGIN_LOCKOUT_MINUTES
        )
        return JSONResponse(
            {
                "error": f"Too many failed attempts. Account locked for {LOGIN_LOCKOUT_MINUTES} minutes."
            },
            status_code=429,
        )

    remaining = LOGIN_MAX_ATTEMPTS - login_attempts[client_ip]
    return JSONResponse(
        {"error": f"Invalid username or password. {remaining} attempt(s) remaining."},
        status_code=401,
    )


@router.post("/api/logout")
async def logout(response: Response, session: Optional[str] = Cookie(None)):
    if session:
        clear_session(session)
    response.delete_cookie("session")
    return {"success": True}


@router.get("/api/check-auth")
async def check_auth(session: Optional[str] = Cookie(None)):
    return {"authenticated": validate_session(session)}
