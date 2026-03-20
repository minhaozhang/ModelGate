# Database Integration Design

## Overview

Add PostgreSQL database support to store providers configuration, request logs, and statistics. Enable dynamic management of model providers through database and API.

## Goals

- Replace hardcoded `CONFIG["providers"]` with database-stored configuration
- Store request logs in database instead of JSONL files
- Persist statistics in database for historical analysis
- Provide API endpoints for managing providers

## Database Schema

### providers

```sql
CREATE TABLE providers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    base_url VARCHAR(255) NOT NULL,
    api_key VARCHAR(255),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### request_logs

```sql
CREATE TABLE request_logs (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER REFERENCES providers(id),
    model VARCHAR(100) NOT NULL,
    messages JSONB,
    response TEXT,
    tokens JSONB,
    latency_ms FLOAT,
    status VARCHAR(20) NOT NULL,
    error TEXT,
    headers JSONB,
    request_body JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_request_logs_created_at ON request_logs(created_at);
CREATE INDEX idx_request_logs_provider_id ON request_logs(provider_id);
```

### hourly_stats

```sql
CREATE TABLE hourly_stats (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER REFERENCES providers(id),
    hour_key VARCHAR(20) NOT NULL,
    requests INTEGER DEFAULT 0,
    tokens INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    UNIQUE(provider_id, hour_key)
);
```

## Architecture Changes

### File Structure

```
api-proxy/
├── api_proxy.py           # Main application (routes, handlers)
├── database.py            # Database connection and models
├── requirements.txt       # Dependencies
└── ...
```

### Configuration

- Database connection via `DATABASE_URL` environment variable
- Fallback to SQLite for development if not set

### Dependencies

```
fastapi
uvicorn
httpx
asyncpg
sqlalchemy[asyncio]
python-dotenv
```

## API Endpoints (New)

| Endpoint | Methods | Description |
|----------|---------|-------------|
| `/providers` | GET | List all providers |
| `/providers` | POST | Create new provider |
| `/providers/{id}` | PUT | Update provider |
| `/providers/{id}` | DELETE | Delete provider |

## Implementation Notes

1. Use SQLAlchemy 2.0 async patterns
2. Load providers into memory on startup, refresh on changes
3. Batch insert logs for performance
4. Keep in-memory stats cache, persist periodically
