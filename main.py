import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.app_paths import APP_BASE_PATH
from core.config import CONFIG, error_logger
from core.database import init_db
from core.i18n import render
from core.log_sanitizer import sanitize_text_for_log
from services.provider import load_providers
from services.auth import load_api_keys


class BasePathMiddleware:
    def __init__(self, app, base_path: str):
        self.app = app
        self.base_path = base_path.rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            path = scope.get("path", "")
            if path == self.base_path or path.startswith(self.base_path + "/"):
                child_path = path[len(self.base_path) :] or "/"
                root_path = scope.get("root_path", "")
                scope = dict(scope)
                scope["root_path"] = f"{root_path}{self.base_path}"
                scope["path"] = child_path
        await self.app(scope, receive, send)


app = FastAPI(title="ModelGate")
app.add_middleware(BasePathMiddleware, base_path=APP_BASE_PATH)
ASSETS_DIR = Path(__file__).resolve().parent / "assets"


@app.get("/")
async def root_page(request: Request):
    base_url = str(request.base_url).rstrip("/")
    return HTMLResponse(
        render(
            request,
            "public/index.html",
            base_url=base_url,
            icp_number=os.getenv("ICP_NUMBER", ""),
        )
    )


@app.get("/favicon.svg", include_in_schema=False)
async def favicon_svg():
    return FileResponse(ASSETS_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    return FileResponse(ASSETS_DIR / "favicon.ico", media_type="image/x-icon")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    log_message = (
        f"[HTTP {'WARN' if exc.status_code == 401 else 'ERROR'}] "
        f"{request.method} {request.url} - Status: {exc.status_code}, Detail: {exc.detail}"
    )
    if exc.status_code == 401:
        error_logger.warning(log_message)
    else:
        error_logger.error(log_message)
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    try:
        body = await request.body()
        body_str = sanitize_text_for_log(body)
    except Exception:
        body_str = ""
    error_logger.error(
        f"[VALIDATION ERROR] {request.method} {request.url}\n"
        f"  Errors: {sanitize_text_for_log(exc.errors(), limit=1500)}\n"
        f"  Body: {body_str}"
    )
    return JSONResponse(
        {"error": "Validation error", "details": exc.errors()}, status_code=422
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    try:
        body = await request.body()
        body_str = sanitize_text_for_log(body)
    except Exception:
        body_str = ""
    error_logger.error(
        f"[UNHANDLED ERROR] {request.method} {request.url}\n"
        f"  Error: {type(exc).__name__}: {sanitize_text_for_log(exc)}\n"
        f"  Body: {body_str}"
    )
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.on_event("startup")
async def startup():
    from core.config import providers_cache, api_keys_cache, logger

    await init_db()
    await load_providers()
    await load_api_keys()
    logger.info(
        f"Loaded {len(providers_cache)} providers, {len(api_keys_cache)} API keys from database"
    )

    from services.scheduler import startup_scheduler

    await startup_scheduler()


@app.on_event("shutdown")
async def shutdown():
    from services.scheduler import shutdown_scheduler

    shutdown_scheduler()


from routes import (
    proxy,
    auth,
    providers,
    models,
    provider_models,
    keys,
    stats,
    logs,
    pages,
    user,
    opencode,
)

app.include_router(proxy.router)
app.include_router(auth.router)
app.include_router(providers.router)
app.include_router(models.router)
app.include_router(provider_models.router)
app.include_router(keys.router)
app.include_router(stats.router)
app.include_router(logs.router)
app.include_router(pages.router)
app.include_router(user.router)
app.include_router(opencode.router)


if __name__ == "__main__":
    from core.config import logger, admin_users

    users_str = ", ".join(admin_users.keys())
    print(f"""
╔════════════════════════════════════════════════════════════╗
║  ModelGate Started                                        ║
║  Dashboard: http://localhost:{CONFIG["port"]}{APP_BASE_PATH}/admin/home          ║
║  API: http://localhost:{CONFIG["port"]}{APP_BASE_PATH}/v1/chat/completions         ║
║  Admin Users: {users_str:<43} ║
╚════════════════════════════════════════════════════════════╝
    """)
    uvicorn.run(app, host="0.0.0.0", port=CONFIG["port"], access_log=False)
