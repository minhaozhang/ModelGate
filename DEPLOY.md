# API Proxy 部署指南

## 环境要求

- Docker
- PostgreSQL 14+
- 本地镜像仓库（如 localhost:5000）

---

## 部署流程

### 1. 本地构建并推送镜像

```bash
# 构建镜像
docker build -t localhost:5000/api-proxy:latest .

# 推送到本地镜像仓库
docker push localhost:5000/api-proxy:latest
```

### 2. 生产服务器拉取并启动

```bash
# 拉取镜像
docker pull <REGISTRY_IP>:5000/api-proxy:latest

# 停止并删除旧容器
docker stop api-proxy && docker rm api-proxy

# 启动新容器
docker run -d --name api-proxy \
  -p 8765:8765 \
  -e DATABASE_URL="postgresql+asyncpg://api-proxy:password@host:5432/api-proxy" \
  -e PORT=8765 \
  -e ADMIN_PASSWORD="YourPassword" \
  -v /opt/api-proxy/logs:/app/logs \
  --restart unless-stopped \
  <REGISTRY_IP>:5000/api-proxy:latest
```

### 3. 验证部署

```bash
# 查看容器状态
docker ps | grep api-proxy

# 查看日志
docker logs -f api-proxy

# 健康检查
curl http://localhost:8765/v1/models
```

---

## 环境变量

| 变量 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `DATABASE_URL` | 是 | PostgreSQL 连接串 | `postgresql+asyncpg://user:pass@host:5432/db` |
| `PORT` | 否 | 服务端口，默认 8765 | `8765` |
| `ADMIN_PASSWORD` | 是 | 管理后台密码 | `ZxcvbnmZaq1#)` |

---

## 数据库初始化

```sql
CREATE USER "api-proxy" WITH PASSWORD 'your_password';
CREATE DATABASE "api-proxy" OWNER "api-proxy";
```

---

## 运维命令

```bash
# 查看日志
docker logs -f api-proxy

# 重启服务
docker restart api-proxy

# 进入容器
docker exec -it api-proxy /bin/bash

# 查看资源占用
docker stats api-proxy
```

---

## Nginx 反向代理（可选）

```nginx
server {
    listen 80;
    server_name api.example.com;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }
}
```
