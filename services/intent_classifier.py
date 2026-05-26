INTENT_RULES = [
    ("coding", {
        "keywords": [
            "function", "def ", "class ", "import ", "const ", "let ",
            "return", "console.log", "print(", "async ", "await ",
            "```python", "```javascript", "```java", "```go", "```cpp",
            "bug", "fix", "debug", "compile", "runtime error",
            "git ", "npm ", "pip ", "cargo ", "maven", "gradle",
            "API endpoint", "REST API", "webhook", "sdk",
            "refactor", "code review", "CRUD", "database",
            "algorithm", "data structure", "leetcode",
        ],
        "system_hint": [
            "programming", "coding assistant", "developer",
            "software engineer", "backend", "frontend", "fullstack",
        ],
    }),
    ("writing", {
        "keywords": [
            "write a", "draft", "report", "summary", "outline",
            "article", "blog", "essay", "proposal", "memo",
            "translate", "rewrite", "paraphrase", "polish",
            "grammar", "spelling", "proofread",
            "email", "letter", "document", "whitepaper",
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
            "layout", "responsive", "component",
            "user flow", "design system", "brand",
        ],
        "system_hint": [
            "designer", "UI/UX", "graphic designer", "product designer",
        ],
    }),
]

DEFAULT_INTENT = "chat"


def classify_intent(messages: list[dict]) -> str:
    if not messages:
        return DEFAULT_INTENT

    scores: dict[str, int] = {}
    for intent_name, _ in INTENT_RULES:
        scores[intent_name] = 0

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
                        scores[intent_name] += 3

        if role in ("user", "assistant"):
            for intent_name, rules in INTENT_RULES:
                for kw in rules.get("keywords", []):
                    if kw.lower() in content_lower:
                        scores[intent_name] += 1

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return DEFAULT_INTENT
    return best
