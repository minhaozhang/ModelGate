INTENT_RULES = [
    ("coding", {
        "keywords": [
            "def ", "class ", "import ", "const ", "let ",
            "console.log", "print(", "async ", "await ",
            "```python", "```javascript", "```java", "```go", "```cpp", "```typescript",
            "bug", "fix", "debug", "compile", "runtime error", "stack trace",
            "git ", "npm ", "pip ", "cargo ", "maven", "gradle",
            "API endpoint", "REST API", "webhook", "sdk",
            "refactor", "code review", "CRUD",
            "algorithm", "data structure", "leetcode",
            "syntax error", "typeerror", "nullpointer", "segfault",
            "unit test", "pytest", "jest",
            "parameter", "function", "variable", "return",
            "handler", "middleware", "endpoint", "route",
            "deploy", "build", "docker", "container",
            "\u4fee\u6539\u4ee3\u7801", "\u5199\u4e2a\u51fd\u6570", "\u5b9e\u73b0\u4e00\u4e2a",
            "\u91cd\u6784", "\u4fee\u590dbug", "\u8c03\u8bd5", "\u7f16\u8bd1",
            "\u4ee3\u7801\u5ba1\u6838", "\u6539\u4e86\u54ea\u4e9b",
            "\u4fee\u6539\u7684\u4ee3\u7801", "\u4ee3\u7801\u6539",
            "\u53d6\u6d88request", "\u805a\u5408\u7ed3\u679c",
            "\u524d\u7aef\u548c\u540e\u53f0", "\u4fee\u6539\u63a5\u53e3",
            "\u524d\u7aef\u548c\u540e\u53f0\u7684\u63a5\u53e3",
        ],
        "system_hint": [
            "coding assistant", "code assistant",
        ],
    }),
    ("writing", {
        "keywords": [
            "write a", "draft", "report", "summary", "outline",
            "article", "blog", "essay", "proposal", "memo",
            "translate", "rewrite", "paraphrase", "polish",
            "grammar", "spelling", "proofread",
            "email", "letter", "whitepaper",
            "readme", "changelog", "release notes", "markdown",
            "documentation", "doc ", "guide", "tutorial",
            "how to use", "getting started", "usage",
            "explain", "describe", "what is", "why does",
            "help me write", "help me draft",
            "bullet point", "table of contents",
            "\u5199\u4e00\u7bc7", "\u8349\u7a3f", "\u62a5\u544a", "\u603b\u7ed3", "\u63d0\u7eb2",
            "\u6587\u7ae0", "\u535a\u5ba2", "\u7ffb\u8bd1", "\u4fee\u6539\u75c5\u53e5",
            "\u6587\u6863", "\u6559\u7a0b", "\u6307\u5357", "\u8bf4\u660e\u4e66",
            "\u79d1\u666e", "\u89e3\u91ca", "\u4ec0\u4e48\u662f", "\u4ecb\u7ecd\u4e00\u4e0b",
            "\u5e2e\u6211\u5199", "\u5e2e\u6211\u62df", "\u8bb2\u89e3",
            "\u662f\u4ec0\u4e48", "\u670d\u52a1\u662f\u4ec0\u4e48",
        ],
        "system_hint": [
            "writer", "copywriter", "editor", "translator",
            "content creator", "technical writer",
        ],
    }),
    ("testing", {
        "keywords": [
            "test case", "unit test", "integration test", "e2e test",
            "pytest", "jest", "junit", "assert", "test suite",
            "coverage", "mock", "stub", "fixture", "benchmark",
            "qa", "regression", "validation", "load test", "stress test",
            "\u6d4b\u8bd5\u7528\u4f8b", "\u5355\u5143\u6d4b\u8bd5", "\u538b\u6d4b",
        ],
        "system_hint": [
            "qa engineer", "tester", "quality assurance",
        ],
    }),
    ("design", {
        "keywords": [
            "UI", "UX", "wireframe", "mockup", "prototype",
            "Figma", "Sketch", "Photoshop", "illustration",
            "logo", "icon", "color palette", "typography",
            "layout", "responsive", "user flow", "design system", "brand",
            "\u8bbe\u8ba1", "\u539f\u578b", "\u4ea4\u4e92", "\u754c\u9762",
            "\u5e03\u5c40", "\u914d\u8272", "\u7ec4\u4ef6\u8bbe\u8ba1",
        ],
        "system_hint": [
            "designer", "UI/UX", "graphic designer", "product designer",
        ],
    }),
]

DEFAULT_INTENT = "chat"

SYSTEM_HINT_WEIGHT = 1
LAST_MSG_WEIGHT = 3
HISTORY_MSG_WEIGHT = 1

_SYSTEM_REMINDER_PATTERNS = ["<system-reminder>", "</system-reminder>"]


def _strip_system_reminders(content: str) -> str:
    start = 0
    result_parts = []
    while True:
        begin = content.find("<system-reminder>", start)
        if begin == -1:
            result_parts.append(content[start:])
            break
        result_parts.append(content[start:begin])
        end = content.find("</system-reminder>", begin)
        if end == -1:
            break
        start = end + len("</system-reminder>")
    return "".join(result_parts)


def _extract_text(content) -> str:
    if isinstance(content, str):
        return _strip_system_reminders(content)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(_strip_system_reminders(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(_strip_system_reminders(item))
        return " ".join(parts)
    return str(content) if content else ""


def classify_intent(messages: list[dict]) -> str:
    if not messages:
        return DEFAULT_INTENT

    scores: dict[str, int] = {}
    for intent_name, _ in INTENT_RULES:
        scores[intent_name] = 0

    user_messages = []
    for msg in messages:
        role = msg.get("role", "")
        content = _extract_text(msg.get("content") or "")
        content_lower = content.lower()

        if role == "system":
            for intent_name, rules in INTENT_RULES:
                for hint in rules.get("system_hint", []):
                    if hint.lower() in content_lower:
                        scores[intent_name] += SYSTEM_HINT_WEIGHT

        if role in ("user", "assistant"):
            user_messages.append(content_lower)

    last_user_msg = user_messages[-1] if user_messages else ""

    for msg_content in user_messages:
        weight = LAST_MSG_WEIGHT if msg_content is last_user_msg else HISTORY_MSG_WEIGHT
        for intent_name, rules in INTENT_RULES:
            for kw in rules.get("keywords", []):
                if kw.lower() in msg_content:
                    scores[intent_name] += weight

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return DEFAULT_INTENT
    return best
