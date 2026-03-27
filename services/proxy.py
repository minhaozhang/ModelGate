import json
import re
import time
import uuid
import asyncio
import httpx
from typing import Optional
from datetime import datetime, timedelta
from fastapi import Request
from fastapi.responses import Response, JSONResponse, StreamingResponse

REPEATED_CHUNK_LIMIT = 10
PROVIDER_REQUEST_TIMEOUT_SECONDS = 300.0


def parse_minimax_tool_calls(content: str) -> tuple[str, list[dict]]:
    """
    Parse MiniMax XML tool_call format and convert to OpenAI tool_calls format.
    Returns (cleaned_content, tool_calls_list)
    """
    tool_calls = []
    pattern = r"<minimax:tool_call>\s*(.*?)\s*</minimax:tool_call>"
    matches = re.findall(pattern, content, re.DOTALL)

    for match in matches:
        invoke_pattern = r'<invoke\s+name="([^"]+)"[^>]*>(.*?)</invoke>'
        invoke_matches = re.findall(invoke_pattern, match, re.DOTALL)

        for func_name, params_xml in invoke_matches:
            arguments = {}
            param_pattern = r'<parameter\s+name="([^"]+)"[^>]*>(.*?)</parameter>'
            param_matches = re.findall(param_pattern, params_xml, re.DOTALL)

            for param_name, param_value in param_matches:
                arguments[param_name] = param_value.strip()

            tool_calls.append(
                {
                    "id": f"call_{uuid.uuid4().hex[:24]}",
                    "type": "function",
                    "function": {
                        "name": func_name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            )

    cleaned_content = re.sub(pattern, "", content, flags=re.DOTALL).strip()

    return cleaned_content, tool_calls


from sqlalchemy import update, func

from core.config import (
    providers_cache,
    providers_cache_time,
    PROVIDERS_CACHE_TTL_MINUTES,
    api_keys_cache,
    update_stats,
    logger,
    error_logger,
    provider_semaphores,
)
from core.database import async_session_maker, RequestLog, Provider


async def load_providers():
    from core.config import providers_cache, providers_cache_time
    from core.database import ProviderModel, Model

    from sqlalchemy import select

    async with async_session_maker() as session:
        result = await session.execute(
            select(Provider).where(Provider.is_active == True)
        )
        providers = result.scalars().all()

        providers_cache.clear()
        for p in providers:
            pm_result = await session.execute(
                select(ProviderModel, Model)
                .where(
                    ProviderModel.provider_id == p.id,
                    ProviderModel.is_active == True,
                )
                .join(Model, ProviderModel.model_id == Model.id)
            )
            provider_models_data = []
            for pm, model in pm_result.all():
                provider_models_data.append(
                    {
                        "id": pm.id,
                        "model_name": pm.model_name_override
                        or (model.display_name if model else None),
                        "actual_model_name": model.name if model else None,
                        "is_multimodal": model.is_multimodal if model else False,
                    }
                )

            providers_cache[p.name] = {
                "id": p.id,
                "base_url": p.base_url,
                "api_key": p.api_key or "",
                "models": provider_models_data,
                "max_concurrent": p.max_concurrent or 3,
                "merge_consecutive_messages": p.merge_consecutive_messages or False,
            }

            max_conc = p.max_concurrent or 3
            existing = provider_semaphores.get(p.name)
            if existing is None or getattr(existing, "_value", None) != max_conc:
                provider_semaphores[p.name] = asyncio.Semaphore(max_conc)

        import core.config as config

        config.providers_cache_time = datetime.now()


async def get_provider_config(provider_name: str) -> Optional[dict]:
    from core.config import providers_cache, providers_cache_time

    if providers_cache_time is None or (
        datetime.now() - providers_cache_time
    ) > timedelta(minutes=PROVIDERS_CACHE_TTL_MINUTES):
        await load_providers()
    return providers_cache.get(provider_name)


async def load_api_keys():
    from core.config import api_keys_cache
    from core.database import ApiKey, ApiKeyModel
    from sqlalchemy import select

    async with async_session_maker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.is_active == True))
        keys = result.scalars().all()

        api_keys_cache.clear()
        for k in keys:
            models_result = await session.execute(
                select(ApiKeyModel.provider_model_id).where(
                    ApiKeyModel.api_key_id == k.id
                )
            )
            model_ids = [row[0] for row in models_result.fetchall()]
            api_keys_cache[k.key] = {
                "id": k.id,
                "name": k.name,
                "allowed_provider_model_ids": model_ids,
            }


async def validate_api_key(
    auth_header: str, model: str
) -> tuple[Optional[int], Optional[str]]:
    if not auth_header:
        return None, "Missing API key"

    if auth_header.startswith("Bearer "):
        key = auth_header[7:]
    else:
        key = auth_header

    key_info = api_keys_cache.get(key)
    if not key_info:
        return None, "Invalid API key"

    allowed_models = key_info.get("allowed_provider_model_ids", [])

    if allowed_models:
        provider_name, actual_model = parse_model(model)

        if not provider_name:
            return key_info["id"], None

        provider_config = await get_provider_config(provider_name)
        if not provider_config:
            return None, f"Provider '{provider_name}' not found"

        provider_model_id = None
        for pm in provider_config.get("models", []):
            pm_model_name = pm.get("model_name")
            if (
                pm_model_name == actual_model
                or pm_model_name == actual_model.split("/")[-1]
            ):
                provider_model_id = pm["id"]
                break

        if provider_model_id is None:
            return (
                None,
                f"Model '{actual_model}' not found in provider '{provider_name}'",
            )

        if provider_model_id not in allowed_models:
            return None, f"API key not authorized for model '{model}'"

    return key_info["id"], None


async def create_request_log(
    provider_name: str,
    model: str,
    api_key_id: Optional[int] = None,
    request_body: Optional[dict] = None,
) -> int:
    """Create a pending request log entry, return log_id"""
    async with async_session_maker() as session:
        provider_id = None
        if provider_name:
            pinfo = providers_cache.get(provider_name)
            if pinfo:
                provider_id = pinfo.get("id")

        log = RequestLog(
            api_key_id=api_key_id,
            provider_id=provider_id,
            model=model,
            status="pending",
        )
        session.add(log)
        await session.commit()
        return log.id


async def update_request_log(
    log_id: int,
    response: str = "",
    tokens: Optional[dict] = None,
    latency_ms: Optional[float] = None,
    status: str = "success",
    error: Optional[str] = None,
):
    """Update an existing request log entry"""
    async with async_session_maker() as session:
        await session.execute(
            update(RequestLog)
            .where(RequestLog.id == log_id)
            .values(
                response=response,
                tokens=tokens or {},
                latency_ms=latency_ms,
                status=status,
                error=error,
                updated_at=func.now(),
            )
        )
        await session.commit()


async def log_request(
    provider_name: str,
    model: str,
    response: str,
    tokens: dict,
    latency_ms: float,
    status: str,
    api_key_id: Optional[int] = None,
    error: Optional[str] = None,
):
    """Directly insert a completed request log (for non-streaming success/error)"""
    async with async_session_maker() as session:
        provider_id = None
        if provider_name:
            pinfo = providers_cache.get(provider_name)
            if pinfo:
                provider_id = pinfo.get("id")

        log = RequestLog(
            api_key_id=api_key_id,
            provider_id=provider_id,
            model=model,
            response=response,
            tokens=tokens,
            latency_ms=latency_ms,
            status=status,
            error=error,
        )
        session.add(log)
        await session.commit()


def parse_model(model: str) -> tuple[str, str]:
    if "/" in model:
        parts = model.split("/", 1)
        return parts[0], parts[1]
    return "", model


def _coerce_int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
            return int(value)
    return None


def _first_usage_int(usage: dict, *keys: str) -> Optional[int]:
    for key in keys:
        value = _coerce_int(usage.get(key))
        if value is not None:
            return value
    return None


def _estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(len(text) // 4, 1)


def _estimate_prompt_tokens(req_body: Optional[dict]) -> int:
    if not req_body:
        return 0

    payload = {}
    for key in (
        "messages",
        "input",
        "prompt",
        "tools",
        "tool_choice",
        "temperature",
        "max_tokens",
    ):
        if key in req_body:
            payload[key] = req_body[key]

    if not payload:
        payload = req_body

    try:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        serialized = str(payload)

    return _estimate_text_tokens(serialized)


def build_tokens_record(
    usage: Optional[dict],
    req_body: Optional[dict] = None,
    response_text: str = "",
    reasoning_text: str = "",
) -> dict:
    raw_usage = usage if isinstance(usage, dict) else {}
    tokens_record = dict(raw_usage)

    prompt_tokens = _first_usage_int(
        raw_usage,
        "prompt_tokens",
        "input_tokens",
        "promptTokens",
        "inputTokens",
    )
    completion_tokens = _first_usage_int(
        raw_usage,
        "completion_tokens",
        "output_tokens",
        "completionTokens",
        "outputTokens",
    )
    total_tokens = _first_usage_int(
        raw_usage,
        "total_tokens",
        "totalTokens",
    )

    estimated = False

    if prompt_tokens is None:
        if total_tokens is not None and completion_tokens is not None:
            prompt_tokens = max(total_tokens - completion_tokens, 0)
        else:
            prompt_tokens = _estimate_prompt_tokens(req_body)
            estimated = True

    if completion_tokens is None:
        if total_tokens is not None and prompt_tokens is not None:
            completion_tokens = max(total_tokens - prompt_tokens, 0)
        else:
            completion_tokens = _estimate_text_tokens(response_text + reasoning_text)
            estimated = True

    if total_tokens is None:
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
        estimated = True

    tokens_record.update(
        {
            "prompt_tokens": prompt_tokens or 0,
            "completion_tokens": completion_tokens or 0,
            "total_tokens": total_tokens or 0,
            "estimated": estimated,
        }
    )
    return tokens_record


async def get_provider_and_model(model: str) -> tuple[Optional[dict], str, str]:
    provider_name, actual_model = parse_model(model)
    if not provider_name:
        if providers_cache:
            provider_name = list(providers_cache.keys())[0]
            logger.debug("[PROXY] No provider prefix, using default: %s", provider_name)
        else:
            return None, model, ""
    config = await get_provider_config(provider_name)
    return config, actual_model, provider_name


def get_model_config(provider_config: dict, model_name: str) -> Optional[dict]:
    if not provider_config:
        return None
    for pm in provider_config.get("models", []):
        pm_model_name = pm.get("model_name")
        if pm_model_name == model_name or pm_model_name == model_name.split("/")[-1]:
            return pm
    return None


async def proxy_request(request: Request, endpoint: str):
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]
    body = await request.body()

    try:
        body_json = json.loads(body) if body else {}
    except json.JSONDecodeError:
        body_json = {}

    model = body_json.get("model", "unknown")
    messages = body_json.get("messages", [])

    auth_header = request.headers.get("authorization", "")
    api_key_id, auth_error = await validate_api_key(auth_header, model)
    if auth_error:
        return JSONResponse({"error": auth_error}, status_code=401)

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

        messages = body_json.get("messages", [])

        merge_messages = provider_config.get("merge_consecutive_messages", False)

        if merge_messages or not is_multimodal:
            system_msgs = [m for m in messages if m.get("role") == "system"]
            other_msgs = [m for m in messages if m.get("role") != "system"]
            if len(system_msgs) > 1:
                text_parts = []
                for m in system_msgs:
                    content = m.get("content", "")
                    if isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                text_parts.append(c.get("text", ""))
                            elif isinstance(c, str):
                                text_parts.append(c)
                    else:
                        text_parts.append(content)
                merged_system = {
                    "role": "system",
                    "content": "\n\n".join(text_parts),
                }
                body_json["messages"] = [merged_system] + other_msgs
                messages = body_json["messages"]

        if merge_messages:
            merged_msgs = []
            for m in messages:
                has_tool_content = m.get("tool_calls") or m.get("tool_call_id")
                if (
                    merged_msgs
                    and merged_msgs[-1].get("role") == m.get("role")
                    and not has_tool_content
                    and not (
                        merged_msgs[-1].get("tool_calls")
                        or merged_msgs[-1].get("tool_call_id")
                    )
                ):
                    prev_content = merged_msgs[-1].get("content", "")
                    curr_content = m.get("content", "")
                    if isinstance(prev_content, str) and isinstance(curr_content, str):
                        merged_msgs[-1]["content"] = (
                            prev_content + "\n\n" + curr_content
                        )
                    else:
                        merged_msgs.append(m)
                else:
                    merged_msgs.append(m)
            if len(merged_msgs) != len(messages):
                body_json["messages"] = merged_msgs

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
        headers = {
            "content-type": "application/json",
            "user-agent": "opencode/1.2.27 ai-sdk/provider-utils/3.0.20 runtime/bun/1.3.10",
            "connection": "keep-alive",
            "accept": "*/*",
        }

        if provider_config.get("api_key"):
            headers["authorization"] = f"Bearer {provider_config['api_key']}"

        original_headers = dict(headers)

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
            f"[REQUEST] Provider: {provider_name.upper()}, Model: {actual_model}, Key: {key_name}, Messages: {msg_count}, Stream: {stream}{multimodal_tag}"
        )
        logger.info(f"[REQUEST] Target: {target_url}")
        logger.debug("[REQUEST] Headers: %s", original_headers)
        logger.debug(
            f"[REQUEST] Body: {body.decode() if isinstance(body, bytes) else body}"
        )

        # 流式请求：先创建 pending 日志
        stream_log_id = None
        if stream:
            stream_log_id = await create_request_log(
                provider_name, actual_model, api_key_id=api_key_id
            )

        async with httpx.AsyncClient(timeout=PROVIDER_REQUEST_TIMEOUT_SECONDS) as client:
            if stream:
                return await handle_streaming(
                    target_url,
                    headers,
                    body,
                    provider_name,
                    actual_model,
                    messages,
                    start_time,
                    original_headers,
                    body_json,
                    api_key_id,
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
                    original_headers,
                    body_json,
                    api_key_id,
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
            error=str(e),
        )
        error_logger.error(
            f"[REQUEST ERROR] Provider: {provider_name}, Model: {actual_model}\n"
            f"  Error: {type(e).__name__}: {e}\n"
            f"  Request Body: {json.dumps(body_json, ensure_ascii=False)[:1000]}"
        )
        return JSONResponse({"error": str(e)}, status_code=500)


async def handle_normal(
    client,
    url,
    headers,
    body,
    provider,
    model,
    messages,
    start_time,
    req_headers,
    req_body,
    api_key_id,
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

    if provider == "minimax" and "choices" in resp_json and resp_json["choices"]:
        message = resp_json["choices"][0].get("message", {})
        content = message.get("content", "")
        if "<Parsed>" in content and "</Parsed>" in content:
            start_idx = content.find("<Parsed>")
            end_idx = content.find("</Parsed>") + 9
            reasoning = content[start_idx + 8 : end_idx - 9]
            remaining = content[:start_idx] + content[end_idx:]
            message["reasoning_content"] = reasoning
            message["content"] = remaining.strip()
            content = remaining.strip()
        if "<minimax:tool_call>" in content:
            cleaned_content, tool_calls = parse_minimax_tool_calls(content)
            if tool_calls:
                message["content"] = cleaned_content if cleaned_content else None
                message["tool_calls"] = tool_calls
                resp_json["choices"][0]["finish_reason"] = "tool_calls"
                logger.info(f"[MINIMAX TOOL_CALLS] Parsed {len(tool_calls)} tool calls")

    response_text = ""
    reasoning_text = ""
    if "choices" in resp_json and resp_json["choices"]:
        message = resp_json["choices"][0].get("message", {})
        response_text = message.get("content", "")
        reasoning_text = message.get("reasoning_content", "")

    tokens_record = build_tokens_record(
        resp_json.get("usage"),
        req_body=req_body,
        response_text=response_text,
        reasoning_text=reasoning_text,
    )
    total_tokens = tokens_record["total_tokens"]

    is_error = resp.status_code >= 400
    retry_after = resp.headers.get("retry-after")
    if retry_after:
        error_logger.warning(
            f"[API] {provider} rate limited, retry-after: {retry_after}s"
        )

    if not is_error and resp_json.get("error"):
        is_error = True
        error_logger.error(
            f"[API ERROR] Provider: {provider}, Model: {model}, API returned error: {resp_json.get('error')}"
        )

    update_stats(
        provider, model, total_tokens, api_key_id=api_key_id, is_error=is_error
    )
    await log_request(
        provider,
        model,
        response_text,
        tokens_record,
        latency,
        "error" if is_error else "success",
        api_key_id=api_key_id,
        error=resp.text if is_error else None,
    )

    if is_error:
        error_logger.error(
            f"[API ERROR] Provider: {provider}, Model: {model}, Status: {resp.status_code}\n"
            f"  Request Body: {json.dumps(req_body, ensure_ascii=False)[:1000]}\n"
            f"  Response: {resp.text[:1000]}"
        )

    logger.info(
        f"[RESPONSE] Status: {resp.status_code}, Tokens: {total_tokens}, Latency: {latency:.0f}ms"
    )
    logger.debug("[RESPONSE] Body: %s", resp.text)

    semaphore.release()
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers={"content-type": "application/json"},
    )


async def _normalize_sse_stream(aiter_lines):
    """Normalize raw SSE stream: split merged data lines, handle non-data JSON."""
    async for raw_line in aiter_lines:
        line = raw_line.rstrip()
        if not line:
            continue

        if line.startswith("data: "):
            content = line[6:]
            if "data: " in content:
                parts = content.split("data: ")
                for part in parts:
                    part = part.strip()
                    if part:
                        yield f"data: {part}"
            else:
                yield line
        elif line.startswith("{"):
            yield f"data: {line}"
        elif line.startswith(":"):
            continue


async def handle_streaming(
    url,
    headers,
    body,
    provider,
    model,
    messages,
    start_time,
    req_headers,
    req_body,
    api_key_id,
    semaphore,
    request_id,
    log_id,
    request,
):
    logger.debug(
        "[STREAM REQUEST] Provider: %s, Model: %s, URL: %s", provider, model, url
    )
    if provider == "minimax":
        body_json = json.loads(body) if body else {}
        msgs = body_json.get("messages", [])
        logger.info(f"[MINIMAX MSG COUNT] {len(msgs)}")
        for i, m in enumerate(msgs):
            role = m.get("role", "unknown")
            content = m.get("content")
            content_type = type(content).__name__
            logger.info(f"[MINIMAX MSG {i}] role={role}, content_type={content_type}")
            if isinstance(content, list):
                logger.info(f"[MINIMAX MSG {i} CONTENT] {json.dumps(content)[:200]}")

    async def stream_generator():
        total_content = ""
        total_reasoning = ""
        total_raw_content = ""
        in_thinking = False
        in_tool_call = False
        thinking_buffer = ""
        tool_call_buffer = ""
        last_content = ""
        repeated_count = 0
        last_usage = None
        try:
            async with httpx.AsyncClient(timeout=PROVIDER_REQUEST_TIMEOUT_SECONDS) as client:
                async with client.stream(
                    "POST", url, headers=headers, content=body
                ) as resp:
                    if resp.status_code >= 400:
                        error_body = await resp.aread()
                        retry_after = resp.headers.get("retry-after")
                        error_msg = error_body.decode()[:500]
                        if retry_after:
                            error_logger.warning(
                                f"[STREAM ERROR] {provider} rate limited, retry-after: {retry_after}s"
                            )
                        raise Exception(f"HTTP {resp.status_code}: {error_msg}")

                    if provider == "minimax":
                        logger.info(f"[MINIMAX RESP] status={resp.status_code}")
                    chunk_count = 0
                    async for line in _normalize_sse_stream(resp.aiter_lines()):
                        if provider == "minimax":
                            if chunk_count < 5:
                                logger.info(
                                    f"[MINIMAX LINE {chunk_count}] {repr(line[:300])}"
                                )
                            if not line.startswith("data: ") and line.strip():
                                logger.warning(
                                    f"[MINIMAX NON-DATA LINE] {repr(line[:300])}"
                                )
                        if line.startswith("data: "):
                            line_content = line[6:]
                            if line_content == "[DONE]":
                                yield f"data: [DONE]\n\n"
                                break
                            try:
                                chunk = json.loads(line_content)
                                chunk_count += 1

                                if chunk.get("usage"):
                                    last_usage = chunk["usage"]

                                if chunk.get("error"):
                                    error_msg = chunk.get("error")
                                    if isinstance(error_msg, dict):
                                        error_msg = error_msg.get(
                                            "message", str(error_msg)
                                        )
                                    raise Exception(f"API error: {error_msg}")

                                if "choices" in chunk and chunk["choices"]:
                                    choice = chunk["choices"][0]
                                    finish_reason = choice.get("finish_reason")
                                    if finish_reason == "error":
                                        raise Exception(
                                            "Stream finished with error status"
                                        )

                                    delta = choice.get("delta", {})
                                    content = delta.get("content", "")

                                    if provider == "minimax" and content:
                                        total_raw_content += content
                                        if "<minimax:tool_call>" in total_raw_content:
                                            in_tool_call = True

                                        if in_tool_call:
                                            if (
                                                "</minimax:tool_call>"
                                                in total_raw_content
                                            ):
                                                cleaned, tool_calls = (
                                                    parse_minimax_tool_calls(
                                                        total_raw_content
                                                    )
                                                )
                                                if tool_calls:
                                                    for i, tc in enumerate(tool_calls):
                                                        tc_chunk = {
                                                            "id": chunk.get("id", ""),
                                                            "object": chunk.get(
                                                                "object",
                                                                "chat.completion.chunk",
                                                            ),
                                                            "created": chunk.get(
                                                                "created", 0
                                                            ),
                                                            "model": chunk.get(
                                                                "model", ""
                                                            ),
                                                            "choices": [
                                                                {
                                                                    "index": 0,
                                                                    "delta": {
                                                                        "tool_calls": [
                                                                            {
                                                                                "index": i,
                                                                                "id": tc[
                                                                                    "id"
                                                                                ],
                                                                                "type": "function",
                                                                                "function": {
                                                                                    "name": tc[
                                                                                        "function"
                                                                                    ][
                                                                                        "name"
                                                                                    ],
                                                                                    "arguments": tc[
                                                                                        "function"
                                                                                    ][
                                                                                        "arguments"
                                                                                    ],
                                                                                },
                                                                            }
                                                                        ]
                                                                    },
                                                                    "finish_reason": None,
                                                                }
                                                            ],
                                                        }
                                                        yield f"data: {json.dumps(tc_chunk)}\n\n"
                                                        logger.info(
                                                            f"[MINIMAX TOOL_CALL] {tc['function']['name']}"
                                                        )
                                                    finish_chunk = {
                                                        "id": chunk.get("id", ""),
                                                        "object": chunk.get(
                                                            "object",
                                                            "chat.completion.chunk",
                                                        ),
                                                        "created": chunk.get(
                                                            "created", 0
                                                        ),
                                                        "model": chunk.get("model", ""),
                                                        "choices": [
                                                            {
                                                                "index": 0,
                                                                "delta": {},
                                                                "finish_reason": "tool_calls",
                                                            }
                                                        ],
                                                    }
                                                    yield f"data: {json.dumps(finish_chunk)}\n\n"
                                                    total_raw_content = ""
                                                    in_tool_call = False
                                                continue
                                            else:
                                                delta.pop("content", None)
                                                data = json.dumps(chunk)
                                                line = f"data: {data}"
                                        else:
                                            thinking_buffer += content
                                            new_content = ""
                                            new_reasoning = ""

                                            i = 0
                                            while i < len(thinking_buffer):
                                                if not in_thinking:
                                                    start_idx = thinking_buffer.find(
                                                        "<Parsed>", i
                                                    )
                                                    if start_idx != -1:
                                                        new_content += thinking_buffer[
                                                            i:start_idx
                                                        ]
                                                        i = start_idx + 8
                                                        in_thinking = True
                                                    else:
                                                        new_content += thinking_buffer[
                                                            i:
                                                        ]
                                                        break
                                                else:
                                                    end_idx = thinking_buffer.find(
                                                        "</Parsed>", i
                                                    )
                                                    if end_idx != -1:
                                                        new_reasoning += (
                                                            thinking_buffer[i:end_idx]
                                                        )
                                                        i = end_idx + 9
                                                        in_thinking = False
                                                    else:
                                                        new_reasoning += (
                                                            thinking_buffer[i:]
                                                        )
                                                        break

                                            if in_thinking:
                                                thinking_buffer = ""
                                                if new_content:
                                                    delta["content"] = new_content
                                                else:
                                                    delta.pop("content", None)
                                                if new_reasoning:
                                                    delta["reasoning_content"] = (
                                                        new_reasoning
                                                    )
                                                    total_reasoning += new_reasoning
                                            else:
                                                thinking_buffer = ""
                                                if new_content:
                                                    delta["content"] = new_content
                                                    total_content += new_content
                                                else:
                                                    delta.pop("content", None)
                                                if new_reasoning:
                                                    delta["reasoning_content"] = (
                                                        new_reasoning
                                                    )
                                                    total_reasoning += new_reasoning

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
                                logger.warning(
                                    f"[SSE] Invalid JSON, skipping line: {line[:100]}... Error: {e}"
                                )
                                continue
                            yield f"{line.rstrip()}\n\n"

                            # 定期检查客户端是否断开
                            if chunk_count % 10 == 0:
                                if await request.is_disconnected():
                                    logger.info(
                                        f"[STREAM] Client disconnected at chunk {chunk_count}"
                                    )
                                    latency = (time.time() - start_time) * 1000
                                    tokens_record = build_tokens_record(
                                        last_usage,
                                        req_body=req_body,
                                        response_text=total_content,
                                        reasoning_text=total_reasoning,
                                    )
                                    await update_request_log(
                                        log_id,
                                        response=total_content,
                                        tokens=tokens_record,
                                        latency_ms=latency,
                                        status="cancelled",
                                    )
                                    return

            latency = (time.time() - start_time) * 1000
            tokens_record = build_tokens_record(
                last_usage,
                req_body=req_body,
                response_text=total_content,
                reasoning_text=total_reasoning,
            )
            total_tokens = tokens_record["total_tokens"]
            update_stats(provider, model, total_tokens, api_key_id=api_key_id)
            await update_request_log(
                log_id,
                response=total_content,
                tokens=tokens_record,
                latency_ms=latency,
                status="success",
            )
            logger.info(f"[STREAM COMPLETE] ~{total_tokens} tokens | {latency:.0f}ms")
            logger.debug("[STREAM RESPONSE] Content: %s", total_content)
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            update_stats(provider, model, 0, api_key_id=api_key_id, is_error=True)
            await update_request_log(
                log_id,
                response="",
                tokens={},
                latency_ms=latency,
                status="error",
                error=str(e),
            )
            error_logger.error(
                f"[STREAM ERROR] Provider: {provider}, Model: {model}\n"
                f"  Error: {type(e).__name__}: {e}\n"
                f"  Request Body: {json.dumps(req_body, ensure_ascii=False)[:1000]}"
            )
            error_msg = json.dumps(
                {"error": {"message": str(e), "type": type(e).__name__}}
            )
            yield f"data: {error_msg}\n\n"
        finally:
            semaphore.release()

    return StreamingResponse(stream_generator(), media_type="text/event-stream")
