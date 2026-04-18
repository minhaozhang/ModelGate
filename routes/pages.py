from typing import Optional

from fastapi import APIRouter, Cookie, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core.app_paths import build_app_url
from core.config import admin_users, validate_session
from core.i18n import render

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
            return RedirectResponse(url=build_app_url(request, "/admin/m"))
        return RedirectResponse(url=build_app_url(request, "/admin/home"))
    if _is_mobile(request):
        return RedirectResponse(url=build_app_url(request, "/admin/m/login"))
    return RedirectResponse(url=build_app_url(request, "/admin/login"))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, session: Optional[str] = Cookie(None)):
    if _is_mobile(request):
        return RedirectResponse(url=build_app_url(request, "/admin/m/login"))
    if _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/home"))
    return HTMLResponse(content=render(request, "admin/login.html"))


@router.get("/home", response_class=HTMLResponse)
async def home_page(request: Request, session: Optional[str] = Cookie(None)):
    if _is_mobile(request):
        return RedirectResponse(url=build_app_url(request, "/admin/m"))
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/home.html"))


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/config.html"))


@router.get("/api-keys", response_class=HTMLResponse)
async def api_keys_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/api_keys.html"))


@router.get("/monitor", response_class=HTMLResponse)
async def monitor_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/monitor.html"))


@router.get("/errors", response_class=HTMLResponse)
async def errors_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/errors.html"))


@router.get("/m/login", response_class=HTMLResponse)
async def mobile_login_page(request: Request, session: Optional[str] = Cookie(None)):
    if _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/m"))
    default_username = next(iter(admin_users.keys())) if len(admin_users) == 1 else ""
    return HTMLResponse(
        content=render(
            request,
            "admin/mobile_login.html",
            default_username=default_username,
        )
    )


@router.get("/m", response_class=HTMLResponse)
async def mobile_home_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/m/login"))
    return HTMLResponse(content=render(request, "admin/mobile_home.html"))


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/reports.html"))


@router.get("/documents", response_class=HTMLResponse)
async def documents_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/documents.html"))


@router.get("/mcp-servers", response_class=HTMLResponse)
async def mcp_servers_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/mcp_servers.html"))


@router.get("/request-logs", response_class=HTMLResponse)
async def request_logs_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/request_logs.html"))
