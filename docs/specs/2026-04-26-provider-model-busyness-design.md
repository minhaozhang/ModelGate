# ProviderModel Busyness Level Availability

## Summary

Allow per-binding configuration of when a provider-model is available based on system busyness level. Expensive models can be configured to only activate when the system is busy (cheaper models are overwhelmed), saving cost when the system is idle.

## Requirements

- Config on ProviderModel (provider-model binding) granularity
- Single threshold field: `max_busyness_level`
- NULL = always available (default)
- Logic: only available when `current_level <= max_busyness_level`
- When unavailable: return 503 with message "当前系统{level_label}，该模型不可用，请前往用户界面查看推荐模型列表"
- NOT silently skipped — explicitly rejected so user knows to switch models

## Busyness Levels (reference)

1. 极度繁忙 (extremely_busy)
2. 较繁忙 (very_busy)
3. 繁忙 (busy)
4. 正常 (normal)
5. 空闲 (idle)
6. 无人问津 (quiet)

Lower = busier. Higher = quieter.

## Example

`max_busyness_level = 3` (繁忙):

| Current Level | Available? |
|---|---|
| 1 极度繁忙 | Yes |
| 2 较繁忙 | Yes |
| 3 繁忙 | Yes |
| 4 正常 | No — rejected |
| 5 空闲 | No — rejected |
| 6 无人问津 | No — rejected |

## Changes

### 1. Database

Add column to `provider_models` table:

```python
max_busyness_level = Column(Integer, nullable=True)  # NULL = no limit
```

`init_db` auto-creates via `create_all`.

### 2. Provider Cache

`load_providers()` reads `max_busyness_level` into `providers_cache[provider]["models"]` for each model entry.

### 3. API

- `GET /admin/api/providers/{id}/models` — include `max_busyness_level` in response
- `PUT /admin/api/providers/{id}/models/{pm_id}` — accept `max_busyness_level` update

### 4. Proxy Check (services/proxy.py)

After determining provider + model, before forwarding request:

```python
current_level = busyness_state.get("level")
model_max_level = model_config.get("max_busyness_level")
if model_max_level is not None and current_level > model_max_level:
    level_label = LEVEL_LABELS.get(current_level, "")
    return error_response(
        f"当前系统{level_label}，该模型不可用，请前往用户界面查看推荐模型列表",
        status_code=503,
        error_type="model_unavailable",
    )
```

### 5. UI (config.html)

In the Provider-Model Bindings section, each bound model row gets a dropdown:

```
[模型名]  [繁忙级别: 不限 ▾]  [🔑] [✕]
```

Options: 不限 / 1-极度繁忙 / 2-较繁忙 / 3-繁忙 / 4-正常 / 5-空闲 / 6-无人问津

Selecting a value calls the PUT API immediately.
