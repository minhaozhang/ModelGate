# 系统繁忙程度分级设计

## 级别定义

判断顺序：从级别1到级别6依次检查，命中即停。

| 级别 | 名称 | 完整条件 |
|------|------|----------|
| 1 | 极度繁忙 | 被限流供应商数 ≥ 2 **且** 10分钟内活跃用户 > 10 **且** 429占总请求 > 50% |
| 2 | 较繁忙 | 被限流供应商数 ≥ 1 **且** 10分钟内活跃用户 > 10 **且** 429占总请求 > 50% |
| 3 | 繁忙 | 10分钟内活跃用户 > 10 **且** 429占总请求 > 50% |
| 4 | 正常 | 有活跃请求 **或** 10分钟内有请求记录，且不满足级别1-3 |
| 5 | 空闲 | 无活跃请求 **且** 10分钟内无请求记录 **且** 1小时内有请求记录 |
| 6 | 无人问津 | 无活跃请求 **且** 1小时内无请求记录 |

## 数据来源

全部来自内存，不需要额外 DB 查询：

- **被限流供应商数** → `providers_cache` 中有 `disabled_reason` 的 provider 数量
- **活跃用户数** → `active_requests` 中去重的 `api_key_id` 数量
- **429占比** → `stats` 中 `rate_limited` / `total_requests`（10分钟窗口）
- **近期请求记录** → `requests_per_second` 滚动窗口 或 `active_requests`

## 刷新机制

- 每 **5 分钟**定时计算（加入 scheduler）
- 结果缓存在内存 `busyness_state: dict`，包含：
  - `level`: int (1-6)
  - `name`: str
  - `disabled_providers`: int
  - `active_users_10min`: int
  - `rate_429_ratio`: float
  - `has_active_requests`: bool
  - `last_request_at`: str (ISO timestamp)
  - `computed_at`: str (ISO timestamp)

## 展示

1. **User Dashboard**：替换现有健康评分，显示繁忙等级（图标+文字+颜色）
2. **Admin Dashboard**：顶部状态栏显示当前级别
3. **消息中心**（新功能）：记录级别变化通知

## 路由控制规则（后台可配置）

在 Admin 系统配置中新增"繁忙控制规则"，存储在 `system_config` 表：

```json
{
  "busyness_rules": [
    {"min_level": 3, "action": "downgrade", "target_models": ["deepseek/deepseek-v4-pro"], "redirect_to": "deepseek/deepseek-v4-flash"},
    {"min_level": 2, "action": "suggest", "message": "系统繁忙，建议使用轻量模型"},
    {"min_level": 1, "action": "block", "target_models": ["openai/openai-chatgpt/gpt-5.4"]}
  ]
}
```

三种 action：
- **downgrade**：自动降级到便宜模型
- **suggest**：API 响应 header 加 `X-System-Busyness`，前端展示建议
- **block**：直接拒绝，返回 503

## 实现分阶段

### Phase 1: 级别计算核心
- 新建 `services/busyness.py`：级别计算逻辑
- `core/config.py`：新增 `busyness_state` 缓存
- `services/scheduler.py`：新增 5 分钟定时任务

### Phase 2: 展示层
- Admin Dashboard 顶部显示级别
- User Dashboard 替换健康评分
- API 接口暴露级别数据

### Phase 3: 路由控制
- `services/proxy.py`：请求前检查规则
- Admin 后台规则配置页面
- downgrade/suggest/block 三种 action 实现

### Phase 4: 消息中心
- 级别变化时生成通知
- Admin 和 User 消息中心 UI
- 定时任务中心（管理所有定时任务）
