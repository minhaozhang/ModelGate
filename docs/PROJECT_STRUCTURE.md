# ModelGate 目录结构约定

本文档记录迁移后的仓库结构和文件放置规则。当前约定是：纯 Python 应用代码集中在 `app/`，运行时页面和静态资源集中在 `web/`，部署配置和数据库维护文件分别进入 `deploy/`、`db/`。

## 当前结构

```text
ModelGate/
├─ app/                     # Python 应用包
│  ├─ __init__.py
│  ├─ main.py               # FastAPI 应用入口，注册路由和中间件
│  ├─ core/                 # 全局配置、数据库模型、缓存、客户端 IP 等基础设施
│  ├─ routes/               # FastAPI HTTP 路由层
│  └─ services/             # 业务逻辑、代理运行时、供应商适配、统计和存储服务
├─ web/                     # 运行时 Web 资源
│  ├─ templates/            # Jinja2 页面模板
│  ├─ static/               # CSS、JS、字体等静态资源
│  ├─ assets/               # favicon 等应用资源
│  └─ locales/              # i18n 翻译资源
├─ deploy/
│  └─ nginx/                # Nginx 反向代理配置
├─ db/
│  ├─ schema.sql            # 数据库 schema 快照
│  └─ migrations/           # 数据库维护/迁移脚本
├─ tests/                   # 单元测试和回归测试
├─ docs/                    # 设计、架构、运维、使用说明文档
├─ design/                  # 设计稿、方案稿、视觉探索产物
│  └─ homepage/             # 首页方案稿：index.html、index-a.html ... index-f.html
├─ image/                   # README 或文档引用的公开截图资源
├─ README.md
├─ README_CN.md
├─ requirements.txt
├─ Dockerfile
├─ docker-compose.yml
├─ docker-compose.override.yml
└─ start.bat
```

## 目录职责

### Python 代码

- `app/main.py`：应用启动入口，只保留 app 初始化、路由注册、中间件、静态资源挂载等装配逻辑。
- `app/core/`：底层能力，包含配置、数据库模型、全局 cache、常量和通用基础设施。业务规则不应继续堆到这里。
- `app/routes/`：HTTP 接口层，只负责请求解析、鉴权依赖、响应组装和调用 service。
- `app/services/`：业务逻辑层。代理、供应商路由、日志、busyness、文档、存储、分析等核心逻辑放这里。
- `app/services/proxy_runtime/`：代理请求执行路径的运行时模块，包含普通请求、流式请求、并发控制、请求构造和响应处理。
- `tests/`：测试代码。新 bugfix 应优先在这里补回归测试。

### 页面和静态资源

- `web/templates/`：服务端渲染模板，不放临时 HTML 设计稿。
- `web/static/`：运行时加载的 CSS、JS、字体等静态资源。
- `web/assets/`：应用运行需要的图标和资源文件。
- `web/locales/`：Babel 翻译文件和编译后的 message catalog。
- `image/`：README 或文档明确引用的截图。
- `design/`：设计探索、方案稿、对比稿。当前首页 `index*.html` 放在 `design/homepage/`。

### 文档

- `docs/`：项目文档、架构图、设计说明、操作指南。
- `docs/guides/`：用户或运维指南。
- `docs/specs/`：需求和设计规格。
- `docs/superpowers/`：实现计划和设计计划。
- 临时解析出来的报告目录、截图中间产物不要提交；需要沉淀时整理成正式 markdown 后放入 `docs/`。

### 部署和数据库

- `Dockerfile`、`docker-compose*.yml`：保留在根目录，避免改变现有构建上下文和部署命令。
- `deploy/nginx/`：反向代理配置。它属于部署基础设施，不属于 `web/`。
- `db/migrations/`：数据库维护/迁移脚本。目前主要是 RBAC 表结构和初始化数据脚本，不是完整 Alembic 迁移体系。
- `db/schema.sql`：数据库 schema 快照。

如果未来引入 Alembic 或类似迁移工具，`db/migrations/` 可以进一步替换为标准工具目录。若要继续收敛部署配置，可以再评估把 Docker Compose 相关文件迁到 `deploy/docker/`，但需要同步更新 CI/CD、文档和启动命令。

## 根目录规则

根目录只保留项目入口和基础配置：

- 文档入口：`README.md`、`README_CN.md`、`AGENTS.md`、`DEPLOY.md`
- 依赖和构建：`requirements.txt`、`package.json`、`package-lock.json`
- 部署入口：`Dockerfile`、`docker-compose*.yml`
- 配置模板：`.env.example`、`.dockerignore`、`.gitignore`
- 本地启动脚本：`start.bat`

不要再把这些东西放根目录：

- 临时脚本：`_extract_*.py`、`_parse_*.py`、`_test_*.py`
- 手工调试脚本：例如临时数据库检查、临时 semaphore 打印
- 根目录截图：`*.png`
- 压缩包：`*.zip`
- 设计稿 HTML：`index-*.html`，应放到 `design/<topic>/`
- 运行时上传文件：`uploads/`
- 日志和缓存：`logs/`、`__pycache__/`、`.ruff_cache/`
- 本地 agent/worktree 状态：`.agents/`、`.claude/worktrees/`

## 新文件放置建议

- 新 HTTP 接口：`app/routes/<domain>.py`
- 新业务逻辑：`app/services/<domain>.py`
- 代理运行时细分逻辑：`app/services/proxy_runtime/<topic>.py`
- 新数据库模型：`app/core/database.py`，并补 `db/migrations/` 维护脚本
- 新管理端页面：`web/templates/admin/`，并配对应 `app/routes/pages.py`
- 新用户端页面：`web/templates/user/`，并配对应 `app/routes/user.py`
- 新静态资源：`web/static/`
- 新翻译资源：`web/locales/`
- 新文档：`docs/`
- 新设计稿：`design/<topic>/`
- 新回归测试：`tests/test_<topic>.py`

## 启动和维护命令

```bash
python -m app.main
python db/migrations/add_rbac_tables.py
python db/migrations/init_rbac_data.py
pybabel compile -d web/locales
```

Docker Compose 的 Nginx 配置挂载路径是 `deploy/nginx/nginx.conf`，静态资源挂载路径是 `web/static/`。

## Ignore 规则

`.gitignore` 应覆盖运行时和临时产物：

- Python 缓存：`__pycache__/`、`*.py[cod]`
- 日志：`logs/`
- 本地环境：`.env`、`.env.*`、`.venv/`
- 前端依赖：`node_modules/`
- 运行时文件：`uploads/`
- 临时解析脚本和截图：根目录 `_extract_docx*.py`、`_parse_screenshots*.py`、`*.png`
- 临时包：根目录 `*.zip`
- 本地 agent 状态：`.agents/`、`.claude/worktrees/`

## 清理原则

- 先移动或删除没有运行时引用的文件，再改 ignore。
- 删除 tracked 文件前先用 `git grep` 确认没有引用。
- 不提交 `.env`、真实数据库连接串、上传文件、日志、缓存、临时截图。
- 设计稿可以保留，但必须进入 `design/`，不要放根目录。
