# ModelGate
[![star](https://gitee.com/zmh/ModelGate/badge/star.svg?theme=white)](https://gitee.com/zmh/ModelGate/stargazers)

<p align="center">
  <img src="assets/favicon.svg" alt="ModelGate logo" width="96" height="96">
</p>

ModelGate 是一个基于 FastAPI 的 LLM 网关，提供多供应商路由、API Key 管控、请求日志、监控看板和用户仪表盘能力。

## 核心特性

- 支持智谱、DeepSeek、Ollama、MiniMax 以及任意 OpenAI 兼容接口
- 提供 OpenAI 兼容代理接口，如 `/v1/chat/completions`、`/v1/models`
- 按供应商维度做并发控制和限流
- 支持 API Key 管理及按 Key 分配可用模型
- 流式请求会先记为 `pending`，完成后再更新为最终状态
- 记录上游真实 HTTP 状态码，例如 `200`、`429`、`500`
- 管理端支持总览、监控、配置、API Key 管理、使用指引
- 用户端支持推荐模型、系统健康度、趋势图、模型使用分析
- 支持中英文国际化
- 提供桌面端和移动端管理界面

## 界面截图

### 管理首页

![Admin Dashboard](image/admin-dashboard.png)

### 监控页

![Admin Monitor](image/admin-monitor.png)

### 用户仪表盘

![User Dashboard](image/user-dashboard.png)

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

默认本地地址：

- 服务地址：`http://localhost:8765`
- 管理端：`http://localhost:8765/admin/home`
- 用户端：`http://localhost:8765/user/login`

Windows 可直接使用：

- `start.bat`

## Docker 使用

构建并推送到本项目使用的本地镜像仓库：

```bash
docker build -t localhost:5002/modelgate:latest .
docker push localhost:5002/modelgate:latest
```

启动容器示例：

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

## 数据库

初始化示例：

```sql
CREATE USER "modelgate" WITH PASSWORD 'your_password';
CREATE DATABASE "modelgate" OWNER "modelgate";
```

表结构见：

- [`schema.sql`](schema.sql)

应用启动时也会执行部分兼容性补列逻辑，例如给 `request_logs` 增加新字段。

## API 接口

### OpenAI 兼容接口

- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `GET /v1/models`

### 模型命名格式

推荐使用：

```text
provider/model
```

示例：

```text
zhipu/glm-4
deepseek/chat
minimax/MiniMax-M2.5
```

## 管理端页面

- `/admin/home`：总览、实时统计、慢请求、趋势图
- `/admin/config`：供应商、模型、绑定关系配置
- `/admin/api-keys`：API Key 管理与模型授权
- `/admin/monitor`：组成分析、热点、响应时间分析
- `/admin/usage`：客户端接入说明

## 用户端页面

用户通过 `/user/login` 登录后可以查看：

- 自己的请求量和 token 统计
- 推荐模型气泡
- 最近 20 分钟系统健康度
- 活跃请求情况
- 请求趋势和模型使用情况
- OpenCode 配置输出

## 请求日志

`request_logs` 中会记录：

- API Key、供应商、模型
- token 和响应耗时
- 归一化后的状态字段
- 上游供应商真实 HTTP 状态码
- 错误详情

流式请求会先写入 `pending`，结束后再更新为最终状态。

## 项目结构

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

## 开发说明

- 使用 Python 3.10+ 风格
- 基于 FastAPI + SQLAlchemy async + PostgreSQL
- Babel 负责国际化编译
- 日志文件位于 `logs/proxy.log`、`logs/admin.log`、`logs/error.log`

## License

Apache 2.0
