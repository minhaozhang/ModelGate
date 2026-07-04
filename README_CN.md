# ModelGate

<p align="center">
  <img src="web/assets/favicon.svg" alt="ModelGate logo" width="96" height="96">
</p>

ModelGate 是一个基于 FastAPI 的 LLM 网关，提供多供应商路由、API Key 管控、请求日志、监控看板和用户仪表盘能力。适用于集团或企业内部统一管理和分配 AI 模型 Token，实现跨部门的模型调用管控与成本追踪。

## 核心特性

- 支持智谱、DeepSeek、Ollama、MiniMax 以及任意 OpenAI 兼容接口
- 提供 OpenAI 兼容代理接口：`/v1/chat/completions`、`/v1/embeddings`、`/v1/models`
- 提供 Anthropic 兼容代理接口：`/anthropic/v1/messages`，完整协议转换（流式、工具调用、思考模式、缓存控制）
- 模型别名路由：按别名调用模型（如 `gpt-4o`），无需供应商前缀，自动按健康度+意图+优先级选择最优供应商
- 意图分类：根据消息内容自动分类为 coding/writing/testing/design/chat，用于智能路由和日志分析
- 供应商 Key 健康度评分：5 分钟滑动窗口评分（0–100），路由时优先选择健康的 Key
- 供应商 Key 优先级：手动设置 Key 优先级，按 (priority DESC, health DESC) 排序实现有序降级
- 分层 asyncio 信号量并发控制：非 bypass API Key 全局最多 2 并发，再叠加供应商 Key / 模型维度限制
- 供应商多 Key 支持，粘性路由和 Key 级别禁用/恢复
- 供应商 Key 自动降级：401/403/429 错误时自动尝试下一个 Key
- API Key 管理及按 Key 分配可用模型，支持 bypass_busyness 跳过繁忙限制
- 请求内容分离存储：messages、response、thinking、tool_calls 存入独立 `request_contents` 表，按需加载
- 流式请求生命周期追踪：`pending` -> `success` / `error` / `timeout`
- 记录上游真实 HTTP 状态码（200、429、500 等）、意图、请求模型、实际模型、Key 标签
- 模型标签：为模型分配标签（如 coding、reasoning、vision），用于筛选和意图路由
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

### 移动端仪表盘

![Mobile Dashboard](image/mobile-dashboard.png)

## 快速开始

```bash
pip install -r requirements.txt
python -m app.main
```

默认本地地址：

- 服务地址：`http://localhost:8765`
- 管理端：`http://localhost:8765/admin/home`
- 用户端：`http://localhost:8765/user/login`

Windows 可直接使用 `start.bat`，会提示选择日志级别并自动重启服务。

## Docker

### Docker Run

```bash
docker build -t your-registry:5002/modelgate:latest .
docker push your-registry:5002/modelgate:latest

docker run -d --name modelgate \
  -p 8765:8765 \
  -e DATABASE_URL="postgresql+asyncpg://modelgate:password@host:5432/modelgate" \
  -e PORT=8765 \
  -e ADMIN_USERS="admin:YourPassword" \
  -v /opt/modelgate/logs:/app/logs \
  -v /opt/modelgate/reports:/app/reports \
  -v /opt/modelgate/uploads:/app/uploads/documents \
  --restart unless-stopped \
  your-registry:5002/modelgate:latest
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

表结构见 [`db/schema.sql`](db/schema.sql)。

应用启动时会自动执行兼容性补列逻辑（例如给 `request_logs` 增加新字段）。

## API 接口

### OpenAI 兼容接口

- `POST /v1/chat/completions` - 对话补全（支持流式和非流式）
- `POST /v1/embeddings` - 文本向量
- `GET /v1/models` - 查询可用模型列表

### Anthropic 兼容接口

- `POST /anthropic/v1/messages` - Anthropic Messages API（支持流式和非流式）

ModelGate 将 Anthropic 协议请求翻译为 OpenAI 格式发送给上游供应商，并将响应翻译回 Anthropic 格式。支持特性：

- 流式和非流式响应
- 工具调用（function calling），支持并行工具调用控制
- 扩展思考模式（thinking），含签名透传
- 缓存控制（`cache_control` 标记，支持 system、user、assistant、tool_result 块）
- 系统提示词支持结构化内容块
- 请求日志中记录 `inbound_protocol` 字段，支持协议级分析

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

`request_logs` 记录：API Key、供应商、模型、token、延迟、状态、上游 HTTP 状态码、客户端 IP、User-Agent、意图（intent）、请求模型（requested_model）、实际模型（actual_model）、Key 标签（provider_key_label）、错误详情。

流式请求先写入 `pending`，结束后更新为 `success`、`error`、`timeout` 或 `cancelled`。

超过 30 天的日志自动归档到 `request_logs_history`。`request_logs_all` 视图联合两张表，对外透明查询。

### 请求内容（分离存储）

请求的 messages、返回文本、thinking/reasoning、tool_calls 存入独立的 `request_contents` 表，保持 `request_logs` 主表精简，列表查询更快。

- **按需加载**：在日志查看器中点击 "Content" 按钮，通过 `GET /admin/api/logs/{id}/content` 懒加载
- **级联删除**：主日志归档或删除时，关联内容自动清理

## 并发控制

基于 asyncio semaphore 的四层限流：

1. **API Key 总并发** — 非 `bypass_busyness` API Key 在所有供应商和模型上合计最多 2 个并发请求
2. **API Key 供应商模型并发** — 按 (api_key, provider_key, model) 控制并发，并可随繁忙等级动态调整；`bypass_busyness` API Key 跳过用户侧繁忙并发限制
3. **供应商 Key 并发** — 每个供应商 Key 使用独立的 `max_concurrent`
4. **系统级并发** — 全局并发超限时返回 `local_rate_limited`

供应商 Key 支持粘性路由（同一个 API Key 的请求优先落到同一个供应商 Key）。

## 供应商 Key 自动降级

当供应商配置了多个 API Key 时，如果当前 Key 调用失败，ModelGate 会自动尝试下一个 Key：

- **可重试错误**：HTTP 401（认证失败）、403（禁止访问）、429（限流）、529（过载）
- 每次请求时 Key 随机打乱，实现均匀分布
- 粘性路由优先——如果粘性 Key 可用，只使用该 Key
- 并发受限的 Key 会被跳过（带警告日志），尝试下一个可用 Key
- 降级尝试日志以 `[KEY FALLBACK]` 前缀记录

## Key 健康度评分

每个供应商 Key 有基于 5 分钟滑动窗口的实时健康评分（0–100）：

| 事件 | 分数影响 |
|------|---------|
| Key 被禁用（无效 / 额度用尽） | 直接设为 0 |
| 429/529 限频 | 每次扣 15 |
| 5xx 服务端错误 | 每次扣 10 |
| 4xx 客户端错误（非 429） | 每次扣 5 |
| 成功请求 | 每 10 次成功加 5 |

健康等级：优秀（90–100，绿）/ 良好（60–89，蓝）/ 警告（30–59，黄）/ 危险（1–29，橙）/ 不可用（0，红）。

`pick_api_keys` 按健康度降序返回 Key，优先使用健康的 Key。

## Key 优先级

供应商 Key 支持手动优先级（`priority` 字段，默认 0）。`pick_api_keys` 按 `(priority DESC, health DESC)` 排序，实现有序降级（如总是先尝试 Key A，再尝试 Key B）。

## 模型别名路由

模型可以通过别名调用，无需 `供应商/模型` 前缀：

```text
# 显式指定：路由到特定供应商
zhipu/glm-5

# 别名调用：自动按健康度+意图+优先级选择最优供应商
gpt-4o
```

别名匹配多个供应商时，按 `(tag_match DESC, health DESC, priority DESC)` 排序：

1. **tag_match**：模型标签包含请求意图 → 1，否则 → 0
2. **health**：供应商 Key 健康度
3. **priority**：供应商-模型绑定的手动优先级

## 意图分类

根据请求消息内容自动分类为五种意图：

| 意图 | 说明 | Badge 颜色 |
|------|------|-----------|
| `coding` | 编程、调试、代码审查 | 蓝色 |
| `writing` | 文档、翻译、编辑 | 琥珀色 |
| `testing` | 单元测试、QA、验证 | 玫瑰色 |
| `design` | UI/UX、线框图、设计系统 | 紫色 |
| `chat` | 日常对话（默认） | 灰色 |

分类基于关键词匹配（不调用 LLM），`system_hint` 权重为 3 倍。分类结果存入 `request_logs.intent`，在日志查看器中显示为彩色 badge。

## 模型标签

模型可以设置标签（逗号分隔），用于筛选和意图路由：

- 标签如 `coding`、`reasoning`、`vision`、`flash` 表示模型特长
- 路由时标签与请求意图匹配，优先选择标签匹配的模型
- 在管理端配置页和用户端以 badge 形式展示

## 定时任务

| 任务 | 执行周期 | 说明 |
|------|----------|------|
| 超时清理 | 每 10 分钟 | 将超过 10 分钟仍为 pending 的请求标记为 timeout |
| 每日聚合 | 00:05 | 按小时/天汇总请求数到各统计表 |
| 日志归档 | 00:20 | 将 30 天前的请求日志归档 |

## 项目结构

```text
modelgate/
├── app/                     # Python 应用包
│   ├── main.py              # FastAPI 应用入口
│   ├── core/                # 配置、数据库模型、i18n、路径工具
│   ├── routes/              # FastAPI 路由
│   └── services/            # 业务逻辑和代理运行时
├── web/                     # 运行时 Web 资源
│   ├── templates/           # Jinja2 模板 (admin/, user/, public/, components/)
│   ├── static/              # CSS、JS、字体等静态资源
│   ├── assets/              # 应用图片和图标资源
│   └── locales/             # 国际化：en, zh
├── deploy/
│   └── nginx/               # Docker 反向代理配置
├── db/
│   ├── schema.sql
│   └── migrations/          # 数据库维护脚本
├── Dockerfile
└── DEPLOY.md
```

## 开发说明

- Python 3.10+ | FastAPI | SQLAlchemy async | PostgreSQL
- 代码检查与格式化：`ruff check . && ruff format .`
- 类型检查：`mypy app --ignore-missing-imports`
- 国际化编译：`pybabel compile -d web/locales`
- 日志文件：`logs/proxy.log`、`logs/admin.log`、`logs/error.log`

## 商业支持

生产级集群部署、定制化集成或功能定制开发，请联系：

**minhaozhang@henngtiansoft.com**

## License

Apache 2.0
