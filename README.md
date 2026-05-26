# ModelGate

<p align="center">
  <img src="assets/favicon.svg" alt="ModelGate logo" width="96" height="96">
</p>

ModelGate is a FastAPI-based LLM gateway for multi-provider routing, API key management, request logging, and dashboard monitoring. Designed for teams and organizations to centrally manage and distribute AI model access across departments.

## Highlights

- Multi-provider routing: Zhipu, DeepSeek, Ollama, Minimax, and any OpenAI-compatible API
- OpenAI-compatible proxy endpoints: `/v1/chat/completions`, `/v1/embeddings`, `/v1/models`
- Anthropic-compatible proxy endpoint: `/anthropic/v1/messages` with full protocol translation (streaming, tool calls, thinking, cache_control)
- Model alias routing: call models by alias (e.g. `gpt-4o`) without provider prefix, auto-select best provider by health + intent + priority
- Intent classification: auto-classify requests as coding/writing/testing/design/chat based on message content, used for smart routing and log analytics
- Provider key health scoring: sliding-window (5 min) health score (0–100), prioritize healthy keys in routing
- Provider key priority: manual priority per key for ordered fallback, sorted by (priority DESC, health DESC)
- Layered concurrency control: API key model limit -> provider key limit with per-key semaphore
- Provider multi-key support with sticky routing and key-level disable/reenable
- Provider key fallback: automatically tries the next API key on 401/403/429 errors
- Auto-disable provider/key on usage limit errors, auto-reenable on scheduled task
- API key management with per-key model access control and bypass_busyness option
- Request content logging: separate `request_contents` table for messages, response, thinking, tool_calls — lazy-loaded via Content button
- Streaming request lifecycle tracking: `pending` -> `success` / `error` / `timeout`
- Upstream and downstream status code logging
- Model tags: assign tags to models (e.g. coding, reasoning, vision) for filtering and intent-based routing
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
docker build -t your-registry:5002/modelgate:latest .
docker push your-registry:5002/modelgate:latest

docker run -d --name modelgate \
  -p 8765:8765 \
  -e DATABASE_URL="postgresql+asyncpg://modelgate:password@host:5432/modelgate" \
  -e PORT=8765 \
  -e ADMIN_USERS="admin:YourPassword" \
  -v /opt/modelgate/logs:/app/logs \
  -v /opt/modelgate/reports:/app/reports \
  -v /opt/modelgate/uploads:/app/uploads/documents \
  --restart unless-stopped \
  your-registry:5002/modelgate:latest
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

### Anthropic-compatible Endpoint

- `POST /anthropic/v1/messages` - Anthropic Messages API (streaming and non-streaming)

ModelGate translates Anthropic protocol requests to OpenAI format for upstream providers, and translates responses back. Supported features:

- Streaming and non-streaming responses
- Tool use (function calling) with parallel tool call control
- Extended thinking with signature passthrough
- Cache control (`cache_control` markers on system, user, assistant, and tool_result blocks)
- System prompt as structured content blocks
- `inbound_protocol` tracking in request logs for protocol-level analytics

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

`request_logs` stores: API key, provider, model, tokens, latency, status, upstream/downstream HTTP status codes, client IP, user agent, intent, requested_model, actual_model, provider_key_label, and error details.

Streaming requests are inserted as `pending` first, then updated to `success`, `error`, `timeout`, or `cancelled`.

Logs older than 30 days are automatically archived to `request_logs_history`. A `request_logs_all` view unions both tables for transparent querying.

### Request Content (Separate Storage)

Request messages, response text, thinking/reasoning, and tool calls are stored in a separate `request_contents` table, keeping `request_logs` lean for fast list queries.

- **Lazy loading**: click the "Content" button in the log viewer to fetch via `GET /admin/api/logs/{id}/content`
- **Cascade delete**: content rows are automatically removed when the parent log is archived or deleted

## Concurrency Control

Three-layer semaphore-based rate control:

1. **API key model limit** — per (api_key, model) concurrency cap, adjustable by busyness level; `bypass_busyness` API keys bypass both busyness rules and user concurrency limits
2. **Provider key limit** — per provider key with configurable max_concurrent
3. **System-level limit** — global concurrency with `local_rate_limited` rejection when exceeded

Provider keys support sticky routing (requests from the same API key route to the same provider key).

## Key Health Scoring

Each provider key has a real-time health score (0–100) based on a 5-minute sliding window:

| Event | Score Impact |
|-------|-------------|
| Key disabled (invalid / quota exceeded) | Set to 0 |
| 429/529 rate limited | -15 per event |
| 5xx server error | -10 per event |
| 4xx client error (non-429) | -5 per event |
| Successful request | +5 per 10 successes |

Health levels: Excellent (90–100, green) / Good (60–89, blue) / Warning (30–59, yellow) / Critical (1–29, orange) / Unavailable (0, red).

Keys are sorted by health score in `pick_api_keys`, so healthier keys are used first.

## Key Priority

Provider keys support manual priority (`priority` field, default 0). `pick_api_keys` sorts by `(priority DESC, health DESC)`, enabling ordered key fallback (e.g. always try Key A first, then Key B).

## Model Alias Routing

Models can be called by alias instead of `provider/model`:

```text
# Explicit: route to a specific provider
zhipu/glm-5

# Alias: auto-select best provider by health + intent + priority
gpt-4o
```

When an alias matches multiple providers, the routing sorts candidates by `(tag_match DESC, health DESC, priority DESC)`:

1. **tag_match**: if the model's tags include the request's intent → 1, else → 0
2. **health**: provider key health score
3. **priority**: manual priority on the provider-model binding

## Intent Classification

Requests are auto-classified by message content into one of five intents:

| Intent | Description | Badge Color |
|--------|-------------|-------------|
| `coding` | Programming, debugging, code review | Blue |
| `writing` | Documentation, translation, editing | Amber |
| `testing` | Unit tests, QA, validation | Rose |
| `design` | UI/UX, wireframes, design systems | Purple |
| `chat` | General conversation (default) | Gray |

Classification uses keyword matching (no LLM call), with `system_hint` weighted 3× higher than user/assistant keywords. The intent is stored in `request_logs.intent` and displayed as a colored badge in the log viewer.

## Model Tags

Models can be assigned tags (comma-separated) for filtering and intent-based routing:

- Tags like `coding`, `reasoning`, `vision`, `flash` indicate model strengths
- Tags are matched against the request intent for smart alias routing
- Displayed as badges in admin config and user portal

## Provider Key Fallback

When a provider has multiple API keys configured, ModelGate automatically falls back to the next key if the current one fails:

- **Retryable errors**: HTTP 401 (authentication), 403 (forbidden), 429 (rate limit), 529 (overloaded)
- Keys are shuffled on each request for even distribution
- Sticky routing takes priority — if a sticky key is available, only that key is used
- Concurrency-limited keys are skipped with a warning, trying the next available key
- Fallback attempts are logged with `[KEY FALLBACK]` prefix

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
│   ├── anthropic_proxy.py   # /anthropic/v1/messages — Anthropic protocol proxy
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
│   ├── proxy.py             # Main proxy logic, streaming, provider dispatch, key fallback
│   ├── proxy_runtime/       # Runtime helpers: SSE, MiniMax, message preprocessing
│   ├── anthropic_inbound.py # Anthropic↔OpenAI protocol translation (request & response)
│   ├── auth.py              # API key validation + time-based access rules
│   ├── provider.py          # Provider/model resolution, alias routing, sticky routing
│   ├── provider_limiter.py  # Provider/key disable, reenable, usage limit detection
│   ├── key_health.py        # Sliding-window key health scoring (0-100)
│   ├── intent_classifier.py # Keyword-based intent classification (coding/writing/testing/design/chat)
│   ├── scheduler.py         # APScheduler tasks
│   ├── stats_aggregator.py  # Daily stats aggregation, archiving
│   ├── logging.py           # Request log CRUD + request content (separate storage)
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

## Commercial Support

For production-grade cluster deployment, custom integration, or tailored feature development, contact:

**minhaozhang@henngtiansoft.com**

## License

Apache 2.0
