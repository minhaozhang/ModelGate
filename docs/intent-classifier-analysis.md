# Intent 分类器问题分析（基于真实日志）

## 数据集

- 6 个日志文件，**25,728 条请求**
- 全部来自 opencode / agent 类客户端（coding 场景为主）

## 当前分类器的问题

### 问题 1：当前实现混入了 system/assistant 消息

当前 `classify_intent()` 会扫 system + 所有 user + 所有 assistant，关键词命中即可加分。导致：

| 模式 | 当前分布 | 只看 user 消息后 |
|------|--------:|----------------:|
| coding | 17,762 (69%) | 9,553 (37%) |
| writing | 4,854 (19%) | 4,892 (19%) |
| chat | 1,587 (6%) | 9,393 (37%) |
| design | 1,424 (6%) | 1,230 (5%) |
| testing | 101 (0.4%) | 660 (3%) |

**46% 的请求在两种算法下分类不一致** — 说明当前结果严重不稳定。

### 问题 2：关键词权重过粗

从真实分歧样本看到的误判模式：

| 用户话术 | 当前分类 | 应该是 | 误判原因 |
|---------|---------|-------|---------|
| `执行` | writing | coding | "writing" 命中了 system/assistant 里的 "write" |
| `重启服务` | coding → chat | coding | user 短句没关键词，掉到 chat |
| `检查代码 / 排查报错` | chat | coding | "代码" 不在 coding 关键词里 |
| `mock数据 / 写个vue页面` | chat | coding | 现代 coding 话术没覆盖 |
| `帮我写一篇文章` | writing | writing ✓ | 正确 |
| `生成 PPT` | writing/design | design/writing | 边界模糊，但写作属性更强 |
| `重新排版 / 加宽 / 改样式` | chat | design | design 关键词覆盖不够 |
| `添加重置按钮` | chat | design/coding | UI 调整是 design 或 coding |

### 问题 3：缺少"上下文延续"识别

opencode 会话里 60%+ 的请求是 **2-5 字短句**（`执行`、`确认`、`继续`、`对`、`不对`），这些显然是**承接上一轮意图**。当前每条请求独立分类，必然掉到 chat。

### 问题 4：客户端注入的"伪用户消息"干扰

opencode / sisyphus / 各种 agent 框架会注入大量模板：
- `<!-- OMO_INTERNAL_INITIATOR -->`
- `<system-reminder>...</system-reminder>`（已过滤）
- `<EXTREMELY_IMPORTANT>...superpowers...`
- `[search-mode] MAXIMIZE SEARCH EFFORT. Launch multiple background agents...`
- `Continue if you have next steps, or stop and ask for clarification...`
- `Attached media from tool result:`

这些**不是用户真实意图**，但当前都会被当作 user 消息扫描，污染结果。

## 改进方向（只基于用户话术，不依赖 tool_calls / system prompt 来源）

### A. 只看 user 消息，过滤注入噪音

```python
# 在 classify_intent 入口先做：
NOISE_PATTERNS = [
    r"^<!--.*-->$",                              # HTML 注释协议
    r"<system-reminder>",                         # 已有，扩展到其他协议
    r"<EXTREMELY_IMPORTANT>",
    r"<Work_Context>",
    r"\[search-mode\]",
    r"\[CONTEXT\]:",
    r"^Continue if you have next steps",          # opencode 续跑模板
    r"^Attached media from tool result",
    r"Called the .+ tool with the following",     # opencode 工具回显
    r"^<user_input>",                             # sisyphus 模板
]
```

### B. 短句承接：上一轮意图传递

如果当前 user 消息 < 8 字符且无信息量（`执行`/`确认`/`继续`/`对`/`是`/`好`/`可以`/`不对`/`重新来`），**继承上一轮 intent**。需要 ModelGate 在请求级别维护一个 `(api_key_id, session_id) → last_intent` 的内存缓存（LRU, 30 分钟过期）。

短句白名单：
```
执行, 确认, 继续, 对, 是, 好, 可以, 不对, 不行, 重新来, 开工,
yes, ok, sure, continue, go, exactly, right, correct, 重启,
开始, 实施, 没有, 无, 详细点, 再改改
```

### C. 重写关键词（覆盖真实中文 coding 话术）

从 25k 日志里观察到的真实话术，当前完全没覆盖的：

**coding（遗漏严重）：**
```
"代码", "报错", "排查", "重启", "启动", "联通", "方法", "类",
"接口", "页面", "功能", "按钮", "逻辑", "数据", "字段",
"看一下", "检查", "验证", "对比", "分析", "调试",
"vue", "react", "html", "css", "js", "java", "python", "spring",
"mock", "字段", "数据库", "缓存", "session", "token",
"启动类", "依赖", "报错", "异常", "exception", "error",
"重置", "新增", "修改", "删除", "查询", "筛选", "列表",
"前端", "后端", "服务", "微服务",
```

**design（覆盖太窄）：**
```
"样式", "排版", "布局", "居中", "对齐", "间距", "宽度", "高度",
"颜色", "字号", "加粗", "放大", "缩小", "调整",
"美观", "好看", "不好看", "重新设计",
"原型", "界面", "组件", "导航栏", "侧边栏", "弹窗",
"设计图", "UI", "UX",
```

**writing（边界要收窄，避免误伤 coding）：**
```
# 保留：真正的创作类
"写一篇文章", "写一篇博客", "起草", "翻译这段",
"写讲解稿", "写报告", "做PPT", "生成PPT",
"写README", "写文档", "编写说明书", "写教程",

# 删除（容易误伤 coding）：
# "write a"  ← 写代码也常带这个
# "doc "     ← 太短，.doc / docx 都会命中
# "explain", "describe"  ← 调试时也常用
```

### D. 引入"上下文否定"机制

检测到下面这些**强 coding 信号**时，即使有 writing 关键词也判 coding：
- 同时出现 `报错 / 异常 / exception / error / 重启 / 启动`
- 同时出现文件路径 `\.+\.(py|js|ts|java|go|vue|html|css|json|xml|md)`
- 同时出现代码符号 `() {} [] => -> :: ;`

## 建议落地

最小改动版本（不引入 session 状态）：
1. 改 `classify_intent`：只扫 user 消息（去掉 system/assistant）
2. 加噪音过滤（HTML 注释、agent 模板）
3. 重写关键词列表（按上面）
4. 加上下文否定规则

完整版本（需要 session 缓存）：
5. 加短句承接（< 8 字符继承上一轮）

**不建议做的：**
- ❌ 用 LLM 调用做分类（每条请求多 200ms 延迟 + 成本）
- ❌ 用 tool_calls 判定（用户已说明：写文档/设计也用工具）
- ❌ 用 system prompt 来源判定（opencode 也能做设计/文档）

---

详细样本数据见 `tmp_intent_analysis.md`（25k 条日志的分类对比 + 抽样）。
