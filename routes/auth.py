from typing import Optional
from fastapi import APIRouter, Response, Cookie
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import CONFIG, validate_session, create_session, clear_session

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    password: str


@router.post("/api/login")
async def login(data: LoginRequest, response: Response):
    if data.password == CONFIG["admin_password"]:
        token = create_session()
        response.set_cookie(
            key="session",
            value=token,
            httponly=True,
            max_age=86400,
            samesite="lax",
        )
        return {"success": True}
    return JSONResponse({"error": "Invalid password"}, status_code=401)


@router.post("/api/logout")
async def logout(response: Response, session: Optional[str] = Cookie(None)):
    if session:
        clear_session(session)
    response.delete_cookie("session")
    return {"success": True}


@router.get("/api/check-auth")
async def check_auth(session: Optional[str] = Cookie(None)):
    return {"authenticated": validate_session(session)}
