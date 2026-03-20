# API Proxy

A FastAPI-based proxy server for LLM API requests with provider management, API key control, and usage monitoring.

## Features

- **Multi-Provider Support**: Zhipu, DeepSeek, Ollama, Minimax, and any OpenAI-compatible API
- **Rate Limiting**: Per-provider concurrency control via semaphores
- **API Key Management**: Per-key model access control
- **Streaming Support**: Real-time streaming responses with token estimation
- **Web Dashboard**: Monitor usage, manage providers, models, and API keys
- **User Portal**: API key holders can view their own usage statistics
- **OpenCode Config**: Generate `opencode.json` configuration for AI coding assistants

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python main.py

# Server: http://localhost:8765
# Dashboard: http://localhost:8765/home
```

Windows: Use `start.bat` (auto-kills existing process on port 8765)

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | postgresql+asyncpg://... | PostgreSQL connection string |
| `PORT` | 8765 | Server port |
| `ADMIN_PASSWORD` | admin123 | Dashboard login password |

### Database Migration

```sql
-- Add max_concurrent column if not exists
ALTER TABLE providers ADD COLUMN IF NOT EXISTS max_concurrent INTEGER DEFAULT 3;
```

## API Endpoints

### Proxy
- `POST /v1/chat/completions` - Chat completions (OpenAI compatible)
- `POST /v1/embeddings` - Embeddings
- `GET /v1/models` - List available models

### Model Format
Use `provider/model` format to specify provider:
```
zhipu/glm-4      # Routes to Zhipu provider
deepseek/chat    # Routes to DeepSeek provider
glm-4            # Uses default provider
```

## Dashboard

Access the admin dashboard at `/home` after login:

- **Home**: Overview with charts and statistics
- **Config**: Manage providers and models
- **API Keys**: Create and manage API keys with model restrictions
- **Monitor**: Real-time request logs
- **OpenCode Config**: Generate configuration for AI coding assistants
- **Usage Guide**: How to configure clients

## User Portal

API key holders can access their usage at `/user/login`:
- View request statistics
- See token consumption
- Monitor model usage
- View usage trends with charts

### Remember API Key
The user portal supports remembering API keys via `localStorage`:
- Check "Remember API Key" when logging in
- Next visit will auto-login with saved key
- Logout with option to clear saved key

## Rate Limiting

Each provider has a `max_concurrent` setting (default: 3):
- Requests acquire a semaphore slot before proxying
- When limit reached, returns HTTP 429 error
- Non-streaming: release after response
- Streaming: release when stream completes (in `finally` block)

## Project Structure

```
api-proxy/
├── main.py              # FastAPI app, exception handlers
├── config.py            # Global state, caches, logging
├── database.py          # SQLAlchemy models
├── deps.py              # FastAPI dependencies
├── routes/              # API endpoints
│   ├── proxy.py         # /v1/chat/completions, /v1/models
│   ├── providers.py     # Provider CRUD
│   ├── models.py        # Model CRUD
│   ├── keys.py          # API Key CRUD
│   ├── stats.py         # Statistics endpoints
│   ├── logs.py          # Request log queries
│   ├── user.py          # User portal
│   └── opencode.py      # OpenCode config generator
├── services/            # Business logic
│   ├── proxy.py         # Core proxy, streaming, rate limiting
│   └── stats_aggregator.py
├── templates/           # HTML templates
└── logs/api.log         # Rotating log file
```

## Development

```bash
# Linting
ruff check .
ruff format .

# Type checking
mypy main.py database.py config.py --ignore-missing-imports
```

## Docker

```bash
docker-compose up -d

# Or directly
docker run -d -p 8765:8765 \
  -e DATABASE_URL=postgresql+asyncpg://user:pass@host/db \
  -e ADMIN_PASSWORD=your_password \
  api-proxy
```

## License

MIT
