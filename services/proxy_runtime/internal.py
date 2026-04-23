import asyncio
import json
import time

from sqlalchemy import select

from core.config import logger, record_request_rate, update_stats
from core.database import ApiKey, async_session_maker
from core.log_sanitizer import sanitize_text_for_log
from services.logging import log_request
from services.message import preprocess_messages
from services.minimax import process_minimax_response
from services.provider import (
    get_model_config,
    get_provider_and_model,
    pick_api_key,
)
from services.provider_limiter import check_usage_limit_error, disable_provider_key
from services.proxy_runtime.adapters import get_adapter
from services.proxy_runtime.client import (
    PROVIDER_REQUEST_TIMEOUT_SECONDS,
    get_http_client,
)
from services.proxy_runtime.common import schedule_api_key_last_used_update
from services.proxy_runtime.concurrency import (
    RATE_LIMITED_STATUSES,
    SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS,
    _get_api_key_model_limit,
    _get_or_create_api_key_model_semaphore,
    _get_or_create_provider_key_semaphore,
    _get_provider_key_limit,
)
from services.proxy_runtime.request_builder import build_headers
from services.proxy_runtime.response_handler import (
    _extract_provider_error,
    _extract_response_fields,
    _resolve_request_status,
)
from services.tokens import (
    build_response_meta,
    build_tokens_record,
    estimate_request_context_tokens,
    log_response_meta,
)


async def ensure_internal_api_key_exists(api_key_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(ApiKey.id).where(ApiKey.id == api_key_id, ApiKey.is_active)
        )
        return result.scalar_one_or_none() is not None


async def call_internal_model_via_proxy(
    requested_model: str,
    body_json: dict,
    api_key_id: int,
    purpose: str,
    client_ip: str,
    user_agent: str,
    timeout_seconds: float | None = None,
) -> dict:
    start_time = time.time()

    if not await ensure_internal_api_key_exists(api_key_id):
        return {
            "ok": False,
            "provider_name": None,
            "actual_model_name": None,
            "status_code": None,
            "payload": None,
            "error": f"Internal API key {api_key_id} not found or inactive",
        }

    req_body = dict(body_json)
    provider_config, actual_model, provider_name = await get_provider_and_model(
        requested_model
    )
    if not provider_config:
        return {
            "ok": False,
            "provider_name": None,
            "actual_model_name": None,
            "status_code": None,
            "payload": None,
            "error": f"Unknown provider for model: {requested_model}",
        }

    api_key_model_sem_key, api_key_model_semaphore = (
        _get_or_create_api_key_model_semaphore(
            api_key_id, requested_model, _get_api_key_model_limit()
        )
    )
    api_key_model_acquired = False
    provider_key_semaphore = None
    acquired = False

    try:
        await asyncio.wait_for(
            api_key_model_semaphore.acquire(),
            timeout=SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS,
        )
        api_key_model_acquired = True
    except asyncio.TimeoutError:
        message = (
            f"API key {api_key_id} already reached max concurrency for model '{requested_model}'"
        )
        logger.warning("[RATE LIMIT] %s at max concurrency", api_key_model_sem_key)
        return {
            "ok": False,
            "provider_name": provider_name,
            "actual_model_name": actual_model,
            "status_code": 429,
            "payload": None,
            "error": message,
        }

    try:
        chosen_api_key, chosen_key_id = pick_api_key(
            provider_config, api_key_id, provider_name
        )
        if not chosen_api_key:
            api_key_model_semaphore.release()
            api_key_model_acquired = False
            return {
                "ok": False,
                "provider_name": provider_name,
                "actual_model_name": actual_model,
                "status_code": None,
                "payload": None,
                "error": f"No active provider key available for '{provider_name}'",
            }

        if chosen_key_id is not None:
            provider_key_sem_key, provider_key_semaphore = (
                _get_or_create_provider_key_semaphore(
                    chosen_key_id,
                    provider_name,
                    _get_provider_key_limit(provider_config, chosen_key_id),
                )
            )
            try:
                await asyncio.wait_for(
                    provider_key_semaphore.acquire(),
                    timeout=SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS,
                )
                acquired = True
            except asyncio.TimeoutError:
                api_key_model_semaphore.release()
                api_key_model_acquired = False
                message = (
                    f"Provider key {chosen_key_id} for '{provider_name}' is at max concurrency"
                )
                logger.warning("[RATE LIMIT] %s at max concurrency", provider_key_sem_key)
                return {
                    "ok": False,
                    "provider_name": provider_name,
                    "actual_model_name": actual_model,
                    "status_code": 429,
                    "payload": None,
                    "error": message,
                }

        schedule_api_key_last_used_update(api_key_id)
        protocol = provider_config.get("protocol", "openai")
        adapter = get_adapter(protocol)
        model_config = get_model_config(provider_config, actual_model)
        req_body["model"] = actual_model
        is_multimodal = (
            model_config.get("is_multimodal", False) if model_config else False
        )
        merge_messages = provider_config.get("merge_consecutive_messages", False)
        req_body = preprocess_messages(req_body, merge_messages, is_multimodal)

        if req_body.get("stream"):
            req_body["stream"] = False
        req_body.pop("stream_options", None)

        req_body = adapter.preprocess_body(req_body, provider_config)
        req_body = adapter.transform_request(req_body, provider_config)

        if provider_name == "minimax" and merge_messages:
            req_body.pop("thinking", None)
            req_body["reasoning_split"] = True

        request_context_tokens = estimate_request_context_tokens(req_body)
        headers = build_headers(
            provider_config,
            api_key=chosen_api_key,
            protocol=protocol,
        )
        target_path = adapter.get_target_path("/chat/completions")
        target_url = f"{provider_config['base_url']}{target_path}"
        body = json.dumps(req_body).encode("utf-8")

        client = get_http_client()
        resp = await client.post(
            target_url,
            headers=headers,
            content=body,
            timeout=timeout_seconds or PROVIDER_REQUEST_TIMEOUT_SECONDS,
        )

        try:
            raw_resp_json = resp.json()
        except json.JSONDecodeError:
            raw_resp_json = {}

        usage_limit_err = check_usage_limit_error(raw_resp_json, provider_name)
        if usage_limit_err:
            await disable_provider_key(
                provider_name, provider_config, chosen_key_id, usage_limit_err
            )
            return {
                "ok": False,
                "provider_name": provider_name,
                "actual_model_name": actual_model,
                "status_code": resp.status_code,
                "payload": raw_resp_json,
                "error": usage_limit_err,
            }

        latency = (time.time() - start_time) * 1000
        if resp.status_code >= 400 and protocol != "openai":
            resp_json = adapter.transform_error_response(raw_resp_json, resp.status_code)
        else:
            resp_json = adapter.transform_response(raw_resp_json)
        if provider_name == "minimax":
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
        provider_error = _extract_provider_error(resp_json)
        request_status = _resolve_request_status(resp.status_code, provider_error)
        is_error = request_status == "error"

        update_stats(
            provider_name,
            actual_model,
            total_tokens,
            api_key_id=api_key_id,
            is_error=is_error,
            is_rate_limited=request_status in RATE_LIMITED_STATUSES,
        )
        if not is_error and total_tokens > 0:
            record_request_rate(total_tokens, latency)
        log_response_meta(provider_name, actual_model, response_meta)
        await log_request(
            provider_name,
            actual_model,
            response_text,
            tokens_record,
            latency,
            request_status,
            api_key_id=api_key_id,
            upstream_status_code=resp.status_code,
            downstream_status_code=None,
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
            logger.warning(
                "[INTERNAL %s] %s/%s failed with status %s: %s",
                purpose.upper(),
                provider_name,
                actual_model,
                resp.status_code,
                sanitize_text_for_log(provider_error or resp.text, limit=800),
            )
        elif request_status in RATE_LIMITED_STATUSES:
            logger.warning(
                "[INTERNAL %s] %s/%s rate limited with status %s: %s",
                purpose.upper(),
                provider_name,
                actual_model,
                resp.status_code,
                sanitize_text_for_log(provider_error or resp.text, limit=800),
            )

        return {
            "ok": request_status == "success",
            "provider_name": provider_name,
            "actual_model_name": actual_model,
            "status_code": resp.status_code,
            "payload": resp_json,
            "error": provider_error
            if provider_error
            else (resp.text if is_error else None),
        }
    except Exception as exc:
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
            downstream_status_code=None,
            client_ip=client_ip,
            user_agent=user_agent,
            request_context_tokens=estimate_request_context_tokens(req_body),
            error=str(exc),
        )
        logger.warning(
            "[INTERNAL %s] %s/%s exception: %s",
            purpose.upper(),
            provider_name,
            actual_model,
            sanitize_text_for_log(exc, limit=800),
        )
        return {
            "ok": False,
            "provider_name": provider_name,
            "actual_model_name": actual_model,
            "status_code": None,
            "payload": None,
            "error": str(exc),
        }
    finally:
        if acquired and provider_key_semaphore is not None:
            provider_key_semaphore.release()
        if api_key_model_acquired:
            api_key_model_semaphore.release()
