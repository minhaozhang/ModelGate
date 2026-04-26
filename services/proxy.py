import asyncio
import json
import time
import uuid

from fastapi import Request

from core.config import (
    providers_cache,
    update_stats,
    logger,
    error_logger,
)
from core.log_sanitizer import (
    sanitize_payload_for_log,
    sanitize_text_for_log,
)
from core.client_ip import get_client_ip
from services.provider import (
    get_provider_and_model,
    get_model_config,
    get_disabled_provider_reason,
    pick_api_key,
)
from services.auth import validate_api_key
from services.logging import (
    create_request_log,
    log_request,
)
from services.tokens import (
    estimate_request_context_tokens,
)
from services.deepseek_compat import is_deepseek_thinking_active, patch_reasoning_content
from services.busyness import LEVEL_LABELS
from services.message import preprocess_messages
from services.proxy_runtime import (
    LOCAL_RATE_LIMITED_STATUS,
    SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS,
    SEMAPHORE_RETRY_AFTER_SECONDS,
    _get_provider_key_model_limit,
    _get_or_create_provider_key_model_semaphore,
    _get_or_create_provider_key_semaphore,
    _get_provider_key_limit,
    _openai_error_response,
    build_headers,
    call_internal_model_via_proxy as runtime_call_internal_model_via_proxy,
    ensure_internal_api_key_exists as runtime_ensure_internal_api_key_exists,
    get_http_client,
    handle_normal as runtime_handle_normal,
    handle_streaming as runtime_handle_streaming,
    log_request_info,
    schedule_api_key_last_used_update,
)
from services.proxy_runtime.adapters import get_adapter


INTERNAL_ANALYSIS_API_KEY_ID = 1
INTERNAL_ANALYSIS_CLIENT_IP = "internal"
INTERNAL_ANALYSIS_USER_AGENT = "modelgate/internal-analysis"


def _check_busyness_rules(model: str) -> str | None:
    from core.config import busyness_state, system_config

    if not busyness_state:
        return model
    rules = system_config.get("busyness_rules", [])
    if not rules:
        return model
    current_level = busyness_state.get("level", 6)
    for rule in rules:
        min_level = rule.get("min_level", 0)
        if current_level > min_level:
            continue
        action = rule.get("action")
        target_models = rule.get("target_models", [])
        if target_models and model not in target_models:
            continue
        if action == "block":
            return None
        if action == "downgrade":
            redirect_to = rule.get("redirect_to")
            if redirect_to and redirect_to != model:
                logger.info("[BUSYNESS] Downgrading %s -> %s (level %d)", model, redirect_to, current_level)
                return redirect_to
            break
        if action == "suggest":
            break
    return model


def _check_busyness_block(model: str):
    from core.config import busyness_state, system_config

    if not busyness_state:
        return None
    rules = system_config.get("busyness_rules", [])
    if not rules:
        return None
    current_level = busyness_state.get("level", 6)
    for rule in rules:
        min_level = rule.get("min_level", 0)
        if current_level > min_level:
            continue
        action = rule.get("action")
        if action != "block":
            continue
        target_models = rule.get("target_models", [])
        if target_models and model not in target_models:
            continue
        return _openai_error_response(
            rule.get("message", f"System busy (level {current_level}), model {model} temporarily unavailable"),
            503,
            "server_error",
            "busyness_block",
        )
    return None


def _get_busyness_suggestion_headers(model: str) -> dict[str, str]:
    from core.config import busyness_state, system_config

    if not busyness_state:
        return {}
    current_level = busyness_state.get("level", 6)
    for rule in system_config.get("busyness_rules", []):
        if rule.get("action") != "suggest":
            continue
        min_level = rule.get("min_level", 0)
        if current_level > min_level:
            continue
        target_models = rule.get("target_models", [])
        if target_models and model not in target_models:
            continue
        message = rule.get("message") or LEVEL_LABELS.get(current_level, "System busy")
        return {
            "X-System-Busyness": str(current_level),
            "X-System-Busyness-Label": str(
                busyness_state.get("label") or LEVEL_LABELS.get(current_level, "")
            ),
            "X-System-Busyness-Message": str(message),
        }
    return {}


async def proxy_request(request: Request, endpoint: str):
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]
    body = await request.body()

    try:
        body_json = json.loads(body) if body else {}
    except json.JSONDecodeError:
        body_json = {}

    model = body_json.get("model", "unknown")
    auth_header = request.headers.get("authorization", "")
    api_key_id, auth_error = await validate_api_key(auth_header, model)
    if auth_error:
        return _openai_error_response(
            auth_error, 401, "authentication_error", "invalid_api_key"
        )

    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    _schedule_api_key_last_used_update(api_key_id)

    busyness_headers = _get_busyness_suggestion_headers(model)
    busyness_model = _check_busyness_rules(model)
    if busyness_model is None:
        return _check_busyness_block(model)
    if busyness_model != model:
        model = busyness_model
        body_json["model"] = model

    block_response = _check_busyness_block(model)
    if block_response:
        return block_response

    provider_config, actual_model, provider_name = await get_provider_and_model(model)
    if not provider_config:
        disabled_reason = (
            await get_disabled_provider_reason(provider_name) if provider_name else None
        )
        if disabled_reason:
            return _openai_error_response(
                f"Provider '{provider_name}' is disabled: {disabled_reason}",
                400,
                "invalid_request_error",
                "provider_disabled",
            )
        logger.error("[PROXY ERROR] Unknown provider for model: %s", model)
        logger.debug(
            "[PROXY ERROR] Available providers: %s", list(providers_cache.keys())
        )
        return _openai_error_response(
            f"Unknown provider for model: {model}",
            400,
            "invalid_request_error",
            "model_not_found",
        )

    model_config = get_model_config(provider_config, actual_model)
    if model_config:
        max_level = model_config.get("max_busyness_level")
        if max_level is not None:
            from core.config import busyness_state
            current_level = busyness_state.get("level", 6)
            if current_level > max_level:
                level_label = LEVEL_LABELS.get(current_level, "")
                return _openai_error_response(
                    f"当前系统{level_label}，该模型不可用，请前往用户界面查看推荐模型列表",
                    503,
                    "server_error",
                    "model_unavailable",
                    headers=busyness_headers or None,
                )

    provider_key_semaphore = None
    provider_key_model_semaphore = None
    acquired = False
    provider_key_model_acquired = False

    entered_handler = False
    try:
        chosen_api_key, chosen_key_id = pick_api_key(
            provider_config, api_key_id, provider_name
        )
        if not chosen_api_key:
            reasons = provider_config.get("disabled_key_reasons") or []
            msg = f"供应商 '{provider_name}' 无可用的 API Key"
            if reasons:
                msg = f"'{provider_name}' \u6682\u4e0d\u53ef\u7528\uff1a{reasons[0]}"
            return _openai_error_response(
                msg,
                400,
                "invalid_request_error",
                "no_api_key",
                headers=busyness_headers or None,
            )

        if chosen_key_id is not None:
            provider_key_sem_key, provider_key_semaphore = _get_or_create_provider_key_semaphore(
                chosen_key_id,
                provider_name,
                _get_provider_key_limit(provider_config, chosen_key_id),
            )
            try:
                await asyncio.wait_for(
                    provider_key_semaphore.acquire(),
                    timeout=SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS,
                )
                acquired = True
            except asyncio.TimeoutError:
                message = (
                    f"Provider key {chosen_key_id} for '{provider_name}' is at max concurrency"
                )
                logger.warning("[RATE LIMIT] %s at max concurrency", provider_key_sem_key)
                update_stats(
                    provider_name,
                    actual_model,
                    0,
                    api_key_id=api_key_id,
                    is_rate_limited=True,
                )
                await log_request(
                    provider_name,
                    actual_model,
                    "",
                    {},
                    (time.time() - start_time) * 1000,
                    LOCAL_RATE_LIMITED_STATUS,
                    api_key_id=api_key_id,
                    upstream_status_code=429,
                    downstream_status_code=429,
                    client_ip=client_ip,
                    user_agent=user_agent,
                    request_context_tokens=estimate_request_context_tokens(body_json),
                    error=message,
                )
                return _openai_error_response(
                    message,
                    429,
                    "rate_limit_error",
                    "provider_key_concurrency_reached",
                    headers={
                        **busyness_headers,
                        "retry-after": str(SEMAPHORE_RETRY_AFTER_SECONDS),
                    },
                )

            provider_model_key = f"{provider_name}/{actual_model}"
            provider_key_model_sem_key, provider_key_model_semaphore = (
                _get_or_create_provider_key_model_semaphore(
                    chosen_key_id,
                    provider_model_key,
                    _get_provider_key_model_limit(),
                )
            )
            try:
                await asyncio.wait_for(
                    provider_key_model_semaphore.acquire(),
                    timeout=SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS,
                )
                provider_key_model_acquired = True
            except asyncio.TimeoutError:
                if acquired and provider_key_semaphore is not None:
                    provider_key_semaphore.release()
                    acquired = False
                message = (
                    f"Provider key {chosen_key_id} already reached max concurrency for model '{provider_model_key}'"
                )
                logger.warning(
                    "[RATE LIMIT] %s at max concurrency", provider_key_model_sem_key
                )
                update_stats(
                    provider_name,
                    actual_model,
                    0,
                    api_key_id=api_key_id,
                    is_rate_limited=True,
                )
                await log_request(
                    provider_name,
                    actual_model,
                    "",
                    {},
                    (time.time() - start_time) * 1000,
                    LOCAL_RATE_LIMITED_STATUS,
                    api_key_id=api_key_id,
                    upstream_status_code=429,
                    downstream_status_code=429,
                    client_ip=client_ip,
                    user_agent=user_agent,
                    request_context_tokens=estimate_request_context_tokens(body_json),
                    error=message,
                )
                return _openai_error_response(
                    message,
                    429,
                    "rate_limit_error",
                    "provider_key_model_concurrency_reached",
                    headers={
                        **busyness_headers,
                        "retry-after": str(SEMAPHORE_RETRY_AFTER_SECONDS),
                    },
                )

        model_config = get_model_config(provider_config, actual_model)
        body_json["model"] = actual_model
        is_multimodal = (
            model_config.get("is_multimodal", False) if model_config else False
        )
        merge_messages = provider_config.get("merge_consecutive_messages", False)
        body_json = preprocess_messages(body_json, merge_messages, is_multimodal)
        messages = body_json["messages"]

        if is_deepseek_thinking_active(provider_name, actual_model, body_json, model_config):
            messages = patch_reasoning_content(messages)

        stream = body_json.get("stream", False)

        adapter = get_adapter(provider_config.get("protocol", "openai"))
        if stream:
            stream_options = body_json.get("stream_options")
            if isinstance(stream_options, dict):
                stream_options = dict(stream_options)
            else:
                stream_options = {}
            stream_options["include_usage"] = True
            body_json["stream_options"] = stream_options

        body_json = adapter.preprocess_body(body_json, provider_config)
        body_json = adapter.transform_request(body_json, provider_config)

        if provider_name == "minimax" and merge_messages:
            body_json.pop("thinking", None)
            body_json.pop("stream_options", None)
            body_json["reasoning_split"] = True

        if provider_config.get("protocol", "openai") != "openai":
            logger.debug(
                "[ADAPTER] protocol=%s transformed_body=%s",
                provider_config.get("protocol"),
                sanitize_payload_for_log(body_json),
            )

        body = json.dumps(body_json).encode()
        request_context_tokens = estimate_request_context_tokens(body_json)
        adapter_endpoint = adapter.get_target_path(endpoint)
        target_url = f"{provider_config['base_url']}{adapter_endpoint}"
        headers = build_headers(provider_config, api_key=chosen_api_key, protocol=provider_config.get("protocol", "openai"))

        _log_request_info(
            provider_name,
            actual_model,
            auth_header,
            messages,
            is_multimodal,
            stream,
            target_url,
            headers,
            body,
        )

        stream_log_id = None
        if stream:
            stream_log_id = await create_request_log(
                provider_name,
                actual_model,
                api_key_id=api_key_id,
                client_ip=client_ip,
                user_agent=user_agent,
                request_context_tokens=request_context_tokens,
            )

        client = get_http_client()
        provider_protocol = provider_config.get("protocol", "openai")
        entered_handler = True
        if stream:
            return await handle_streaming(
                target_url,
                headers,
                body,
                provider_name,
                actual_model,
                messages,
                start_time,
                body_json,
                api_key_id,
                client_ip,
                user_agent,
                request_context_tokens,
                provider_key_semaphore,
                provider_key_model_semaphore,
                request_id,
                stream_log_id,
                request,
                chosen_key_id=chosen_key_id,
                protocol=provider_protocol,
                extra_response_headers=busyness_headers,
            )
        return await handle_normal(
            client,
            target_url,
            headers,
            body,
            provider_name,
            actual_model,
            messages,
            start_time,
            body_json,
            api_key_id,
            client_ip,
            user_agent,
            request_context_tokens,
            provider_key_semaphore,
            provider_key_model_semaphore,
            request_id,
            chosen_key_id=chosen_key_id,
            protocol=provider_protocol,
            extra_response_headers=busyness_headers,
        )
    except Exception as e:
        if not entered_handler:
            if provider_key_model_acquired and provider_key_model_semaphore is not None:
                provider_key_model_semaphore.release()
            if acquired and provider_key_semaphore is not None:
                provider_key_semaphore.release()
        latency = (time.time() - start_time) * 1000
        update_stats(
            provider_name, actual_model, 0, api_key_id=api_key_id, is_error=True
        )
        await log_request(
            provider_name,
            actual_model,
            "",
            {},
            latency,
            "error",
            api_key_id=api_key_id,
            downstream_status_code=502,
            client_ip=client_ip,
            user_agent=user_agent,
            request_context_tokens=estimate_request_context_tokens(body_json),
            error=str(e),
        )
        error_logger.error(
            f"[REQUEST ERROR] Provider: {provider_name}, Model: {actual_model}\n"
            f"  Error: {type(e).__name__}: {sanitize_text_for_log(e)}\n"
            f"  Request Body: {sanitize_payload_for_log(body_json)}"
        )
        err_msg = (
            f"Proxy error: {type(e).__name__}: {sanitize_text_for_log(e, limit=500)}"
        )
        return _openai_error_response(err_msg, 502, "api_error", "proxy_error")

async def _ensure_internal_api_key_exists(api_key_id: int) -> bool:
    return await runtime_ensure_internal_api_key_exists(api_key_id)


async def call_internal_model_via_proxy(
    requested_model: str,
    body_json: dict,
    api_key_id: int = INTERNAL_ANALYSIS_API_KEY_ID,
    purpose: str = "analysis",
    timeout_seconds: float | None = None,
) -> dict:
    return await runtime_call_internal_model_via_proxy(
        requested_model=requested_model,
        body_json=body_json,
        api_key_id=api_key_id,
        purpose=purpose,
        client_ip=INTERNAL_ANALYSIS_CLIENT_IP,
        user_agent=f"{INTERNAL_ANALYSIS_USER_AGENT}:{purpose}",
        timeout_seconds=timeout_seconds,
    )

def _build_headers(provider_config: dict, api_key: str | None = None, protocol: str = "openai") -> dict:
    return build_headers(provider_config, api_key=api_key, protocol=protocol)


def _schedule_api_key_last_used_update(api_key_id: int | None) -> None:
    schedule_api_key_last_used_update(api_key_id)


def _log_request_info(
    provider,
    model,
    auth_header,
    messages,
    is_multimodal,
    stream,
    target_url,
    headers,
    body,
):
    log_request_info(
        provider,
        model,
        auth_header,
        messages,
        is_multimodal,
        stream,
        target_url,
        headers,
        body,
    )


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
    protocol="openai",
):
    return await runtime_handle_normal(
        client=client,
        url=url,
        headers=headers,
        body=body,
        provider=provider,
        model=model,
        messages=messages,
        start_time=start_time,
        req_body=req_body,
        api_key_id=api_key_id,
        client_ip=client_ip,
        user_agent=user_agent,
        request_context_tokens=request_context_tokens,
        semaphore=semaphore,
        api_key_model_semaphore=api_key_model_semaphore,
        request_id=request_id,
        chosen_key_id=chosen_key_id,
        protocol=protocol,
    )


async def handle_streaming(
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
    log_id,
    request,
    chosen_key_id=None,
    protocol="openai",
):
    return await runtime_handle_streaming(
        url=url,
        headers=headers,
        body=body,
        provider=provider,
        model=model,
        messages=messages,
        start_time=start_time,
        req_body=req_body,
        api_key_id=api_key_id,
        client_ip=client_ip,
        user_agent=user_agent,
        request_context_tokens=request_context_tokens,
        semaphore=semaphore,
        api_key_model_semaphore=api_key_model_semaphore,
        request_id=request_id,
        log_id=log_id,
        request=request,
        chosen_key_id=chosen_key_id,
        protocol=protocol,
    )
