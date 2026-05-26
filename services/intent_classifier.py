INTENT_RULES = [
    ("develop", {
        "keywords": [
            "function", "def ", "class ", "import ", "const ", "let ",
            "return", "console.log", "print(", "async ", "await ",
            "```python", "```javascript", "```java", "```go",
            "bug", "fix", "debug", "compile", "runtime error",
            "git ", "npm ", "pip ", "cargo ", "API endpoint",
            "refactor", "unit test", "code review",
        ],
        "system_hint": [
            "you are a", "programming", "coding assistant",
            "developer", "software engineer",
        ],
    }),
    ("document", {
        "keywords": [
            "write a", "draft", "report", "summary", "outline",
            "article", "blog", "essay", "proposal", "memo",
            "translate", "rewrite", "paraphrase", "polish",
            "grammar", "spelling", "proofread",
        ],
        "system_hint": [
            "you are a writer", "copywriter", "editor",
        ],
    }),
    ("test", {
        "keywords": [
            "test case", "unit test", "integration test",
            "pytest", "jest", "junit", "assert",
            "coverage", "mock", "stub", "fixture",
            "qa", "regression", "validation",
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
