# API Key 使用报告导出 — 设计文档

## 概述

为管理员提供按 API Key 维度的使用报告导出功能。支持选择时间范围，异步生成 Word 文档（.docx），包含数据表格和 AI 趣味分析（中文）。

## 需求

- 管理员选择时间范围（起止日期），生成报告
- 按 API Key 聚合统计：请求数、Token 用量、成功率、延迟、模型分布、时段分布
- AI 自动生成趣味分析：夜猫子、早起鸟、输出狂人等奖项
- 输出为 Word（.docx）格式，含表格和文字分析
- 异步生成，前端轮询进度，完成后下载
- 数据超过 1 个月时自动跨历史表查询（通过 `request_logs_all` 视图）

## 架构

### 数据流

```
管理员选择时间范围 → POST /admin/api/reports/usage
→ 复用 AnalysisRecord + start_analysis_task() 创建任务
→ asyncio.create_task() 后台执行:
    1. 查询 request_logs_all 按 api_key_id 聚合
    2. 组装结构化统计数据
    3. 调用内部 LLM 生成中文趣味分析
    4. python-docx 生成 Word 文档
    5. 保存到 reports/usage/ 目录
→ 前端轮询 GET /admin/api/reports/usage/{task_id}
→ 完成后 GET /admin/api/reports/usage/{task_id}/download
```

### 查询层

使用 `RequestLogRead`（映射到 `request_logs_all` 视图）查询，自动跨 `request_logs` + `request_logs_history` 两张表，无需额外处理。

## API 端点

### POST /admin/api/reports/usage

创建报告生成任务。

**请求体：**
```json
{
  "start_date": "2026-04-01",
  "end_date": "2026-04-11"
}
```

**响应：**
```json
{
  "task_id": 123,
  "status": "pending"
}
```

### GET /admin/api/reports/usage/{task_id}

查询任务状态。

**响应（进行中）：**
```json
{
  "task_id": 123,
  "status": "running",
  "message": "正在查询数据..."
}
```

**响应（完成）：**
```json
{
  "task_id": 123,
  "status": "success",
  "download_url": "/admin/api/reports/usage/123/download"
}
```

**响应（失败）：**
```json
{
  "task_id": 123,
  "status": "failed",
  "error": "AI 模型调用失败"
}
```

### GET /admin/api/reports/usage/{task_id}/download

下载生成的 Word 文件。返回 `FileResponse`，Content-Type: `application/vnd.openxmlformats-officedocument.wordprocessingml.document`。

## 数据查询

从 `request_logs_all` 按 `api_key_id` 聚合，时间范围由 `created_at` 过滤。

每个 API Key 收集的指标：

| 指标 | SQL 来源 |
|------|---------|
| 总请求数 | `COUNT(id)` |
| 总 Token | `SUM(tokens->>'total_tokens')` fallback `tokens->>'estimated'` |
| 成功/失败/超时/限流数 | `COUNT CASE status` |
| 模型分布 | `GROUP BY model`, `COUNT` |
| 24 小时时段分布 | `EXTRACT(hour FROM created_at)` 分桶 |
| 按天请求分布 | `DATE(created_at)` 分桶 |
| 平均延迟 | `AVG(latency_ms)` |
| P95 延迟 | `PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)` |

API Key 名称通过 `get_api_key_name_map()` 解析（先查 `api_keys_cache`，再查库）。

## AI 分析

### 模型选择

复用 `_choose_analysis_model()` 逻辑，优先使用 `glm-5-turbo`，fallback 到其他可用模型。

### Prompt 设计

将聚合后的结构化数据（JSON）发送给 LLM，要求输出中文趣味分析，包含以下奖项：

| 奖项 | 判定依据 |
|------|---------|
| 最勤奋奖 | 总请求数最多 |
| 夜猫子奖 | 0:00-6:00 请求占比最高 |
| 早起鸟奖 | 6:00-9:00 请求占比最高 |
| 输出狂人奖 | 总 Token 消耗最多 |
| 模型尝鲜者 | 使用模型种类最多 |
| 稳定输出奖 | 日均请求方差最小（排除请求数过少的 Key） |
| 效率之王 | 平均延迟最低（排除请求数过少的 Key） |

LLM 输出格式要求：每个奖项一个段落，包含 Key 名称、数据支撑和一句话评语。最后附总体趋势评语。

### 调用方式

复用 `call_internal_model_via_proxy()`，`api_key_id=1`，`purpose="usage-report"`。

## Word 文档结构

```
ModelGate API Key 使用报告
时间范围：YYYY-MM-DD ~ YYYY-MM-DD
生成时间：YYYY-MM-DD HH:MM

一、概览
  [表格] API Key | 请求数 | Token 用量 | 成功率 | 平均延迟 | 最常用模型

二、各 API Key 详细统计
  [每个 Key 一个小节]
  - 请求趋势（按天）
  - 模型使用分布
  - 时段活跃分布（24 小时）

三、AI 趣味分析
  [各奖项 + 评语]

四、附录
  - 生成时间、使用模型、数据来源说明
```

### python-docx 样式

- 标题：14pt 黑体
- 副标题：12pt 黑体
- 正文：11pt 宋体
- 表格：带边框，表头浅灰背景
- 语言：中文

## 文件存储

路径：`reports/usage/{start_date}_{end_date}_{timestamp}.docx`

Docker volume 已挂载 `./reports:/app/reports`，文件持久化。

## 新增依赖

```
python-docx>=1.1.0
```

## 前端

在 admin 导航栏新增"使用报告"入口，页面包含：
- 日期范围选择器（起止日期）
- "生成报告"按钮
- 生成进度提示（轮询状态）
- 完成后显示"下载"按钮
- 历史报告列表（最近生成的几份）

## 新增文件

| 文件 | 说明 |
|------|------|
| `services/usage_report.py` | 报告生成核心逻辑：数据查询、AI 分析、docx 生成 |
| `routes/reports.py` | API 端点路由 |
| `templates/admin/reports.html` | 管理员报告页面 |
| `reports/usage/` | 报告文件输出目录 |

## 复用

| 组件 | 来源 |
|------|------|
| `AnalysisRecord` + `start_analysis_task()` | `services/analysis_store.py` |
| `RequestLogRead` (request_logs_all 视图) | `core/database.py` |
| `call_internal_model_via_proxy()` | `services/proxy.py` |
| `_choose_analysis_model()` | `routes/logs.py`（提取为公共函数） |
| `get_api_key_name_map()` | `routes/stats.py`（提取为公共函数） |
| Token 提取模式 | `routes/stats.py:44-48` |
