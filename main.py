import os
import sys
import logging
from logging.handlers import RotatingFileHandler

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import CONFIG, logger
from database import init_db
from services.proxy import load_providers, load_api_keys

app = FastAPI(title="API Proxy")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    from config import logger

    logger.error(
        f"[HTTP ERROR] {request.method} {request.url} - Status: {exc.status_code}, Detail: {exc.detail}"
    )
    logger.debug(f"[HTTP ERROR] Headers: {dict(request.headers)}")
    try:
        body = await request.body()
        logger.debug(f"[HTTP ERROR] Body: {body.decode()}")
    except Exception:
        pass
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    from config import logger

    logger.error(
        f"[VALIDATION ERROR] {request.method} {request.url} - Errors: {exc.errors()}"
    )
    logger.debug(f"[VALIDATION ERROR] Headers: {dict(request.headers)}")
    try:
        body = await request.body()
        logger.debug(f"[VALIDATION ERROR] Body: {body.decode()}")
    except Exception:
        pass
    return JSONResponse(
        {"error": "Validation error", "details": exc.errors()}, status_code=422
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    from config import logger

    logger.error(
        f"[UNHANDLED ERROR] {request.method} {request.url} - {type(exc).__name__}: {exc}"
    )
    logger.debug(f"[UNHANDLED ERROR] Headers: {dict(request.headers)}")
    try:
        body = await request.body()
        logger.debug(f"[UNHANDLED ERROR] Body: {body.decode()}")
    except Exception:
        pass
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.on_event("startup")
async def startup():
    from config import providers_cache, api_keys_cache, logger

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
    from config import logger

    print(f"""
╔════════════════════════════════════════════════════════════╗
║  API Proxy Started                                        ║
║  Dashboard: http://localhost:{CONFIG["port"]}/home                ║
║  API: http://localhost:{CONFIG["port"]}/v1/chat/completions         ║
║  Admin Password: {CONFIG["admin_password"]:<39} ║
╚════════════════════════════════════════════════════════════╝
    """)
    uvicorn.run(app, host="0.0.0.0", port=CONFIG["port"])
