# ModelGate 部署指南

## 环境要求

- Docker
- PostgreSQL 14+
- 本地镜像仓库

---

## 部署流程

### 1. 本地构建并推送镜像

```bash
docker build -t localhost:5002/modelgate:latest .
docker push localhost:5002/modelgate:latest
```

### 2. 生产服务器拉取并启动

```bash
docker pull <REGISTRY_IP>:5005/modelgate:latest
docker stop modelgate && docker rm modelgate
docker run -d --name modelgate \
  -p 8765:8765 \
  -e DATABASE_URL="postgresql+asyncpg://modelgate:password@host:5432/modelgate" \
  -e PORT=8765 \
  -e ADMIN_USERS="admin:YourPassword" \
  -v /opt/modelgate/logs:/app/logs \
  --restart unless-stopped \
  <REGISTRY_IP>:5005/modelgate:latest
```

### 3. 验证

```bash
docker logs -f modelgate
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
CREATE USER "modelgate" WITH PASSWORD 'your_password';
CREATE DATABASE "modelgate" OWNER "modelgate";
```

---

## 运维命令

```bash
docker logs -f modelgate      # 查看日志
docker restart modelgate      # 重启服务
docker stats modelgate        # 资源占用
```
