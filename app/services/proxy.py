import asyncio
import json
import time
import uuid

from fastapi import Request
from fastapi.responses import Response, StreamingResponse

from app.core.config import (
    providers_cache,
    update_stats,
    logger,
    error_logger,
)
from app.core.log_sanitizer import (
    sanitize_payload_for_log,
    sanitize_text_for_log,
)
from app.core.client_ip import get_client_ip
from app.services.provider import (
    RouteResult,
    explain_provider_key_candidates,
    explain_provider_model_candidates,
    get_provider_and_model,
    get_provider_model_candidates,
    get_model_config,
    get_cached_context_hard_limit,
    get_disabled_provider_reason,
    pick_api_keys,
)
from app.services.auth import validate_api_key
from app.services.logging import create_request_log
from app.services.tokens import (
    estimate_request_context_tokens,
)
from app.services.deepseek_compat import is_deepseek_thinking_active, patch_reasoning_content
from app.services.busyness import LEVEL_LABELS
from app.services.message import preprocess_messages
from app.services.proxy_runtime import (
    LOCAL_RATE_LIMITED_STATUS,
    SEMAPHORE_RETRY_AFTER_SECONDS,
    USER_PROVIDER_MODEL_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS,
    _get_user_api_key_limit,
    _get_user_provider_model_limit,
    _get_or_create_user_api_key_semaphore,
    _get_or_create_user_provider_model_semaphore,
    _get_or_create_provider_key_semaphore,
    _get_or_create_standard_model_semaphore,
    _get_provider_key_limit,
    _openai_error_response,
    acquire_scoped_semaphore,
    build_headers,
    call_internal_model_via_proxy as runtime_call_internal_model_via_proxy,
    ensure_internal_api_key_exists as runtime_ensure_internal_api_key_exists,
    get_http_client,
    handle_normal as runtime_handle_normal,
    handle_streaming as runtime_handle_streaming,
    log_request_info,
    schedule_api_key_last_used_update,
)
from app.services.proxy_runtime.response_handler import _is_key_retryable_status, _is_route_fallback_status
from app.services.proxy_runtime.adapters import get_adapter


INTERNAL_ANALYSIS_API_KEY_ID = 1
INTERNAL_ANALYSIS_CLIENT_IP = "internal"
INTERNAL_ANALYSIS_USER_AGENT = "modelgate/internal-analysis"


def _api_key_bypasses_busyness(api_key_id: int | None) -> bool:
    from app.core.config import api_keys_cache

    for key_info in api_keys_cache.values():
        if key_info.get("id") == api_key_id:
            return bool(key_info.get("bypass_busyness", False))
    return False


def _get_api_key_preferred_tags(api_key_id: int | None) -> str | None:
    from app.core.config import api_keys_cache

    if not api_key_id:
        return None
    for key_info in api_keys_cache.values():
        if key_info.get("id") == api_key_id:
            return key_info.get("preferred_tags")
    return None


def _get_api_key_info(api_key_id: int | None) -> dict | None:
    from app.core.config import api_keys_cache

    if not api_key_id:
        return None
    for key_info in api_keys_cache.values():
        if key_info.get("id") == api_key_id:
            return key_info
    return {
        "id": api_key_id,
        "allowed_provider_model_ids": [],
        "allowed_model_ids": [],
    }


def check_model_access(
    key_info: dict | None,
    provider_model_id: int | None,
    model_id: int | None,
    requested_model_id: int | None = None,
    is_forced_provider: bool = False,
) -> bool:
    if not key_info:
        return False
    allowed_pm_ids = set(key_info.get("allowed_provider_model_ids") or [])
    allowed_model_ids = set(key_info.get("allowed_model_ids") or [])
    if not allowed_pm_ids and not allowed_model_ids:
        return True
    if is_forced_provider:
        return False
    if requested_model_id is not None and requested_model_id in allowed_model_ids:
        return True
    return model_id is not None and model_id in allowed_model_ids


def build_model_access_denied_message(model: str) -> str:
    user_login_url = "https://leturx.cc/modelgate/user/login"
    display_model = model or "unknown"
    return (
        f"当前 API Key 没有模型权限，无法使用模型 '{display_model}'。"
        f"请登录 {user_login_url} 查看自己的模型权限；"
        "如果你使用 OpenCode，请在 ModelGate 用户中心重新获取或更新 OpenCode 配置后重试。"
        "若管理员刚调整过权限，请刷新配置后再发起请求。"
    )


def _coerce_route_result(route, requested_model: str) -> RouteResult:
    if isinstance(route, RouteResult):
        return route
    provider_config, actual_model, provider_name = route
    model_config = get_model_config(provider_config, actual_model) if provider_config else None
    model_name = (
        model_config.get("model_name")
        if model_config
        else actual_model
    )
    upstream_model_name = (
        model_config.get("upstream_model_name")
        if model_config
        else actual_model
    )
    return RouteResult(
        provider_config=provider_config,
        provider_name=provider_name,
        provider_id=provider_config.get("id") if provider_config else None,
        provider_model_id=model_config.get("id") if model_config else None,
        model_id=model_config.get("model_id") if model_config else None,
        requested_model_id=model_config.get("model_id") if model_config else None,
        requested_model=requested_model,
        model_name=model_name or actual_model,
        upstream_model_name=upstream_model_name or actual_model,
        is_forced_provider="/" in requested_model,
    )


def _strip_key_secrets(items: list[dict]) -> list[dict]:
    stripped = []
    for item in items or []:
        safe_item = dict(item)
        safe_item.pop("api_key", None)
        stripped.append(safe_item)
    return stripped


def _build_routing_decision(
    base_decision: dict,
    route_result: RouteResult | None = None,
    key_explanation: dict | None = None,
    chosen_key_id: int | None = None,
    outcome: str | None = None,
) -> dict:
    decision = dict(base_decision or {})
    if route_result:
        decision.update(
            {
                "selected_provider": route_result.provider_name,
                "selected_provider_model_id": route_result.provider_model_id,
                "selected_model_id": route_result.model_id,
                "selected_upstream_model": route_result.upstream_model_name,
            }
        )
        if route_result.provider_key_ids:
            decision["selected_provider_key_scope"] = route_result.provider_key_ids
    if key_explanation is not None:
        decision["key_candidates"] = _strip_key_secrets(
            key_explanation.get("ordered", [])
        )
        decision["key_filtered"] = _strip_key_secrets(
            key_explanation.get("filtered", [])
        )
    if chosen_key_id is not None:
        decision["selected_provider_key_id"] = chosen_key_id
    if outcome:
        decision["outcome"] = outcome
    return decision


def _get_key_label(provider_config: dict, key_id: int | None) -> str | None:
    if not key_id:
        return None
    for k in (provider_config.get("api_keys") or []):
        if k.get("id") == key_id:
            return k.get("label") or None
    return None


def _response_error_code(response: Response) -> str | None:
    body = getattr(response, "body", b"")
    if not body:
        return None
    try:
        if isinstance(body, str):
            payload = json.loads(body)
        else:
            payload = json.loads(bytes(body).decode("utf-8"))
    except Exception:
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return str(code) if code not in (None, "") else None


def _should_prefer_local_rate_limit_response(response: Response) -> bool:
    return _response_error_code(response) in {
        "provider_disabled",
        "invalid_api_key",
        "no_available_api_key",
    }


def _best_disabled_key_failure(provider_config: dict, provider_name: str) -> tuple[str | None, int]:
    disabled_keys = provider_config.get("disabled_keys") or []
    best_reason = None
    best_priority = None
    for key in disabled_keys:
        reason = key.get("disabled_reason") or key.get("reason")
        if not reason:
            continue
        try:
            priority = int(key.get("priority") or 0)
        except (TypeError, ValueError):
            priority = 0
        if best_priority is None or priority > best_priority:
            label = key.get("label") or (
                f"Key#{key.get('id')}" if key.get("id") else "Key"
            )
            best_reason = f"{provider_name} {label}：{reason}"
            best_priority = priority
    if best_reason is not None:
        return best_reason, int(best_priority or 0)

    reasons = provider_config.get("disabled_key_reasons") or []
    if reasons:
        return str(reasons[0]), 0
    return None, -1


def _no_available_key_message(
    provider_name: str,
    route_result: RouteResult,
    best_disabled_reason: str | None = None,
) -> str:
    if route_result.provider_key_ids:
        return (
            f"模型 '{provider_name}/{route_result.model_name or route_result.upstream_model_name}' "
            "当前路由限定的 API Key 暂不可用"
            "（健康评分过低或限流被暂时屏蔽，请稍后重试）"
        )
    if best_disabled_reason:
        return f"'{provider_name}' 暂不可用：{best_disabled_reason}（请稍后重试）"
    return (
        f"供应商 '{provider_name}' 当前没有可用的 API Key"
        "（所有 Key 均因健康评分过低或限流被暂时屏蔽，请稍后重试）"
    )


def _check_busyness_rules(model: str) -> str | None:
    from app.core.config import busyness_state, system_config

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
    from app.core.config import busyness_state, system_config

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
    from app.core.config import busyness_state, system_config

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
    inbound_protocol = request.headers.get("x-inbound-protocol", "openai") or "openai"
    api_key_id, auth_error = await validate_api_key(auth_header, model)
    if auth_error:
        return _openai_error_response(
            auth_error, 401, "authentication_error", "invalid_api_key"
        )

    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    from app.services.billing_rules import check_daily_quota

    quota_info = await check_daily_quota(api_key_id)
    if quota_info:
        message = (
            f"Daily spending quota exceeded for this API key: "
            f"{quota_info['charged_cny']:.2f} / {quota_info['quota_cny']:.2f} CNY charged today. "
            f"Requests resume at {quota_info['reset_at']}."
        )
        logger.warning(
            "[DAILY QUOTA] key=%s charged=%.4f quota=%.2f — rejecting",
            api_key_id,
            quota_info["charged_cny"],
            quota_info["quota_cny"],
        )
        await create_request_log(
            "",
            model,
            status=LOCAL_RATE_LIMITED_STATUS,
            api_key_id=api_key_id,
            client_ip=client_ip,
            user_agent=user_agent,
            latency_ms=(time.time() - start_time) * 1000,
            downstream_status_code=429,
            error=message,
            inbound_protocol=inbound_protocol,
            requested_model=model,
            actual_model=model,
        )
        return _openai_error_response(
            message,
            429,
            "rate_limit_error",
            "daily_quota_exceeded",
            headers={"retry-after": str(quota_info["retry_after"])},
        )

    _schedule_api_key_last_used_update(api_key_id)

    bypass_busyness = _api_key_bypasses_busyness(api_key_id)
    busyness_headers = _get_busyness_suggestion_headers(model)
    busyness_model = model if bypass_busyness else _check_busyness_rules(model)
    if busyness_model is None:
        return _check_busyness_block(model)
    if busyness_model != model:
        model = busyness_model
        body_json["model"] = model

    block_response = None if bypass_busyness else _check_busyness_block(model)
    if block_response:
        return block_response

    requested_model = model
    request_context_tokens = estimate_request_context_tokens(body_json)
    from app.services.intent_classifier import classify_intent

    request_intent = classify_intent(body_json.get("messages") or [])

    hard_limit = get_cached_context_hard_limit(requested_model)
    if hard_limit and request_context_tokens > hard_limit:
        message = (
            f"This model's maximum context length is {hard_limit} tokens. "
            f"However, your messages resulted in ~{request_context_tokens} tokens. "
            "Please reduce the length of the messages or compact the conversation."
        )
        logger.warning(
            "[CONTEXT HARD LIMIT] model=%s estimated=%s limit=%s key=%s",
            requested_model,
            request_context_tokens,
            hard_limit,
            api_key_id,
        )
        await create_request_log(
            "",
            requested_model,
            status="error",
            api_key_id=api_key_id,
            client_ip=client_ip,
            user_agent=user_agent,
            request_context_tokens=request_context_tokens,
            latency_ms=(time.time() - start_time) * 1000,
            upstream_status_code=400,
            downstream_status_code=400,
            error=message,
            inbound_protocol=inbound_protocol,
            intent=request_intent,
            requested_model=requested_model,
            actual_model=requested_model,
        )
        return _openai_error_response(
            message, 400, "invalid_request_error", "context_length_exceeded"
        )

    try:
        model_explanation = await explain_provider_model_candidates(
            model,
            messages=body_json.get("messages"),
            preferred_tags=_get_api_key_preferred_tags(api_key_id),
            context_tokens=request_context_tokens,
        )
    except Exception as exc:
        logger.warning("[ROUTING EXPLAIN] model explanation unavailable: %s", exc)
        model_explanation = {"ordered": [], "filtered": []}
    routing_decision_base = {
        "requested_model": requested_model,
        "context_tokens": request_context_tokens,
        "model_candidates": model_explanation.get("ordered", []),
        "model_filtered": model_explanation.get("filtered", []),
    }
    route_candidates = [
        _coerce_route_result(route, requested_model)
        for route in await get_provider_model_candidates(
            model,
            messages=body_json.get("messages"),
            preferred_tags=_get_api_key_preferred_tags(api_key_id),
            context_tokens=request_context_tokens,
        )
    ]
    key_info = _get_api_key_info(api_key_id)
    provider_config = None
    provider_name = ""
    actual_model = requested_model
    chosen_key_id = None

    provider_key_semaphore = None
    user_api_key_semaphore = None
    user_provider_model_semaphore = None
    model_concurrency_semaphore = None
    acquired = False
    user_api_key_acquired = False
    user_provider_model_acquired = False
    model_conc_acquired = False

    entered_handler = False

    from app.services.provider import get_cached_model_max_concurrent

    model_conc_limit = get_cached_model_max_concurrent(model)
    if model_conc_limit is not None:
        _, model_concurrency_semaphore = _get_or_create_standard_model_semaphore(
            model, model_conc_limit
        )
        if model_conc_limit == 0:
            message = (
                f"模型 '{model}' 已被设置为并发 0（停用），无法处理新请求"
            )
            logger.warning("[MODEL CONCURRENCY] %s limit=0 — rejecting", model)
            update_stats(
                provider_name,
                actual_model,
                0,
                api_key_id=api_key_id,
                is_rate_limited=True,
            )
            await create_request_log(
                provider_name,
                actual_model,
                status=LOCAL_RATE_LIMITED_STATUS,
                api_key_id=api_key_id,
                client_ip=client_ip,
                user_agent=user_agent,
                request_context_tokens=estimate_request_context_tokens(body_json),
                latency_ms=(time.time() - start_time) * 1000,
                upstream_status_code=429,
                downstream_status_code=429,
                error=message,
                inbound_protocol=inbound_protocol,
                intent=request_intent,
                requested_model=requested_model,
                actual_model=actual_model,
            )
            return _openai_error_response(
                message,
                429,
                "rate_limit_error",
                "model_zero_concurrency",
                headers={
                    **busyness_headers,
                    "retry-after": str(SEMAPHORE_RETRY_AFTER_SECONDS),
                },
            )

    try:
        # Standard-model concurrency cap: acquire a slot once for the whole
        # request (all route/key fallback attempts). limit==0 was already
        # rejected above; positive limits queue with the shared timeout.
        if model_concurrency_semaphore is not None and model_conc_limit > 0:
            try:
                await acquire_scoped_semaphore(
                    model_concurrency_semaphore,
                    USER_PROVIDER_MODEL_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS,
                )
                model_conc_acquired = True
            except asyncio.TimeoutError:
                message = (
                    f"模型 '{model}' 的总并发请求已达上限，请等待当前请求完成后再试"
                )
                logger.warning(
                    "[MODEL CONCURRENCY] %s at max concurrency (%d)", model, model_conc_limit
                )
                update_stats(
                    provider_name,
                    actual_model,
                    0,
                    api_key_id=api_key_id,
                    is_rate_limited=True,
                )
                await create_request_log(
                    provider_name,
                    actual_model,
                    status=LOCAL_RATE_LIMITED_STATUS,
                    api_key_id=api_key_id,
                    client_ip=client_ip,
                    user_agent=user_agent,
                    request_context_tokens=estimate_request_context_tokens(body_json),
                    latency_ms=(time.time() - start_time) * 1000,
                    upstream_status_code=429,
                    downstream_status_code=429,
                    error=message,
                    inbound_protocol=inbound_protocol,
                    intent=request_intent,
                    requested_model=requested_model,
                    actual_model=actual_model,
                )
                return _openai_error_response(
                    message,
                    429,
                    "rate_limit_error",
                    "model_concurrency_reached",
                    headers={
                        **busyness_headers,
                        "retry-after": str(SEMAPHORE_RETRY_AFTER_SECONDS),
                    },
                )
        if not bypass_busyness:
            user_api_key_sem_key, user_api_key_semaphore = (
                _get_or_create_user_api_key_semaphore(
                    api_key_id,
                    _get_user_api_key_limit(False),
                )
            )
            try:
                await acquire_scoped_semaphore(
                    user_api_key_semaphore,
                    USER_PROVIDER_MODEL_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS,
                )
                user_api_key_acquired = True
            except asyncio.TimeoutError:
                message = "您的 API Key 总并发请求已达上限，请等待当前请求完成后再试"
                logger.warning(
                    "[RATE LIMIT] %s at max concurrency", user_api_key_sem_key
                )
                update_stats(
                    provider_name,
                    actual_model,
                    0,
                    api_key_id=api_key_id,
                    is_rate_limited=True,
                )
                await create_request_log(
                    provider_name,
                    actual_model,
                    status=LOCAL_RATE_LIMITED_STATUS,
                    api_key_id=api_key_id,
                    client_ip=client_ip,
                    user_agent=user_agent,
                    request_context_tokens=estimate_request_context_tokens(body_json),
                    latency_ms=(time.time() - start_time) * 1000,
                    upstream_status_code=429,
                    downstream_status_code=429,
                    error=message,
                    inbound_protocol=inbound_protocol,
                    intent=request_intent,
                    requested_model=requested_model,
                    actual_model=actual_model,
                    routing_decision=_build_routing_decision(
                        routing_decision_base,
                        outcome="user_global_concurrency_reached",
                    ),
                )
                return _openai_error_response(
                    message,
                    429,
                    "rate_limit_error",
                    "user_global_concurrency_reached",
                    headers={
                        **busyness_headers,
                        "retry-after": str(SEMAPHORE_RETRY_AFTER_SECONDS),
                    },
                )

        last_response = None
        no_provider_seen = False
        access_denied_seen = False
        known_model_without_provider_seen = False
        first_no_key_failure = None
        preferred_local_rate_limit_response = None

        def remember_local_rate_limit_response(message: str, code: str) -> None:
            nonlocal preferred_local_rate_limit_response
            if preferred_local_rate_limit_response is not None:
                return
            preferred_local_rate_limit_response = _openai_error_response(
                message,
                429,
                "rate_limit_error",
                code,
                headers={
                    **busyness_headers,
                    "retry-after": str(SEMAPHORE_RETRY_AFTER_SECONDS),
                },
            )

        if route_candidates and model_explanation.get("is_auto_model"):
            from app.core.config import busyness_state
            cand_summary = ",".join(
                f"{r.provider_name}/{r.upstream_model_name or r.model_name}(pm={r.provider_model_id})"
                for r in route_candidates
            )
            logger.warning(
                "[AUTO ROUTING] user=%s candidates=[%s] busyness_level=%s",
                api_key_id,
                cand_summary,
                busyness_state.get("level"),
            )

        for route_idx, route_result in enumerate(route_candidates):
            provider_config = route_result.provider_config
            provider_name = route_result.provider_name
            standard_model = route_result.model_name or requested_model
            upstream_model = route_result.upstream_model_name or standard_model
            actual_model = standard_model
            is_last_route = route_idx == len(route_candidates) - 1

            if not provider_config:
                no_provider_seen = True
                if route_result.model_id or route_result.requested_model_id:
                    known_model_without_provider_seen = True
                continue

            if not check_model_access(
                key_info,
                route_result.provider_model_id,
                route_result.model_id,
                requested_model_id=route_result.requested_model_id,
                is_forced_provider=route_result.is_forced_provider,
            ):
                access_denied_seen = True
                continue

            model_config = get_model_config(provider_config, standard_model)
            if model_config:
                max_level = model_config.get("max_busyness_level")
                if max_level is not None:
                    from app.core.config import busyness_state

                    current_level = busyness_state.get("level", 6)
                    if current_level > max_level and not bypass_busyness:
                        if not is_last_route and not route_result.is_forced_provider:
                            continue
                        level_label = LEVEL_LABELS.get(current_level, "")
                        return _openai_error_response(
                            f"当前系统{level_label}，该模型不可用，请前往用户界面查看推荐模型列表",
                            503,
                            "server_error",
                            "model_unavailable",
                            headers=busyness_headers or None,
                        )

            request_context_tokens = estimate_request_context_tokens(body_json)
            all_keys = pick_api_keys(
                provider_config,
                api_key_id,
                provider_name,
                context_tokens=request_context_tokens,
                allowed_key_ids=route_result.provider_key_ids,
            )
            key_explanation = explain_provider_key_candidates(
                provider_config,
                api_key_id,
                provider_name,
                context_tokens=request_context_tokens,
                allowed_key_ids=route_result.provider_key_ids,
            )
            if not key_explanation.get("ordered") and all_keys:
                key_explanation = {
                    "ordered": [
                        {
                            "key_id": key_id,
                            "label": _get_key_label(provider_config, key_id),
                            "priority": 0,
                            "health": 100,
                            "policy_priority": 0,
                            "sticky": False,
                            "standby": False,
                            "matched_rules": [],
                            "filtered_reasons": [],
                        }
                        for _api_key, key_id in all_keys
                    ],
                    "filtered": [],
                }
            if not all_keys:
                reasons = provider_config.get("disabled_key_reasons") or []
                best_disabled_reason, best_disabled_priority = _best_disabled_key_failure(
                    provider_config,
                    provider_name,
                )
                msg = _no_available_key_message(
                    provider_name,
                    route_result,
                    best_disabled_reason,
                )
                if (
                    first_no_key_failure is None
                    or best_disabled_priority > first_no_key_failure.get("disabled_priority", -1)
                ):
                    first_no_key_failure = {
                        "provider_name": provider_name,
                        "actual_model": actual_model,
                        "message": msg,
                        "reasons": reasons,
                        "disabled_priority": best_disabled_priority,
                        "route_result": route_result,
                        "key_explanation": key_explanation,
                    }
                if not is_last_route and not route_result.is_forced_provider:
                    continue
                reported_failure = first_no_key_failure
                provider_name = reported_failure["provider_name"]
                actual_model = reported_failure["actual_model"]
                msg = reported_failure["message"]
                reasons = reported_failure["reasons"]
                route_result = reported_failure["route_result"]
                key_explanation = reported_failure["key_explanation"]
                logger.warning("[NO KEY] provider=%s reasons=%s", provider_name, reasons)
                update_stats(
                    provider_name,
                    actual_model,
                    0,
                    api_key_id=api_key_id,
                    is_rate_limited=True,
                )
                await create_request_log(
                    provider_name,
                    actual_model,
                    status=LOCAL_RATE_LIMITED_STATUS,
                    api_key_id=api_key_id,
                    client_ip=client_ip,
                    user_agent=user_agent,
                    request_context_tokens=request_context_tokens,
                    latency_ms=(time.time() - start_time) * 1000,
                    upstream_status_code=429,
                    downstream_status_code=429,
                    error=msg,
                    inbound_protocol=inbound_protocol,
                    intent=request_intent,
                    requested_model=requested_model,
                    actual_model=actual_model,
                    routing_decision=_build_routing_decision(
                        routing_decision_base,
                        route_result,
                        key_explanation={
                            "ordered": [],
                            "filtered": key_explanation.get("filtered", []),
                        },
                    ),
                )
                retry_headers = {"Retry-After": "30"}
                if busyness_headers:
                    retry_headers.update(busyness_headers)
                return _openai_error_response(
                    msg,
                    429,
                    "rate_limit_error",
                    "no_available_api_key",
                    headers=retry_headers,
                )

            route_body_json = json.loads(json.dumps(body_json))
            route_body_json["model"] = upstream_model
            is_multimodal = (
                model_config.get("is_multimodal", False) if model_config else False
            )
            merge_messages = provider_config.get("merge_consecutive_messages", False)
            route_body_json = preprocess_messages(route_body_json, merge_messages, is_multimodal)
            messages = route_body_json["messages"]

            if is_deepseek_thinking_active(provider_name, upstream_model, route_body_json, model_config):
                messages = patch_reasoning_content(messages)

            request_intent = classify_intent(messages)
            stream = route_body_json.get("stream", False)

            adapter = get_adapter(provider_config.get("protocol", "openai"))
            if stream:
                stream_options = route_body_json.get("stream_options")
                if isinstance(stream_options, dict):
                    stream_options = dict(stream_options)
                else:
                    stream_options = {}
                stream_options["include_usage"] = True
                route_body_json["stream_options"] = stream_options

            route_body_json = adapter.preprocess_body(route_body_json, provider_config)
            route_body_json = adapter.transform_request(route_body_json, provider_config)

            if provider_name == "minimax" and merge_messages:
                route_body_json.pop("thinking", None)
                route_body_json.pop("stream_options", None)
                route_body_json["reasoning_split"] = True

            if provider_config.get("protocol", "openai") != "openai":
                logger.debug(
                    "[ADAPTER] protocol=%s transformed_body=%s",
                    provider_config.get("protocol"),
                    sanitize_payload_for_log(route_body_json),
                )

            body = json.dumps(route_body_json).encode()
            request_context_tokens = estimate_request_context_tokens(route_body_json)
            adapter_endpoint = adapter.get_target_path(endpoint)
            provider_protocol = provider_config.get("protocol", "openai")
            route_exhausted = False

            for attempt_idx, (chosen_api_key, chosen_key_id) in enumerate(all_keys):
                target_url = f"{provider_config['base_url']}{adapter_endpoint}"
                headers = build_headers(provider_config, api_key=chosen_api_key, protocol=provider_protocol)

                if attempt_idx == 0:
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

                if chosen_key_id is not None:
                    provider_key_sem_key, provider_key_semaphore = _get_or_create_provider_key_semaphore(
                        chosen_key_id,
                        provider_name,
                        _get_provider_key_limit(provider_config, chosen_key_id),
                    )
                    try:
                        await acquire_scoped_semaphore(
                            provider_key_semaphore,
                            USER_PROVIDER_MODEL_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS,
                        )
                        acquired = True
                    except asyncio.TimeoutError:
                        message = (
                            f"当前模型 '{requested_model}' 的可用供应商 Key 并发已达上限，请稍后重试"
                        )
                        remember_local_rate_limit_response(
                            message,
                            "provider_key_concurrency_reached",
                        )
                        if attempt_idx < len(all_keys) - 1:
                            logger.warning(
                                "[KEY FALLBACK] Key %s provider-key concurrency reached (limit=%s), trying next key",
                                chosen_key_id,
                                getattr(provider_key_semaphore, "_modelgate_scoped_limit", "?"),
                            )
                            continue
                        if not is_last_route and not route_result.is_forced_provider:
                            logger.warning(
                                "[ROUTE FALLBACK] Provider %s provider-key concurrency exhausted (limit=%s), trying next provider",
                                provider_name,
                                getattr(provider_key_semaphore, "_modelgate_scoped_limit", "?"),
                            )
                            route_exhausted = True
                            break
                        logger.warning(
                            "[RATE LIMIT] %s at max concurrency (limit=%s)",
                            provider_key_sem_key,
                            getattr(provider_key_semaphore, "_modelgate_scoped_limit", "?"),
                        )
                        update_stats(
                            provider_name,
                            actual_model,
                            0,
                            api_key_id=api_key_id,
                            is_rate_limited=True,
                        )
                        await create_request_log(
                            provider_name,
                            actual_model,
                            status=LOCAL_RATE_LIMITED_STATUS,
                            api_key_id=api_key_id,
                            client_ip=client_ip,
                            user_agent=user_agent,
                            request_context_tokens=request_context_tokens,
                            latency_ms=(time.time() - start_time) * 1000,
                            upstream_status_code=429,
                            downstream_status_code=429,
                            error=message,
                            inbound_protocol=inbound_protocol,
                            intent=request_intent,
                            requested_model=requested_model,
                            actual_model=actual_model,
                            provider_key_id=chosen_key_id,
                            provider_key_label=_get_key_label(provider_config, chosen_key_id),
                            routing_decision=_build_routing_decision(
                                routing_decision_base,
                                route_result,
                                key_explanation,
                                chosen_key_id,
                                "provider_key_concurrency_reached",
                            ),
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

                    provider_model_key = f"{provider_name}/{route_result.provider_model_id or upstream_model}"
                    user_provider_model_sem_key, user_provider_model_semaphore = (
                        _get_or_create_user_provider_model_semaphore(
                            api_key_id,
                            chosen_key_id,
                            provider_model_key,
                            _get_user_provider_model_limit(bypass_busyness),
                        )
                    )
                    try:
                        await acquire_scoped_semaphore(
                            user_provider_model_semaphore,
                            USER_PROVIDER_MODEL_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS,
                        )
                        user_provider_model_acquired = True
                    except asyncio.TimeoutError:
                        if acquired and provider_key_semaphore is not None:
                            provider_key_semaphore.release()
                            acquired = False
                        message = (
                            f"当前模型 '{requested_model}' 的用户并发已达上限，请等待当前请求完成后再试"
                        )
                        remember_local_rate_limit_response(
                            message,
                            "user_provider_model_concurrency_reached",
                        )
                        if attempt_idx < len(all_keys) - 1:
                            logger.warning(
                                "[KEY FALLBACK] Key %s user-concurrency reached (limit=%s), trying next key",
                                chosen_key_id,
                                getattr(user_provider_model_semaphore, "_modelgate_scoped_limit", "?"),
                            )
                            continue
                        if not is_last_route and not route_result.is_forced_provider:
                            logger.warning(
                                "[ROUTE FALLBACK] Provider %s user/provider-model concurrency exhausted (limit=%s), trying next provider",
                                provider_name,
                                getattr(user_provider_model_semaphore, "_modelgate_scoped_limit", "?"),
                            )
                            route_exhausted = True
                            break
                        logger.warning(
                            "[RATE LIMIT] %s at max concurrency (limit=%s)",
                            user_provider_model_sem_key,
                            getattr(user_provider_model_semaphore, "_modelgate_scoped_limit", "?"),
                        )
                        update_stats(
                            provider_name,
                            actual_model,
                            0,
                            api_key_id=api_key_id,
                            is_rate_limited=True,
                        )
                        await create_request_log(
                            provider_name,
                            actual_model,
                            status=LOCAL_RATE_LIMITED_STATUS,
                            api_key_id=api_key_id,
                            client_ip=client_ip,
                            user_agent=user_agent,
                            request_context_tokens=request_context_tokens,
                            latency_ms=(time.time() - start_time) * 1000,
                            upstream_status_code=429,
                            downstream_status_code=429,
                            error=message,
                            inbound_protocol=inbound_protocol,
                            intent=request_intent,
                            requested_model=requested_model,
                            actual_model=actual_model,
                            provider_key_id=chosen_key_id,
                            provider_key_label=_get_key_label(provider_config, chosen_key_id),
                            routing_decision=_build_routing_decision(
                                routing_decision_base,
                                route_result,
                                key_explanation,
                                chosen_key_id,
                                "user_provider_model_concurrency_reached",
                            ),
                        )
                        return _openai_error_response(
                            message,
                            429,
                            "rate_limit_error",
                            "user_provider_model_concurrency_reached",
                            headers={
                                **busyness_headers,
                                "retry-after": str(SEMAPHORE_RETRY_AFTER_SECONDS),
                            },
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
                        inbound_protocol=inbound_protocol,
                        intent=request_intent,
                        request_messages=messages,
                        requested_model=requested_model,
                        actual_model=actual_model,
                        provider_key_id=chosen_key_id,
                        provider_key_label=_get_key_label(provider_config, chosen_key_id),
                        routing_decision=_build_routing_decision(
                            routing_decision_base,
                            route_result,
                            key_explanation,
                            chosen_key_id,
                            "stream_started",
                        ),
                    )

                client = get_http_client()
                entered_handler = True
                try:
                    if stream:
                        response = await handle_streaming(
                            target_url,
                            headers,
                            body,
                            provider_name,
                            actual_model,
                            messages,
                            start_time,
                            route_body_json,
                            api_key_id,
                            client_ip,
                            user_agent,
                            request_context_tokens,
                            provider_key_semaphore,
                            user_provider_model_semaphore,
                            user_api_key_semaphore,
                            request_id,
                            stream_log_id,
                            request,
                            chosen_key_id=chosen_key_id,
                            protocol=provider_protocol,
                            extra_response_headers=busyness_headers,
                            intent=request_intent,
                            requested_model=requested_model,
                            provider_key_label=_get_key_label(provider_config, chosen_key_id),
                            model_concurrency_semaphore=model_concurrency_semaphore,
                            routing_decision=_build_routing_decision(
                                routing_decision_base,
                                route_result,
                                key_explanation,
                                chosen_key_id,
                                "stream_started",
                            ),
                        )
                        if isinstance(response, StreamingResponse):
                            user_api_key_acquired = False
                            user_api_key_semaphore = None
                        model_conc_acquired = False
                        model_concurrency_semaphore = None
                    else:
                        response = await handle_normal(
                            client,
                            target_url,
                            headers,
                            body,
                            provider_name,
                            actual_model,
                            messages,
                            start_time,
                            route_body_json,
                            api_key_id,
                            client_ip,
                            user_agent,
                            request_context_tokens,
                            provider_key_semaphore,
                            user_provider_model_semaphore,
                            request_id,
                            chosen_key_id=chosen_key_id,
                            protocol=provider_protocol,
                            extra_response_headers=busyness_headers,
                            intent=request_intent,
                            requested_model=requested_model,
                            provider_key_label=_get_key_label(provider_config, chosen_key_id),
                            inbound_protocol=inbound_protocol,
                            model_concurrency_semaphore=model_concurrency_semaphore,
                            routing_decision=_build_routing_decision(
                                routing_decision_base,
                                route_result,
                                key_explanation,
                                chosen_key_id,
                                "normal_started",
                            ),
                        )
                except Exception as handler_exc:
                    logger.warning(
                        "[ROUTE FALLBACK] Provider %s raised %s: %s, trying next provider",
                        provider_name,
                        type(handler_exc).__name__,
                        sanitize_text_for_log(handler_exc, limit=200),
                    )
                    acquired = False
                    user_provider_model_acquired = False
                    provider_key_semaphore = None
                    user_provider_model_semaphore = None
                    model_conc_acquired = False
                    model_concurrency_semaphore = None
                    last_response = _openai_error_response(
                        f"供应商 '{provider_name}' 请求异常: {type(handler_exc).__name__}",
                        502,
                        "api_error",
                        "provider_request_exception",
                        headers=busyness_headers or None,
                    )
                    if not is_last_route and not route_result.is_forced_provider:
                        route_exhausted = True
                        break
                    if route_result.is_forced_provider:
                        return last_response
                    break

                acquired = False
                user_provider_model_acquired = False
                provider_key_semaphore = None
                user_provider_model_semaphore = None
                model_conc_acquired = False
                model_concurrency_semaphore = None

                if isinstance(response, Response) and not isinstance(response, StreamingResponse):
                    last_response = response
                    status_code = response.status_code

                    if status_code < 400:
                        return response

                    if _is_key_retryable_status(status_code):
                        if attempt_idx < len(all_keys) - 1:
                            logger.warning(
                                "[KEY FALLBACK] Key %s returned status %d, trying next key",
                                chosen_key_id, status_code,
                            )
                            continue
                        if not is_last_route and not route_result.is_forced_provider:
                            logger.warning(
                                "[ROUTE FALLBACK] Provider %s keys returned retryable errors, trying next provider",
                                provider_name,
                            )
                            route_exhausted = True
                            break
                        if (
                            preferred_local_rate_limit_response is not None
                            and _should_prefer_local_rate_limit_response(response)
                        ):
                            if model_explanation.get("is_auto_model"):
                                from app.core.config import busyness_state
                                logger.warning(
                                    "[AUTO BLOCKED] user=%s model=%s busyness_level=%s routes_exhausted=%d",
                                    api_key_id,
                                    requested_model,
                                    busyness_state.get("level"),
                                    len(route_candidates),
                                )
                            return preferred_local_rate_limit_response
                        if route_result.is_forced_provider:
                            return response
                        break

                    if _is_route_fallback_status(status_code):
                        if not is_last_route and not route_result.is_forced_provider:
                            logger.warning(
                                "[ROUTE FALLBACK] Provider %s returned status %d, trying next provider",
                                provider_name, status_code,
                            )
                            route_exhausted = True
                            break
                        if route_result.is_forced_provider:
                            return response
                        break

                return response

            if route_exhausted:
                continue

        if last_response is not None:
            if (
                preferred_local_rate_limit_response is not None
                and _should_prefer_local_rate_limit_response(last_response)
            ):
                return preferred_local_rate_limit_response
            logger.warning(
                "[ROUTE FALLBACK] All providers failed for model %s, last status=%d",
                model,
                getattr(last_response, "status_code", 0),
            )
            return _openai_error_response(
                f"模型 '{model}' 当前没有可用的供应商，所有供应商均请求失败，请稍后重试或联系管理员检查供应商状态",
                503,
                "server_error",
                "model_unavailable",
            )
        if access_denied_seen:
            return _openai_error_response(
                build_model_access_denied_message(requested_model),
                403,
                "permission_error",
                "model_access_denied",
            )
        if known_model_without_provider_seen:
            return _openai_error_response(
                f"模型 '{model}' 当前暂无可用供应商或供应商 Key，请稍后重试或联系管理员检查供应商与 Key 状态",
                503,
                "server_error",
                "model_unavailable",
            )
        if no_provider_seen:
            disabled_reason = (
                await get_disabled_provider_reason(provider_name) if provider_name else None
            )
            if disabled_reason:
                return _openai_error_response(
                    f"模型 '{model}' 暂不可用，请尝试其他模型",
                    400,
                    "invalid_request_error",
                    "provider_disabled",
                )
        logger.error("[PROXY ERROR] Unknown provider for model: %s", model)
        logger.debug(
            "[PROXY ERROR] Available providers: %s", list(providers_cache.keys())
        )
        return _openai_error_response(
            f"未找到模型: {model}，请检查模型名称或前往用户界面查看可用模型",
            400,
            "invalid_request_error",
            "model_not_found",
        )
    except Exception as e:
        if not entered_handler:
            if user_provider_model_acquired and user_provider_model_semaphore is not None:
                user_provider_model_semaphore.release()
            if acquired and provider_key_semaphore is not None:
                provider_key_semaphore.release()
        latency = (time.time() - start_time) * 1000
        update_stats(
            provider_name, actual_model, 0, api_key_id=api_key_id, is_error=True
        )
        await create_request_log(
            provider_name,
            actual_model,
            status="error",
            api_key_id=api_key_id,
            client_ip=client_ip,
            user_agent=user_agent,
            request_context_tokens=estimate_request_context_tokens(body_json),
            latency_ms=latency,
            downstream_status_code=502,
            error=str(e),
            inbound_protocol=inbound_protocol,
            intent=request_intent,
            requested_model=requested_model,
            actual_model=actual_model,
            provider_key_id=chosen_key_id,
            provider_key_label=_get_key_label(provider_config, chosen_key_id),
        )
        error_logger.error(
            f"[REQUEST ERROR] Provider: {provider_name}, Model: {actual_model}\n"
            f"  Error: {type(e).__name__}: {sanitize_text_for_log(e)}\n"
            f"  Request Body: {sanitize_payload_for_log(body_json)}"
        )
        err_msg = (
            f"请求处理失败: {type(e).__name__}"
        )
        return _openai_error_response(err_msg, 502, "api_error", "proxy_error")
    finally:
        if user_api_key_acquired and user_api_key_semaphore is not None:
            user_api_key_semaphore.release()
        if model_conc_acquired and model_concurrency_semaphore is not None:
            model_concurrency_semaphore.release()

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
    provider_key_semaphore,
    user_provider_model_semaphore,
    request_id,
    chosen_key_id=None,
    protocol="openai",
    extra_response_headers=None,
    intent=None,
    requested_model=None,
    provider_key_label=None,
    routing_decision=None,
    inbound_protocol=None,
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
        provider_key_semaphore=provider_key_semaphore,
        user_provider_model_semaphore=user_provider_model_semaphore,
        request_id=request_id,
        chosen_key_id=chosen_key_id,
        protocol=protocol,
        extra_response_headers=extra_response_headers,
        intent=intent,
        requested_model=requested_model,
        provider_key_label=provider_key_label,
        routing_decision=routing_decision,
        inbound_protocol=inbound_protocol,
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
    provider_key_semaphore,
    user_provider_model_semaphore,
    user_api_key_semaphore,
    request_id,
    log_id,
    request,
    chosen_key_id=None,
    protocol="openai",
    extra_response_headers=None,
    intent=None,
    requested_model=None,
    provider_key_label=None,
    routing_decision=None,
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
        provider_key_semaphore=provider_key_semaphore,
        user_provider_model_semaphore=user_provider_model_semaphore,
        user_api_key_semaphore=user_api_key_semaphore,
        request_id=request_id,
        log_id=log_id,
        request=request,
        chosen_key_id=chosen_key_id,
        protocol=protocol,
        extra_response_headers=extra_response_headers,
        intent=intent,
        requested_model=requested_model,
        provider_key_label=provider_key_label,
        routing_decision=routing_decision,
    )
