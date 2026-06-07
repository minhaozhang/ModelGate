# ModelGate v2 设计文档：Key 健康度 / 模型别名与智能路由 / 请求内容日志

日期：2026-05-26

---

## 1. 供应商 Key 健康度

### 1.1 目标

实时评估每个 ProviderKey 的可用性，用于：
- 智能路由时优先选择健康的 key
- Admin 页面直观展示 key 状态
- 自动降级不健康的 key

### 1.2 健康度评分（0-100，100 最佳）

评分基于内存滑动窗口，统计最近 5 分钟的请求结果：

| 事件 | 扣分 | 衰减 |
|---|---|---|
| Key 被禁用（Invalid Key / 额度用尽） | 直接设为 0 | 重新启用后恢复 60 |
| 429/529 限频 | 每次 -15 | 5 分钟窗口过期后恢复 |
| 5xx 服务端错误 | 每次 -10 | 5 分钟窗口过期后恢复 |
| 4xx 客户端错误（非 429） | 每次 -5 | 5 分钟窗口过期后恢复 |
| 成功请求 | 每 10 次成功 +5 | 上限 100 |

健康度等级：

| 分数区间 | 等级 | 颜色 | 说明 |
|---|---|---|---|
| 90-100 | 优秀 | 绿色 | 正常运行 |
| 60-89 | 良好 | 蓝色 | 偶有限频/错误 |
| 30-59 | 警告 | 黄色 | 频繁出错/限频 |
| 1-29 | 危险 | 橙色 | 接近不可用 |
| 0 | 不可用 | 红色 | 已禁用 |

### 1.3 数据结构

**内存结构**（`services/key_health.py`）：

```python
# 滑动窗口：每个 key 维护最近 5 分钟的事件列表
_key_events: dict[int, list[KeyEvent]] = {}

class KeyEvent:
    timestamp: float       # time.monotonic()
    event_type: str        # "success" | "error_4xx" | "error_429" | "error_5xx" | "disabled"
    status_code: int
```

**计算逻辑**：

```python
def compute_health_score(key_id: int) -> int:
    # 1. 如果 key 被禁用，直接返回 0
    # 2. 清理 5 分钟前的事件
    # 3. 统计窗口内各类事件数量
    # 4. 基础分 100
    #    - disabled_count > 0 → 0
    #    - rate_limited_count * 15
    #    - server_error_count * 10
    #    - client_error_count * 5
    #    - success_count // 10 * 5
    # 5. max(0, min(100, base - deductions + bonus))
```

### 1.4 集成点

| 集成位置 | 说明 |
|---|---|
| `services/proxy_runtime/response_handler.py` | `_record_stream_result` 和 `handle_normal` 记录请求结果时，同步调用 `record_key_event` |
| `services/provider_limiter.py` | `disable_provider_key` 时记录 `disabled` 事件 |
| `services/provider.py` | `pick_api_keys` 返回 key 时按健康度降序排列 |
| `services/provider.py` | `load_providers` 加载缓存时，附带每个 key 的当前健康度 |

### 1.5 API

```
GET /admin/api/providers/{id}/keys/health
Response: {
  "keys": [
    {
      "key_id": 1,
      "label": "default",
      "is_active": true,
      "health_score": 85,
      "health_level": "good",
      "events_5m": {
        "success": 120,
        "rate_limited": 2,
        "server_error": 0,
        "client_error": 1
      },
      "disabled_reason": null
    }
  ]
}
```

### 1.6 Admin 前端

供应商配置页面的 Key 列表增加：
- 健康度进度条（颜色按等级）
- 5 分钟事件统计小数字
- hover 显示详情

---

## 2. 模型别名 + 标签 + 智能路由

### 2.1 目标

- 用户可以按别名调用模型（如 `gpt-4o`），无需 `供应商/模型` 前缀
- 系统自动匹配所有绑定该别名的供应商，选择健康度最高的
- 保留 `供应商/模型` 显式调用方式，向后兼容
- 模型可打标签，方便管理和筛选

### 2.2 数据库变更

**Model 表增加字段**：

```sql
ALTER TABLE models ADD COLUMN IF NOT EXISTS tags TEXT;  -- 逗号分隔，如 "develop,document,test,flash"
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `tags` | TEXT | 模型用途标签，逗号分隔。如 `develop,document,test,flash` |

预定义标签含义：

| 标签 | 说明 |
|---|---|
| `develop` | 开发/编程 |
| `document` | 文档/写作 |
| `test` | 测试/验证 |
| `flash` | 快速/低延迟 |
| `reasoning` | 推理/思考 |
| `vision` | 图像/多模态 |

**ProviderModel 表增加字段**：

```sql
ALTER TABLE provider_models ADD COLUMN IF NOT EXISTS alias VARCHAR(100);
ALTER TABLE provider_models ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 0;
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `alias` | VARCHAR(100) | 模型别名，用户调用时使用的名称。如 `gpt-4o`、`claude-3.5` |
| `priority` | INTEGER | 手动优先级，数值越大越优先。默认 0，用于在同健康度时打破平局 |

**唯一约束**：同一供应商下 alias 不能重复。

### 2.3 路由匹配逻辑

修改 `services/provider.py` 的 `get_provider_and_model`：

```
输入: model = "gpt-4o"

1. 如果包含 "/" → 走原有逻辑（显式指定供应商）
   model = "openai/gpt-4o" → provider="openai", actual_model="gpt-4o"

2. 如果不包含 "/" → 走别名匹配
   a. 遍历 providers_cache，找所有 ProviderModel.alias == "gpt-4o" 的记录
   b. 收集候选: [(provider_name, provider_config, model_config, key_health_score, priority, tag_match), ...]
   c. 过滤: 排除 provider 已禁用、model 已禁用、无可用 key 的
   d. 计算意图: classify_intent(messages) → intent (如 "develop")
   e. tag_match: 候选模型的 Model.tags 包含 intent → 1，否则 → 0
   f. 排序: 按 (tag_match DESC, key_health_score DESC, priority DESC) 排序
   g. 选第一个 → provider_name, actual_model
   h. 如果无匹配 → 返回错误 "No provider available for model 'gpt-4o'"
```

### 2.4 别名索引

别名匹配需要高效查找。在 `load_providers` 时构建内存索引：

```python
# alias_index: {alias: [(provider_name, pm_dict, model_tags, priority), ...]}
_alias_index: dict[str, list[tuple[str, dict, str, int]]] = {}
```

`load_providers` 时重建索引，同时附带 Model.tags 供意图匹配使用。

### 2.5 API 变更

**Model Create/Update 增加**：

```python
class ModelCreate(BaseModel):
    name: str
    display_name: Optional[str] = None
    tags: Optional[str] = None           # 新增，如 "develop,flash"
    ...

class ModelUpdate(BaseModel):
    tags: Optional[str] = None            # 新增
    ...
```

**ProviderModel Create/Update 增加**：

```python
class ProviderModelCreate(BaseModel):
    model_id: int
    model_name_override: Optional[str] = None
    alias: Optional[str] = None          # 新增
    is_active: bool = True
    priority: Optional[int] = 0          # 新增

class ProviderModelUpdate(BaseModel):
    model_name_override: Optional[str] = None
    alias: Optional[str] = None          # 新增
    is_active: Optional[bool] = None
    max_busyness_level: Optional[int] = None
    priority: Optional[int] = None       # 新增
```

**新增 API**：

```
GET /admin/api/models/resolve?name=gpt-4o
Response: {
  "alias": "gpt-4o",
  "providers": [
    {"provider": "openai", "actual_model": "gpt-4o", "health": 95, "priority": 10},
    {"provider": "azure", "actual_model": "gpt-4o-2024-08-06", "health": 80, "priority": 5}
  ],
  "selected": "openai"
}
```

### 2.6 Admin 前端

供应商绑定模型页面：
- 增加别名输入框
- 增加优先级数字输入

模型管理页面：
- 增加标签输入框（逗号分隔，或 chip 输入）
- 模型列表显示标签 badge

用户侧：
- 用户 Dashboard 的可用模型列表按别名展示
- 标签显示为小 badge（来自 Model.tags）

### 2.7 上下文意图分类

根据请求 messages 内容自动判断用户用途（develop/document/test/chat），用于：
1. **实时路由**：别名匹配时，优先选标签匹配的供应商（如写代码 → 优先 develop 标签的模型）
2. **事后记录**：分类结果写入 request_logs，用于统计和展示

#### 分类规则（关键词匹配，无需调 LLM）

```python
INTENT_RULES = [
    ("develop", {
        "keywords": ["function", "def ", "class ", "import ", "const ", "let ",
                      "return", "console.log", "print(", "async ", "await ",
                      "```python", "```javascript", "```java", "```go",
                      "bug", "fix", "debug", "compile", "runtime error",
                      "git ", "npm ", "pip ", "cargo ", "API endpoint",
                      "refactor", "unit test", "code review"],
        "system_hint": ["you are a", "programming", "coding assistant",
                        "developer", "software engineer"],
    }),
    ("document", {
        "keywords": ["write a", "draft", "report", "summary", "outline",
                      "article", "blog", "essay", "proposal", "memo",
                      "translate", "rewrite", "paraphrase", "polish",
                      "grammar", "spelling", "proofread"],
        "system_hint": ["you are a writer", "copywriter", "editor"],
    }),
    ("test", {
        "keywords": ["test case", "unit test", "integration test",
                      "pytest", "jest", "junit", "assert",
                      "coverage", "mock", "stub", "fixture",
                      "qa", "regression", "validation"],
    }),
]

DEFAULT_INTENT = "chat"
```

#### 分类算法

```python
def classify_intent(messages: list[dict]) -> str:
    """
    1. 取 system message（如有），检查 system_hint 匹配
    2. 取最近 3 条 user/assistant message，检查 keywords 匹配
    3. 统计各 intent 命中数，取最高
    4. 都没命中 → "chat"
    """
    scores = {intent: 0 for intent in INTENT_RULES}
    
    for msg in messages:
        role = msg.get("role", "")
        content = (msg.get("content") or "").lower()
        
        if role == "system":
            for intent, rules in INTENT_RULES:
                for hint in rules.get("system_hint", []):
                    if hint in content:
                        scores[intent] += 3  # system prompt 权重高
        
        if role in ("user", "assistant"):
            for intent, rules in INTENT_RULES:
                for kw in rules.get("keywords", []):
                    if kw.lower() in content:
                        scores[intent] += 1
    
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return DEFAULT_INTENT
    return best
```

#### 路由集成

别名匹配排序改为三级：

```
排序: (tag_match DESC, key_health_score DESC, priority DESC)
```

`tag_match`：候选模型的 tags 包含当前请求意图 → 1，否则 → 0。

即：同别名多供应商时，标签匹配 + 健康度高 + 优先级高的胜出。

#### 日志记录

`request_logs` 增加字段：

```sql
ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS intent VARCHAR(20);
```

每次请求写入 `intent` 分类结果。

#### API Key 级别偏好

`api_keys` 表增加可选字段：

```sql
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS preferred_tags TEXT;
```

用户 API Key 可设置偏好标签（如 `develop,flash`），分类后优先匹配用户偏好。

#### Admin 前端

- 请求日志列表：显示意图 badge（develop 绿 / document 蓝 / test 橙 / chat 灰）
- API Key 管理：增加偏好标签输入

---

## 3. 请求内容日志（分离存储）

### 3.1 目标

将请求上下文（messages）和返回内容（response、tool_calls、thinking）从 `request_logs` 分离到新表，减少主表体积，按需查询。

### 3.2 新表：request_contents

```sql
CREATE TABLE request_contents (
    id SERIAL PRIMARY KEY,
    log_id INTEGER NOT NULL REFERENCES request_logs(id) ON DELETE CASCADE,
    request_messages JSONB,       -- 原始 messages 数组
    response_content TEXT,        -- 模型返回文本
    response_tool_calls JSONB,    -- tool_calls 数据
    response_thinking TEXT,       -- reasoning/thinking 内容
    response_raw JSONB,           -- 完整返回 JSON（可选，大流量时可不存）
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_request_contents_log_id ON request_contents (log_id);
CREATE INDEX idx_request_contents_created_at ON request_contents (created_at);
```

| 字段 | 说明 |
|---|---|
| `log_id` | 关联 request_logs.id，一对一 |
| `request_messages` | 用户发送的 messages 数组 |
| `response_content` | 提取的文本回复 |
| `response_tool_calls` | 提取的 tool_calls |
| `response_thinking` | 提取的 reasoning_content |
| `response_raw` | 可选，完整返回 JSON |

### 3.3 ORM 模型

```python
class RequestContent(Base):
    __tablename__ = "request_contents"

    id = Column(Integer, primary_key=True)
    log_id = Column(Integer, ForeignKey("request_logs.id", ondelete="CASCADE"), unique=True, nullable=False)
    request_messages = Column(JSONB, nullable=True)
    response_content = Column(Text, nullable=True)
    response_tool_calls = Column(JSONB, nullable=True)
    response_thinking = Column(Text, nullable=True)
    response_raw = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
```

### 3.4 写入逻辑

在现有的 `create_request_log` / `update_request_log` 基础上：

```python
# create_request_log 时，同时写入 request_contents
async def create_request_log(..., request_messages=None):
    log_id = ...  # 现有逻辑
    if request_messages:
        async with async_session_maker() as session:
            content = RequestContent(
                log_id=log_id,
                request_messages=request_messages,
            )
            session.add(content)
            await session.commit()
    return log_id

# update_request_log 时，更新 request_contents
async def update_request_log(..., response_content=None, response_tool_calls=None,
                              response_thinking=None, response_raw=None):
    ...  # 现有逻辑
    async with async_session_maker() as session:
        await session.execute(
            update(RequestContent)
            .where(RequestContent.log_id == log_id)
            .values(
                response_content=response_content,
                response_tool_calls=response_tool_calls,
                response_thinking=response_thinking,
                response_raw=response_raw,
            )
        )
```

### 3.5 读取逻辑

- 请求日志列表页：只查 `request_logs`，不 JOIN `request_contents`（性能优先）
- 点击某条日志查看详情时：`GET /admin/api/logs/{id}/content`，按需加载
- 错误分析页面同理，按需加载

### 3.6 清理策略

- `request_contents` 随 `request_logs` 级联删除
- 已有的 `archive_old_request_logs` 定时任务自动处理
- 可选：增加单独的 `request_contents` 保留天数（如比主日志短），在定时任务中单独清理

### 3.7 API

```
GET /admin/api/logs/{log_id}/content
Response: {
  "log_id": 123,
  "request_messages": [...],
  "response_content": "...",
  "response_tool_calls": [...],
  "response_thinking": "...",
  "response_raw": {...}
}
```

---

## 4. 实现优先级和依赖关系

```
Phase 1: Key 健康度（独立，无外部依赖）
  ├── services/key_health.py
  ├── 集成到 response_handler / provider_limiter
  ├── 修改 pick_api_keys 排序
  └── Admin API + 前端

Phase 2: 模型别名 + 标签 + 智能路由（依赖 Phase 1 的健康度）
  ├── DB: ProviderModel 增加 alias/tags/priority
  ├── 修改 load_providers 构建别名索引
  ├── 修改 get_provider_and_model 支持别名匹配
  ├── Admin API + 前端
  └── 用户侧模型列表调整

Phase 3: 请求内容日志（独立，但建议最后做）
  ├── DB: 新建 request_contents 表
  ├── 修改 create/update_request_log
  ├── 新增详情查询 API
  └── Admin 前端日志详情弹窗
```

Phase 1 和 Phase 3 可以并行开发，Phase 2 依赖 Phase 1。

---

## 5. 影响范围

| 变更 | 影响文件 |
|---|---|
| Key 健康度 | 新增 `services/key_health.py`；修改 `response_handler.py`, `provider_limiter.py`, `provider.py`, `providers.py` (Admin route) |
| 模型别名/标签/意图分类 | 修改 `core/database.py`, `provider.py`, `provider_models.py`, `models.py` (Admin route), `proxy.py`, `logging.py`, 新增 `services/intent_classifier.py`, 前端模板 |
| 请求内容日志 | 修改 `core/database.py`, `services/logging.py`, `routes/logs.py`, 前端模板 |
