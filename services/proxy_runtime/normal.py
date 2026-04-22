import json
import time

from fastapi.responses import Response

from core.config import (
    error_logger,
    finish_active_request,
    logger,
    providers_cache,
    record_request_rate,
    register_active_request,
    update_stats,
)
from core.log_sanitizer import sanitize_payload_for_log, sanitize_text_for_log
from services.logging import log_request
from services.minimax import process_minimax_response
from services.provider_limiter import check_usage_limit_error, disable_provider_key
from services.proxy_runtime.concurrency import (
    RATE_LIMITED_STATUSES,
    SEMAPHORE_RETRY_AFTER_SECONDS,
)
from services.proxy_runtime.response_handler import (
    _extract_provider_error,
    _extract_response_fields,
    _is_rate_limited_status,
    _normalize_upstream_error,
    _openai_error_response,
    _resolve_request_status,
)
from services.tokens import build_response_meta, build_tokens_record, log_response_meta


async def handle_normal(
    client,
    url,
    headers,
    body,
    provider,
    model,
    messages,
    start_time,
    req_body,
    api_key_id,
    client_ip,
    user_agent,
    request_context_tokens,
    semaphore,
    api_key_model_semaphore,
    request_id,
    chosen_key_id=None,
):
    logger.debug(
        "[NORMAL REQUEST] Provider: %s, Model: %s, URL: %s", provider, model, url
    )

    is_active_request_registered = False
    semaphores_released = False
    try:
        await register_active_request(
            request_id,
            provider,
            model,
            api_key_id,
            client_ip=client_ip,
        )
        is_active_request_registered = True

        resp = await client.post(url, headers=headers, content=body)
        latency = (time.time() - start_time) * 1000

        try:
            resp_json = resp.json()
        except json.JSONDecodeError:
            resp_json = {}

        usage_limit_err = check_usage_limit_error(resp_json, provider)
        if usage_limit_err:
            provider_config = providers_cache.get(provider, {})
            await disable_provider_key(
                provider, provider_config, chosen_key_id, usage_limit_err
            )
            return _openai_error_response(
                f"\u4f9b\u5e94\u5546 '{provider}' \u56e0\u989d\u5ea6\u9650\u5236\u5df2\u6682\u505c\u4f7f\u7528\uff0c\u8bf7\u5c1d\u8bd5\u5176\u4ed6\u4f9b\u5e94\u5546",
                429,
                "rate_limit_error",
                "provider_disabled",
            )

        if provider == "minimax":
            process_minimax_response(resp_json)

        response_text, reasoning_text, tool_calls, finish_reason = (
            _extract_response_fields(resp_json)
        )

        response_meta = build_response_meta(
            response_text=response_text,
            reasoning_text=reasoning_text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )
        tokens_record = build_tokens_record(
            resp_json.get("usage"),
            req_body=req_body,
            response_text=response_text,
            reasoning_text=reasoning_text,
            response_meta=response_meta,
        )
        total_tokens = tokens_record["total_tokens"]

        request_status = _resolve_request_status(resp.status_code)
        is_error = request_status == "error"
        retry_after = resp.headers.get("retry-after")
        if retry_after:
            error_logger.warning(
                f"[API] {provider} rate limited, retry-after: {retry_after}s"
            )

        provider_error = _extract_provider_error(resp_json)
        if provider_error:
            request_status = _resolve_request_status(resp.status_code, provider_error)
            is_error = request_status == "error"
        if is_error and provider_error:
            error_logger.error(
                f"[API ERROR] Provider: {provider}, Model: {model}, API returned error: {provider_error}"
            )

        update_stats(
            provider,
            model,
            total_tokens,
            api_key_id=api_key_id,
            is_error=is_error,
            is_rate_limited=request_status in RATE_LIMITED_STATUSES,
        )
        if not is_error and total_tokens > 0:
            record_request_rate(total_tokens, latency)
        log_response_meta(provider, model, response_meta)
        await log_request(
            provider,
            model,
            response_text,
            tokens_record,
            latency,
            request_status,
            api_key_id=api_key_id,
            upstream_status_code=resp.status_code,
            client_ip=client_ip,
            user_agent=user_agent,
            request_context_tokens=request_context_tokens,
            error=(
                sanitize_text_for_log(provider_error, limit=2000)
                if provider_error
                else sanitize_text_for_log(resp.text, limit=2000)
            )
            if request_status != "success"
            else None,
        )

        if is_error:
            error_logger.error(
                f"[API ERROR] Provider: {provider}, Model: {model}, Status: {resp.status_code}\n"
                f"  Request Body: {sanitize_payload_for_log(req_body)}\n"
                f"  Response: {sanitize_text_for_log(resp.text)}"
            )

        logger.info(
            f"[RESPONSE] Status: {resp.status_code}, Tokens: {total_tokens}, Latency: {latency:.0f}ms"
        )
        logger.debug("[RESPONSE] Body: %s", sanitize_text_for_log(resp.text))

        resp_headers = {"content-type": "application/json"}
        if _is_rate_limited_status(resp.status_code):
            if retry_after:
                resp_headers["retry-after"] = retry_after
            else:
                resp_headers["retry-after"] = str(SEMAPHORE_RETRY_AFTER_SECONDS)

        if request_status != "success":
            resp_content = _normalize_upstream_error(
                resp_json,
                resp.status_code,
                provider,
                raw_error_text=sanitize_text_for_log(resp.text, limit=2000),
            )
        else:
            resp_content = resp.content

        response = Response(
            content=resp_content,
            status_code=resp.status_code,
            headers=resp_headers,
        )
        api_key_model_semaphore.release()
        if semaphore is not None:
            semaphore.release()
        semaphores_released = True
        return response
    finally:
        if is_active_request_registered:
            await finish_active_request(request_id)
        if not semaphores_released:
            if semaphore is not None:
                semaphore.release()
            api_key_model_semaphore.release()
