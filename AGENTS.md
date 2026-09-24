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
