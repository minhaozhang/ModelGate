import json
import time

from fastapi.responses import Response, StreamingResponse

from core.config import (
    error_logger,
    finish_active_request,
    logger,
    providers_cache,
    register_active_request,
    update_stats,
)
from core.log_sanitizer import sanitize_text_for_log
from services.logging import log_request, update_request_log
from services.minimax import MinimaxStreamProcessor
from services.provider_limiter import check_usage_limit_error, disable_provider_key
from services.proxy_runtime.client import REPEATED_CHUNK_LIMIT, get_http_client
from services.proxy_runtime.concurrency import (
    RATE_LIMITED_STATUSES,
    SEMAPHORE_RETRY_AFTER_SECONDS,
)
from services.proxy_runtime.response_handler import (
    _extract_provider_error,
    _is_rate_limited_status,
    _normalize_upstream_error,
    _record_stream_result,
    _resolve_request_status,
)
from services.sse import normalize_sse_stream
from services.tokens import _collect_tool_calls


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
):
    logger.debug(
        "[STREAM REQUEST] Provider: %s, Model: %s, URL: %s", provider, model, url
    )

    client = get_http_client()
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
        req = client.build_request("POST", url, headers=headers, content=body)
        resp = await client.send(req, stream=True)

        if resp.status_code >= 400:
            error_body = await resp.aread()
            await resp.aclose()
            latency = (time.time() - start_time) * 1000
            error_text = error_body.decode("utf-8", errors="replace")
            retry_after = resp.headers.get("retry-after")
            if retry_after:
                error_logger.warning(
                    f"[STREAM ERROR] {provider} rate limited, retry-after: {retry_after}s"
                )
            try:
                resp_json = json.loads(error_body)
            except json.JSONDecodeError:
                resp_json = {}
            usage_limit_err = check_usage_limit_error(resp_json, provider)
            if usage_limit_err:
                provider_config = providers_cache.get(provider, {})
                await disable_provider_key(
                    provider, provider_config, chosen_key_id, usage_limit_err
                )
            provider_error = _extract_provider_error(resp_json)
            request_status = _resolve_request_status(resp.status_code, provider_error)
            update_stats(
                provider,
                model,
                0,
                api_key_id=api_key_id,
                is_error=request_status == "error",
                is_rate_limited=request_status in RATE_LIMITED_STATUSES,
            )
            await log_request(
                provider,
                model,
                "",
                {},
                latency,
                request_status,
                api_key_id=api_key_id,
                upstream_status_code=resp.status_code,
                client_ip=client_ip,
                user_agent=user_agent,
                request_context_tokens=request_context_tokens,
                error=sanitize_text_for_log(provider_error or error_text, limit=2000),
            )
            if log_id:
                await update_request_log(
                    log_id,
                    status=request_status,
                    upstream_status_code=resp.status_code,
                    error=sanitize_text_for_log(
                        provider_error or error_text, limit=2000
                    ),
                )
            if is_active_request_registered:
                await finish_active_request(request_id)
            log_fn = (
                error_logger.warning
                if request_status in RATE_LIMITED_STATUSES
                else error_logger.error
            )
            log_fn(
                f"[STREAM ERROR] Provider: {provider}, Model: {model}, Status: {resp.status_code}\n"
                f"  Response: {sanitize_text_for_log(error_text)}"
            )
            resp_headers = {"content-type": "application/json"}
            if _is_rate_limited_status(resp.status_code):
                if retry_after:
                    resp_headers["retry-after"] = retry_after
                else:
                    resp_headers["retry-after"] = str(SEMAPHORE_RETRY_AFTER_SECONDS)
            normalized_body = _normalize_upstream_error(
                resp_json,
                resp.status_code,
                provider,
                raw_error_text=sanitize_text_for_log(error_text, limit=2000),
            )
            response = Response(
                content=normalized_body,
                status_code=resp.status_code,
                headers=resp_headers,
            )
            api_key_model_semaphore.release()
            if semaphore is not None:
                semaphore.release()
            semaphores_released = True
            return response
    except Exception as e:
        if is_active_request_registered:
            await finish_active_request(request_id)
        if not semaphores_released:
            if semaphore is not None:
                semaphore.release()
            api_key_model_semaphore.release()
        raise e

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
        upstream_status_code = resp.status_code

        try:
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
                        if result[0] == "skip":
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
                            user_agent,
                            request_context_tokens,
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
                user_agent,
                request_context_tokens,
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
                user_agent,
                request_context_tokens,
                start_time,
                log_id,
                "error",
                upstream_status_code=upstream_status_code,
                error=e,
            )
            yield f"data: {json.dumps({'error': {'message': str(e), 'type': type(e).__name__}})}\n\n"
        finally:
            await finish_active_request(request_id)
            api_key_model_semaphore.release()
            if semaphore is not None:
                semaphore.release()

    return StreamingResponse(stream_generator(), media_type="text/event-stream")
