from typing import Optional
from fastapi import APIRouter, Cookie, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from core.config import validate_session
from core.database import async_session_maker, ApiKey

router = APIRouter(prefix="/admin", tags=["pages"])

MOBILE_UA_KEYWORDS = ("android", "iphone", "ipad", "ipod", "mobile")


def _is_mobile(request: Request) -> bool:
    ua = (request.headers.get("user-agent") or "").lower()
    return any(kw in ua for kw in MOBILE_UA_KEYWORDS)


def _check_auth(session: Optional[str]) -> bool:
    return validate_session(session)


@router.get("/", response_class=HTMLResponse)
async def root(request: Request, session: Optional[str] = Cookie(None)):
    if _check_auth(session):
        if _is_mobile(request):
            return RedirectResponse(url="/admin/m")
        return RedirectResponse(url="/admin/home")
    if _is_mobile(request):
        return RedirectResponse(url="/admin/m/login")
    return RedirectResponse(url="/admin/login")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, session: Optional[str] = Cookie(None)):
    if _is_mobile(request):
        return RedirectResponse(url="/admin/m/login")
    if _check_auth(session):
        return RedirectResponse(url="/admin/home")
    from templates.admin.login import LOGIN_PAGE_HTML

    return HTMLResponse(content=LOGIN_PAGE_HTML)


@router.get("/home", response_class=HTMLResponse)
async def home_page(request: Request, session: Optional[str] = Cookie(None)):
    if _is_mobile(request):
        return RedirectResponse(url="/admin/m")
    if not _check_auth(session):
        return RedirectResponse(url="/admin/login")
    from templates.admin.home import HOME_PAGE_HTML

    return HTMLResponse(content=HOME_PAGE_HTML)


@router.get("/config", response_class=HTMLResponse)
async def config_page(session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url="/admin/login")
    from templates.admin.config import CONFIG_PAGE_HTML

    return HTMLResponse(content=CONFIG_PAGE_HTML)


@router.get("/api-keys", response_class=HTMLResponse)
async def api_keys_page(session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url="/admin/login")
    from templates.admin.api_keys import API_KEYS_PAGE_HTML

    return HTMLResponse(content=API_KEYS_PAGE_HTML)


@router.get("/monitor", response_class=HTMLResponse)
async def monitor_page(session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url="/admin/login")
    from templates.admin.monitor import MONITOR_PAGE_HTML

    return HTMLResponse(content=MONITOR_PAGE_HTML)


@router.get("/m/login", response_class=HTMLResponse)
async def mobile_login_page(session: Optional[str] = Cookie(None)):
    if _check_auth(session):
        return RedirectResponse(url="/admin/m")
    from templates.admin.mobile import MOBILE_LOGIN_HTML

    return HTMLResponse(content=MOBILE_LOGIN_HTML)


@router.get("/m", response_class=HTMLResponse)
async def mobile_home_page(session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url="/admin/m/login")
    from templates.admin.mobile import MOBILE_HOME_HTML

    return HTMLResponse(content=MOBILE_HOME_HTML)


@router.get("/usage", response_class=HTMLResponse)
async def usage_page(session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url="/admin/login")
    from templates.admin.usage import USAGE_PAGE_HTML

    return HTMLResponse(content=USAGE_PAGE_HTML)


# @router.get("/api-keys/{key_id}/query", response_class=HTMLResponse)
# async def api_key_query_page(key_id: int):
#     async with async_session_maker() as session:
#         result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
#         key = result.scalar_one_or_none()
#         if not key:
#             return HTMLResponse("<h1>API Key not found</h1>", status_code=404)
#         from templates.query import QUERY_PAGE_HTML
#
#         html = QUERY_PAGE_HTML.format(name=key.name, key_id=key_id)
#         return HTMLResponse(content=html)
