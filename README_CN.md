# API Proxy

基于 FastAPI 的 LLM API 代理服务器，支持多提供商管理、API Key 控制、用量监控和 Web 管理面板。

## 功能特性

- **多提供商支持**：智谱、DeepSeek、Ollama、Minimax 及任意 OpenAI 兼容 API
- **并发限流**：基于信号量的提供商级并发控制
- **API Key 管理**：支持按 Key 限制可访问的模型
- **流式响应**：实时流式输出，支持 token 估算
- **Web 管理面板**：用量监控、提供商/模型/API Key 管理
- **用户门户**：API Key 持有者可查看自己的用量统计
- **OpenCode 配置**：一键生成 AI 编程助手配置
- **实时统计**：10 秒滑动窗口的每秒请求数/tokens 统计
- **请求日志**：流式请求状态追踪，超时请求自动检测

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python main.py

# 服务地址: http://localhost:8765
# 管理面板: http://localhost:8765/admin/home
```

Windows 用户可使用 `start.bat`（会自动终止占用 8765 端口的进程）

## 配置

### 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `DATABASE_URL` | 是 | PostgreSQL 连接字符串 |
| `PORT` | 否 | 服务端口，默认 8765 |
| `ADMIN_USERS` | 是 | 管理员账户，格式：`用户名:密码,用户名:密码` |

### 数据库初始化

```sql
CREATE USER "api-proxy" WITH PASSWORD 'your_password';
CREATE DATABASE "api-proxy" OWNER "api-proxy";
```

完整数据库结构见 `schema.sql`。

## API 接口

### 代理接口（OpenAI 兼容）

- `POST /v1/chat/completions` - 对话补全
- `POST /v1/embeddings` - 文本向量化
- `GET /v1/models` - 获取可用模型列表

### 模型格式

使用 `提供商/模型` 格式指定提供商：

```
zhipu/glm-4      # 路由到智谱
deepseek/chat    # 路由到 DeepSeek
glm-4            # 使用默认提供商
```

## 管理面板

登录后访问 `/admin/home`：

- **首页**：总览图表、实时统计
- **配置**：管理提供商和模型
- **API Keys**：创建和管理 API Key，设置模型访问权限
- **监控**：实时请求日志、慢请求检测

## 用户门户

API Key 持有者可访问 `/user/login` 查看：

- 请求统计
- Token 消耗
- 模型使用情况
- OpenCode 配置获取

## 并发控制

每个提供商可设置 `max_concurrent`（默认 3）：

- 请求代理前先获取信号量槽位
- 达到限制时返回 HTTP 429 错误
- 非流式请求：响应后释放
- 流式请求：流结束后释放（在 `finally` 块中）

## 项目结构

```
api-proxy/
├── main.py                  # FastAPI 应用、异常处理
├── core/                    # 核心模块
│   ├── config.py            # 全局状态、缓存、日志
│   ├── database.py          # SQLAlchemy 模型
│   └── deps.py              # FastAPI 依赖
├── routes/                  # API 端点
│   ├── proxy.py             # /v1/chat/completions, /v1/models
│   ├── providers.py         # 提供商 CRUD
│   ├── keys.py              # API Key CRUD
│   ├── stats.py             # 统计接口
│   ├── logs.py              # 请求日志查询
│   ├── user.py              # 用户门户
│   └── opencode.py          # OpenCode 配置生成
├── services/                # 业务逻辑
│   ├── proxy.py             # 核心代理、流式处理、限流
│   ├── scheduler.py         # 定时任务
│   └── stats_aggregator.py  # 统计聚合
├── templates/               # HTML 模板
│   ├── admin/               # 管理面板页面
│   ├── user/                # 用户门户页面
│   └── public/              # 公开页面
└── logs/                    # 日志文件（自动轮转）
```

## Docker 部署

```bash
# 构建并推送到本地镜像仓库
docker build -t localhost:5002/api-proxy:latest .
docker push localhost:5002/api-proxy:latest

# 生产服务器拉取并运行
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

## 许可证

Apache 2.0
