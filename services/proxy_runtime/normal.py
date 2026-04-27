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
from services.logging import create_request_log
from services.minimax import process_minimax_response
from services.provider_limiter import check_usage_limit_error, disable_provider_key
from services.proxy_runtime.adapters import get_adapter
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
    provider_key_semaphore,
    user_provider_model_semaphore,
    request_id,
    chosen_key_id=None,
    protocol="openai",
    extra_response_headers: dict[str, str] | None = None,
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
            prompt_tokens=request_context_tokens,
        )
        is_active_request_registered = True

        resp = await client.post(url, headers=headers, content=body)
        latency = (time.time() - start_time) * 1000

        try:
            raw_resp_json = resp.json()
        except json.JSONDecodeError:
            raw_resp_json = {}

        usage_limit_err = check_usage_limit_error(raw_resp_json, provider)
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
                headers=extra_response_headers,
            )

        adapter = get_adapter(protocol)
        if resp.status_code >= 400 and protocol != "openai":
            resp_json = adapter.transform_error_response(raw_resp_json, resp.status_code)
        else:
            resp_json = adapter.transform_response(raw_resp_json)

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
        await create_request_log(
            provider,
            model,
            status=request_status,
            api_key_id=api_key_id,
            client_ip=client_ip,
            user_agent=user_agent,
            request_context_tokens=request_context_tokens,
            response=response_text,
            tokens=tokens_record,
            latency_ms=latency,
            upstream_status_code=resp.status_code,
            downstream_status_code=resp.status_code,
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
            f"[RESPONSE] Status: {resp.status_code}, "
            f"Tokens: {total_tokens} (prompt={tokens_record.get('prompt_tokens', 0)}, "
            f"completion={tokens_record.get('completion_tokens', 0)}), "
            f"Latency: {latency:.0f}ms"
        )
        logger.debug("[RESPONSE] Body: %s", sanitize_text_for_log(resp.text))

        resp_headers = {"content-type": "application/json"}
        if extra_response_headers:
            resp_headers.update(extra_response_headers)
        if _is_rate_limited_status(resp.status_code):
            if retry_after:
                resp_headers["retry-after"] = retry_after
            else:
                resp_headers["retry-after"] = str(SEMAPHORE_RETRY_AFTER_SECONDS)

        if request_status != "success":
            if protocol != "openai" and resp_json:
                resp_content = json.dumps(resp_json).encode()
            else:
                resp_content = _normalize_upstream_error(
                    resp_json,
                    resp.status_code,
                    provider,
                    raw_error_text=sanitize_text_for_log(resp.text, limit=2000),
                )
        else:
            resp_content = json.dumps(resp_json).encode()

        response = Response(
            content=resp_content,
            status_code=resp.status_code,
            headers=resp_headers,
        )
        if user_provider_model_semaphore is not None:
            user_provider_model_semaphore.release()
        if provider_key_semaphore is not None:
            provider_key_semaphore.release()
        semaphores_released = True
        return response
    finally:
        if is_active_request_registered:
            await finish_active_request(request_id)
        if not semaphores_released:
            if provider_key_semaphore is not None:
                provider_key_semaphore.release()
            if user_provider_model_semaphore is not None:
                user_provider_model_semaphore.release()
