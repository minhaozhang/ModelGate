import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func

from core.config import validate_session, providers_cache, logger
from core.database import (
    async_session_maker,
    RequestLogRead as RequestLog,
    AnalysisRecord,
    Provider,
    ApiKey,
)
from core.i18n import get_locale, translate
from services.analysis_store import (
    ANALYSIS_STATUS_FAILED,
    ANALYSIS_STATUS_PENDING,
    ANALYSIS_STATUS_RUNNING,
    ANALYSIS_STATUS_SUCCESS,
    ANALYSIS_TYPE_DAILY_ERROR_REPORT,
    get_analysis_record,
    get_report_root,
    read_report_markdown,
    start_analysis_task,
    upsert_analysis_record,
    write_report_markdown,
)
from services.proxy import call_internal_model_via_proxy

router = APIRouter(prefix="/admin/api", tags=["logs"])
ERROR_STATUSES = ("error", "timeout")
ERROR_REPORT_SAMPLE_LIMIT = 120
ERROR_REPORT_LOG_LIMIT = 200


class AnalysisRequest(BaseModel):
    language: Optional[str] = None
    model: Optional[str] = None


CONTEXT_BUCKETS = [
    (0, 8192, "0-8k"),
    (8192, 16384, "8k-16k"),
    (16384, 32768, "16k-32k"),
    (32768, 65536, "32k-64k"),
    (65536, 98304, "64k-96k"),
    (98304, 131072, "96k-128k"),
    (131072, None, "128k+"),
]


def require_admin(session: Optional[str] = Cookie(None)):
    if not validate_session(session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


def get_token_count(tokens_payload) -> int:
    return (
        (tokens_payload or {}).get("total_tokens")
        or (tokens_payload or {}).get("estimated")
        or 0
    )


async def _get_maps(
    session, logs: list[RequestLog]
) -> tuple[dict[int, str], dict[int, str]]:
    provider_ids = {log.provider_id for log in logs if log.provider_id is not None}
    api_key_ids = {log.api_key_id for log in logs if log.api_key_id is not None}

    provider_map: dict[int, str] = {}
    if provider_ids:
        provider_result = await session.execute(
            select(Provider).where(Provider.id.in_(provider_ids))
        )
        provider_map = {
            provider.id: provider.name for provider in provider_result.scalars()
        }

    api_key_map: dict[int, str] = {}
    if api_key_ids:
        api_key_result = await session.execute(
            select(ApiKey).where(ApiKey.id.in_(api_key_ids))
        )
        api_key_map = {api_key.id: api_key.name for api_key in api_key_result.scalars()}

    return provider_map, api_key_map


def _serialize_error_log(
    log: RequestLog,
    provider_map: dict[int, str],
    api_key_map: dict[int, str],
) -> dict:
    return {
        "id": log.id,
        "provider": provider_map.get(log.provider_id, "-")
        if log.provider_id is not None
        else "-",
        "api_key": api_key_map.get(log.api_key_id, f"Key-{log.api_key_id}")
        if log.api_key_id is not None
        else "-",
        "model": log.model,
        "status": log.status,
        "upstream_status_code": log.upstream_status_code,
        "latency_ms": log.latency_ms,
        "request_context_tokens": log.request_context_tokens,
        "tokens": log.tokens,
        "client_ip": log.client_ip,
        "user_agent": log.user_agent,
        "error": log.error,
        "created_at": log.created_at.isoformat(),
    }


def _build_error_summary(logs: list[dict]) -> dict:
    total = len(logs)
    total_timeouts = sum(1 for log in logs if log.get("status") == "timeout")
    total_errors = total - total_timeouts

    provider_counter = Counter(log.get("provider") or "-" for log in logs)
    model_counter = Counter(log.get("model") or "-" for log in logs)
    status_code_counter = Counter(
        str(log.get("upstream_status_code"))
        for log in logs
        if log.get("upstream_status_code") is not None
    )
    context_values = [
        int(log.get("request_context_tokens") or 0)
        for log in logs
        if int(log.get("request_context_tokens") or 0) > 0
    ]
    timeout_context_values = [
        int(log.get("request_context_tokens") or 0)
        for log in logs
        if log.get("status") == "timeout"
        and int(log.get("request_context_tokens") or 0) > 0
    ]

    return {
        "total_logs": total,
        "total_errors": total_errors,
        "total_timeouts": total_timeouts,
        "top_providers": provider_counter.most_common(5),
        "top_models": model_counter.most_common(5),
        "top_status_codes": status_code_counter.most_common(5),
        "avg_context_tokens": round(sum(context_values) / len(context_values), 1)
        if context_values
        else None,
        "max_context_tokens": max(context_values) if context_values else None,
        "avg_timeout_context_tokens": round(
            sum(timeout_context_values) / len(timeout_context_values), 1
        )
        if timeout_context_values
        else None,
    }


def _format_top_items(items: list[tuple[str, int]]) -> str:
    if not items:
        return "-"
    return ", ".join(f"{name} ({count})" for name, count in items[:5])


def _percentile(values: list[float], ratio: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * ratio))))
    return ordered[index]


def _get_context_bucket_label(tokens: Optional[int]) -> str:
    value = int(tokens or 0)
    for start, end, label in CONTEXT_BUCKETS:
        if end is None and value >= start:
            return label
        if end is not None and start <= value < end:
            return label
    return CONTEXT_BUCKETS[0][2]


def _serialize_analysis_log(log: RequestLog, provider_map: dict[int, str]) -> dict:
    return {
        "provider": provider_map.get(log.provider_id, "-")
        if log.provider_id is not None
        else "-",
        "model": log.model or "-",
        "status": log.status,
        "latency_ms": float(log.latency_ms or 0),
        "request_context_tokens": int(log.request_context_tokens or 0),
        "upstream_status_code": log.upstream_status_code,
    }


def _build_context_risk_summary(logs: list[dict]) -> list[dict]:
    grouped: dict[str, dict[str, list[dict]]] = {}
    for log in logs:
        model_name = log.get("model") or "-"
        bucket_label = _get_context_bucket_label(log.get("request_context_tokens"))
        grouped.setdefault(model_name, {}).setdefault(bucket_label, []).append(log)

    summaries: list[dict] = []
    for model_name, bucket_map in grouped.items():
        bucket_rows: list[dict] = []
        slow_threshold = None
        timeout_threshold = None
        error_threshold = None

        for _, _, bucket_label in CONTEXT_BUCKETS:
            items = bucket_map.get(bucket_label, [])
            if not items:
                continue
            requests_count = len(items)
            latencies = [
                float(item.get("latency_ms") or 0)
                for item in items
                if float(item.get("latency_ms") or 0) > 0
            ]
            timeout_count = sum(1 for item in items if item.get("status") == "timeout")
            error_count = sum(
                1 for item in items if item.get("status") in ERROR_STATUSES
            )
            avg_latency_ms = (
                round(sum(latencies) / len(latencies), 1) if latencies else None
            )
            p95_latency_ms = (
                round(_percentile(latencies, 0.95), 1) if latencies else None
            )
            timeout_rate = timeout_count / requests_count if requests_count else 0.0
            error_rate = error_count / requests_count if requests_count else 0.0

            bucket_rows.append(
                {
                    "bucket": bucket_label,
                    "requests": requests_count,
                    "avg_latency_ms": avg_latency_ms,
                    "p95_latency_ms": p95_latency_ms,
                    "timeout_rate": round(timeout_rate, 4),
                    "error_rate": round(error_rate, 4),
                }
            )

            if (
                slow_threshold is None
                and requests_count >= 5
                and p95_latency_ms is not None
                and p95_latency_ms >= 20000
            ):
                slow_threshold = bucket_label
            if (
                timeout_threshold is None
                and requests_count >= 5
                and timeout_rate >= 0.05
            ):
                timeout_threshold = bucket_label
            if error_threshold is None and requests_count >= 5 and error_rate >= 0.08:
                error_threshold = bucket_label

        total_requests = sum(item["requests"] for item in bucket_rows)
        if total_requests <= 0:
            continue

        summaries.append(
            {
                "model": model_name,
                "requests": total_requests,
                "slow_threshold": slow_threshold,
                "timeout_threshold": timeout_threshold,
                "error_threshold": error_threshold,
                "buckets": bucket_rows,
            }
        )

    summaries.sort(
        key=lambda item: (
            -(1 if item["timeout_threshold"] else 0),
            -(1 if item["error_threshold"] else 0),
            -(1 if item["slow_threshold"] else 0),
            -item["requests"],
            item["model"],
        )
    )
    return summaries


def _build_opencode_suggestions(
    request: Request, context_summary: list[dict]
) -> list[dict]:
    suggestions: list[dict] = []
    for item in context_summary[:6]:
        context_limit = 131072
        output_limit = 8192
        note = translate(
            request,
            "No clear risk threshold is visible yet, so keep a conservative default and continue observing.",
        )

        if item["timeout_threshold"] == "32k-64k":
            context_limit = 32768
            output_limit = 4096
            note = translate(
                request,
                "Timeouts start to rise around 32k-64k context, so a stricter context cap is safer.",
            )
        elif item["timeout_threshold"] in {"64k-96k", "96k-128k", "128k+"}:
            context_limit = 65536
            output_limit = 4096
            note = translate(
                request,
                "Timeout risk becomes visible at larger contexts, so limiting long sessions can improve stability.",
            )
        elif item["error_threshold"] in {"32k-64k", "64k-96k"}:
            context_limit = 32768
            output_limit = 6144
            note = translate(
                request,
                "Error rate rises once context grows, so use a moderate context ceiling for OpenCode.",
            )
        elif item["slow_threshold"]:
            context_limit = 65536
            output_limit = 6144
            note = translate(
                request,
                "Latency grows materially at higher context, so reduce context and output together for smoother usage.",
            )

        suggestions.append(
            {
                "model": item["model"],
                "context": context_limit,
                "output": output_limit,
                "note": note,
            }
        )
    return suggestions


def _format_context_risk_lines(
    request: Request, context_summary: list[dict]
) -> list[str]:
    if not context_summary:
        return [
            f"- {translate(request, 'There is not enough completed traffic today to infer a stable context threshold yet.')}"
        ]

    lines: list[str] = []
    for item in context_summary[:6]:
        slow_text = item["slow_threshold"] or translate(request, "not obvious yet")
        timeout_text = item["timeout_threshold"] or translate(
            request, "not obvious yet"
        )
        error_text = item["error_threshold"] or translate(request, "not obvious yet")
        lines.append(
            "- "
            + translate(
                request,
                "{model}: slows down around {slow}, timeout risk rises around {timeout}, and error risk rises around {error}.",
                model=item["model"],
                slow=slow_text,
                timeout=timeout_text,
                error=error_text,
            )
        )
    return lines


def _format_bucket_table_markdown(context_summary: list[dict]) -> str:
    rows = [
        "| Model | Bucket | Requests | Avg Latency(ms) | P95(ms) | Timeout Rate | Error Rate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in context_summary[:4]:
        for bucket in item["buckets"]:
            rows.append(
                f"| {item['model']} | {bucket['bucket']} | {bucket['requests']} | "
                f"{bucket['avg_latency_ms'] or '-'} | {bucket['p95_latency_ms'] or '-'} | "
                f"{bucket['timeout_rate']:.1%} | {bucket['error_rate']:.1%} |"
            )
    return "\n".join(rows)


def _build_rule_based_markdown(
    summary: dict, context_summary: list[dict], request: Request
) -> str:
    findings: list[str] = []
    recommendations: list[str] = []

    if summary["total_timeouts"] > 0:
        findings.append(
            translate(
                request,
                "Timeouts are present today, which suggests some requests are exceeding the proxy timeout window or upstream is stalling",
            )
        )
        recommendations.append(
            translate(
                request,
                "Inspect timeout samples first and compare their request_context_tokens to see whether oversized context is a common trigger",
            )
        )

    if summary["top_status_codes"]:
        top_status_code, top_status_count = summary["top_status_codes"][0]
        findings.append(
            translate(
                request,
                "The most common upstream status today is {status_code} with {count} records",
                status_code=top_status_code,
                count=top_status_count,
            )
        )
        if top_status_code == "429":
            recommendations.append(
                translate(
                    request,
                    "Check provider-side rate limiting and reduce burst concurrency or add provider-side capacity",
                )
            )
        elif top_status_code == "500":
            recommendations.append(
                translate(
                    request,
                    "Review provider-side stability and correlate 500 responses with oversized prompts or specific models",
                )
            )

    if summary["max_context_tokens"] and summary["max_context_tokens"] >= 80000:
        findings.append(
            translate(
                request,
                "Very large request contexts appeared today, and they may be amplifying latency or upstream failures",
            )
        )
        recommendations.append(
            translate(
                request,
                "Trim prompt history or tool schema size for high-context requests and compare whether the same provider/model becomes more stable",
            )
        )

    if summary["top_providers"]:
        provider_name, provider_count = summary["top_providers"][0]
        findings.append(
            translate(
                request,
                "The provider with the most failures today is {provider} with {count} logs",
                provider=provider_name,
                count=provider_count,
            )
        )

    if not recommendations:
        recommendations.append(
            translate(
                request,
                "Review the top failing provider-model combinations and prioritize the ones with repeated upstream 500 or timeout patterns",
            )
        )

    summary_text = translate(
        request,
        "Today there are {total_logs} failure logs, including {total_errors} errors and {total_timeouts} timeouts.",
        total_logs=summary["total_logs"],
        total_errors=summary["total_errors"],
        total_timeouts=summary["total_timeouts"],
    )

    opencode_suggestions = _build_opencode_suggestions(request, context_summary)

    lines = [
        f"# {translate(request, 'Daily Error Analysis Report')}",
        "",
        f"## {translate(request, 'Executive Summary')}",
        summary_text,
        "",
        f"## {translate(request, 'Hotspots')}",
        f"- {translate(request, 'Top providers')}: {_format_top_items(summary['top_providers'])}",
        f"- {translate(request, 'Top models')}: {_format_top_items(summary['top_models'])}",
        f"- {translate(request, 'Top upstream status codes')}: {_format_top_items(summary['top_status_codes'])}",
        f"- {translate(request, 'Max context tokens')}: {summary['max_context_tokens'] or '-'}",
        f"- {translate(request, 'Average timeout context')}: {summary['avg_timeout_context_tokens'] or '-'}",
        "",
        f"## {translate(request, 'Model Context Risk Analysis')}",
    ]
    lines.extend(_format_context_risk_lines(request, context_summary))
    lines.append("")
    if context_summary:
        lines.append(_format_bucket_table_markdown(context_summary))
        lines.append("")
    lines.append(f"## {translate(request, 'Key Findings')}")
    lines.extend(
        [f"- {item}" for item in findings]
        or [
            f"- {translate(request, 'No dominant anomaly is visible from the current rule-based summary.')}"
        ]
    )
    lines.append("")
    lines.append(f"## {translate(request, 'OpenCode Configuration Suggestions')}")
    if opencode_suggestions:
        for item in opencode_suggestions:
            lines.append(
                "- "
                + translate(
                    request,
                    "{model}: suggest limit.context={context}, limit.output={output}. {note}",
                    model=item["model"],
                    context=item["context"],
                    output=item["output"],
                    note=item["note"],
                )
            )
    else:
        lines.append(
            f"- {translate(request, 'There is not enough data yet to suggest per-model OpenCode limits.')}"
        )
    lines.append("")
    lines.append("```json")
    lines.append("{")
    lines.append('  "provider": {')
    lines.append('    "model-token-plan": {')
    lines.append('      "models": {')
    preview_suggestions = opencode_suggestions[:3]
    for index, item in enumerate(preview_suggestions):
        suffix = "," if index < len(preview_suggestions) - 1 else ""
        lines.append(
            f'        "{item["model"]}": {{"limit": {{"context": {item["context"]}, "output": {item["output"]}}}}}{suffix}'
        )
    lines.append("      }")
    lines.append("    }")
    lines.append("  }")
    lines.append("}")
    lines.append("```")
    lines.append("")
    lines.append(f"## {translate(request, 'Recommended Actions')}")
    lines.extend([f"- {item}" for item in recommendations])
    lines.append("")
    lines.append(f"## {translate(request, 'How to Read This Report')}")
    lines.append(
        translate(
            request,
            "Use this report as an operational summary for incident review, shift handoff, or OpenCode limit tuning. Focus first on the bucket where latency, timeout rate, or error rate starts to jump materially.",
        )
    )
    return "\n".join(lines)


def _extract_text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


_COT_LINE_RE = re.compile(r"^\d+\.\s+\*\*")
_SUB_BULLET_RE = re.compile(r"^\s+\*\*")
_GENERIC_COT_RE = re.compile(r"^\s*[-*]\s+\*")


def _strip_cot_from_content(text: str) -> str:
    if not text or not isinstance(text, str):
        return text
    lines = text.splitlines()
    has_cot = any(_COT_LINE_RE.match(line) for line in lines[:5])
    if not has_cot:
        return text
    non_cot_lines = [
        line
        for line in lines
        if not _COT_LINE_RE.match(line)
        and not _SUB_BULLET_RE.match(line)
        and not _GENERIC_COT_RE.match(line)
        and line.strip()
    ]
    if non_cot_lines:
        return "\n".join(non_cot_lines).strip()
    return ""


def _strip_code_fence(text: str) -> str:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return raw


def _choose_analysis_model() -> tuple[Optional[str], Optional[dict], Optional[str]]:
    preferred_models = ("glm-5-turbo", "glm-5", "glm-4.6", "glm-4.7")
    preferred_providers = ("zhipu", "deepseek", "minimax", "ollama")
    for provider_name in preferred_providers:
        provider_config = providers_cache.get(provider_name)
        if not provider_config:
            continue
        models = provider_config.get("models") or []
        for preferred in preferred_models:
            for model in models:
                actual_model_name = model.get("actual_model_name") or model.get(
                    "model_name"
                )
                if actual_model_name == preferred:
                    return provider_name, provider_config, actual_model_name
        for model in models:
            actual_model_name = model.get("actual_model_name") or model.get(
                "model_name"
            )
            if actual_model_name:
                return provider_name, provider_config, actual_model_name
    for provider_name, provider_config in providers_cache.items():
        models = provider_config.get("models") or []
        for model in models:
            actual_model_name = model.get("actual_model_name") or model.get(
                "model_name"
            )
            if actual_model_name:
                return provider_name, provider_config, actual_model_name
    return None, None, None


def _chunk_list(items: list, chunk_size: int) -> list[list]:
    if chunk_size <= 0:
        return [items]
    return [
        items[index : index + chunk_size] for index in range(0, len(items), chunk_size)
    ]


async def _call_analysis_model(
    provider_name: str,
    actual_model_name: str,
    system_prompt: str,
    prompt_payload: dict,
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> tuple[Optional[str], Optional[str]]:
    requested_model = f"{provider_name}/{actual_model_name}"

    model_config = None
    provider_cfg = providers_cache.get(provider_name)
    if provider_cfg:
        for m in provider_cfg.get("models", []):
            if m.get("actual_model_name") == actual_model_name:
                model_config = m
                break

    db_max_tokens = (model_config or {}).get("max_tokens", 16384)
    thinking_enabled = (model_config or {}).get("thinking_enabled", False)

    if thinking_enabled:
        effective_max_tokens = max(db_max_tokens, max_tokens)
    else:
        effective_max_tokens = (
            min(max_tokens, db_max_tokens) if max_tokens else db_max_tokens
        )

    body_json = {
        "model": requested_model,
        "temperature": temperature,
        "max_tokens": effective_max_tokens,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": json.dumps(prompt_payload, ensure_ascii=False),
            },
        ],
    }

    try:
        result = await call_internal_model_via_proxy(
            requested_model=requested_model,
            body_json=body_json,
            purpose="error-analysis",
            timeout_seconds=90.0,
        )
        if not result.get("ok"):
            return None, str(result.get("error") or f"HTTP {result.get('status_code')}")

        payload = result.get("payload")
        if not isinstance(payload, dict):
            return None, "invalid_payload"

        message = ((payload.get("choices") or [{}])[0]).get("message") or {}
        content = _strip_cot_from_content(_extract_text_content(message.get("content")))
        if not content:
            content = _extract_text_content(message.get("reasoning_content"))
        text = _strip_code_fence(content)
        if not text:
            return None, "empty_response"
        return text, None
    except Exception as exc:
        return None, str(exc)


def _build_error_report_scope(report_date: str, locale: str, seq: int = 1) -> str:
    return f"{report_date}:{locale}:{seq}"


async def _next_error_report_seq(report_date: str, locale: str) -> int:
    prefix = f"{report_date}:{locale}:"
    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisRecord.scope_key).where(
                AnalysisRecord.analysis_type == ANALYSIS_TYPE_DAILY_ERROR_REPORT,
                AnalysisRecord.scope_key.startswith(prefix),
            )
        )
        existing = result.scalars().all()
    max_seq = 0
    for sk in existing:
        try:
            max_seq = max(max_seq, int(sk.split(":")[-1]))
        except (ValueError, IndexError):
            pass
    return max_seq + 1


def _build_error_report_file_path(report_date: str, locale: str, seq: int = 1) -> Path:
    return get_report_root() / "errors" / report_date / locale / f"{seq}.md"


def _serialize_report_record(record, markdown: Optional[str] = None) -> dict:
    source = "pending"
    if record.status == ANALYSIS_STATUS_SUCCESS:
        source = "ai"
    elif record.status == ANALYSIS_STATUS_FAILED:
        source = "unavailable"
    if record.status == ANALYSIS_STATUS_SUCCESS and not markdown:
        source = "unavailable"

    return {
        "source": source,
        "model_used": record.model_used,
        "generated_at": record.updated_at.isoformat() if record.updated_at else None,
        "markdown": markdown or "",
        "error": record.error,
    }


async def _generate_error_report_with_ai(
    locale: str,
    summary: dict,
    logs: list[dict],
    context_summary: list[dict],
    model_override: Optional[str] = None,
) -> dict:
    if model_override and "/" in model_override:
        override_provider, override_actual = model_override.split("/", 1)
        override_config = providers_cache.get(override_provider)
        if override_config:
            provider_name, provider_config, actual_model_name = (
                override_provider,
                override_config,
                override_actual,
            )
        else:
            provider_name, provider_config, actual_model_name = _choose_analysis_model()
    else:
        provider_name, provider_config, actual_model_name = _choose_analysis_model()
    if not provider_name or not provider_config or not actual_model_name:
        return {
            "source": "unavailable",
            "model_used": None,
            "generated_at": datetime.now().isoformat(),
            "markdown": "",
            "error": "no_available_analysis_model",
        }

    sample_logs = logs[:ERROR_REPORT_SAMPLE_LIMIT]
    language_name = "Chinese" if locale == "zh" else "English"
    chunked_context = _chunk_list(context_summary[:12], 4)
    chunked_logs = _chunk_list(
        [
            {
                "time": log["created_at"],
                "provider": log["provider"],
                "model": log["model"],
                "status": log["status"],
                "upstream_status_code": log["upstream_status_code"],
                "latency_ms": log["latency_ms"],
                "request_context_tokens": log["request_context_tokens"],
                "error": (log.get("error") or "")[:240],
            }
            for log in sample_logs
        ],
        25,
    )
    total_chunks = max(len(chunked_context), len(chunked_logs), 1)
    chunk_summaries: list[dict] = []

    for index in range(total_chunks):
        prompt = {
            "language": language_name,
            "task": (
                "Analyze only this chunk of LLM gateway data. "
                "Return strict JSON only and keep it compact."
            ),
            "response_format": {
                "chunk_summary": "string",
                "risk_points": ["string"],
                "configuration_hints": ["string"],
            },
            "chunk_index": index + 1,
            "total_chunks": total_chunks,
            "summary_metrics": summary if index == 0 else None,
            "context_buckets_definition": [bucket[2] for bucket in CONTEXT_BUCKETS],
            "model_context_risk_summary": chunked_context[index]
            if index < len(chunked_context)
            else [],
            "sample_logs": chunked_logs[index] if index < len(chunked_logs) else [],
        }
        content, error = await _call_analysis_model(
            provider_name=provider_name,
            actual_model_name=actual_model_name,
            system_prompt=(
                "You analyze operational incident logs for an LLM proxy dashboard. "
                "Do not invent facts. Reply with strict JSON only."
            ),
            prompt_payload=prompt,
            max_tokens=2000,
        )
        if not content:
            logger.warning(
                "[ADMIN] Error report chunk generation failed for %s/%s: %s",
                provider_name,
                actual_model_name,
                error,
            )
            return {
                "source": "unavailable",
                "model_used": f"{provider_name}/{actual_model_name}",
                "generated_at": datetime.now().isoformat(),
                "markdown": "",
                "error": error or "chunk_generation_failed",
            }

        try:
            parsed = json.loads(_strip_code_fence(content))
        except Exception:
            parsed = None
        if not isinstance(parsed, dict):
            return {
                "source": "unavailable",
                "model_used": f"{provider_name}/{actual_model_name}",
                "generated_at": datetime.now().isoformat(),
                "markdown": "",
                "error": "invalid_chunk_response",
            }
        try:
            parsed = json.loads(_strip_code_fence(content))
        except Exception:
            parsed = None
        if not isinstance(parsed, dict):
            return {
                "source": "unavailable",
                "model_used": f"{provider_name}/{actual_model_name}",
                "generated_at": datetime.now().isoformat(),
                "markdown": "",
                "error": "invalid_chunk_response",
            }
        chunk_summaries.append(parsed)

    final_prompt = {
        "language": language_name,
        "task": (
            "Combine the chunk analyses into one final Markdown report. "
            "Focus on context thresholds: when each model starts slowing down, timing out, or showing higher error rates. "
            "Also provide OpenCode configuration suggestions for limit.context and limit.output."
        ),
        "required_sections": [
            "Daily Error Analysis Report",
            "Executive Summary",
            "Model Context Risk Analysis",
            "Key Findings",
            "OpenCode Configuration Suggestions",
            "Recommended Actions",
        ],
        "summary_metrics": summary,
        "chunk_analyses": chunk_summaries,
    }
    markdown, error = await _call_analysis_model(
        provider_name=provider_name,
        actual_model_name=actual_model_name,
        system_prompt=(
            "You analyze operational incident logs for an LLM proxy dashboard. "
            "Do not invent facts. Reply with Markdown only. "
            "Use headings and bullet lists. Do not wrap the result in code fences."
        ),
        prompt_payload=final_prompt,
        max_tokens=4000,
    )
    if not markdown:
        logger.warning(
            "[ADMIN] Error report final synthesis failed for %s/%s: %s",
            provider_name,
            actual_model_name,
            error,
        )
        return {
            "source": "unavailable",
            "model_used": f"{provider_name}/{actual_model_name}",
            "generated_at": datetime.now().isoformat(),
            "markdown": "",
            "error": error or "final_synthesis_failed",
        }

    return {
        "source": "ai",
        "model_used": f"{provider_name}/{actual_model_name}",
        "generated_at": datetime.now().isoformat(),
        "markdown": markdown,
    }


async def _load_today_error_logs(
    session, limit: int = ERROR_REPORT_LOG_LIMIT
) -> tuple[list[RequestLog], list[dict], dict]:
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(RequestLog)
        .where(
            RequestLog.created_at >= today_start,
            RequestLog.status.in_(ERROR_STATUSES),
        )
        .order_by(RequestLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    provider_map, api_key_map = await _get_maps(session, logs)
    serialized_logs = [
        _serialize_error_log(log, provider_map, api_key_map) for log in logs
    ]
    return logs, serialized_logs, _build_error_summary(serialized_logs)


async def _load_today_analysis_logs(session) -> list[dict]:
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(RequestLog)
        .where(
            RequestLog.created_at >= today_start,
            RequestLog.status != "pending",
        )
        .order_by(RequestLog.created_at.desc())
    )
    logs = result.scalars().all()
    provider_map, _ = await _get_maps(session, logs)
    return [_serialize_analysis_log(log, provider_map) for log in logs]


async def _run_daily_error_report_analysis(
    report_date: str,
    locale: str,
    summary: dict,
    serialized_logs: list[dict],
    context_summary: list[dict],
    model_override: Optional[str] = None,
    seq: int = 1,
) -> None:
    scope_key = _build_error_report_scope(report_date, locale, seq)
    try:
        await upsert_analysis_record(
            ANALYSIS_TYPE_DAILY_ERROR_REPORT,
            scope_key,
            status=ANALYSIS_STATUS_RUNNING,
            language=locale,
        )
        report = await _generate_error_report_with_ai(
            locale,
            summary,
            serialized_logs,
            context_summary,
            model_override=model_override,
        )
        if report.get("source") != "ai":
            await upsert_analysis_record(
                ANALYSIS_TYPE_DAILY_ERROR_REPORT,
                scope_key,
                status=ANALYSIS_STATUS_FAILED,
                language=locale,
                model_used=report.get("model_used"),
                content=None,
                error=report.get("error"),
            )
            return

        output_path = _build_error_report_file_path(report_date, locale, seq)
        stored_path = write_report_markdown(output_path, report.get("markdown") or "")
        await upsert_analysis_record(
            ANALYSIS_TYPE_DAILY_ERROR_REPORT,
            scope_key,
            status=ANALYSIS_STATUS_SUCCESS,
            language=locale,
            model_used=report.get("model_used"),
            content=stored_path,
            error=None,
        )
    except Exception as exc:
        logger.warning("[ADMIN] Failed to run daily error analysis: %s", exc)
        await upsert_analysis_record(
            ANALYSIS_TYPE_DAILY_ERROR_REPORT,
            scope_key,
            status=ANALYSIS_STATUS_FAILED,
            language=locale,
            model_used=None,
            content=None,
            error=str(exc),
        )


@router.get("/logs/today")
async def get_today_logs(_: bool = Depends(require_admin)):
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    async with async_session_maker() as session:
        result = await session.execute(
            select(RequestLog)
            .where(RequestLog.created_at >= today_start)
            .order_by(RequestLog.created_at.desc())
            .limit(50)
        )
        logs = result.scalars().all()
        return {
            "logs": [
                {
                    "id": log.id,
                    "model": log.model,
                    "status": log.status,
                    "latency_ms": log.latency_ms,
                    "request_context_tokens": log.request_context_tokens,
                    "tokens": log.tokens,
                    "client_ip": log.client_ip,
                    "user_agent": log.user_agent,
                    "created_at": log.created_at.isoformat(),
                }
                for log in logs
            ]
        }


@router.get("/logs/errors/today")
async def get_today_error_logs(_: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        _, serialized_logs, summary = await _load_today_error_logs(session)
        return {
            "logs": serialized_logs,
            "summary": summary,
        }


@router.get("/logs/errors/analyze")
async def get_today_error_report(
    request: Request,
    language: Optional[str] = None,
    _: bool = Depends(require_admin),
):
    async with async_session_maker() as session:
        _, serialized_logs, summary = await _load_today_error_logs(session)
    locale = language if language else get_locale(request)
    report_date = datetime.now().strftime("%Y-%m-%d")

    if not serialized_logs:
        return {
            "summary": summary,
            "report": {
                "source": "empty",
                "model_used": None,
                "generated_at": datetime.now().isoformat(),
                "markdown": "\n".join(
                    [
                        f"# {translate(request, 'Daily Error Analysis Report')}",
                        "",
                        f"## {translate(request, 'Executive Summary')}",
                        translate(
                            request, "No error or timeout logs have been recorded today"
                        ),
                        "",
                        f"## {translate(request, 'Recommended Actions')}",
                        f"- {translate(request, 'No action is needed right now, but keep monitoring for new failures')}",
                    ]
                ),
            },
        }

    prefix = f"{report_date}:{locale}:"
    record = None
    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisRecord)
            .where(
                AnalysisRecord.analysis_type == ANALYSIS_TYPE_DAILY_ERROR_REPORT,
                AnalysisRecord.scope_key.startswith(prefix),
            )
            .order_by(AnalysisRecord.id.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
    if not record:
        return {"summary": summary, "report": None}

    markdown = (
        read_report_markdown(record.content)
        if record.status == ANALYSIS_STATUS_SUCCESS
        else None
    )
    return {
        "summary": summary,
        "report": _serialize_report_record(record, markdown),
    }


@router.get("/logs/errors/reports")
async def list_error_reports(
    language: Optional[str] = None,
    limit: int = 30,
    _: bool = Depends(require_admin),
):
    async with async_session_maker() as session:
        query = (
            select(AnalysisRecord)
            .where(AnalysisRecord.analysis_type == ANALYSIS_TYPE_DAILY_ERROR_REPORT)
            .order_by(AnalysisRecord.scope_key.desc())
            .limit(limit)
        )
        if language:
            query = query.where(AnalysisRecord.language == language)
        result = await session.execute(query)
        records = result.scalars().all()

    items: list[dict] = []
    for r in records:
        parts = r.scope_key.split(":") if r.scope_key else []
        date_part = parts[0] if len(parts) >= 1 else ""
        lang_part = parts[1] if len(parts) >= 2 else ""
        seq_part = parts[2] if len(parts) >= 3 else ""
        items.append(
            {
                "id": r.id,
                "date": date_part,
                "language": lang_part,
                "seq": int(seq_part) if seq_part.isdigit() else 1,
                "status": r.status,
                "model_used": r.model_used,
                "generated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
        )
    return {"reports": items}


@router.get("/logs/errors/reports/{report_id:int}")
async def get_error_report_by_id(
    report_id: int,
    _: bool = Depends(require_admin),
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisRecord).where(
                AnalysisRecord.analysis_type == ANALYSIS_TYPE_DAILY_ERROR_REPORT,
                AnalysisRecord.id == report_id,
            )
        )
        record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Report not found")
    markdown = (
        read_report_markdown(record.content)
        if record.status == ANALYSIS_STATUS_SUCCESS
        else None
    )
    return _serialize_report_record(record, markdown)


@router.get("/analysis/models")
async def get_analysis_models(_: bool = Depends(require_admin)):
    models: list[dict] = []
    for provider_name, provider_config in providers_cache.items():
        for model in provider_config.get("models") or []:
            actual = model.get("actual_model_name") or model.get("model_name")
            if actual:
                models.append(
                    {
                        "provider": provider_name,
                        "model": actual,
                        "display": f"{provider_name}/{actual}",
                    }
                )
    _, _, default_model = _choose_analysis_model()
    return {"models": models, "default": default_model}


@router.post("/logs/errors/analyze")
async def analyze_today_error_logs(
    request: Request,
    body: Optional[AnalysisRequest] = None,
    _: bool = Depends(require_admin),
):
    async with async_session_maker() as session:
        _, serialized_logs, summary = await _load_today_error_logs(session)
        analysis_logs = await _load_today_analysis_logs(session)
    context_summary = _build_context_risk_summary(analysis_logs)
    locale = (body.language if body and body.language else None) or get_locale(request)
    model_override = body.model if body and body.model else None
    report_date = datetime.now().strftime("%Y-%m-%d")
    seq = await _next_error_report_seq(report_date, locale)
    scope_key = _build_error_report_scope(report_date, locale, seq)

    if not serialized_logs:
        return {
            "summary": summary,
            "report": {
                "source": "empty",
                "model_used": None,
                "generated_at": datetime.now().isoformat(),
                "markdown": "\n".join(
                    [
                        f"# {translate(request, 'Daily Error Analysis Report')}",
                        "",
                        f"## {translate(request, 'Executive Summary')}",
                        translate(
                            request, "No error or timeout logs have been recorded today"
                        ),
                        "",
                        f"## {translate(request, 'Recommended Actions')}",
                        f"- {translate(request, 'No action is needed right now, but keep monitoring for new failures')}",
                    ]
                ),
            },
        }

    await upsert_analysis_record(
        ANALYSIS_TYPE_DAILY_ERROR_REPORT,
        scope_key,
        status=ANALYSIS_STATUS_PENDING,
        language=locale,
        model_used=None,
        content=None,
        error=None,
    )
    start_analysis_task(
        ANALYSIS_TYPE_DAILY_ERROR_REPORT,
        scope_key,
        lambda: _run_daily_error_report_analysis(
            report_date,
            locale,
            summary,
            serialized_logs,
            context_summary,
            model_override=model_override,
            seq=seq,
        ),
    )
    record = await get_analysis_record(ANALYSIS_TYPE_DAILY_ERROR_REPORT, scope_key)
    if not record:
        return {"summary": summary, "report": None}

    return {
        "summary": summary,
        "report": _serialize_report_record(record),
    }


@router.get("/logs/all")
async def get_all_logs(limit: int = 100, _: bool = Depends(require_admin)):
    async with async_session_maker() as session:
        count_result = await session.execute(select(func.count(RequestLog.id)))
        total = count_result.scalar() or 0

        result = await session.execute(
            select(RequestLog).order_by(RequestLog.created_at.desc()).limit(limit)
        )
        logs = result.scalars().all()
        return {
            "logs": [
                {
                    "id": log.id,
                    "model": log.model,
                    "status": log.status,
                    "upstream_status_code": log.upstream_status_code,
                    "latency_ms": log.latency_ms,
                    "request_context_tokens": log.request_context_tokens,
                    "tokens": log.tokens,
                    "client_ip": log.client_ip,
                    "user_agent": log.user_agent,
                    "created_at": log.created_at.isoformat(),
                    "response": log.response,
                    "error": log.error,
                }
                for log in logs
            ],
            "total": total,
        }


def _escape_ilike(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/logs/query")
async def query_logs(
    key_name: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = None,
    time_range: str = "1h",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    _: bool = Depends(require_admin),
):
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    now = datetime.now()

    if start_time or end_time:
        try:
            dt_start = (
                datetime.fromisoformat(start_time)
                if start_time
                else now - timedelta(days=7)
            )
            dt_end = datetime.fromisoformat(end_time) if end_time else now
        except ValueError:
            return {"logs": [], "total": 0, "page": page, "page_size": page_size}
    else:
        deltas = {
            "1h": timedelta(hours=1),
            "6h": timedelta(hours=6),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
        }
        dt_start = now - deltas.get(time_range, timedelta(hours=1))
        dt_end = now

    async with async_session_maker() as session:
        api_key_id_filter = None
        if key_name:
            safe_key = _escape_ilike(key_name)
            key_result = await session.execute(
                select(ApiKey).where(ApiKey.name == key_name)
            )
            key = key_result.scalar_one_or_none()
            if key:
                api_key_id_filter = key.id
            else:
                key_result = await session.execute(
                    select(ApiKey).where(ApiKey.name.ilike(f"%{safe_key}%"))
                )
                keys = key_result.scalars().all()
                if keys:
                    api_key_id_filter = [k.id for k in keys]
                else:
                    return {
                        "logs": [],
                        "total": 0,
                        "page": page,
                        "page_size": page_size,
                    }

        q = select(RequestLog).where(
            RequestLog.created_at >= dt_start,
            RequestLog.created_at <= dt_end,
        )
        count_q = select(func.count(RequestLog.id)).where(
            RequestLog.created_at >= dt_start,
            RequestLog.created_at <= dt_end,
        )

        if api_key_id_filter is not None:
            if isinstance(api_key_id_filter, list):
                q = q.where(RequestLog.api_key_id.in_(api_key_id_filter))
                count_q = count_q.where(RequestLog.api_key_id.in_(api_key_id_filter))
            else:
                q = q.where(RequestLog.api_key_id == api_key_id_filter)
                count_q = count_q.where(RequestLog.api_key_id == api_key_id_filter)
        if model:
            safe_model = _escape_ilike(model)
            q = q.where(RequestLog.model.ilike(f"%{safe_model}%"))
            count_q = count_q.where(RequestLog.model.ilike(f"%{safe_model}%"))
        if status:
            q = q.where(RequestLog.status == status)
            count_q = count_q.where(RequestLog.status == status)

        total_result = await session.execute(count_q)
        total = total_result.scalar() or 0

        offset = (page - 1) * page_size
        q = q.order_by(RequestLog.created_at.desc()).offset(offset).limit(page_size)
        result = await session.execute(q)
        logs = result.scalars().all()

        provider_map, api_key_map = await _get_maps(session, logs)

        return {
            "logs": [
                _serialize_error_log(log, provider_map, api_key_map) for log in logs
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
