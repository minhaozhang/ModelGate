"""Intent classifier for routing optimization.

Classifies the user's intent (coding / writing / design / testing / chat) based
on the conversation's user messages. Used by the routing layer to pick models
tagged with matching intent.

Design principles (learned from 25k real production logs):

1. **Only look at user-role messages.** System prompts (opencode / cursor / sisyphus)
   and assistant replies inject coding vocabulary that has nothing to do with the
   user's actual intent.
2. **Filter agent protocol noise.** HTML comments, `<system-reminder>`,
   `[search-mode]`, tool-call echoes, etc. are framework chatter, not user intent.
3. **Short continuations inherit prior intent.** opencode sessions are full of
   2-5 char replies ("执行", "确认", "continue", "ok") that obviously carry the
   intent of the previous substantive user turn. We walk back through the same
   request's message history to find it — no server-side session state needed.
4. **Context negation.** Strong coding signals (file paths, stack traces,
   exception keywords) override writing classification even when "写/写一篇"
   appears in the same message.
"""

from __future__ import annotations

import re
from typing import Optional

__all__ = ["classify_intent", "INTENTS", "DEFAULT_INTENT"]


# ---------------------------------------------------------------------------
# Intent constants
# ---------------------------------------------------------------------------

INTENTS = ("coding", "writing", "design", "testing")
DEFAULT_INTENT = "chat"


# ---------------------------------------------------------------------------
# Noise filtering — agent framework chatter that is NOT user intent
# ---------------------------------------------------------------------------

_NOISE_PATTERNS = [
    re.compile(r"^\s*<!--.*-->\s*$", re.DOTALL),              # HTML comment wrappers (OMO_INTERNAL_INITIATOR etc.)
    re.compile(r"<system-reminder>", re.IGNORECASE),
    re.compile(r"</system-reminder>", re.IGNORECASE),
    re.compile(r"<EXTREMELY_IMPORTANT>", re.IGNORECASE),
    re.compile(r"</EXTREMELY_IMPORTANT>", re.IGNORECASE),
    re.compile(r"<Work_Context>", re.IGNORECASE),
    re.compile(r"<user_input>", re.IGNORECASE),
    re.compile(r"</user_input>", re.IGNORECASE),
    re.compile(r"<SUBAGENT-STOP>", re.IGNORECASE),
    re.compile(r"^\s*\[search-mode\]", re.IGNORECASE),
    re.compile(r"^\s*\[CONTEXT\]:", re.IGNORECASE),
    re.compile(r"^\s*\[Image\s*\d+\]", re.IGNORECASE),        # Multimodal image placeholders
    re.compile(r"^\s*Continue if you have next steps", re.IGNORECASE),
    re.compile(r"^\s*Attached media from tool result", re.IGNORECASE),
    re.compile(r"^\s*Called the .+ tool with the following", re.IGNORECASE),
    re.compile(r"^\s*Review the conversation above", re.IGNORECASE),
    re.compile(r"^\s*MAXIMIZE SEARCH EFFORT", re.IGNORECASE),
]


def _is_noise(text: str) -> bool:
    if not text or not text.strip():
        return True
    for pat in _NOISE_PATTERNS:
        if pat.search(text):
            return True
    return False


# ---------------------------------------------------------------------------
# Short-continuation phrases — inherit previous substantive intent
# ---------------------------------------------------------------------------

_SHORT_CONTINUATIONS = {
    # Chinese
    "执行", "确认", "继续", "对", "是", "好", "可以", "不对", "不行",
    "重新来", "开工", "开始", "实施", "没有", "无", "详细点", "再改改",
    "是的", "对的", "好的", "可以了", "继续吧", "执行吧", "开始吧",
    "重启", "重启一下", "重启服务", "重启起来", "重试", "再试一次",
    "下一步", "继续执行", "嗯", "嗯嗯", "继续吗", "上", "上吧", "干",
    "改", "改下", "改一下", "再改", "全部修改", "全部", "都改",
    "确认执行", "确认修改", "确认下", "确认一下",
    "无", "没有", "不需要", "不用",
    # Coding follow-up questions about prior edits — inherit prior intent
    "你改了么", "你改了吗", "改了么", "改了吗", "修改了么", "修改了吗",
    "改了没有", "改了没",
    # English
    "yes", "ok", "sure", "continue", "go", "exactly", "right",
    "correct", "yeah", "yep", "proceed", "next", "redo", "retry",
    "do it", "go ahead", "sounds good", "looks good", "lgtm",
}

_SHORT_MAX_LEN = 12  # bytes/chars — anything shorter and matching a continuation phrase


def _is_short_continuation(text: str) -> bool:
    stripped = text.strip().lower().rstrip("。，.!!,.")
    if len(stripped) > _SHORT_MAX_LEN:
        return False
    return stripped in _SHORT_CONTINUATIONS


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------

# Ordering matters: first match wins when scores tie (rare).
_INTENT_RULES = [
    (
        "coding",
        {
            "keywords": [
                # --- Code identifiers / symbols ---
                "def ", "class ", "import ", "from ", "const ", "let ", "var ",
                "function ", "return ", "async ", "await ",
                "console.log", "print(", "printf",
                "```python", "```javascript", "```java", "```go", "```cpp",
                "```typescript", "```csharp", "```rust", "```sql", "```bash",
                "():", "=>", "->", "::", "};",
                # --- Tech stack ---
                "vue", "react", "angular", "svelte",
                "html", "css", "scss", "tailwind",
                "javascript", "typescript", "python", "java", "golang", "rust",
                "c++", "c#", "kotlin", "swift",
                "springboot", "spring boot", "spring-boot", "django", "flask",
                "express", "fastapi", "nestjs",
                "docker", "kubernetes", "kubectl",
                "npm ", "yarn ", "pnpm ", "pip ", "cargo ", "maven", "gradle",
                "git ", "github", "gitlab",
                # --- Code objects (Chinese real-world usage) ---
                "代码", "类", "方法", "函数", "变量", "参数", "接口",
                "字段", "属性", "对象", "实例",
                "数据库", "缓存", "session", "token", "cookie",
                "服务", "微服务", "后端", "前端",
                "组件", "模块", "路由", "中间件", "handler",
                "页面", "按钮", "列表", "表单", "弹窗", "下拉", "筛选",
                "json", "xml", "yaml", "toml", "ini",
                "sql", "select ", "insert ", "update ", "delete ",
                # --- Coding actions ---
                "修改", "新增", "删除", "查询", "重置", "添加", "移除",
                "重构", "抽取", "封装", "优化", "改造", "升级",
                "实现", "开发", "编写代码", "写代码", "写一个",
                "mock", "mock数据", "假数据",
                "部署", "发布", "上线", "回滚",
                # --- Debug / troubleshooting ---
                "报错", "异常", "错误", "调试", "排查", "定位",
                "error", "exception", "traceback", "stack trace",
                "syntaxerror", "typeerror", "nullpointer", "segfault",
                "uncaught", "failed to", "cannot find", "undefined",
                "启动", "重启", "停止", "联通", "连接失败",
                "看一下", "检查", "验证", "对比", "分析",
                "log", "日志",
                # --- Tools ---
                "postman", "swagger", "redis", "mysql", "postgres",
                "kafka", "rabbitmq", "elasticsearch",
                # --- File extensions (code files) ---
                ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go",
                ".cs", ".cpp", ".c", ".h", ".rs", ".kt", ".swift",
                ".vue", ".svelte",
                ".sql", ".sh", ".bash",
                ".gitignore", ".env", "dockerfile", "makefile",
            ],
        },
    ),
    (
        "design",
        {
            "keywords": [
                # --- Visual / layout ---
                "排版", "布局", "居中", "对齐", "间距", "宽度", "高度",
                "侧边栏", "导航栏", "顶栏", "底栏", "面包屑", "标签页",
                "移到", "放到", "换行", "同一行", "下一行", "上一行",
                "后面", "前面", "上面", "下面", "左侧", "右侧",
                # --- Style ---
                "样式", "风格", "主题", "色调", "配色", "颜色",
                "字号", "字体", "加粗", "倾斜", "下划线",
                "放大", "缩小", "调整大小", "变宽", "变窄",
                "圆角", "阴影", "边框", "背景",
                "美观", "好看", "不好看", "丑", "精致", "优雅",
                "重新设计", "重新排版", "重新布局",
                # --- Design artifacts ---
                "设计图", "原型", "wireframe", "mockup",
                "figma", "sketch", "adobexd", "photoshop",
                "design system", "组件库",
                "ui", "ux", "user flow", "交互",
                # --- Chinese design verbs ---
                "设计", "界面设计", "交互设计", "视觉",
            ],
        },
    ),
    (
        "writing",
        {
            "keywords": [
                # --- Creation verbs (specific phrases to avoid false positives).
                # Note: bare "改写"/"写" are too generic — they match coding
                # follow-ups like "你改写了么" or UI labels. Require a qualifier.
                "写一篇", "写一份", "写个", "写一段",
                "起草", "撰写", "编撰", "创作",
                "帮我写", "帮我拟", "帮我起草",
                "帮我改写", "改写一下", "改写这段", "改写这段文字",
                "翻译这段", "翻译一下",
                "润色", "校对", "修改病句",
                # --- Document types (compound forms only — bare "报告" matches
                # UI labels like "测试报告"/"报告解读" in coding sessions) ---
                "文章", "博客", "博文", "推文",
                "总结报告", "调研报告", "评测报告", "评估报告",
                "写报告", "出报告", "生成报告",
                "提纲", "大纲",
                "演讲稿", "讲解稿", "发言稿",
                "白皮书", "说明书", "用户手册",
                "readme", "changelog", "release notes",
                "how to", "tutorial", "指南", "教程",
                # --- Office formats (only when paired with write intent) ---
                "做ppt", "做ppt文档", "生成ppt", "编写ppt",
                "做word", "生成docx", "导出word",
                # --- Research / content gathering ---
                "调研", "搜集资料", "整理资料",
                "科普", "讲解一下", "解释一下",
            ],
        },
    ),
    (
        "testing",
        {
            "keywords": [
                "test case", "test suite", "测试用例",
                "unit test", "integration test", "e2e test",
                "单元测试", "集成测试", "端到端测试", "回归测试",
                "pytest", "jest", "junit", "mocha", "cypress",
                "coverage", "覆盖率",
                "assert", "断言",
                "mock server", "mock服务",
                "qa", "质量保证",
                "压测", "性能测试", "stress test", "load test",
                "自动化测试",
            ],
            # Strong keywords: if ANY of these hit, this intent wins outright.
            # Used to override more-frequent coding keywords like "类"/"方法".
            # CAUTION: only put UNAMBIGUOUS markers here. English compounds like
            # "unit test" / "integration test" / "test case" are frequently
            # mentioned in informational contexts (e.g. AGENTS.md scaffolding,
            # CI config explanations, doc requests) — keeping them in the
            # regular `keywords` list lets them contribute to score without
            # hijacking the whole classification. Only Chinese forms and
            # explicit test-framework names are strong enough to override.
            "strong": [
                # Chinese forms — unambiguous
                "单元测试", "集成测试", "端到端测试", "回归测试",
                "测试用例", "压测", "性能测试", "自动化测试",
                # Test framework names — nobody mentions these casually
                "pytest", "jest", "junit", "mocha", "cypress",
            ],
        },
    ),
]


# ---------------------------------------------------------------------------
# Context negation: strong coding signals override writing/design
# ---------------------------------------------------------------------------

# Detect file paths like C:\...\xxx.py or /usr/src/app.js
_FILE_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/]|[\/\.])"               # drive letter or / or ./
    r"[^\s]*?"
    r"\.(?:py|js|ts|jsx|tsx|java|go|cs|cpp|c|h|rs|kt|swift|vue|svelte|"
    r"sql|sh|bash|json|xml|yaml|yml|toml|env|gitignore|"
    r"dockerfile|makefile|csproj)",
    re.IGNORECASE,
)

# Stack-trace / error-line signatures
_ERROR_LINE_PATTERN = re.compile(
    r"(?:Traceback|"
    r"at\s+[A-Za-z_$][\w$]*\s*\(|"
    r"Uncaught\s+\w*Error|"
    r"Exception\s+in\s+thread|"
    r"^\s*File\s+\".+$)",                       # python stack frames
    re.MULTILINE,
)

_CODING_OVERRIDE_KEYWORDS = {
    "报错", "异常", "exception", "error:", "traceback",
    "uncaught", "undefined", "nullpointer",
    "启动类", "启动失败", "无法启动",
    "springboot启动", "spring boot启动",
    "vue-router", "router.esm",
    "控制台报", "console报", "浏览器报",
}


# Code-identifier patterns — when 2+ distinct code identifiers appear in a
# user message, the message is almost certainly technical/coding even if no
# keyword list hit. Real example from logs:
#   "Very thorough exploration. I need to understand all downstream usage of
#    `project_result` records created by `syncPullThirdPlatformFileToSpace`"
# None of the keyword lists hit, but the identifiers are unambiguously code.
_CAMELCASE_ID = re.compile(r"\b[a-z][a-z]{2,}[A-Z][a-zA-Z]{2,}\b")
_SNAKE_CASE_ID = re.compile(r"\b[a-z]+_[a-z_]{2,}\b")
_CODE_BACKTICKS = re.compile(r"`[^`\n]{3,}`")


def _has_strong_coding_signal(text: str) -> bool:
    """Detect unambiguous coding signals in a user message.

    Args:
        text: ORIGINAL case text (camelCase detection needs case preserved).
    """
    text_lower = text.lower()
    if _FILE_PATH_PATTERN.search(text_lower):
        return True
    if _ERROR_LINE_PATTERN.search(text_lower):
        return True
    for kw in _CODING_OVERRIDE_KEYWORDS:
        if kw in text_lower:
            return True
    # Multiple distinct code identifiers — strong signal. camelCase regex
    # runs on original text (case-sensitive); snake_case + backticks on lowered.
    ids = set(_CAMELCASE_ID.findall(text))
    ids |= set(_SNAKE_CASE_ID.findall(text_lower))
    if len(ids) >= 2:
        return True
    # Backtick-wrapped code spans (≥ 2 distinct)
    if len(set(_CODE_BACKTICKS.findall(text_lower))) >= 2:
        return True
    return False


# ---------------------------------------------------------------------------
# Message extraction
# ---------------------------------------------------------------------------

def _strip_system_reminders(content: str) -> str:
    """Remove <system-reminder>...</system-reminder> blocks from content."""
    if "<system-reminder>" not in content:
        return content
    start = 0
    parts: list[str] = []
    while True:
        begin = content.find("<system-reminder>", start)
        if begin == -1:
            parts.append(content[start:])
            break
        parts.append(content[start:begin])
        end = content.find("</system-reminder>", begin)
        if end == -1:
            parts.append(content[begin:])
            break
        start = end + len("</system-reminder>")
    return "".join(parts)


def _extract_text(content) -> str:
    if isinstance(content, str):
        return _strip_system_reminders(content)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(_strip_system_reminders(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(_strip_system_reminders(item))
        return " ".join(parts)
    return str(content) if content else ""


def _extract_user_texts(messages: list[dict]) -> list[str]:
    """Extract cleaned text from user-role messages, skipping agent noise."""
    out: list[str] = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        text = _extract_text(msg.get("content") or "").strip()
        if not text or _is_noise(text):
            continue
        out.append(text)
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

_LAST_MSG_WEIGHT = 3
_HISTORY_MSG_WEIGHT = 1


def _score_intent(user_texts_lower: list[str]) -> dict[str, int]:
    scores = {name: 0 for name, _ in _INTENT_RULES}
    if not user_texts_lower:
        return scores

    last = user_texts_lower[-1]
    for i, txt in enumerate(user_texts_lower):
        weight = _LAST_MSG_WEIGHT if i == len(user_texts_lower) - 1 else _HISTORY_MSG_WEIGHT
        for intent_name, rules in _INTENT_RULES:
            for kw in rules["keywords"]:
                if kw in txt:
                    scores[intent_name] += weight

    return scores


def _pick_best(scores: dict[str, int]) -> str:
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return DEFAULT_INTENT
    return best


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_intent(messages: list[dict]) -> str:
    """Classify the user's intent from conversation messages.

    Args:
        messages: OpenAI-style message list with role/content.

    Returns:
        One of: "coding", "writing", "design", "testing", "chat"
    """
    if not messages:
        return DEFAULT_INTENT

    user_texts = _extract_user_texts(messages)
    if not user_texts:
        return DEFAULT_INTENT

    last_text = user_texts[-1]
    last_text_lower = last_text.lower()

    # --- Strong-keyword override: certain phrases are unambiguous.
    # Checked before short-continuation so "执行单元测试" still classifies
    # as testing rather than inheriting prior intent.
    for intent_name, rules in _INTENT_RULES:
        strong = rules.get("strong") or []
        for kw in strong:
            if kw in last_text_lower:
                return intent_name

    # --- Short-continuation handling: walk back through the conversation
    # history carried in the SAME request to find the previous substantive
    # user turn and reuse its intent. This handles the very common opencode
    # pattern where follow-up replies are 2-5 chars ("执行", "确认", "ok").
    if _is_short_continuation(last_text):
        for prev in reversed(user_texts[:-1]):
            if _is_short_continuation(prev):
                continue
            prev_scores = _score_intent([prev.lower()])
            prev_intent = _pick_best(prev_scores)
            if prev_intent != DEFAULT_INTENT:
                return prev_intent
            break
        # If we couldn't find a substantive prior message, fall through to
        # normal scoring (which will likely return chat — acceptable).

    user_texts_lower = [t.lower() for t in user_texts]
    scores = _score_intent(user_texts_lower)
    best = _pick_best(scores)
    if best == DEFAULT_INTENT:
        # No keyword hit. But if the last message carries strong code
        # identifiers (camelCase / snake_case table names / backticked
        # spans), it's still a coding context — default-chat would lose
        # real coding traffic. Example: "Very thorough exploration.
        # downstream usage of `project_result` created by
        # `syncPullThirdPlatformFileToSpace`".
        if _has_strong_coding_signal(last_text):
            return "coding"
        return DEFAULT_INTENT

    # --- Context negation: if the message shows strong coding signals
    # (file paths, stack traces, exception keywords), override any
    # writing/design classification. Real example from logs:
    #   "帮我写一个基于Java的markdown导出word工具类" → contains ".java" + 报错
    #   should be coding, not writing.
    if best in ("writing", "design") and _has_strong_coding_signal(last_text):
        return "coding"

    return best
