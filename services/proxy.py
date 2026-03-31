import json
import time
import uuid
import asyncio
import httpx
from fastapi import Request
from fastapi.responses import Response, JSONResponse, StreamingResponse

from core.config import (
    providers_cache,
    api_keys_cache,
    update_stats,
    logger,
    error_logger,
    provider_semaphores,
)
from core.log_sanitizer import (
    sanitize_headers_for_log,
    sanitize_payload_for_log,
    sanitize_text_for_log,
)
from core.client_ip import get_client_ip
from services.provider import (
    get_provider_and_model,
    get_model_config,
)
from services.auth import validate_api_key
from services.logging import (
    create_request_log,
    update_request_log,
    log_request,
    update_api_key_last_used,
)
from services.tokens import (
    build_tokens_record,
    build_response_meta,
    log_response_meta,
    _collect_tool_calls,
)
from services.message import preprocess_messages
from services.minimax import process_minimax_response, MinimaxStreamProcessor
from services.sse import normalize_sse_stream

REPEATED_CHUNK_LIMIT = 10
PROVIDER_REQUEST_TIMEOUT_SECONDS = 300.0


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
        return JSONResponse({"error": auth_error}, status_code=401)
    client_ip = get_client_ip(request)
    _schedule_api_key_last_used_update(api_key_id)

    provider_config, actual_model, provider_name = await get_provider_and_model(model)

    if not provider_config:
        logger.error(f"[PROXY ERROR] Unknown provider for model: {model}")
        logger.debug(
            f"[PROXY ERROR] Available providers: {list(providers_cache.keys())}"
        )
        return JSONResponse(
            {"error": f"Unknown provider for model: {model}"}, status_code=400
        )

    semaphore = provider_semaphores.get(provider_name)
    if semaphore is None:
        max_concurrent = provider_config.get("max_concurrent", 3)
        semaphore = asyncio.Semaphore(max_concurrent)
        provider_semaphores[provider_name] = semaphore

    acquired = False
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=0.001)
        acquired = True
    except asyncio.TimeoutError:
        logger.warning(f"[RATE LIMIT] Provider {provider_name} at max concurrency")
        return JSONResponse(
            {"error": f"提供商 '{provider_name}' 达到最大并发数，请稍后重试"},
            status_code=429,
        )

    try:
        body_json["model"] = actual_model

        model_config = get_model_config(provider_config, actual_model)
        is_multimodal = (
            model_config.get("is_multimodal", False) if model_config else False
        )

        merge_messages = provider_config.get("merge_consecutive_messages", False)
        body_json = preprocess_messages(body_json, merge_messages, is_multimodal)
        messages = body_json["messages"]

        stream = body_json.get("stream", False)

        if stream and provider_name != "minimax":
            stream_options = body_json.get("stream_options")
            if isinstance(stream_options, dict):
                stream_options = dict(stream_options)
            else:
                stream_options = {}
            stream_options["include_usage"] = True
            body_json["stream_options"] = stream_options

        if provider_name == "minimax" and merge_messages:
            body_json.pop("thinking", None)
            body_json.pop("stream_options", None)
            body_json["reasoning_split"] = True

        body = json.dumps(body_json).encode()

        target_url = f"{provider_config['base_url']}{endpoint}"
        headers = _build_headers(provider_config)

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
            )

        async with httpx.AsyncClient(
            timeout=PROVIDER_REQUEST_TIMEOUT_SECONDS
        ) as client:
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
                    semaphore,
                    request_id,
                    stream_log_id,
                    request,
                )
            else:
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
                    semaphore,
                    request_id,
                )
    except Exception as e:
        if acquired:
            semaphore.release()
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
            client_ip=client_ip,
            error=str(e),
        )
        error_logger.error(
            f"[REQUEST ERROR] Provider: {provider_name}, Model: {actual_model}\n"
            f"  Error: {type(e).__name__}: {sanitize_text_for_log(e)}\n"
            f"  Request Body: {sanitize_payload_for_log(body_json)}"
        )
        return JSONResponse({"error": str(e)}, status_code=500)


def _build_headers(provider_config: dict) -> dict:
    headers = {
        "content-type": "application/json",
        "user-agent": "opencode/1.2.27 ai-sdk/provider-utils/3.0.20 runtime/bun/1.3.10",
        "connection": "keep-alive",
        "accept": "*/*",
    }
    if provider_config.get("api_key"):
        headers["authorization"] = f"Bearer {provider_config['api_key']}"
    return headers

def _schedule_api_key_last_used_update(api_key_id: int | None) -> None:
    if not api_key_id:
        return

    task = asyncio.create_task(update_api_key_last_used(api_key_id))

    def _handle_task_result(done_task: asyncio.Task) -> None:
        try:
            done_task.result()
        except Exception as exc:
            logger.warning(
                "[API KEY] Failed to update last_used_at: %s",
                sanitize_text_for_log(exc),
            )

    task.add_done_callback(_handle_task_result)


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
    key_name = (
        api_keys_cache.get(auth_header.replace("Bearer ", ""), {}).get(
            "name", "unknown"
        )
        if auth_header.startswith("Bearer ")
        else "unknown"
    )
    msg_count = len(messages)
    has_images = any(
        isinstance(m.get("content"), list)
        and any(
            c.get("type") == "image_url"
            for c in m.get("content", [])
            if isinstance(c, dict)
        )
        for m in messages
    )
    multimodal_tag = " [MULTIMODAL]" if is_multimodal or has_images else ""
    logger.info(
        f"[REQUEST] Provider: {provider.upper()}, Model: {model}, Key: {key_name}, "
        f"Messages: {msg_count}, Stream: {stream}{multimodal_tag}"
    )
    logger.info(f"[REQUEST] Target: {target_url}")
    logger.debug("[REQUEST] Headers: %s", sanitize_headers_for_log(headers))
    logger.debug("[REQUEST] Body: %s", sanitize_payload_for_log(body))


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
        updated = await update_request_log(
            log_id,
            response=total_content,
            tokens=tokens_record,
            latency_ms=latency,
            status="success",
            upstream_status_code=upstream_status_code,
        )
        if not updated:
            await log_request(
                provider,
                model,
                total_content,
                tokens_record,
                latency,
                "success",
                api_key_id=api_key_id,
                upstream_status_code=upstream_status_code,
                client_ip=client_ip,
            )
        logger.info(f"[STREAM COMPLETE] ~{total_tokens} tokens | {latency:.0f}ms")
        logger.debug("[STREAM RESPONSE] Content: %s", total_content)
    elif status == "cancelled":
        updated = await update_request_log(
            log_id,
            response=total_content,
            tokens=tokens_record,
            latency_ms=latency,
            status="cancelled",
            upstream_status_code=upstream_status_code,
        )
        if not updated:
            await log_request(
                provider,
                model,
                total_content,
                tokens_record,
                latency,
                "cancelled",
                api_key_id=api_key_id,
                upstream_status_code=upstream_status_code,
                client_ip=client_ip,
            )
    elif status == "error":
        update_stats(provider, model, 0, api_key_id=api_key_id, is_error=True)
        updated = await update_request_log(
            log_id,
            response=total_content,
            tokens=tokens_record,
            latency_ms=latency,
            status="error",
            upstream_status_code=upstream_status_code,
            error=str(error) if error is not None else None,
        )
        if not updated:
            await log_request(
                provider,
                model,
                total_content,
                tokens_record,
                latency,
                "error",
                api_key_id=api_key_id,
                upstream_status_code=upstream_status_code,
                client_ip=client_ip,
                error=str(error) if error is not None else None,
            )
        error_logger.error(
            f"[STREAM ERROR] Provider: {provider}, Model: {model}\n"
            f"  Error: {type(error).__name__ if error else 'Unknown'}: {sanitize_text_for_log(error)}\n"
            f"  Request Body: {sanitize_payload_for_log(req_body)}"
        )
    return latency


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
    semaphore,
    request_id,
):
    logger.debug(
        "[NORMAL REQUEST] Provider: %s, Model: %s, URL: %s", provider, model, url
    )

    resp = await client.post(url, headers=headers, content=body)
    latency = (time.time() - start_time) * 1000

    try:
        resp_json = resp.json()
    except json.JSONDecodeError:
        resp_json = {}

    if provider == "minimax":
        process_minimax_response(resp_json)

    response_text, reasoning_text, tool_calls, finish_reason = _extract_response_fields(
        resp_json
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

    is_error = resp.status_code >= 400
    retry_after = resp.headers.get("retry-after")
    if retry_after:
        error_logger.warning(
            f"[API] {provider} rate limited, retry-after: {retry_after}s"
        )

    provider_error = _extract_provider_error(resp_json)
    if not is_error and provider_error:
        is_error = True
        error_logger.error(
            f"[API ERROR] Provider: {provider}, Model: {model}, API returned error: {provider_error}"
        )

    update_stats(
        provider, model, total_tokens, api_key_id=api_key_id, is_error=is_error
    )
    log_response_meta(provider, model, response_meta)
    await log_request(
        provider,
        model,
        response_text,
        tokens_record,
        latency,
        "error" if is_error else "success",
        api_key_id=api_key_id,
        upstream_status_code=resp.status_code,
        client_ip=client_ip,
        error=(
            sanitize_text_for_log(provider_error, limit=2000)
            if provider_error
            else sanitize_text_for_log(resp.text, limit=2000)
        )
        if is_error
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

    semaphore.release()
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers={"content-type": "application/json"},
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
    semaphore,
    request_id,
    log_id,
    request,
):
    logger.debug(
        "[STREAM REQUEST] Provider: %s, Model: %s, URL: %s", provider, model, url
    )

    async def stream_generator():
        total_content = ""
        total_reasoning = ""
        last_content = ""
        repeated_count = 0
        last_usage = None
        final_finish_reason = ""
        stream_tool_calls = []
        seen_tool_call_keys: set[str] = set()
        minimax_proc = MinimaxStreamProcessor() if provider == "minimax" else None
        upstream_status_code = None

        try:
            async with httpx.AsyncClient(
                timeout=PROVIDER_REQUEST_TIMEOUT_SECONDS
            ) as client:
                async with client.stream(
                    "POST", url, headers=headers, content=body
                ) as resp:
                    upstream_status_code = resp.status_code
                    if resp.status_code >= 400:
                        error_body = await resp.aread()
                        retry_after = resp.headers.get("retry-after")
                        if retry_after:
                            error_logger.warning(
                                f"[STREAM ERROR] {provider} rate limited, retry-after: {retry_after}s"
                            )
                        error_text = sanitize_text_for_log(error_body.decode("utf-8", errors="replace"))
                        raise Exception(
                            f"HTTP {resp.status_code}: {error_text}"
                        )

                    chunk_count = 0
                    async for line in normalize_sse_stream(resp.aiter_lines()):
                        if not line.startswith("data: "):
                            if not line.strip() or line.startswith(":"):
                                continue
                            try:
                                raw_payload = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            provider_error = _extract_provider_error(raw_payload)
                            if provider_error:
                                raise Exception(f"API error: {provider_error}")
                            continue
                        line_content = line[6:]
                        if line_content == "[DONE]":
                            yield "data: [DONE]\n\n"
                            break
                        try:
                            chunk = json.loads(line_content)
                            chunk_count += 1

                            if chunk.get("usage"):
                                last_usage = chunk["usage"]
                            provider_error = _extract_provider_error(chunk)
                            if provider_error:
                                raise Exception(f"API error: {provider_error}")

                            if "choices" not in chunk or not chunk["choices"]:
                                yield f"{line.rstrip()}\n\n"
                                continue

                            choice = chunk["choices"][0]
                            finish_reason = choice.get("finish_reason")
                            if finish_reason:
                                final_finish_reason = finish_reason
                            if finish_reason == "error":
                                raise Exception("Stream finished with error status")

                            delta = choice.get("delta", {})
                            _collect_tool_calls(
                                delta.get("tool_calls"),
                                seen_tool_call_keys,
                                stream_tool_calls,
                            )
                            content = delta.get("content", "")

                            if minimax_proc and content:
                                result = minimax_proc.process_content(
                                    content,
                                    chunk,
                                    delta,
                                    seen_tool_call_keys,
                                    stream_tool_calls,
                                    _collect_tool_calls,
                                )
                                if result is None:
                                    continue
                                if result[0] == "yield":
                                    final_finish_reason = "tool_calls"
                                    yield result[1]
                                    continue
                                elif result[0] == "skip":
                                    data = json.dumps(chunk)
                                    line = f"data: {data}"
                                elif result[0] == "content":
                                    total_content += result[1]
                                    total_reasoning += result[2]
                                    data = json.dumps(chunk)
                                    line = f"data: {data}"
                            elif content:
                                if content == last_content and content.strip():
                                    repeated_count += 1
                                    if repeated_count >= REPEATED_CHUNK_LIMIT:
                                        logger.warning(
                                            f"[STREAM] Detected repeated content ({repeated_count}x), aborting"
                                        )
                                        raise Exception(
                                            f"Model repeating same content: {content[:50]}..."
                                        )
                                else:
                                    repeated_count = 0
                                last_content = content
                                total_content += content

                            reasoning = delta.get("reasoning_content", "")
                            if reasoning and provider != "minimax":
                                total_reasoning += reasoning

                        except json.JSONDecodeError as e:
                            line_preview = sanitize_text_for_log(
                                line_content[:200].replace("\n", "\\n"),
                                limit=300,
                            )
                            logger.warning(
                                f"[SSE] Invalid JSON, skipping line: {sanitize_text_for_log(line, limit=150)}... Error: {sanitize_text_for_log(e)}"
                            )
                            raise Exception(
                                f"SSE JSON parse error: {e}; chunk={line_preview}"
                            ) from e

                        yield f"{line.rstrip()}\n\n"

                        if chunk_count % 10 == 0:
                            if await request.is_disconnected():
                                logger.info(
                                    f"[STREAM] Client disconnected at chunk {chunk_count}"
                                )
                                await _record_stream_result(
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
                                    start_time,
                                    log_id,
                                    "cancelled",
                                    upstream_status_code=upstream_status_code,
                                )
                                return

            await _record_stream_result(
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
                start_time,
                log_id,
                "success",
                upstream_status_code=upstream_status_code,
            )
        except Exception as e:
            await _record_stream_result(
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
                start_time,
                log_id,
                "error",
                upstream_status_code=upstream_status_code,
                error=e,
            )
            yield f"data: {json.dumps({'error': {'message': str(e), 'type': type(e).__name__}})}\n\n"
        finally:
            semaphore.release()

    return StreamingResponse(stream_generator(), media_type="text/event-stream")
