# Database Integration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan.

**Goal:** Add PostgreSQL database support for providers configuration, request logs, and statistics.

**Architecture:** Create separate `database.py` module with SQLAlchemy async models. Refactor `api_proxy.py` to use database for all data persistence. Add provider management API.

**Tech Stack:** PostgreSQL, SQLAlchemy 2.0 (async), asyncpg

---

## Chunk 1: Database Setup

### Task 1: Update Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add new dependencies**

```
fastapi
uvicorn
httpx
asyncpg
sqlalchemy[asyncio]
python-dotenv
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements.txt`

---

### Task 2: Create Database Module

**Files:**
- Create: `database.py`

- [ ] **Step 1: Create database connection and models**

```python
import os
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./api_proxy.db")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    base_url = Column(String(255), nullable=False)
    api_key = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RequestLog(Base):
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, nullable=True)
    model = Column(String(100), nullable=False)
    messages = Column(JSONB, nullable=True)
    response = Column(Text, nullable=True)
    tokens = Column(JSONB, nullable=True)
    latency_ms = Column(Float, nullable=True)
    status = Column(String(20), nullable=False)
    error = Column(Text, nullable=True)
    headers = Column(JSONB, nullable=True)
    request_body = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (Index("idx_request_logs_created_at", "created_at"),)


class HourlyStat(Base):
    __tablename__ = "hourly_stats"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, nullable=True)
    hour_key = Column(String(20), nullable=False)
    requests = Column(Integer, default=0)
    tokens = Column(Integer, default=0)
    errors = Column(Integer, default=0)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
```

- [ ] **Step 2: Commit**

```bash
git add database.py requirements.txt
git commit -m "feat: add database module with SQLAlchemy models"
```

---

## Chunk 2: Refactor API Proxy

### Task 3: Update API Proxy for Database

**Files:**
- Modify: `api_proxy.py`

- [ ] **Step 1: Update imports**

Replace imports at top with:
```python
import json
import time
import os
from datetime import datetime
from collections import defaultdict
from http import HTTPStatus
from typing import Optional
import httpx
import uvicorn
from fastapi import FastAPI, Request, Response, Depends
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import (
    Provider,
    RequestLog,
    HourlyStat,
    async_session,
    init_db,
    engine,
)
```

- [ ] **Step 2: Update CONFIG and add provider cache**

```python
CONFIG = {
    "port": int(os.getenv("PORT", 8765)),
}

providers_cache: dict[str, dict] = {}
```

- [ ] **Step 3: Add provider loading function**

```python
async def load_providers():
    global providers_cache
    async with async_session() as session:
        result = await session.execute(select(Provider).where(Provider.is_active == True))
        providers = result.scalars().all()
        providers_cache = {
            p.name: {"base_url": p.base_url, "api_key": p.api_key or ""}
            for p in providers
        }
```

- [ ] **Step 4: Update log_request function**

```python
async def log_request(
    provider: str,
    model: str,
    messages: list,
    response_text: str,
    tokens_used: dict,
    latency_ms: float,
    status: str,
    error: Optional[str] = None,
    headers: Optional[dict] = None,
    request_body: Optional[dict] = None,
):
    async with async_session() as session:
        log = RequestLog(
            provider_id=None,
            model=model,
            messages=messages,
            response=response_text,
            tokens=tokens_used,
            latency_ms=latency_ms,
            status=status,
            error=error,
            headers=headers,
            request_body=request_body,
        )
        session.add(log)
        await session.commit()
```

- [ ] **Step 5: Update detect_provider to use cache**

```python
def detect_provider(model: str) -> str:
    model_lower = model.lower()
    for provider_name in providers_cache:
        if provider_name in model_lower:
            return provider_name
    return list(providers_cache.keys())[0] if providers_cache else "unknown"
```

- [ ] **Step 6: Update proxy_request to use cache**

In `proxy_request`, change:
```python
provider_config = CONFIG["providers"].get(provider)
```
to:
```python
provider_config = providers_cache.get(provider)
```

- [ ] **Step 7: Add startup event**

Add before routes:
```python
@app.on_event("startup")
async def startup():
    await init_db()
    await load_providers()
    print(f"Loaded {len(providers_cache)} providers from database")
```

- [ ] **Step 8: Commit**

```bash
git add api_proxy.py
git commit -m "feat: integrate database for providers and logging"
```

---

## Chunk 3: Provider Management API

### Task 4: Add Provider CRUD Endpoints

**Files:**
- Modify: `api_proxy.py`

- [ ] **Step 1: Add Pydantic models**

```python
from pydantic import BaseModel

class ProviderCreate(BaseModel):
    name: str
    base_url: str
    api_key: Optional[str] = None

class ProviderUpdate(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    is_active: Optional[bool] = None
```

- [ ] **Step 2: Add provider endpoints**

```python
@app.get("/providers")
async def list_providers():
    async with async_session() as session:
        result = await session.execute(select(Provider))
        providers = result.scalars().all()
        return {"providers": [
            {"id": p.id, "name": p.name, "base_url": p.base_url, "is_active": p.is_active}
            for p in providers
        ]}


@app.post("/providers")
async def create_provider(data: ProviderCreate):
    async with async_session() as session:
        provider = Provider(name=data.name, base_url=data.base_url, api_key=data.api_key)
        session.add(provider)
        await session.commit()
        await load_providers()
        return {"id": provider.id, "name": provider.name}


@app.put("/providers/{provider_id}")
async def update_provider(provider_id: int, data: ProviderUpdate):
    async with async_session() as session:
        result = await session.execute(select(Provider).where(Provider.id == provider_id))
        provider = result.scalar_one_or_none()
        if not provider:
            return JSONResponse({"error": "Provider not found"}, status_code=404)
        if data.base_url is not None:
            provider.base_url = data.base_url
        if data.api_key is not None:
            provider.api_key = data.api_key
        if data.is_active is not None:
            provider.is_active = data.is_active
        await session.commit()
        await load_providers()
        return {"id": provider.id}


@app.delete("/providers/{provider_id}")
async def delete_provider(provider_id: int):
    async with async_session() as session:
        result = await session.execute(select(Provider).where(Provider.id == provider_id))
        provider = result.scalar_one_or_none()
        if not provider:
            return JSONResponse({"error": "Provider not found"}, status_code=404)
        await session.delete(provider)
        await session.commit()
        await load_providers()
        return {"deleted": True}
```

- [ ] **Step 3: Commit**

```bash
git add api_proxy.py
git commit -m "feat: add provider CRUD endpoints"
```

---

## Chunk 4: Stats and Logs API

### Task 5: Update Stats and Logs Endpoints

**Files:**
- Modify: `api_proxy.py`

- [ ] **Step 1: Update get_stats endpoint**

```python
@app.get("/stats")
async def get_stats():
    async with async_session() as session:
        from sqlalchemy import func
        
        total_result = await session.execute(select(func.count(RequestLog.id)))
        total_requests = total_result.scalar() or 0
        
        tokens_result = await session.execute(
            select(func.sum(RequestLog.tokens["total_tokens"].as_integer()))
        )
        total_tokens = tokens_result.scalar() or 0
        
        errors_result = await session.execute(
            select(func.count(RequestLog.id)).where(RequestLog.status == "error")
        )
        total_errors = errors_result.scalar() or 0
        
        return {
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "providers": dict(stats["providers"]),
            "models": dict(stats["models"]),
        }
```

- [ ] **Step 2: Update logs endpoints**

```python
@app.get("/logs/today")
async def get_today_logs():
    today = datetime.now().strftime("%Y-%m-%d")
    async with async_session() as session:
        result = await session.execute(
            select(RequestLog)
            .where(RequestLog.created_at >= today)
            .order_by(RequestLog.created_at.desc())
            .limit(50)
        )
        logs = result.scalars().all()
        return {"logs": [
            {
                "id": log.id,
                "model": log.model,
                "status": log.status,
                "latency_ms": log.latency_ms,
                "tokens": log.tokens,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]}


@app.get("/logs/all")
async def get_all_logs(limit: int = 100):
    async with async_session() as session:
        result = await session.execute(
            select(RequestLog)
            .order_by(RequestLog.created_at.desc())
            .limit(limit)
        )
        logs = result.scalars().all()
        return {"logs": [
            {
                "id": log.id,
                "model": log.model,
                "status": log.status,
                "latency_ms": log.latency_ms,
                "tokens": log.tokens,
                "created_at": log.created_at.isoformat(),
                "response": log.response,
                "error": log.error,
            }
            for log in logs
        ]}
```

- [ ] **Step 3: Commit**

```bash
git add api_proxy.py
git commit -m "feat: update stats and logs endpoints for database"
```

---

## Summary

1. Install dependencies: `pip install -r requirements.txt`
2. Set `DATABASE_URL` environment variable
3. Run: `python api_proxy.py`
4. Add providers via API: `POST /providers`

Ready to execute?
