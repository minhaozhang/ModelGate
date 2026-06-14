# Provider Key Routing Workspace Implementation Plan

日期：2026-06-14

## 目标

把 `docs/specs/2026-06-13-provider-key-health-routing-design.md` 中已经定下来的 Provider Key health、策略模板、按时间/上下文规则、路由预览、自动跨供应商 fallback 和配置工作台实现到当前代码中，并修正现有代码与设计不一致的地方。

## 当前基线

- 已完成：供应商模型排序为 `tag_match, provider_model.priority, health`。
- 已完成：供应商 Key 排序为 `provider_key.priority, health`。
- 已完成：health 事件记录到 provider key id。
- 未完成：Key 规则和策略模板仍只存在文档/原型。
- 未完成：`proxy_request()` 仍只尝试一个供应商模型，Key 并发耗尽后不会自动切同标准模型下的其他供应商。
- 未完成：`/admin/config` 仍是大模板加弹窗，没有模型与供应商工作台 tabs、策略抽屉和路由预览。

## 实现阶段

### 1. 数据模型与 schema 迁移

新增或扩展：

- `provider_keys.cost_role`
- `provider_key_strategy_templates`
- `provider_key_strategy_assignments`
- `provider_key_routing_rules`

初始化内置模板：

- `always_available`
- `time_window`
- `small_context_prefer`
- `peak_offload`
- `primary_unavailable_fallback`
- `metered_standby`

验收：

- `init_db()` 可在已有数据库重复执行。
- 列表接口能返回 key 的成本角色、模板摘要和规则数。

### 2. Provider Key 规则引擎

新增服务模块 `app/services/provider_key_routing.py`：

- `ProviderKeyCandidate`
- `RoutingContext`
- `evaluate_provider_key_candidates()`
- `explain_provider_key_candidates()`

规则能力：

- `deny`
- `allow`
- `prefer`
- `deprioritize`
- `standby`
- 时间段，含跨午夜
- 星期、日期
- `min_context_tokens` / `max_context_tokens`
- sticky 只能作为排序加分，不能绕过硬过滤
- health 为 0 进入硬过滤

验收：

- 单测覆盖文档列出的 Key 规则用例。
- `pick_api_keys()` 继续返回旧格式，避免一次性破坏调用方。
- 新增解释 API 返回候选、过滤原因和命中规则。

### 3. 供应商模型候选与跨供应商 fallback

在 `app/services/provider.py` 中新增：

- `get_provider_model_candidates()`
- 复用 `get_provider_and_model()` 取第一候选，保持兼容。

在 `app/services/proxy.py` 中调整：

- 标准模型请求按供应商模型候选循环。
- 显式 `provider/model` 请求只尝试指定供应商。
- 当前供应商所有 Key 并发满、用户 Key + 供应商模型并发满、或所有 Key 返回可重试错误时，自动路由尝试下一个供应商模型。
- 用户 API Key 总并发满仍直接返回。

验收：

- 自动路由下 Key 并发满会切到另一个供应商。
- 显式供应商请求不会跨供应商。
- 日志仍记录最终 provider/model/provider_key。

### 4. Admin API

新增管理接口：

- `GET /admin/api/routing/strategy-templates`
- `POST /admin/api/routing/strategy-templates`
- `PUT /admin/api/routing/strategy-templates/{id}`
- `GET /admin/api/providers/{provider_id}/keys/{key_id}/strategy`
- `PUT /admin/api/providers/{provider_id}/keys/{key_id}/strategy`
- `POST /admin/api/routing/resolve`

验收：

- API 使用 RBAC 权限依赖。
- 保存策略后刷新 provider cache。
- 预览接口与真实选择器共用同一套解释逻辑。

### 5. Admin UI 工作台

把 `/admin/config` 改为一个页面多 tab：

- Overview
- Providers
- Standard Models
- Model Routing
- Strategy Templates
- Route Preview

第一版原则：

- 保持现有功能完整，不引入独立侧边栏页面。
- Provider Key 行只显示摘要。
- 策略配置进入右侧抽屉。
- 策略模板先从模板库选择，再填少量参数。
- Route Preview 能解释最终选中和过滤原因。

验收：

- 现有供应商、模型、绑定和 Key 管理可用。
- 策略模板、Key 策略、路由预览可用。
- 桌面和移动尺寸不出现明显重叠。

### 6. 测试与验证

命令：

```powershell
python -m compileall app tests -q
python -m unittest discover -s tests -v
```

浏览器验证：

- 打开 `/modelgate/admin/config`。
- 验证每个 tab 可切换。
- 新建/修改 Key 策略。
- 使用 Route Preview 验证上午小上下文、下午高峰、主 Key 停用、并发耗尽场景。

## 实施顺序

1. 数据模型和 seed。
2. 规则引擎和单测。
3. Provider cache 加载策略。
4. 管理 API 和预览接口。
5. 供应商模型候选与跨供应商 fallback。
6. UI 工作台和策略抽屉。
7. 回归测试和本地浏览器验证。
