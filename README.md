# ModelGate

<p align="center">
  <img src="assets/favicon.svg" alt="ModelGate logo" width="96" height="96">
</p>

ModelGate is a FastAPI-based LLM gateway for provider routing, API key control, and usage monitoring.

Repository / image compatibility notes:

- Repository directory: `modelgate/`
- Docker image tag: `modelgate`
- Product name / dashboard name: `ModelGate`

## Features

- **Multi-Provider Support**: Zhipu, DeepSeek, Ollama, Minimax, and any OpenAI-compatible API
- **Rate Limiting**: Per-provider concurrency control via semaphores
- **API Key Management**: Per-key model access control
- **Streaming Support**: Real-time streaming responses with token estimation and SSE normalization
- **Web Dashboard**: Monitor usage, manage providers, models, and API keys (admin + mobile)
- **User Portal**: API key holders can view their own usage statistics
- **OpenCode Config**: Generate configuration for AI coding assistants
- **Real-time Stats**: 10-second sliding window for requests/token rates
- **Request Logging**: Pending status for streaming, timeout detection for stale requests
- **i18n Support**: English/Chinese bilingual UI with Jinja2 + Babel
 language switcher
- **Dark Mode**: Admin dashboard dark/light theme toggle
- **Thinking Model Config**: Per-model thinking settings with configurable budget tokens
- **Modular Architecture**: Services split into provider, auth, logging, tokens, message, sse, minimax
 streaming
- **Mobile Responsive**: Separate mobile admin dashboard with auto-redirect

- **Usage Guide**: Built-in API client configuration guide (ChatGPT-Next-Web, Python, cURL, VS Code)



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
| `LOG_LEVEL` | No | Log level: DEBUG, INFO (default), WARNING, ERROR |

### Database Setup

```sql
CREATE USER "modelgate" WITH PASSWORD 'your_password';
CREATE DATABASE "modelgate" OWNER "modelgate";
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

Access the ModelGate admin dashboard at `/admin/home` after login:

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
modelgate/
├── main.py                  # FastAPI app, exception handlers
├── core/
│   ├── config.py            # Global state, caches, logging
│   ├── database.py          # SQLAlchemy models
│   └── i18n.py              # Jinja2 + Babel i18n renderer
├── routes/                  # API endpoints
│   ├── proxy.py             # /v1/chat/completions proxy handler
│   ├── pages.py             # Admin/user page routes
│   ├── providers.py         # Provider CRUD
│   ├── keys.py              # API Key CRUD
│   ├── stats.py             # Statistics endpoints
│   ├── logs.py              # Request log queries
│   ├── user.py              # User portal APIs
│   └── opencode.py          # OpenCode config generator
├── services/                # Business logic
│   ├── proxy.py             # Core proxy orchestration
│   ├── provider.py          # Provider loading & config
│   ├── auth.py              # API key validation
│   ├── logging.py           # Request logging
│   ├── tokens.py            # Token estimation & tracking
│   ├── message.py           # Message preprocessing
│   ├── minimax.py            # Minimax streaming processor
│   └── sse.py                # SSE stream normalization
├── templates/               # Jinja2 HTML templates
│   ├── admin/                # Admin dashboard pages
│   ├── user/                # User portal pages
│   ├── public/              # Public pages (opencode, query)
│   └── components/          # Shared nav, language switcher
├── locales/                 # Translation files
│   ├── en/LC_MESSAGES/      # English translations
│   └── zh/LC_MESSAGES/      # Chinese translations
└── logs/                    # Rotating log files
```

## Docker Deployment

```bash
# Build and push to local registry
docker build -t localhost:5002/modelgate:latest .
docker push localhost:5002/modelgate:latest

# Run on production server
docker pull <REGISTRY_IP>:5005/modelgate:latest
docker run -d --name modelgate \
  -p 8765:8765 \
  -e DATABASE_URL="postgresql+asyncpg://modelgate:password@host:5432/modelgate" \
  -e PORT=8765 \
  -e ADMIN_USERS="admin:YourPassword" \
  -v /opt/modelgate/logs:/app/logs \
  --restart unless-stopped \
  <REGISTRY_IP>:5005/modelgate:latest
```

## License

Apache 2.0
