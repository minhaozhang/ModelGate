from typing import Optional

from fastapi import APIRouter, Cookie, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.app_paths import build_app_url
from app.core.config import validate_session
from app.core.i18n import render

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
    return HTMLResponse(content=render(request, "admin/config.html", active_page="config"))


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


@router.get("/m/login", response_class=HTMLResponse)
async def mobile_login_page(request: Request, session: Optional[str] = Cookie(None)):
    return HTMLResponse(
        content=render(
            request,
            "admin/mobile_login.html",
            default_username="",
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


@router.get("/report-center", response_class=HTMLResponse)
async def report_center_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/report_center.html"))


@router.get("/daily-reports", response_class=HTMLResponse)
async def daily_reports_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/daily_reports.html"))


@router.get("/documents", response_class=HTMLResponse)
async def documents_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/documents.html"))


@router.get("/request-logs", response_class=HTMLResponse)
async def request_logs_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/request_logs.html"))


@router.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/users.html"))


@router.get("/roles", response_class=HTMLResponse)
async def roles_page(request: Request, session: Optional[str] = Cookie(None)):
    if not _check_auth(session):
        return RedirectResponse(url=build_app_url(request, "/admin/login"))
    return HTMLResponse(content=render(request, "admin/roles.html"))
