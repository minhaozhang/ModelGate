# API Proxy 生产部署指南

## 环境要求

- Docker & Docker Compose
- PostgreSQL 14+ 数据库
- 2GB+ RAM
- Linux 服务器（Ubuntu 20.04+ 推荐）

---

## 离线部署（推荐）

如果服务器无法拉取镜像，使用离线部署方式：

### 1. 本地导出镜像

```bash
# 在有网络的机器上执行
docker save -o api-proxy.tar api-proxy:latest

# 同时导出依赖镜像（如有需要）
docker save -o python-3.12-slim.tar python:3.12-slim
```

### 2. 上传文件到服务器

通过 scp、U盘等方式上传：
- `api-proxy.tar`
- `docker-compose.yml`
- `.env`

```bash
# scp 方式示例
scp api-proxy.tar user@server:/opt/api-proxy/
scp docker-compose.yml user@server:/opt/api-proxy/
scp .env user@server:/opt/api-proxy/
```

### 3. 服务器导入镜像

```bash
cd /opt/api-proxy

# 导入镜像
docker load -i api-proxy.tar

# 确认导入成功
docker images | grep api-proxy
```

### 4. 启动服务

```bash
docker-compose up -d
```

---

## 在线部署

### 1. 准备服务器

```bash
# 安装 Docker
curl -fsSL https://get.docker.com | sh

# 安装 Docker Compose
apt install docker-compose -y
```

### 2. 创建目录

```bash
mkdir -p /opt/api-proxy
cd /opt/api-proxy
```

### 3. 上传文件

将以下文件上传到服务器：
- `docker-compose.yml`
- `.env` (配置文件)
- 或手动创建配置

### 4. 配置文件

创建 `.env` 文件：

```bash
cat > .env << EOF
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/database
PORT=8765
ADMIN_PASSWORD=YourStrongPassword123!
PUBLIC_URL=https://your-domain.com
EOF
```

### 5. 启动服务

```bash
docker-compose up -d
```

---

## 配置说明

### 环境变量

| 变量 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `DATABASE_URL` | 是 | PostgreSQL 连接串 | `postgresql+asyncpg://user:pass@host:5432/db` |
| `PORT` | 否 | 服务端口，默认 8765 | `8765` |
| `ADMIN_PASSWORD` | 是 | 管理后台密码 | `ZxcvbnmZaq1#)` |
| `PUBLIC_URL` | 否 | 公开访问 URL | `https://api.example.com` |

### PostgreSQL 数据库初始化

```sql
-- 创建数据库和用户
CREATE USER "api-proxy" WITH PASSWORD 'your_password';
CREATE DATABASE "api-proxy" OWNER "api-proxy";

-- 连接到数据库执行
\c api-proxy

-- 创建扩展（如果需要）
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

---

## Docker Compose 配置

### 生产环境 docker-compose.yml

```yaml
services:
  api-proxy:
    image: api-proxy:latest
    container_name: api-proxy
    ports:
      - "8765:8765"
    environment:
      - DATABASE_URL=postgresql+asyncpg://user:password@host:5432/database
      - PORT=8765
      - ADMIN_PASSWORD=YourStrongPassword123!
      - PUBLIC_URL=https://your-domain.com
    volumes:
      - ./logs:/app/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8765/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

---

## Nginx 反向代理配置（可选）

如果需要域名访问和 SSL：

```nginx
server {
    listen 80;
    server_name api.example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate /etc/ssl/certs/cert.pem;
    ssl_certificate_key /etc/ssl/private/key.pem;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

---

## 运维命令

```bash
# 查看日志
docker-compose logs -f

# 查看状态
docker-compose ps

# 重启服务
docker-compose restart

# 停止服务
docker-compose down

# 更新部署
docker-compose pull
docker-compose up -d

# 进入容器
docker exec -it api-proxy /bin/bash
```

---

## 数据备份

```bash
# 备份数据库
pg_dump -h host -U user -d database > backup_$(date +%Y%m%d).sql

# 备份配置
cp .env .env.bak
```

---

## 故障排查

### 服务无法启动
```bash
docker-compose logs api-proxy
```

### 数据库连接失败
```bash
# 检查数据库是否运行
pg_isready -h host -p 5432

# 测试连接
psql "postgresql://user:pass@host:5432/database"
```

### 端口被占用
```bash
# 查找占用进程
lsof -i :8765

# 或
netstat -tlnp | grep 8765
```

---

## 安全建议

1. **修改默认密码** - 首次部署务必修改 `ADMIN_PASSWORD`
2. **启用 SSL** - 生产环境必须使用 HTTPS
3. **限制数据库访问** - 配置 pg_hba.conf 限制 IP 访问
4. **定期备份** - 设置 cron 任务自动备份数据库
5. **日志监控** - 监控日志目录磁盘使用

---

## 更新日志

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2026-03-21 | 初始版本 |

---

## 联系支持

如有问题，请检查日志或提交 Issue。
