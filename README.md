# API Proxy

A FastAPI-based proxy server for LLM API requests with provider management, API key control, and usage monitoring.

## Features

- **Multi-Provider Support**: Zhipu, DeepSeek, Ollama, Minimax, and any OpenAI-compatible API
- **Rate Limiting**: Per-provider concurrency control via semaphores
- **API Key Management**: Per-key model access control
- **Streaming Support**: Real-time streaming responses with token estimation
- **Web Dashboard**: Monitor usage, manage providers, models, and API keys
- **User Portal**: API key holders can view their own usage statistics
- **OpenCode Config**: Generate configuration for AI coding assistants
- **Real-time Stats**: 10-second sliding window for requests/tokens per second
- **Request Logging**: Pending status for streaming, timeout detection for stale requests

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python main.py

# Server: http://localhost:8765
# Dashboard: http://localhost:8765/admin/home
```

Windows: Use `start.bat` (auto-kills existing process on port 8765)

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `PORT` | No | Server port (default: 8765) |
| `ADMIN_USERS` | Yes | Admin accounts, format: `user:pass,user:pass` |

### Database Setup

```sql
CREATE USER "api-proxy" WITH PASSWORD 'your_password';
CREATE DATABASE "api-proxy" OWNER "api-proxy";
```

See `schema.sql` for full schema.

## API Endpoints

### Proxy (OpenAI Compatible)

- `POST /v1/chat/completions` - Chat completions
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

Access the admin dashboard at `/admin/home` after login:

- **Home**: Overview with charts and real-time statistics
- **Config**: Manage providers and models
- **API Keys**: Create and manage API keys with model restrictions
- **Monitor**: Real-time request logs, slow request detection

## User Portal

API key holders can access their usage at `/user/login`:

- View request statistics
- See token consumption
- Monitor model usage
- Get OpenCode configuration

## Rate Limiting

Each provider has a `max_concurrent` setting (default: 3):

- Requests acquire a semaphore slot before proxying
- When limit reached, returns HTTP 429 error
- Non-streaming: release after response
- Streaming: release when stream completes

## Project Structure

```
api-proxy/
├── main.py                  # FastAPI app, exception handlers
├── core/                    # Core modules
│   ├── config.py            # Global state, caches, logging
│   ├── database.py          # SQLAlchemy models
│   └── deps.py              # FastAPI dependencies
├── routes/                  # API endpoints
│   ├── proxy.py             # /v1/chat/completions, /v1/models
│   ├── providers.py         # Provider CRUD
│   ├── keys.py              # API Key CRUD
│   ├── stats.py             # Statistics endpoints
│   ├── logs.py              # Request log queries
│   ├── user.py              # User portal
│   └── opencode.py          # OpenCode config generator
├── services/                # Business logic
│   ├── proxy.py             # Core proxy, streaming, rate limiting
│   ├── scheduler.py         # Scheduled jobs
│   └── stats_aggregator.py  # Stats aggregation
├── templates/               # HTML templates
│   ├── admin/               # Admin dashboard pages
│   ├── user/                # User portal pages
│   └── public/              # Public pages
└── logs/                    # Rotating log files
```

## Docker Deployment

```bash
# Build and push to local registry
docker build -t localhost:5002/api-proxy:latest .
docker push localhost:5002/api-proxy:latest

# Run on production server
docker pull <REGISTRY_IP>:5005/api-proxy:latest
docker run -d --name api-proxy \
  -p 8765:8765 \
  -e DATABASE_URL="postgresql+asyncpg://api-proxy:password@host:5432/api-proxy" \
  -e PORT=8765 \
  -e ADMIN_USERS="admin:YourPassword" \
  -v /opt/api-proxy/logs:/app/logs \
  --restart unless-stopped \
  <REGISTRY_IP>:5005/api-proxy:latest
```

## License

Apache 2.0
