# API Key 每日费用额度 + 峰谷计费乘数 — 设计文档

> 状态：已批准（2026-08-25）。
> 需求确认：限额载体 = API Key；峰谷语义 = 计费乘数；超额行为 = 429 + 次日重试；
> 时段定义 = 全局；扣费口径 = 成本价（total_cost_cny）。

## 背景

平台需要控制每个使用方的每日花费：每把 API Key 一个每日额度（CNY），用完即拒；
同时引入高峰/低峰时段乘数，高峰期扣费加速、低峰期扣费减速，引导错峰使用。

现有基础：

- 每请求成本已在响应完成时计算（`pricing.enrich_tokens_with_billing` →
  `total_cost_cny`，写入 request_logs.tokens JSONB）。
- `api_key_daily_stats`（date+hour 聚合）由异步聚合器写入，不适合做实时记账
  （竞争 + 延迟）。
- 错误格式转换已有：OpenAI 错误体自动转 Anthropic 格式（429 → `rate_limit_error`）。

## 方案

### 1. 数据层

- `api_keys` 加列 `daily_quota_cny FLOAT NULL`：NULL = 用全局默认；0 = 不限额；
  正数 = 该 key 每日额度。
- 新表 `api_key_daily_usage`：

| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| api_key_id | INTEGER FK api_keys ON DELETE CASCADE | |
| date | VARCHAR(10) | 本地时区自然日 `YYYY-MM-DD`，与现有 stats 口径一致 |
| charged_cny | FLOAT | 当日累计扣费（成本价 × 峰谷乘数） |
| requests_charged | INTEGER | 计费请求数（审计用） |
| updated_at | TIMESTAMP | |

唯一索引 `(api_key_id, date)`，行不存在即当日未消费，跨日自动滚新行（旧行保留
供报表，不清理）。

### 2. 峰谷规则（全局，system_settings category `billing`）

| key | 默认 | 说明 |
|---|---|---|
| `peak_windows` | `09:00-12:00,14:00-18:00` | 逗号分隔 HH:MM-HH:MM，支持跨零点（如 `22:00-06:00`） |
| `weekend_offpeak` | `true` | 周六周日全天按低峰 |
| `peak_multiplier` | `1.5` | 高峰扣费乘数 |
| `offpeak_multiplier` | `0.8` | 低峰扣费乘数 |
| `default_daily_quota_cny` | ``（空=全局不限） | 新 key/未设置 key 的默认额度 |

乘数判定用**请求完成时刻**（与成本计算同点，避免流式请求跨时段的记账歧义）。

### 3. 计费链路

`enrich_tokens_with_billing` 增加可选参数 `api_key_id`（内部路径不传，天然豁免）：

1. 算完 `total_cost_cny` 后，若传了 `api_key_id`：取当前时段乘数，
   `charge = total_cost_cny × multiplier`。
2. UPSERT 递增 `api_key_daily_usage`（`charged_cny += charge`，
   `requests_charged += 1`），原子操作。
3. tokens JSONB 附加审计字段：`billing_period`（peak/offpeak）、
   `billing_multiplier`、`daily_charged_cny`（本次扣费额）。
4. 通知去重：当日首次达到额度时给管理员发一条 Notification
   （`type=system, level=warning`），以"当日已发过"标记去重（查最近通知标题）。

### 4. 拦截（`proxy_request` 入口）

位置：`validate_api_key` 成功之后、busyness 检查之前（`app/services/proxy.py`）。

- 读 key 的 `daily_quota_cny`（NULL → 全局默认；解析失败或 ≤0 → 不拦）。
- 查当日 `charged_cny >= quota` → 拒绝：
  - HTTP 429 + `Retry-After`（到次日 00:00 本地时间的秒数）
  - OpenAI 错误体 `rate_limit_error / daily_quota_exceeded`，message 含已用/额度
    与重置时间（Anthropic 客户端经现有转换层自动得到 `rate_limit_error`）。
  - 记一条 request_log（status=rate_limited，error=message）。
- 进行中的流式请求允许跑完（最后一个请求可能小幅超额，业界通行）。
- 并发竞态：多请求同时读过旧值 → 双方放行，扣费超额 ≤ 单请求成本，可接受；
  记账 UPSERT 原子无丢失。

### 5. 管理/用户界面

- **admin 系统配置页**：新增"计费规则"卡片——峰谷时段（文本输入，格式校验）、
  周末低峰开关、两个乘数、默认每日额度。读写走 `/admin/api/system/config`。
- **admin API Key 编辑**：`daily_quota_cny` 字段（空=默认，0=不限）。
- **用户 dashboard**：`/user/api/stats` 附带 `daily_quota`（额度或 null=不限）、
  `daily_charged_cny`（今日已扣）、`billing_period`、`billing_multiplier`；
  前端显示进度条 + 当前时段 badge。

### 6. 错误处理

- 峰谷配置解析失败（格式错）→ 退化为全天 offpeak 乘数 1.0，warning 日志。
- 记账 UPSERT 异常 → warning 日志，不影响响应返回（记账尽力而为，拦截下次生效）。
- 拦截查询异常 → 放行请求（quota 检查失败不应阻断服务），error 日志。

## 验证计划

1. 单测（新 `tests/test_billing_rules.py`）：
   - 时段判定：工作日高峰窗口内/外、周末、跨零点窗口、非法配置退化。
   - 乘数与扣费计算、UPSERT 幂等递增。
   - 拦截阈值：未达/达到/超额、quota=0 不限、NULL 回退全局默认。
   - Retry-After 秒数 = 到次日零点。
2. 集成：`enrich_tokens_with_billing(api_key_id=...)` 后 usage 表递增、
   tokens JSONB 含审计字段；internal 路径不记账。
3. 全量回归无新增失败。

## 已知限制

- 额度按"扣费额"（成本×乘数）计，不是原始成本——报表口径需说明。
- 时段判定在完成时刻，跨时段边界的长流式请求按完成时刻计。
- 无余额结转、无按月额度（当前需求只有每日）。
