"""Coding-only model access gate.

Some models are reserved for real programming-agent workloads (Claude Code,
Codex CLI, OpenCode, DSH ...). Admins flag them with ``models.coding_only``;
this module decides — leniently — whether an inbound request looks like a
programming-tool request or like knowledge-base / chatbot / generic-SDK
traffic that should be sent elsewhere.

Decision order (first match wins):

1.  Inbound protocol ``responses`` (Codex wire API) or ``anthropic``
    (Claude Code / Anthropic SDK wire API)  -> allow (tool-native endpoint)
2.  User-Agent carries a known coding-tool marker            -> allow
3.  System prompt carries a coding-agent marker              -> allow
4.  System prompt carries a chatbot / knowledge-base marker  -> reject
5.  User-Agent carries a generic SDK/client marker           -> reject
6.  Estimated context below ``coding_gate.min_context_tokens``
    (default 10000)                                          -> reject
7.  Anything else (unknown but heavy, non-bot traffic)       -> allow

All matching is case-insensitive substring matching, so a marker like
``"codex"`` also matches ``"codex_cli_rs/0.9.3"``.
"""
from __future__ import annotations

import app.core.config as config

__all__ = [
    "evaluate_coding_gate",
    "DEFAULT_MIN_CONTEXT_TOKENS",
    "coding_gate_rejection_message",
]

DEFAULT_MIN_CONTEXT_TOKENS = 10000

# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

# Requests arriving on these inbound protocols are tool-native traffic:
# /v1/responses is the Codex CLI wire API, /v1/messages is what Claude Code
# and Anthropic-SDK based coding tools speak.
CODING_INBOUND_PROTOCOLS = {"responses", "anthropic"}

# User-Agent substrings of known coding tools. Kept broad on purpose:
# "codex" also covers codex_cli_rs, "claude-cli"/"claude code" cover Claude
# Code, "opencode" covers opencode's "opencode/local ai-sdk/... runtime/node".
CODING_TOOL_UA_KEYWORDS = (
    "opencode",
    "claude-cli",
    "claude code",
    "claude-code",
    "codex",
    "cursor",
    "windsurf",
    "cline",
    "roo-code",
    "roo code",
    "kilocode",
    "kilo code",
    "gemini-cli",
    "aider",
    "continue/",
    "dsh/",
    "deepseek-harness",
    "deepseek harness",
    "trae",
    "codebuddy",
    "copilot",
    "codeium",
    "tabnine",
    "zed/",
    "pearai",
    "goose",
    "openhands",
    "devin",
    "sweeper",
    "pi/",
    "pi-ai",
)

# User-Agent substrings of generic programmatic clients. Requests from these
# are chat-bot / RAG-pipeline style traffic unless a stronger coding signal
# (endpoint protocol, system prompt) says otherwise. Calibrated against real
# production traffic (2026-10-06): the top offender is Python-urllib (82% of
# requests), then OpenAI/Python and OpenAI/JS SDKs.
GENERIC_CLIENT_UA_KEYWORDS = (
    "python-urllib",
    "python-requests",
    "python-httpx",
    "openai/",  # OpenAI/Python, OpenAI/JS, OpenAI/Java, OpenAI/Go SDKs
    "openai-python",
    "go-http-client",
    "java/",
    "apache-httpclient",
    "okhttp/",
    "axios/",
    "node-fetch",
    "undici",
    "aiohttp/",
    "guzzle",
    "http.rb",
    "restsharp",
    "curl/",
    "postmanruntime",
    "insomnia",
    "hoppscotch",
    "apifox",
    "langchain",
    "llamaindex",
    "dify",
    "coze",
    "fastgpt",
    "ragflow",
    "maxkb",
    "openwebui",
    "open-webui",
    "lobehub",
    "nextchat",
    "chatgpt-next-web",
)

# System-prompt substrings that mark a coding agent. Coding tools ship rich,
# distinctive prompts ("You are Claude Code ...", "You are a coding agent ...").
CODING_SYSTEM_MARKERS = (
    "you are claude code",
    "you are codex",
    "you are opencode",
    "you are an interactive cli tool",
    "you are a coding agent",
    "coding agent",
    "agentic coding",
    "coding assistant",
    "software engineering",
    "programming assistant",
    "编程助手",
    "代码助手",
    "编程智能体",
    "代码补全",
    "结对编程",
    "deepseek harness",
    "terminal-based coding",
    "ide integration",
)

# System-prompt substrings that mark chatbot / knowledge-base / customer
# service bots and non-coding batch workloads (LLM-judge / eval / annotation
# pipelines). Deliberately concrete: bare "assistant"/"agent" must NOT
# appear here because coding prompts use those words constantly.
BOT_SYSTEM_MARKERS = (
    "知识库",
    "客服",
    "聊天机器人",
    "你是机器人",
    "智能客服",
    "数字人",
    "虚拟主播",
    "智能问答",
    "检索增强",
    "基于以下资料",
    "根据资料回答",
    "知识问答",
    "企业助手",
    "打分",
    "评分",
    "裁判",
    "标注员",
    "entailment",
    "judge whether",
    "you are a judge",
    "you are a strict",
    "numeric score in [0",
    "return only one valid json",
    "relevance score",
    "chatbot",
    "knowledge base",
    "customer service",
    "faq bot",
    "virtual assistant for customer",
)

_SYSTEM_TEXT_CAP_CHARS = 20000


def _min_context_tokens() -> int:
    raw = (config.system_settings or {}).get("coding_gate.min_context_tokens")
    if raw is None:
        return DEFAULT_MIN_CONTEXT_TOKENS
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return DEFAULT_MIN_CONTEXT_TOKENS
    return value if value > 0 else DEFAULT_MIN_CONTEXT_TOKENS


def _system_text(messages: list) -> str:
    """Concatenated system-role content (developer role included), capped."""
    parts: list[str] = []
    total = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").lower()
        if role not in ("system", "developer"):
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict)
            )
        else:
            continue
        parts.append(text)
        total += len(text)
        if total >= _SYSTEM_TEXT_CAP_CHARS:
            break
    return "\n".join(parts)[:_SYSTEM_TEXT_CAP_CHARS]


def _first_user_text(messages: list) -> str:
    """First user-role message, capped.

    Eval/judge pipelines often ship their whole instruction as a single user
    message with no system role ("You are a strict path entailment judge.
    ..."), so the non-coding markers must look here too. Allow-markers never
    scan this — a bot quoting coding vocabulary in a user message must not
    pass the gate.
    """
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").lower() != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict)
            )
        else:
            continue
        return text[:_SYSTEM_TEXT_CAP_CHARS]
    return ""


def _match_any(haystack_lower: str, markers: tuple[str, ...]) -> str | None:
    for marker in markers:
        if marker in haystack_lower:
            return marker
    return None


def evaluate_coding_gate(
    *,
    messages: list,
    context_tokens: int,
    user_agent: str,
    inbound_protocol: str = "openai",
) -> tuple[bool, str, str]:
    """Return ``(allowed, reason, detail)``.

    ``reason`` is a stable machine-readable tag used in logs/429 payloads:
    coding_endpoint / coding_tool_ua / coding_system_prompt /
    bot_system_prompt / generic_client_ua / below_min_context /
    unclassified_large_context. ``detail`` is the matched marker (if any)
    for the log line.
    """
    protocol = (inbound_protocol or "openai").lower()
    if protocol in CODING_INBOUND_PROTOCOLS:
        return True, "coding_endpoint", protocol

    ua = (user_agent or "").lower()
    ua_marker = _match_any(ua, CODING_TOOL_UA_KEYWORDS)
    if ua_marker:
        return True, "coding_tool_ua", ua_marker

    system_lower = _system_text(messages or []).lower()
    coding_marker = _match_any(system_lower, CODING_SYSTEM_MARKERS)
    if coding_marker:
        return True, "coding_system_prompt", coding_marker

    # Non-coding markers scan system roles AND the first user message (eval
    # pipelines put their whole judge instruction into a single user turn).
    bot_haystack = system_lower + "\n" + _first_user_text(messages or []).lower()
    bot_marker = _match_any(bot_haystack, BOT_SYSTEM_MARKERS)
    if bot_marker:
        return False, "bot_system_prompt", bot_marker

    generic_marker = _match_any(ua, GENERIC_CLIENT_UA_KEYWORDS)
    if generic_marker:
        return False, "generic_client_ua", generic_marker

    min_tokens = _min_context_tokens()
    if int(context_tokens or 0) < min_tokens:
        return False, "below_min_context", f"{context_tokens}<{min_tokens}"

    return True, "unclassified_large_context", f"{context_tokens}>= {min_tokens}"


def coding_gate_rejection_message(model: str, reason: str, detail: str) -> str:
    # Deliberately vague: do not reveal the detection criteria (tools, UA,
    # prompt markers) to callers. Details live in the [CODING GATE] log line.
    return "该模型仅面向编程使用。"


# Internal ModelGate callers (scheduler health checks, report analysis ...)
# hit the gate too, but infrastructure probes must never be blocked by a
# usage policy — exempt them by purpose.
INTERNAL_GATE_EXEMPT_PURPOSES = {"glm-health-check"}


def evaluate_internal_coding_gate(
    *,
    model: str,
    purpose: str,
    messages: list,
    context_tokens: int,
    user_agent: str,
) -> str | None:
    """Gate wrapper for internal callers.

    Returns the rejection message (block) or None (allow). Infrastructure
    purposes listed in ``INTERNAL_GATE_EXEMPT_PURPOSES`` always pass.
    """
    if (purpose or "") in INTERNAL_GATE_EXEMPT_PURPOSES:
        return None
    allowed, reason, detail = evaluate_coding_gate(
        messages=messages,
        context_tokens=context_tokens,
        user_agent=user_agent,
    )
    if allowed:
        return None
    return coding_gate_rejection_message(model, reason, detail)
