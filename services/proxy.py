import json
import time
import asyncio
import httpx
from typing import Optional
from datetime import datetime, timedelta
from fastapi import Request
from fastapi.responses import Response, JSONResponse, StreamingResponse

from config import (
    providers_cache,
    providers_cache_time,
    PROVIDERS_CACHE_TTL_MINUTES,
    api_keys_cache,
    update_stats,
    logger,
    error_logger,
    provider_semaphores,
)
from database import async_session_maker, RequestLog, Provider


async def load_providers():
    from config import providers_cache, providers_cache_time
    from database import ProviderModel, Model

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
                    }
                )

            providers_cache[p.name] = {
                "base_url": p.base_url,
                "api_key": p.api_key or "",
                "models": provider_models_data,
                "max_concurrent": p.max_concurrent or 3,
            }

            if p.name not in provider_semaphores or provider_semaphores[
                p.name
            ]._value != (p.max_concurrent or 3):
                provider_semaphores[p.name] = asyncio.Semaphore(p.max_concurrent or 3)

        import config

        config.providers_cache_time = datetime.now()


async def get_provider_config(provider_name: str) -> Optional[dict]:
    from config import providers_cache, providers_cache_time

    if providers_cache_time is None or (
        datetime.now() - providers_cache_time
    ) > timedelta(minutes=PROVIDERS_CACHE_TTL_MINUTES):
        await load_providers()
    return providers_cache.get(provider_name)


async def load_api_keys():
    from config import api_keys_cache
    from database import ApiKey, ApiKeyModel
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


async def log_request(
    provider_name: str,
    model: str,
    messages: list,
    response: str,
    tokens: dict,
    latency_ms: float,
    status: str,
    api_key_id: Optional[int] = None,
    error: Optional[str] = None,
    headers: Optional[dict] = None,
    request_body: Optional[dict] = None,
):
    async with async_session_maker() as session:
        provider_id = None
        if provider_name:
            for pid, pinfo in providers_cache.items():
                if pinfo.get("name") == provider_name:
                    provider_id = pid
                    break

        log = RequestLog(
            api_key_id=api_key_id,
            provider_id=provider_id,
            model=model,
            messages=messages,
            response=response,
            tokens=tokens,
            latency_ms=latency_ms,
            status=status,
            error=error,
            headers=headers,
            request_body=request_body,
        )
        session.add(log)
        await session.commit()


def parse_model(model: str) -> tuple[str, str]:
    if "/" in model:
        parts = model.split("/", 1)
        return parts[0], parts[1]
    return "", model


async def get_provider_and_model(model: str) -> tuple[Optional[dict], str, str]:
    provider_name, actual_model = parse_model(model)
    if not provider_name:
        if providers_cache:
            provider_name = list(providers_cache.keys())[0]
            logger.debug(f"[PROXY] No provider prefix, using default: {provider_name}")
        else:
            return None, model, ""
    config = await get_provider_config(provider_name)
    return config, actual_model, provider_name


async def proxy_request(request: Request, endpoint: str):
    start_time = time.time()
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
            {"error": f"Provider '{provider_name}' is at maximum concurrency"},
            status_code=429,
        )

    body_json["model"] = actual_model

    if provider_name == "minimax":
        body_json.pop("thinking", None)
        body_json.pop("stream_options", None)
        body_json["reasoning_split"] = True
        messages = body_json.get("messages", [])
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]
        if len(system_msgs) > 1:
            merged_system = {
                "role": "system",
                "content": "\n\n".join(m.get("content", "") for m in system_msgs),
            }
            body_json["messages"] = [merged_system] + other_msgs

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

    stream = body_json.get("stream", False)

    key_name = (
        api_keys_cache.get(auth_header.replace("Bearer ", ""), {}).get(
            "name", "unknown"
        )
        if auth_header.startswith("Bearer ")
        else "unknown"
    )
    logger.info(
        f"[REQUEST] Provider: {provider_name.upper()}, Model: {actual_model}, Key: {key_name}, Messages: {len(messages)}, Stream: {stream}"
    )
    logger.info(f"[REQUEST] Target: {target_url}")
    logger.debug(f"[REQUEST] Headers: {original_headers}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
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
                messages,
                "",
                {},
                latency,
                "error",
                api_key_id=api_key_id,
                error=str(e),
                headers=original_headers,
                request_body=body_json,
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
):
    logger.debug(f"[NORMAL REQUEST] Provider: {provider}, Model: {model}, URL: {url}")

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

    usage = resp_json.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

    response_text = ""
    if "choices" in resp_json and resp_json["choices"]:
        response_text = resp_json["choices"][0].get("message", {}).get("content", "")

    is_error = resp.status_code >= 400
    update_stats(
        provider, model, total_tokens, api_key_id=api_key_id, is_error=is_error
    )
    await log_request(
        provider,
        model,
        messages,
        response_text,
        usage,
        latency,
        "error" if is_error else "success",
        api_key_id=api_key_id,
        error=resp.text if is_error else None,
        headers=req_headers,
        request_body=req_body,
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
    req_headers,
    req_body,
    api_key_id,
    semaphore,
):
    logger.debug(f"[STREAM REQUEST] Provider: {provider}, Model: {model}, URL: {url}")
    if provider == "minimax":
        body_json = (
            json.loads(body)
            if isinstance(body, bytes)
            else json.loads(body)
            if body
            else {}
        )
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
        in_thinking = False
        thinking_buffer = ""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST", url, headers=headers, content=body
                ) as resp:
                    if provider == "minimax":
                        logger.info(f"[MINIMAX RESP] status={resp.status_code}")
                    chunk_count = 0
                    async for line in resp.aiter_lines():
                        if provider == "minimax" and chunk_count < 3:
                            logger.info(
                                f"[MINIMAX LINE {chunk_count}] {repr(line[:150])}"
                            )
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                yield f"data: [DONE]\n\n"
                                break
                            try:
                                chunk = json.loads(data)
                                chunk_count += 1
                                if "choices" in chunk and chunk["choices"]:
                                    delta = chunk["choices"][0].get("delta", {})
                                    content = delta.get("content", "")

                                    if provider == "minimax" and content:
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
                                                    new_content += thinking_buffer[i:]
                                                    break
                                            else:
                                                end_idx = thinking_buffer.find(
                                                    "</Parsed>", i
                                                )
                                                if end_idx != -1:
                                                    new_reasoning += thinking_buffer[
                                                        i:end_idx
                                                    ]
                                                    i = end_idx + 9
                                                    in_thinking = False
                                                else:
                                                    new_reasoning += thinking_buffer[i:]
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
                                        total_content += content

                                    reasoning = delta.get("reasoning_content", "")
                                    if reasoning and provider != "minimax":
                                        total_reasoning += reasoning
                            except json.JSONDecodeError:
                                pass
                            yield f"{line}\n\n"

            latency = (time.time() - start_time) * 1000
            approx_tokens = (len(total_content) + len(total_reasoning)) // 2
            update_stats(provider, model, approx_tokens, api_key_id=api_key_id)
            await log_request(
                provider,
                model,
                messages,
                total_content,
                {"total_tokens": approx_tokens, "estimated": approx_tokens},
                latency,
                "success",
                api_key_id=api_key_id,
                headers=req_headers,
                request_body=req_body,
            )
            logger.info(f"[STREAM COMPLETE] ~{approx_tokens} tokens | {latency:.0f}ms")
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            update_stats(provider, model, 0, api_key_id=api_key_id, is_error=True)
            await log_request(
                provider,
                model,
                messages,
                "",
                {},
                latency,
                "error",
                api_key_id=api_key_id,
                error=str(e),
                headers=req_headers,
                request_body=req_body,
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
