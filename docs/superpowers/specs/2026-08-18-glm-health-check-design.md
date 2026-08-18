# GLM 模型定时健康检查 — 设计文档

## 背景

需要一个定时任务在每天 05:30 调用一次 GLM 模型，验证 zhipu 供应商全链路（路由 → 选 key → 上游调用 → 计费日志）可用。生产环境已配置 `glm-5.3` 模型。

## 需求

- 每日 05:30 执行（cron `30 5 * * *`），后台定时任务页可修改 cron、可暂停。
- 通过网关内部链路调用（与微信自动回复、用量报告同路径），调用真实计入 request_logs 与统计。
- 成功：任务日志记 success + 耗时，无其他动作。
- 失败：创建后台 Notification（type=system, level=error，含失败原因），任务日志记 failed。
- 模型名可配置（系统配置 `scheduler.glm_health_check_model`），默认 `glm-5.3`，生产换模型无需改代码。

## 方案

### 1. 新文件 `app/services/glm_health_check.py`

```python
async def run_glm_health_check() -> None
```

- 读系统配置 `get_setting("scheduler", "glm_health_check_model", "glm-5.3")`。
- 构造极小请求：system "You are a health check probe."，user "ping"，`max_tokens=8`，`stream=False`。
- 调用 `call_internal_model_via_proxy`（`purpose="glm-health-check"`，`api_key_id=INTERNAL_ANALYSIS_API_KEY_ID`，timeout 60s）。
- 成功判定：`result["ok"]` 且 choices[0].message.content 非空。
- 失败：先 `create_notification("system", "error", ...)`（标题"GLM 模型健康检查失败"，正文含模型名与失败原因前 300 字符，通知失败仅 warning 日志不吞主异常），再 raise RuntimeError。

### 2. `app/services/scheduler.py` 注册

- `TASK_REGISTRY` 增加条目 `glm_health_check`：名称"GLM 模型健康检查"，描述"每日定时调用 GLM 模型验证 zhipu 供应商链路可用，失败时发送后台通知"，默认 cron `30 5 * * *`，func 指向 `run_glm_health_check`。
- 新增 `_task_glm_health_check` handler（直接用 registry func 走 `_run_task_with_logging`），加入 `TASK_HANDLERS`。
- `_ensure_task_records` 启动时自动插入 `scheduler_tasks` 记录；后台定时任务页无需前端改动。

### 3. 数据库

无迁移。复用 `scheduler_tasks` / `scheduler_task_logs` / `notifications` 现有表。

## 错误处理

- 配置的模型不存在：网关返回"未找到模型"错误 → 走失败路径（通知 + failed）。
- 无可用 key / 限流 / 上游 5xx：网关返回非 ok → 失败路径。
- 通知创建本身失败：warning 日志，不影响任务 failed 状态记录。

## 验证计划

1. `py_compile` + 容器重建。
2. 成功路径：本地无 glm-5.3，临时将系统配置 `glm_health_check_model` 设为 `glm-4.5`，手动触发任务 → success，request_logs 出现一条 `intent/purpose=glm-health-check` 记录。
3. 失败路径：配置设为不存在的模型名，手动触发 → notifications 出现 error 通知，任务日志 failed。
4. 验证后清理：临时配置删除、测试产生的通知删除。
5. 生产部署：默认值即 glm-5.3，无需配置即生效。
