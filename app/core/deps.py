from typing import Optional
from fastapi import Cookie, Depends
from fastapi.responses import JSONResponse

from app.services.rbac_auth import decode_access_token


def get_session(session: Optional[str] = Cookie(None)) -> Optional[str]:
    return session


def require_auth(session: Optional[str] = Depends(get_session)) -> Optional[str]:
    if not session or not session.startswith("ey") or not decode_access_token(session):
        return None
    return session


def require_auth_response(session: Optional[str] = Depends(get_session)):
    if not session or not session.startswith("ey") or not decode_access_token(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return session
