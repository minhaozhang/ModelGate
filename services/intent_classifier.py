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


def classify_intent(messages: list[dict]) -> str:
    if not messages:
        return DEFAULT_INTENT

    scores: dict[str, int] = {}
    for intent_name, _ in INTENT_RULES:
        scores[intent_name] = 0

    user_messages = []
    for msg in messages:
        role = msg.get("role", "")
        content = (msg.get("content") or "")
        if not isinstance(content, str):
            content = str(content) if content else ""
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
