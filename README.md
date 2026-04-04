# ModelGate

<p align="center">
  <img src="assets/favicon.svg" alt="ModelGate logo" width="96" height="96">
</p>

ModelGate is a FastAPI-based LLM gateway for multi-provider routing, API key management, request logging, and dashboard monitoring.

## Highlights

- Multi-provider routing: Zhipu, DeepSeek, Ollama, Minimax, and any OpenAI-compatible API
- OpenAI-compatible proxy endpoints: `/v1/chat/completions`, `/v1/embeddings`, `/v1/models`
- Per-provider concurrency limits with asyncio semaphore-based rate control
- API key management with per-key model access control
- Streaming request lifecycle tracking: `pending` -> `success` / `error` / `timeout`
- Upstream status code logging (200, 429, 500, etc.)
- AI-powered daily error analysis with persisted reports
- AI-powered model recommendations and timing advice for users
- Admin dashboards: overview, monitoring, configuration, error analysis, usage guide
- User portal: personal stats, health score, recommendations, OpenCode config export
- OpenCode integration: auto-generated config with per-model context/output limits
- English / Chinese i18n with Babel
- Desktop and mobile admin UI
- Reverse proxy support via configurable base path
- Daily stats aggregation and 30-day log archiving

## Screenshots

### Admin Dashboard

![Admin Dashboard](image/admin-dashboard.png)

### Admin Monitor

![Admin Monitor](image/admin-monitor.png)

### User Dashboard

![User Dashboard](image/user-dashboard.png)

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

Default local addresses:

- Server: `http://localhost:8765`
- Admin: `http://localhost:8765/admin/home`
- User portal: `http://localhost:8765/user/login`

Windows helper: `start.bat` prompts for log level and restarts the service on port 8765.

## Docker

```bash
docker build -t localhost:5002/modelgate:latest .
docker push localhost:5002/modelgate:latest

docker run -d --name modelgate \
  -p 8765:8765 \
  -e DATABASE_URL="postgresql+asyncpg://modelgate:password@host:5432/modelgate" \
  -e PORT=8765 \
  -e ADMIN_USERS="admin:YourPassword" \
  -v /opt/modelgate/logs:/app/logs \
  --restart unless-stopped \
  localhost:5002/modelgate:latest
```

See [DEPLOY.md](DEPLOY.md) for full deployment instructions.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `PORT` | No | Service port, default `8765` |
| `ADMIN_USERS` | Recommended | Admin accounts, format: `user:pass,user:pass` |
| `ADMIN_USERNAME` | No | Fallback admin username |
| `ADMIN_PASSWORD` | No | Fallback admin password |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `ICP_NUMBER` | No | ICP filing number shown on landing page |

## Database

```sql
CREATE USER "modelgate" WITH PASSWORD 'your_password';
CREATE DATABASE "modelgate" OWNER "modelgate";
```

Schema: [`schema.sql`](schema.sql)

The app performs runtime compatibility migrations on startup (e.g., adding new columns to `request_logs`).

## API

### OpenAI-compatible Endpoints

- `POST /v1/chat/completions` - Chat completions (streaming and non-streaming)
- `POST /v1/embeddings` - Text embeddings
- `GET /v1/models` - List available models

### Model Naming

```text
provider/model
```

Examples: `zhipu/glm-4`, `deepseek/chat`, `minimax/MiniMax-M2.5`

## Dashboards

### Admin

- `/admin/home` - Overview, realtime stats, slow requests, trends
- `/admin/config` - Provider, model, and binding configuration
- `/admin/api-keys` - API key management and per-key model access
- `/admin/monitor` - Composition, hotspots, response-time analysis
- `/admin/errors` - Daily error log viewer with AI-powered analysis reports
- `/admin/usage` - Client configuration examples and setup guides
- `/admin/m` - Mobile admin dashboard

### User Portal

API key holders log in at `/user/login` to access:

- Personal request and token statistics (day/week/month)
- 20-minute system health score (error rate, latency, load, active users)
- AI-powered model recommendations with scored reasons
- AI-generated timing advice based on hourly usage patterns
- Active session tracking
- Model catalog with context/output limits and multimodal info
- OpenCode configuration export (`/opencode/setup.md?api_key=...`)

## Request Logging

`request_logs` stores: API key, provider, model, tokens, latency, status, upstream HTTP status code, client IP, user agent, and error details.

Streaming requests are inserted as `pending` first, then updated to `success`, `error`, `timeout`, or `cancelled`.

Logs older than 30 days are automatically archived to `request_logs_history`. A `request_logs_all` view unions both tables for transparent querying.

## Scheduled Tasks

| Task | Schedule | Description |
|------|----------|-------------|
| Timeout cleanup | Every 10 minutes | Mark stale pending requests (>10 min) as `timeout` |
| Daily aggregation | 00:05 | Aggregate request counts into daily/hourly stats tables |
| Log archival | 00:20 | Archive request logs older than 30 days |

## Project Structure

```text
modelgate/
├── main.py                  # App init, middleware, routers, exception handlers
├── core/
│   ├── config.py            # Logging, caches, stats, session management
│   ├── database.py          # SQLAlchemy async engine, all ORM models
│   ├── deps.py              # Auth dependencies
│   ├── i18n.py              # Internationalization
│   ├── app_paths.py         # Base path for reverse proxy
│   ├── client_ip.py         # Multi-header client IP extraction
│   └── log_sanitizer.py     # Sensitive data redaction for logs
├── routes/
│   ├── proxy.py             # /v1/chat/completions, /v1/embeddings, /v1/models
│   ├── auth.py              # Admin login/logout
│   ├── providers.py         # Provider CRUD
│   ├── models.py            # Model CRUD
│   ├── provider_models.py   # Provider-model bindings + auto-sync
│   ├── keys.py              # API key CRUD + per-key stats/logs
│   ├── stats.py             # Statistics and aggregation endpoints
│   ├── logs.py              # Log viewer + AI error analysis
│   ├── pages.py             # Admin HTML pages
│   ├── user.py              # User portal API + pages
│   └── opencode.py          # OpenCode config generation
├── services/
│   ├── proxy.py             # Main proxy logic, streaming, provider dispatch
│   ├── auth.py              # API key validation
│   ├── provider.py          # Provider/model resolution
│   ├── scheduler.py         # APScheduler tasks
│   ├── stats_aggregator.py  # Daily stats aggregation, archiving
│   ├── logging.py           # Request log CRUD
│   ├── tokens.py            # Token estimation and response parsing
│   ├── message.py           # Message preprocessing (merge, truncate)
│   ├── minimax.py           # MiniMax-specific response/tool_call parsing
│   ├── sse.py               # SSE stream normalization
│   └── analysis_store.py    # AI analysis task persistence
├── templates/               # Jinja2 HTML (admin/, user/, public/, components/)
├── locales/                 # i18n: en, zh
├── schema.sql
├── Dockerfile
└── DEPLOY.md
```

## Development

- Python 3.10+ | FastAPI | SQLAlchemy async | PostgreSQL
- Lint & format: `ruff check . && ruff format .`
- Type check: `mypy main.py core/*.py --ignore-missing-imports`
- i18n compile: `pybabel compile -d locales`
- Logs: `logs/proxy.log`, `logs/admin.log`, `logs/error.log`

## License

Apache 2.0
