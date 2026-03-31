# ModelGate

<p align="center">
  <img src="assets/favicon.svg" alt="ModelGate logo" width="96" height="96">
</p>

ModelGate is a FastAPI-based LLM gateway for provider routing, API key control, request logging, and dashboard monitoring.

## Highlights

- Multi-provider routing for Zhipu, DeepSeek, Ollama, Minimax, and OpenAI-compatible APIs
- OpenAI-compatible proxy endpoints such as `/v1/chat/completions` and `/v1/models`
- Per-provider concurrency limits with semaphore-based rate control
- API key management with per-key model access rules
- Streaming request tracking with `pending`, `success`, `error`, and `timeout` states
- Upstream status code logging for provider responses such as `200`, `429`, and `500`
- Admin dashboards for operations, monitoring, API key management, and usage guidance
- User dashboard with recommendations, system health score, trend charts, and model usage stats
- English / Chinese i18n support
- Desktop and mobile admin experiences

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

Windows helper:

- `start.bat` will prompt for log level and restart the service on port `8765`

## Docker

Build and push to the local registry used in this project:

```bash
docker build -t localhost:5002/modelgate:latest .
docker push localhost:5002/modelgate:latest
```

Run a container:

```bash
docker run -d --name modelgate \
  -p 8765:8765 \
  -e DATABASE_URL="postgresql+asyncpg://modelgate:password@host:5432/modelgate" \
  -e PORT=8765 \
  -e ADMIN_USERS="admin:YourPassword" \
  -v /opt/modelgate/logs:/app/logs \
  --restart unless-stopped \
  localhost:5002/modelgate:latest
```

More deployment details are in [DEPLOY.md](DEPLOY.md).

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `PORT` | No | Service port, default `8765` |
| `ADMIN_USERS` | Recommended | Admin accounts in `user:pass,user:pass` format |
| `ADMIN_USERNAME` | Optional | Fallback admin username when `ADMIN_USERS` is not set |
| `ADMIN_PASSWORD` | Optional | Fallback admin password when `ADMIN_USERS` is not set |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## Database

Bootstrap example:

```sql
CREATE USER "modelgate" WITH PASSWORD 'your_password';
CREATE DATABASE "modelgate" OWNER "modelgate";
```

Schema file:

- [`schema.sql`](schema.sql)

The app also performs some runtime compatibility migrations during startup, such as adding newly introduced columns to `request_logs`.

## API

### OpenAI-compatible endpoints

- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `GET /v1/models`

### Model naming

Preferred format:

```text
provider/model
```

Examples:

```text
zhipu/glm-4
deepseek/chat
minimax/MiniMax-M2.5
```

## Dashboards

### Admin

After login, the main admin pages are:

- `/admin/home`: overview, realtime stats, slow requests, trends
- `/admin/config`: providers, models, bindings
- `/admin/api-keys`: key management and model access assignment
- `/admin/monitor`: composition, hotspots, response-time analysis
- `/admin/usage`: client configuration examples

### User

API key holders can log in at `/user/login` and access:

- Personal request and token statistics
- Model recommendation chips
- 20-minute system health score
- Active session visibility
- Request trends and model usage
- OpenCode configuration output

## Request Logging

`request_logs` stores operational data such as:

- API key, provider, model
- tokens and latency
- normalized request status
- upstream provider HTTP status code
- error details for failed requests

Streaming requests are inserted as `pending` first and updated when they complete, fail, or time out.

## Project Structure

```text
modelgate/
├── main.py
├── core/
├── routes/
├── services/
├── templates/
├── locales/
├── image/
├── assets/
├── schema.sql
├── Dockerfile
└── DEPLOY.md
```

## Development Notes

- Python 3.10+ style codebase
- FastAPI + SQLAlchemy async + PostgreSQL
- Babel is used for locale compilation
- Logs are written to `logs/proxy.log`, `logs/admin.log`, and `logs/error.log`

## License

Apache 2.0
