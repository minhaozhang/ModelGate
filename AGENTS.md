# AGENTS.md

## Production Environment

- URL: https://leturx.cc/
- API base: https://leturx.cc/modelgate
- Admin: https://leturx.cc/modelgate/admin/home
- Models endpoint: https://leturx.cc/modelgate/v1/models

## Docker Build & Release

- Release flow: dev commit -> `git checkout master; git merge --ff-only dev` -> push origin(gitee)+atomgit -> `docker build -t 10.100.2.148:5002/modelgate:latest .` -> `docker push` -> back to dev.
- Docker Hub (docker.io) is NOT reachable directly from this machine. Never `docker pull python:...` from docker.io and don't bother with mirror accelerators.
- Local image cache matters: builds normally hit cached layers only (apt/pip layers unchanged between releases because requirements rarely change). `python:3.12-slim` exists locally, retagged from the internal registry:
  ```
  docker pull 10.100.2.148:5002/python:3.12-slim
  docker tag 10.100.2.148:5002/python:3.12-slim python:3.12-slim
  ```
  Do NOT prune local images / buildkit cache casually — losing it means re-downloading apt+pip over slow default sources (~20min+ timeout risk).
- If build cache was wiped: temporarily swap Dockerfile apt sources to `mirrors.aliyun.com` and pip to `-i https://mirrors.aliyun.com/pypi/simple/`, build, then revert the Dockerfile (do not commit the mirror changes). With mirrors apt ~115s, pip ~86s.
- Registry HTTP API (`/v2/_catalog`, `/v2/*/tags/list`) returns 401, but `docker pull/push 10.100.2.148:5002/...` works (credentials in Docker credential store).
- SSH to 10.100.2.148: public key NOT authorized (password-only login historically); agent cannot SSH non-interactively.

## Local Dev Instance & Process Safety (CRITICAL)

- This machine runs OTHER python services (quant_platform arq/scheduler/bot/ml-trading, etc.).
- **NEVER** `Stop-Process -Name python` / `taskkill /F /IM python.exe` / any image-name kill — it wipes the whole python stack on this machine, including unrelated projects.
- To restart the local ModelGate dev instance (port 8765): `powershell -File scripts\dev_restart.ps1` (PID-file + port-listener based, verifies the process command line contains `app.main` before killing). Add `-StopOnly` to just stop it.
- Alternative for release-verification: run in docker (`docker run -d --name mg-local -p 8765:8765 -e DATABASE_URL=... 10.100.2.148:5002/modelgate:latest`) — zero host-process impact.
- Local repro DB: `postgresql+asyncpg://postgres:Zaq1%403edc@10.100.2.148:5432/modelgate_repro`; admin `admin/repro123456`; user key `mg-repro-key-0001`.
- pytest baseline: 13 failed (pre-existing) / 582 passed. Run: `$env:DATABASE_URL='...modelgate_repro'; python -m pytest tests/ -q --tb=no`.
- PowerShell quirk: `Stop-Process` + `Start-Process` in ONE command sometimes errors with "Unknown: ChildProcess.kill" while still taking effect — run them as separate tool calls.
