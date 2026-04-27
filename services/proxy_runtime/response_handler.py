import json
import time

from fastapi.responses import JSONResponse

from core.config import error_logger, logger, record_request_rate, update_stats
from core.log_sanitizer import sanitize_payload_for_log, sanitize_text_for_log
from services.logging import create_request_log, update_request_log
from services.minimax import process_minimax_response
from services.tokens import (
    build_response_meta,
    build_tokens_record,
    log_response_meta,
)
from services.proxy_runtime.concurrency import (
    LOCAL_RATE_LIMITED_STATUS,
    RATE_LIMITED_STATUSES,
    RATE_LIMITED_STATUS,
)


def _openai_error(
    message: str, error_type: str = "api_error", code: str | None = None
) -> dict:
    return {
        "error": {"message": message, "type": error_type, "code": code or error_type}
    }


def _openai_error_response(
    message: str,
    status_code: int,
    error_type: str = "api_error",
    code: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        content=_openai_error(message, error_type, code),
        status_code=status_code,
        headers=headers,
    )


def _is_rate_limited_status(status_code: int) -> bool:
    return status_code in (429, 529)


def _resolve_request_status(status_code: int, provider_error: str | None = None) -> str:
    if _is_rate_limited_status(status_code):
        return RATE_LIMITED_STATUS
    if status_code >= 400 or provider_error:
        return "error"
    return "success"


def _extract_response_fields(resp_json: dict) -> tuple[str, str, list, str]:
    response_text = ""
    reasoning_text = ""
    tool_calls = []
    finish_reason = ""
    if "choices" in resp_json and resp_json["choices"]:
        choice = resp_json["choices"][0]
        message = choice.get("message", {})
        response_text = message.get("content", "")
        reasoning_text = message.get("reasoning_content", "")
        tool_calls = message.get("tool_calls", []) if isinstance(message, dict) else []
        finish_reason = choice.get("finish_reason", "") or ""
    return response_text, reasoning_text, tool_calls, finish_reason


def _format_provider_error(error_obj) -> str:
    if isinstance(error_obj, dict):
        message = (
            error_obj.get("message")
            or error_obj.get("msg")
            or error_obj.get("detail")
            or json.dumps(error_obj, ensure_ascii=False)
        )
        code = error_obj.get("code") or error_obj.get("status_code")
        return f"{message} ({code})" if code not in (None, "") else str(message)
    return str(error_obj)


def _extract_provider_error(payload: dict) -> str | None:
    error_obj = payload.get("error")
    if error_obj:
        return _format_provider_error(error_obj)

    base_resp = payload.get("base_resp")
    if isinstance(base_resp, dict):
        status_code = base_resp.get("status_code")
        status_msg = (
            base_resp.get("status_msg")
            or base_resp.get("message")
            or base_resp.get("detail")
        )
        if status_code not in (None, "", 0, "0", 200, "200") and status_msg:
            return f"{status_msg} ({status_code})"

    status_code = payload.get("status_code")
    status_msg = payload.get("message") or payload.get("msg") or payload.get("detail")
    if status_code not in (None, "", 0, "0", 200, "200") and status_msg:
        return f"{status_msg} ({status_code})"

    return None


def _normalize_upstream_error(
    resp_json: dict,
    status_code: int,
    provider: str,
    raw_error_text: str | None = None,
) -> bytes:
    if provider == "minimax" and resp_json:
        process_minimax_response(resp_json)
    if isinstance(resp_json.get("error"), dict) and "message" in resp_json["error"]:
        return json.dumps(resp_json).encode()
    provider_error = _extract_provider_error(resp_json)
    if provider_error:
        error_type = (
            "rate_limit_error" if _is_rate_limited_status(status_code) else "api_error"
        )
        return json.dumps(_openai_error(provider_error, error_type)).encode()
    if raw_error_text:
        error_type = (
            "rate_limit_error" if _is_rate_limited_status(status_code) else "api_error"
        )
        return json.dumps(_openai_error(raw_error_text, error_type)).encode()
    if resp_json:
        return json.dumps(resp_json).encode()
    error_type = (
        "rate_limit_error" if _is_rate_limited_status(status_code) else "api_error"
    )
    return json.dumps(
        _openai_error(f"Upstream request failed with status {status_code}", error_type)
    ).encode()


async def _record_stream_result(
    total_content,
    total_reasoning,
    stream_tool_calls,
    final_finish_reason,
    last_usage,
    req_body,
    provider,
    model,
    api_key_id,
    client_ip,
    user_agent,
    request_context_tokens,
    start_time,
    log_id,
    status,
    upstream_status_code=None,
    error=None,
):
    latency = (time.time() - start_time) * 1000
    response_meta = build_response_meta(
        response_text=total_content,
        reasoning_text=total_reasoning,
        tool_calls=stream_tool_calls,
        finish_reason=final_finish_reason,
    )
    tokens_record = build_tokens_record(
        last_usage,
        req_body=req_body,
        response_text=total_content,
        reasoning_text=total_reasoning,
        response_meta=response_meta,
    )
    total_tokens = tokens_record["total_tokens"]
    log_response_meta(provider, model, response_meta)

    if status == "success":
        update_stats(provider, model, total_tokens, api_key_id=api_key_id)
        record_request_rate(total_tokens, latency)
        updated = await update_request_log(
            log_id,
            response=total_content,
            tokens=tokens_record,
            latency_ms=latency,
            status="success",
            upstream_status_code=upstream_status_code,
            downstream_status_code=200,
        )
        if not updated:
            await create_request_log(
                provider,
                model,
                status="success",
                api_key_id=api_key_id,
                client_ip=client_ip,
                user_agent=user_agent,
                request_context_tokens=request_context_tokens,
                response=total_content,
                tokens=tokens_record,
                latency_ms=latency,
                upstream_status_code=upstream_status_code,
                downstream_status_code=200,
            )
        logger.info(
            f"[STREAM COMPLETE] ~{total_tokens} tokens "
            f"(prompt={tokens_record.get('prompt_tokens', 0)}, "
            f"completion={tokens_record.get('completion_tokens', 0)}) | {latency:.0f}ms"
        )
        logger.debug("[STREAM RESPONSE] Content: %s", total_content)
    elif status == "cancelled":
        updated = await update_request_log(
            log_id,
            response=total_content,
            tokens=tokens_record,
            latency_ms=latency,
            status="cancelled",
            upstream_status_code=upstream_status_code,
            downstream_status_code=200,
        )
        if not updated:
            await create_request_log(
                provider,
                model,
                status="cancelled",
                api_key_id=api_key_id,
                client_ip=client_ip,
                user_agent=user_agent,
                request_context_tokens=request_context_tokens,
                response=total_content,
                tokens=tokens_record,
                latency_ms=latency,
                upstream_status_code=upstream_status_code,
                downstream_status_code=200,
            )
    elif status in {"error", RATE_LIMITED_STATUS, LOCAL_RATE_LIMITED_STATUS}:
        update_stats(
            provider,
            model,
            0,
            api_key_id=api_key_id,
            is_error=status == "error",
            is_rate_limited=status in RATE_LIMITED_STATUSES,
        )
        updated = await update_request_log(
            log_id,
            response=total_content,
            tokens=tokens_record,
            latency_ms=latency,
            status=status,
            upstream_status_code=upstream_status_code,
            downstream_status_code=200,
            error=str(error) if error is not None else None,
        )
        if not updated:
            await create_request_log(
                provider,
                model,
                status=status,
                api_key_id=api_key_id,
                client_ip=client_ip,
                user_agent=user_agent,
                request_context_tokens=request_context_tokens,
                response=total_content,
                tokens=tokens_record,
                latency_ms=latency,
                upstream_status_code=upstream_status_code,
                downstream_status_code=200,
                error=str(error) if error is not None else None,
            )
        log_fn = (
            error_logger.warning
            if status in RATE_LIMITED_STATUSES
            else error_logger.error
        )
        log_fn(
            f"[STREAM ERROR] Provider: {provider}, Model: {model}\n"
            f"  Error: {type(error).__name__ if error else 'Unknown'}: {sanitize_text_for_log(error)}\n"
            f"  Request Body: {sanitize_payload_for_log(req_body)}"
        )
    return latency
