# ModelGate

<p align="center">
  <img src="assets/favicon.svg" alt="ModelGate logo" width="96" height="96">
</p>

ModelGate 是一个基于 FastAPI 的 LLM 网关，提供多供应商路由、API Key 管控、请求日志、监控看板和用户仪表盘能力。

## 核心特性

- 支持智谱、DeepSeek、Ollama、MiniMax 以及任意 OpenAI 兼容接口
- 提供 OpenAI 兼容代理接口：`/v1/chat/completions`、`/v1/embeddings`、`/v1/models`
- 按供应商维度做 asyncio 信号量并发控制和限流
- API Key 管理及按 Key 分配可用模型
- 流式请求生命周期追踪：`pending` -> `success` / `error` / `timeout`
- 记录上游真实 HTTP 状态码（200、429、500 等）
- AI 驱动的每日错误分析，自动生成持久化报告
- AI 驱动的用户模型推荐和使用时段建议
- 管理端：总览、监控、配置、错误分析、使用指引
- AI 驱动的使用报告生成（DOCX 导出，含统计、趋势和趣味奖项）
- API Key 时段访问规则（时间段、日期范围、星期限制）
- 用户端：个人统计、健康度、推荐模型、OpenCode 配置导出
- OpenCode 集成：自动生成配置，包含每个模型的上下文/输出限制
- 微信 iLink 机器人集成（MCP 协议，QR 登录，自动回复，消息持久化）
- 中英文国际化（Babel）
- 桌面端和移动端管理界面
- 可配置 base path，支持反向代理
- Docker Compose + Nginx 反向代理与静态资源服务
- 每日统计聚合和 30 天日志自动归档

## 界面截图

### 管理首页

![Admin Dashboard](image/admin-dashboard.png)

### 监控页

![Admin Monitor](image/admin-monitor.png)

### 用户仪表盘

![User Dashboard](image/user-dashboard.png)

### 用户报告

![User Report](image/user-report.png)

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

默认本地地址：

- 服务地址：`http://localhost:8765`
- 管理端：`http://localhost:8765/admin/home`
- 用户端：`http://localhost:8765/user/login`

Windows 可直接使用 `start.bat`，会提示选择日志级别并自动重启服务。

## Docker

### Docker Run

```bash
docker build -t localhost:5002/modelgate:latest .
docker push localhost:5002/modelgate:latest

docker run -d --name modelgate \
  -p 8765:8765 \
  -e DATABASE_URL="postgresql+asyncpg://modelgate:password@host:5432/modelgate" \
  -e PORT=8765 \
  -e ADMIN_USERS="admin:YourPassword" \
  -v /opt/modelgate/logs:/app/logs \
  -v /opt/modelgate/reports:/app/reports \
  --restart unless-stopped \
  localhost:5002/modelgate:latest
```

### Docker Compose

仓库内置 `docker-compose.yml`，包含 ModelGate + Nginx 两个服务。Nginx 负责静态资源服务和反向代理，支持 WebSocket。

```bash
docker compose up -d
```

更完整的部署说明见 [DEPLOY.md](DEPLOY.md)。

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `DATABASE_URL` | 是 | PostgreSQL 连接串 |
| `PORT` | 否 | 服务端口，默认 `8765` |
| `ADMIN_USERS` | 推荐 | 管理员账号列表，格式 `user:pass,user:pass` |
| `ADMIN_USERNAME` | 否 | 未设置 `ADMIN_USERS` 时的回退管理员用户名 |
| `ADMIN_PASSWORD` | 否 | 未设置 `ADMIN_USERS` 时的回退管理员密码 |
| `LOG_LEVEL` | 否 | `DEBUG`、`INFO`、`WARNING`、`ERROR` |
| `ICP_NUMBER` | 否 | 备案号，显示在首页底部 |

## 数据库

```sql
CREATE USER "modelgate" WITH PASSWORD 'your_password';
CREATE DATABASE "modelgate" OWNER "modelgate";
```

表结构见 [`schema.sql`](schema.sql)。

应用启动时会自动执行兼容性补列逻辑（例如给 `request_logs` 增加新字段）。

## API 接口

### OpenAI 兼容接口

- `POST /v1/chat/completions` - 对话补全（支持流式和非流式）
- `POST /v1/embeddings` - 文本向量
- `GET /v1/models` - 查询可用模型列表

### 模型命名格式

```text
provider/model
```

示例：`zhipu/glm-4`、`deepseek/chat`、`minimax/MiniMax-M2.5`

## 管理端页面

- `/admin/home` - 总览、实时统计、慢请求、趋势图
- `/admin/config` - 供应商、模型、绑定关系配置（支持自动同步模型列表）
- `/admin/api-keys` - API Key 管理与按 Key 分配可用模型
- `/admin/monitor` - 组成分析、热点、响应时间分析
- `/admin/errors` - 每日错误日志查看，AI 驱动的错误分析报告
- `/admin/reports` - AI 驱动的使用报告生成与 DOCX 下载
- `/admin/system-config` - 出站 User-Agent 管理与 UA 统计
- `/admin/usage` - 客户端接入说明和配置示例
- `/admin/m` - 移动端管理页面

## 用户端页面

用户通过 `/user/login` 使用 API Key 登录后可以查看：

- 个人请求量和 token 统计（日/周/月）
- 最近 20 分钟系统健康度（错误率、延迟、负载、活跃用户）
- AI 驱动的模型推荐，附带评分理由
- AI 生成的小时段使用建议
- 活跃请求追踪
- 模型目录，展示上下文长度、输出限制、多模态信息
- OpenCode 配置导出（`/opencode/setup.md?api_key=...`）

## API Key 时段访问规则

API Key 支持按时间段、日期范围和星期进行访问限制，每次请求都会校验：

- **时间窗口** — `start_time` / `end_time`（如仅允许 09:00–18:00）
- **日期范围** — `start_date` / `end_date`
- **星期过滤** — 限制到特定星期几
- **允许/拒绝语义** — 每条规则有 `allowed` 标志

## 微信 iLink 机器人（MCP）

ModelGate 内置 MCP（Model Context Protocol）服务器，支持微信 iLink 机器人集成，挂载路径 `/weixin`：

- QR 码扫码登录
- 消息轮询、发送和基于内部 LLM 代理的自动回复
- 消息持久化存储
- 按用户上下文线程管理对话
- 详见 [docs/guides/weixin-mcp.md](docs/guides/weixin-mcp.md)

## 请求日志

`request_logs` 记录：API Key、供应商、模型、token、延迟、状态、上游 HTTP 状态码、客户端 IP、User-Agent、错误详情。

流式请求先写入 `pending`，结束后更新为 `success`、`error`、`timeout` 或 `cancelled`。

超过 30 天的日志自动归档到 `request_logs_history`。`request_logs_all` 视图联合两张表，对外透明查询。

## 定时任务

| 任务 | 执行周期 | 说明 |
|------|----------|------|
| 超时清理 | 每 10 分钟 | 将超过 10 分钟仍为 pending 的请求标记为 timeout |
| 每日聚合 | 00:05 | 按小时/天汇总请求数到各统计表 |
| 日志归档 | 00:20 | 将 30 天前的请求日志归档 |

## 项目结构

```text
modelgate/
├── main.py                  # 应用初始化、中间件、路由注册、异常处理
├── core/
│   ├── config.py            # 日志、缓存、统计、会话管理
│   ├── database.py          # SQLAlchemy 异步引擎、所有 ORM 模型
│   ├── deps.py              # 认证依赖
│   ├── i18n.py              # 国际化
│   ├── app_paths.py         # 反向代理 base path
│   ├── client_ip.py         # 多 Header 客户端 IP 提取
│   └── log_sanitizer.py     # 日志敏感信息脱敏
├── routes/
│   ├── proxy.py             # /v1/chat/completions、/v1/embeddings、/v1/models
│   ├── auth.py              # 管理员登录/登出
│   ├── providers.py         # 供应商增删改查
│   ├── models.py            # 模型增删改查
│   ├── provider_models.py   # 供应商-模型绑定 + 自动同步
│   ├── keys.py              # API Key 增删改查 + 按 Key 查统计/日志 + 时段规则
│   ├── stats.py             # 统计与聚合接口
│   ├── logs.py              # 日志查看 + AI 错误分析
│   ├── pages.py             # 管理端 HTML 页面
│   ├── user.py              # 用户端 API + 页面
│   ├── opencode.py          # OpenCode 配置生成
│   ├── reports.py           # 使用报告生成 + DOCX 导出
│   ├── system_config.py     # 系统配置（出站 UA 管理）
│   └── weixin.py            # 微信 MCP 服务端点
├── services/
│   ├── proxy.py             # 核心代理逻辑、流式处理、供应商分发
│   ├── auth.py              # API Key 验证 + 时段访问规则校验
│   ├── provider.py          # 供应商/模型解析
│   ├── scheduler.py         # APScheduler 定时任务
│   ├── stats_aggregator.py  # 每日统计聚合、日志归档
│   ├── logging.py           # 请求日志增改查
│   ├── tokens.py            # Token 估算和响应解析
│   ├── message.py           # 消息预处理（合并、截断）
│   ├── minimax.py           # MiniMax 响应/tool_call 解析
│   ├── sse.py               # SSE 流式数据规范化
│   ├── analysis_store.py    # AI 分析任务持久化
│   ├── usage_report.py      # DOCX 使用报告生成
│   ├── system_config.py     # 出站 UA 自动探测
│   └── weixin.py            # 微信 iLink 机器人客户端
├── templates/               # Jinja2 模板 (admin/, user/, public/, components/)
├── locales/                 # 国际化：en, zh
├── schema.sql
├── Dockerfile
└── DEPLOY.md
```

## 开发说明

- Python 3.10+ | FastAPI | SQLAlchemy async | PostgreSQL
- 代码检查与格式化：`ruff check . && ruff format .`
- 类型检查：`mypy main.py core/*.py --ignore-missing-imports`
- 国际化编译：`pybabel compile -d locales`
- 日志文件：`logs/proxy.log`、`logs/admin.log`、`logs/error.log`

## License

Apache 2.0
