# Codex CLI 接入 ModelGate — 设计文档

> 状态：已实现并部署（2026-08-25）。
> 相关提交：`4ee0236`（UI tab + 端点 + 脚本）、`139c662`（models.json 全字段目录）、`061f23b`（reasoning levels 始终输出）。

## 背景

Codex CLI（含 ChatGPT 桌面端、VS Code Codex 插件，三者共用 `~/.codex/` 配置）只支持
OpenAI Chat Completions / Responses 两种 wire API。ModelGate 网关已实现
`/v1/responses` 端点（OpenAI Responses inbound，见
`docs/specs/2026-08-24-openai-responses-inbound-design.md`），因此可以让 Codex
把 ModelGate 当作一个第三方模型提供方使用，接入平台内所有模型。

与 OpenCode 接入不同，Codex 有一个额外约束：**模型元数据（上下文窗口、推理档位、
输入模态、系统提示词等）不在请求时声明，而是来自本地 `~/.codex/models.json`
模型目录文件**。该文件缺字段或字段不合法时，Codex 会拒绝加载整个目录，agent
将以无系统提示词、错误上下文窗口的状态运行。因此接入的核心工作是生成一份与
官方目录（openai/codex models-manager，Apache-2.0）完全兼容的 `models.json`。

## 需求

- 用户仪表盘新增 "Codex 配置" tab（与 OpenCode Config 并列），DeepSeek 风格双入口：
  1. 一键脚本（Windows `irm setup.ps1 | iex`；macOS/Linux `bash <(curl setup.sh)`）；
  2. 手动配置：config.toml 生成 + models.json 下载 + 可发给 agent 自动配置的完整说明。
- 脚本必须保留用户现有 config.toml 中的 MCP 服务器、信任级别、profiles 等无关配置。
- models.json 按用户 API Key 可用模型动态生成，字段集与官方目录逐键对齐。
- 不引入新数据库表/迁移。

## 方案

### 1. 路由与端点（`app/routes/codex.py`）

| 端点 | 方法 | 用途 |
|---|---|---|
| `/codex/config` | GET | tab 数据：base_url、模型列表、默认模型、API Key（需 key/session） |
| `/codex/models.json` | GET | 生成的模型目录（需 key/session） |
| `/codex/setup.md` | GET | 完整手动配置说明 Markdown |
| `/codex/setup-file` | POST | 上传现有 config.toml，服务端合并后返回（脚本专用） |
| `/codex/setup.ps1` `/codex/setup.sh` | GET | 一键脚本本体（`?key=` 可预嵌 Key） |

鉴权复用 opencode.py 的双通道（`api_key` query 参数或用户 session），
模型列表复用 `build_opencode_config` / `sort_opencode_models`，不重复实现。

### 2. config.toml 生成与合并

生成内容（托管键 + 提供方段）：

```toml
model = "<slug>"
model_provider = "modelgate"
preferred_auth_method = "apikey"
forced_login_method = "api"
model_reasoning_effort = "high"
model_catalog_json = "~/.codex/models.json"

[model_providers.modelgate]
name = "ModelGate"
base_url = "<https://host/modelgate/v1>"
wire_api = "responses"
experimental_bearer_token = "<API Key>"
```

合并策略（`merge_codex_toml`，`/codex/setup-file` 服务端执行）：

- 逐行处理：删除旧的 `[model_providers.modelgate]` 整段与顶层托管键，保留其余
  全部内容（注释、MCP 段、格式）。
- 托管键只识别首个 section header 之前的顶层键（TOML 作用域规则），避免误删
  其他段内的同名键（如 `[profiles.x] model = ...`）。
- 输入输出都过 `tomllib` 校验：输入非法返回 422 让用户先修文件；输出校验失败
  抛 ValueError（防御性，正常不可能触发）。
- 托管键统一插到第一个 section header 之前，避免变成上一个段的键。

### 3. 一键脚本

PowerShell（5.1 兼容）与 bash 两版，共同流程：

1. API Key 解析优先级：URL 预嵌 `?key=` > `MODELGATE_API_KEY` 环境变量 > 交互输入；
   校验必须 `sk-` 开头。
2. 备份现有 config.toml 到 `~/.codex/backup-modelgate/config.toml.<时间戳>`。
3. POST 现有 config.toml 到 `/codex/setup-file`（服务端合并），bash 版用
   `mktemp` + `-D` 头解析 X-Models，成功后 `mv` 原子替换。
4. GET `/codex/models.json` 写入目录。
5. 打印可用模型列表与 `/model` 切换提示。

安全注意：API Key 在 URL query 中传输（与 opencode 脚本一致，HTTPS 前提）；
脚本写入 UTF-8 无 BOM；`Invoke-WebRequest` 显式开 TLS 1.2。

### 4. models.json 目录生成（核心）

`_codex_model_entry()` 把平台模型元数据（opencode 格式）映射为 Codex 目录条目。
**每个条目必须包含官方 `ModelInfo` 的完整字段集**，值分三类：

**(a) 按模型动态** — 来自平台元数据：

| 字段 | 来源 |
|---|---|
| `slug` / `display_name` / `description` | 模型 slug / 名称 |
| `context_window` / `max_context_window` | `limit.context`（默认 204800） |
| `input_modalities` / `supports_image_detail_original` | `modalities.input`（含 image 则支持视觉） |
| `supported_reasoning_levels` | `variants` 的 key（始终输出数组，可为空）；`default_reasoning_level` 取 `high` 或最后一档 |

**(b) 官方资产（全模型共享）** — 从 openai/codex models-manager 提取到
`app/assets/codex/`：

| 资产 | 作用 |
|---|---|
| `instructions_template.md`（17.7KB） | Codex agent 系统提示词。**目录加载器强制要求每个条目有 `base_instructions` 或 `model_messages.instructions_template` 之一，否则整个目录解析失败**（初版精简目录即踩此坑：agent 无系统提示词） |
| `token_budget.json` | 上下文将满提醒模板（`notes` 工具存档指引）+ 自动压缩回退提示 + 缓冲区 16384 tokens |
| `available_in_plans.json` | 官方 22 个计划名全列表，不做计划门槛 |

同一模板同时写入 `base_instructions`（旧客户端）与
`model_messages.instructions_template`（新客户端）。

**(c) 固定能力标记** — 官方语义下的安全默认值：

| 字段 | 值 | 理由 |
|---|---|---|
| `minimal_client_version` | `"0.0.1"` | 任何版本客户端都可见，不被版本门控隐藏 |
| `comp_hash` | `"modelgate"` | 压缩摘要哈希；全平台统一（官方同代系模型同值） |
| `auto_compact_token_limit` | `null` | Codex 自动按上下文窗口 90% 派生，与官方一致 |
| `shell_type` | `"unified_exec"` | 与官方提示词配套的统一 exec 工具 |
| `supports_search_tool` | `false` | 网关 Responses 端点无原生 web_search 工具 |
| `supports_reasoning_summaries` / `supports_reasoning_summary_parameter` | `true` | 平台模型有思维链输出 |
| `service_tiers` / `additional_speed_tiers` / `experimental_supported_tools` | `[]` | 无分级/实验工具 |
| `multi_agent_version` / `auto_review_model_override` / `availability_nux` / `upgrade` / `default_service_tier` / `tool_mode` | `null` | 关闭 OpenAI 专属特性 |
| `node_repl_auto_review_required` / `node_repl_disabled` | `false` | 关闭 node repl 门控 |
| 其余可见性/优先级 | `visibility: "list"`, `supported_in_api: true`, `priority: 0` | 正常列表展示 |

**验证方式**：拉取官方 `models.json`，对生成目录做键集 diff——
缺失键 = 官方有我们无（旧版曾缺 `node_repl_*`、`supports_reasoning_summary_parameter`，
多出 `effective_context_window_percent`），修复后 **0 缺失 / 0 多余**，逐键对齐。

### 5. 前端（`web/templates/user/tab_codex.html`）

- 方式一：展示 API Key（可复制）+ 两条嵌入 Key 的命令行；前提说明。
- 方式二：模型下拉（onchange 重渲染 TOML）+ config.toml 预览/下载 +
  models.json 下载按钮 + 使用步骤。
- 折叠区：完整配置说明（`/codex/setup.md` 渲染），可发给任意 agent 自动执行。
- i18n 沿用 dashboard 惯例：`current_locale == 'zh'` 三元内联，其余走 `_()`。

## 错误处理

- API Key 缺失：所有端点 400 "API Key is required"；无效 401。
- 现有 config.toml 无法解析：`/codex/setup-file` 返回 422 + 具体错误，脚本
  原样转显并退出（不写文件、不动备份）。
- 脚本网络失败：明确提示哪个请求失败，bash 版带 HTTP 状态码。
- 无可用模型：合并端点 400，setup.md 列表区显示占位说明。
- 资产文件缺失：模块导入即失败（fail-fast，部署问题应在启动时暴露）。

## 验证记录（2026-08-25）

1. 单测：`tests/test_codex_route.py` 17 个用例（TOML 合并保留外段/注释、
   422、托管键位置、目录排序、指令字段强制存在、完整字段集断言等）。
2. 端到端：本地起服务，`GET /codex/models.json?api_key=...` 与官方目录键集
   diff 为空；两个模型条目均含 17.7KB 指令模板。
3. 全量回归：60 个 codex+responses 用例通过；全套无新增失败（13 个既有失败
   与本特性无关）。
4. 生产：镜像构建推送私有 registry，正常部署。

## 已知限制 / 后续

- 指令模板第一行 "an agent based on GPT-5" 为官方原文，非 OpenAI 模型读到
  可能有轻微身份混淆；如需优化可按模型自定义模板首行（暂保持与官方逐字一致
  以降低兼容风险）。
- `description` 字段暂用模型显示名，未写功能描述（Codex /model 选择器展示用）。
- 官方目录演进后需人工同步资产与字段集（建议关注 openai/codex models-manager
  的 ModelInfo 变更）。
