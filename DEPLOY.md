# API Proxy 部署指南

## 环境要求

- Docker
- PostgreSQL 14+
- 本地镜像仓库

---

## 部署流程

### 1. 本地构建并推送镜像

```bash
docker build -t localhost:5002/api-proxy:latest .
docker push localhost:5002/api-proxy:latest
```

### 2. 生产服务器拉取并启动

```bash
docker pull <REGISTRY_IP>:5005/api-proxy:latest
docker stop api-proxy && docker rm api-proxy
docker run -d --name api-proxy \
  -p 8765:8765 \
  -e DATABASE_URL="postgresql+asyncpg://api-proxy:password@host:5432/api-proxy" \
  -e PORT=8765 \
  -e ADMIN_USERS="admin:YourPassword" \
  -v /opt/api-proxy/logs:/app/logs \
  --restart unless-stopped \
  <REGISTRY_IP>:5005/api-proxy:latest
```

### 3. 验证

```bash
docker logs -f api-proxy
curl http://localhost:8765/v1/models
```

---

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `DATABASE_URL` | 是 | PostgreSQL 连接串 |
| `PORT` | 否 | 服务端口，默认 8765 |
| `ADMIN_USERS` | 是 | 管理员账户，格式: user:pass,user:pass |

---

## 数据库初始化

```sql
CREATE USER "api-proxy" WITH PASSWORD 'your_password';
CREATE DATABASE "api-proxy" OWNER "api-proxy";
```

---

## 运维命令

```bash
docker logs -f api-proxy      # 查看日志
docker restart api-proxy      # 重启服务
docker stats api-proxy        # 资源占用
```
