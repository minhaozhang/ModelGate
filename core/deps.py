from typing import Optional
from fastapi import Cookie, Depends
from fastapi.responses import JSONResponse

from core.config import validate_session


def get_session(session: Optional[str] = Cookie(None)) -> Optional[str]:
    return session


def require_auth(session: Optional[str] = Depends(get_session)) -> Optional[str]:
    if not validate_session(session):
        return None
    return session


def require_auth_response(session: Optional[str] = Depends(get_session)):
    if not validate_session(session):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return session
