# Proxy Refactor Plan

## Goal

`[services/proxy.py](D:/project/ModelGate/services/proxy.py)` has grown too large and currently mixes:

- HTTP client lifecycle
- layered concurrency control
- request preprocessing
- provider-specific quirks
- normal request handling
- streaming request handling
- internal proxy calls
- response parsing, logging, and error normalization

The direction of the original plan was reasonable, but there is one repository-level constraint:

- We should not rename `services/proxy.py` directly into `services/proxy/`
- Doing that now would risk import-path conflicts with existing code

The safer path in this repo is:

- keep `[services/proxy.py](D:/project/ModelGate/services/proxy.py)` as the compatibility facade
- introduce `services/proxy_runtime/` as the real refactor target
- once external imports are stable, decide later whether a second rename is worthwhile

## Target Structure

```text
services/
  proxy.py
  proxy_runtime/
    __init__.py
    client.py
    concurrency.py
    common.py
    request_builder.py
    response_handler.py
    normal.py
    stream.py
    internal.py
    adapters/
      openai.py
      minimax.py
      anthropic.py
```

## Phases

### Phase 1

Extract the safest shared substrate first:

- `client.py`
- `concurrency.py`
- `response_handler.py`

Expected result:

- existing imports from `services.proxy` keep working
- common infrastructure leaves `proxy.py`
- runtime behavior remains unchanged

### Phase 2

Move the main execution paths into runtime modules:

- `common.py`
- `request_builder.py`
- `normal.py`
- `stream.py`
- `internal.py`

Expected result:

- `proxy_request()` becomes mostly orchestration
- `call_internal_model_via_proxy()` reuses the same shared request/response path
- normal and streaming logic stop living as giant blocks in one file

### Phase 3

Introduce adapters after the shared substrate is stable:

- `adapters/openai.py`
- `adapters/minimax.py`
- `adapters/anthropic.py`

Anthropic should come last, not first. It is safer to stabilize the shared execution model before adding a new provider abstraction.

## Constraints

### Import Compatibility

These imports must keep working during the refactor:

- `from services.proxy import proxy_request`
- `from services.proxy import call_internal_model_via_proxy`
- `from services.proxy import get_http_client`
- `from services.proxy import close_http_client`

### Concurrency Semantics

The existing two-layer limit must not regress:

1. `api_key_model_semaphore`
   key: `{user_api_key_id}:{model}`
   source: system config `api_key_model_max_concurrency`

2. `provider_key_semaphore`
   key: `{provider_key_id}:{provider_name}`
   source: provider key `max_concurrent`

### Provider-Key Disable Logic

The current `glm / minimax` quota or usage-limit handling must be preserved:

- detect provider-key level quota exhaustion
- disable only the affected provider key
- keep that logic in shared runtime paths instead of duplicating it in multiple handlers

## Implemented So Far

### Extracted Modules

- `[services/proxy_runtime/client.py](D:/project/ModelGate/services/proxy_runtime/client.py)`
- `[services/proxy_runtime/concurrency.py](D:/project/ModelGate/services/proxy_runtime/concurrency.py)`
- `[services/proxy_runtime/response_handler.py](D:/project/ModelGate/services/proxy_runtime/response_handler.py)`
- `[services/proxy_runtime/request_builder.py](D:/project/ModelGate/services/proxy_runtime/request_builder.py)`
- `[services/proxy_runtime/common.py](D:/project/ModelGate/services/proxy_runtime/common.py)`
- `[services/proxy_runtime/normal.py](D:/project/ModelGate/services/proxy_runtime/normal.py)`
- `[services/proxy_runtime/stream.py](D:/project/ModelGate/services/proxy_runtime/stream.py)`
- `[services/proxy_runtime/internal.py](D:/project/ModelGate/services/proxy_runtime/internal.py)`

### Compatibility Strategy

`[services/proxy.py](D:/project/ModelGate/services/proxy.py)` still exists and remains the import entrypoint.

Current compatibility approach:

- keep public entrypoints in `services.proxy`
- delegate handler execution into `services.proxy_runtime`
- avoid a risky big-bang move

## Acceptance Criteria

The refactor is acceptable when:

- `services.proxy` is still import-compatible
- shared helpers live under `services/proxy_runtime/`
- normal, streaming, and internal paths run through runtime modules
- layered semaphore behavior remains intact
- provider-key auto-disable behavior still works
- syntax/import checks pass in the actual runtime environment

## Next Steps

1. Verify runtime imports against the real container or app environment
2. Remove dead legacy code from `services/proxy.py` once the delegated path is confirmed stable
3. Start adapter extraction only after the delegated runtime path is proven stable
