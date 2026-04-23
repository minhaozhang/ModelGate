# ModelGate

<p align="center">
  <img src="assets/favicon.svg" alt="ModelGate logo" width="96" height="96">
</p>

ModelGate is a FastAPI-based LLM gateway for multi-provider routing, API key management, request logging, and dashboard monitoring.

## Highlights

- Multi-provider routing: Zhipu, DeepSeek, Ollama, Minimax, and any OpenAI-compatible API
- OpenAI-compatible proxy endpoints: `/v1/chat/completions`, `/v1/embeddings`, `/v1/models`
- Layered concurrency control: API key model limit -> provider key limit with per-key semaphore
- Provider multi-key support with sticky routing and key-level disable/reenable
- Auto-disable provider/key on usage limit errors, auto-reenable on scheduled task
- API key management with per-key model access control
- Streaming request lifecycle tracking: `pending` -> `success` / `error` / `timeout`
- Upstream and downstream status code logging
- MCP proxy: proxy remote MCP servers with API key binding, admin UI, tool sync, logging, and stats
- AI-powered daily error analysis with persisted reports
- AI-powered model recommendations and timing advice for users
- AI-powered usage report generation (DOCX export with stats, trends, and fun awards)
- API key time-based access rules (time windows, date ranges, weekday restrictions)
- Document sharing for admin and user portal
- User portal: personal stats, health score, recommendations, OpenCode config export
- OpenCode integration: auto-generated config with per-model context/output limits
- WeChat iLink Bot integration via MCP (QR login, auto-reply, message persistence)
- MinIO integration for file storage
- English / Chinese i18n with Babel
- Desktop and mobile admin UI with dark/light theme
- Localized static assets (no CDN dependencies)
- Reverse proxy support via configurable base path
- Docker Compose with Nginx reverse proxy and static file serving
- Daily stats aggregation and 30-day log archiving

## Screenshots

### Admin Dashboard

![Admin Dashboard](image/admin-dashboard.png)

### Admin Monitor

![Admin Monitor](image/admin-monitor.png)

### User Dashboard

![User Dashboard](image/user-dashboard.png)

### User Report

![User Report](image/user-report.png)


### Mobile Dashboard

![Mobile Dashboard](image/mobile-dashboard.png)

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

### Docker Run

```bash
docker build -t localhost:5002/modelgate:latest .
docker push localhost:5002/modelgate:latest

docker run -d --name modelgate \
  -p 8765:8765 \
  -e DATABASE_URL="postgresql+asyncpg://modelgate:password@host:5432/modelgate" \
  -e PORT=8765 \
  -e ADMIN_USERS="admin:YourPassword" \
  -v /opt/modelgate/logs:/app/logs \
  -v /opt/modelgate/reports:/app/reports \
  -v /opt/modelgate/uploads:/app/uploads/documents \
  --restart unless-stopped \
  localhost:5002/modelgate:latest
```

### Docker Compose

The repository includes a `docker-compose.yml` with ModelGate + Nginx services. Nginx handles static file serving and reverse proxying with WebSocket support.

```bash
docker compose up -d
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
| `MINIO_ENDPOINT` | No | MinIO endpoint, default `localhost:9000` |
| `MINIO_ACCESS_KEY` | No | MinIO access key |
| `MINIO_SECRET_KEY` | No | MinIO secret key |
| `MINIO_BUCKET` | No | MinIO bucket name, default `modelgate` |
| `MINIO_SECURE` | No | Use HTTPS for MinIO, default `false` |
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
- `/admin/reports` - AI-powered usage report generation and DOCX download
- `/admin/system-config` - Outbound User-Agent management and UA stats
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

## API Key Time-Based Access Rules

API keys can be restricted by time of day, date ranges, and weekdays. Rules are validated on every request:

- **Time windows** — `start_time` / `end_time` (e.g., only allow 09:00–18:00)
- **Date ranges** — `start_date` / `end_date`
- **Weekday filters** — restrict to specific days of the week
- **Allow/deny semantics** — explicit `allowed` flag per rule

## WeChat iLink Bot (MCP)

ModelGate includes an MCP (Model Context Protocol) server for WeChat iLink Bot integration at `/weixin`:

- QR code login flow
- Message polling, sending, and auto-reply via internal LLM proxy
- Message persistence to database
- Per-user context threading for conversations
- See [docs/guides/weixin-mcp.md](docs/guides/weixin-mcp.md) for setup instructions

## Request Logging

`request_logs` stores: API key, provider, model, tokens, latency, status, upstream/downstream HTTP status codes, client IP, user agent, and error details.

Streaming requests are inserted as `pending` first, then updated to `success`, `error`, `timeout`, or `cancelled`.

Logs older than 30 days are automatically archived to `request_logs_history`. A `request_logs_all` view unions both tables for transparent querying.

## Concurrency Control

Three-layer semaphore-based rate control:

1. **API key model limit** — per (api_key, model) concurrency cap
2. **Provider key limit** — per provider key with configurable max_concurrent
3. **System-level limit** — global concurrency with `local_rate_limited` rejection when exceeded

Provider keys support sticky routing (requests from the same API key route to the same provider key).

## Provider Auto-Disable & Reenable

- When a usage limit error is detected (quota exceeded, billing deactivated, etc.), the provider or provider key is automatically disabled with a reason
- Disabled state is shown in admin dashboard with warning icons and error details returned to the client
- A scheduled task reenables all disabled providers and keys every 5 minutes
- Manual reset available in admin config page

## Scheduled Tasks

| Task | Schedule | Description |
|------|----------|-------------|
| Auto-reenable | Every 5 minutes | Reenable disabled provider keys and providers |
| Timeout cleanup | Every 10 minutes | Mark stale pending requests (>10 min) as `timeout` |
| Daily aggregation | 00:05 | Aggregate request counts into daily/hourly stats tables |
| MCP stats aggregation | 00:10 | Aggregate MCP tool usage stats |
| Log archival | 00:20 | Archive request logs older than 30 days |
| Recommendation analysis | 08:00 | Daily AI-powered model recommendation analysis |

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
│   ├── keys.py              # API key CRUD + per-key stats/logs + time rules
│   ├── stats.py             # Statistics, aggregation, live WebSocket
│   ├── logs.py              # Log viewer + AI error analysis
│   ├── pages.py             # Admin HTML pages
│   ├── user.py              # User portal API + pages
│   ├── opencode.py          # OpenCode config generation
│   ├── reports.py           # Usage report generation + DOCX export
│   ├── system_config.py     # System config (outbound UA management)
│   ├── mcp.py               # MCP server CRUD endpoints
│   └── weixin.py            # WeChat MCP server endpoints
├── services/
│   ├── proxy.py             # Main proxy logic, streaming, provider dispatch
│   ├── proxy_runtime/       # Runtime helpers: SSE, MiniMax, message preprocessing
│   ├── auth.py              # API key validation + time-based access rules
│   ├── provider.py          # Provider/model resolution, sticky routing
│   ├── provider_limiter.py  # Provider/key disable, reenable, usage limit detection
│   ├── scheduler.py         # APScheduler tasks
│   ├── stats_aggregator.py  # Daily stats aggregation, archiving
│   ├── logging.py           # Request log CRUD
│   ├── tokens.py            # Token estimation and response parsing
│   ├── message.py           # Message preprocessing (merge, truncate)
│   ├── minimax.py           # MiniMax-specific response/tool_call parsing
│   ├── sse.py               # SSE stream normalization
│   ├── analysis_store.py    # AI analysis task persistence
│   ├── usage_report.py      # DOCX usage report generation
│   ├── system_config.py     # Outbound UA auto-detection
│   ├── mcp.py               # MCP server pool, tool sync, proxy
│   └── weixin.py            # WeChat iLink Bot client
├── templates/               # Jinja2 HTML (admin/, user/, public/, components/)
├── nginx/                   # nginx.conf for Docker reverse proxy
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
