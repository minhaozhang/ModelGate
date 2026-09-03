import json
import re
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Body
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select

from app.core.app_paths import get_app_base_path
from app.core.database import (
    ApiKey,
    ApiKeyModel,
    ApiKeyModelAccess,
    Model,
    Provider,
    ProviderModel,
    async_session_maker,
)
from app.routes.user import get_user_session

router = APIRouter(tags=["docs"])


def strip_json_trailing_commas(json_str: str) -> str:
    """Remove trailing commas from JSON string to make it valid JSON."""
    # Remove trailing commas before } or ]
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
    return json_str


def parse_jsonc(text: str) -> dict:
    """Parse a JSONC document (JSON with // and /* */ comments, trailing commas).

    String-aware: comment markers inside quoted strings (e.g. "https://...")
    are preserved. Raises ValueError on invalid documents.
    """
    text = text.lstrip("\ufeff")
    out = []
    i, n = 0, len(text)
    in_str = False
    quote_char = ""
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote_char:
                in_str = False
            i += 1
            continue
        if c in ('"', "'"):
            in_str = True
            quote_char = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        out.append(c)
        i += 1
    stripped = "".join(out).strip()
    if not stripped:
        return {}
    stripped = strip_json_trailing_commas(re.sub(r",\s*,", ",", stripped))
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("top-level value must be an object")
    return parsed


def build_opencode_base_url(request: Request) -> str:
    base_url = str(request.base_url).rstrip("/")
    app_base_path = get_app_base_path(request)
    if app_base_path and base_url.endswith(app_base_path):
        return f"{base_url}/v1"
    return f"{base_url}{app_base_path}/v1"


def sort_opencode_models(models: dict) -> dict:
    return {
        name: models[name]
        for name in sorted(models.keys(), key=lambda value: value.casefold())
    }


async def build_opencode_config(
    session, base_url: str, api_key: str = None, api_key_id: int = None
):
    if api_key:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key == api_key, ApiKey.is_active == True)
        )
    elif api_key_id:
        result = await session.execute(
            select(ApiKey).where(ApiKey.id == api_key_id, ApiKey.is_active == True)
        )
    else:
        return None
    key = result.scalar_one_or_none()
    if not key:
        return None

    models_result = await session.execute(
        select(ApiKeyModel).where(ApiKeyModel.api_key_id == key.id)
    )
    key_models = models_result.scalars().all()
    allowed_pm_ids = [km.provider_model_id for km in key_models]

    model_access_result = await session.execute(
        select(ApiKeyModelAccess.model_id).where(ApiKeyModelAccess.api_key_id == key.id)
    )
    allowed_model_ids = [row[0] for row in model_access_result.fetchall()]

    from app.services.auto_model_routes import AUTO_MODEL_NAME, get_auto_model_route

    auto_config = await get_auto_model_route(session, AUTO_MODEL_NAME)
    auto_enabled = bool(auto_config.get("enabled"))
    auto_virtual_model_id = auto_config.get("virtual_model_id")
    auto_model_ids = {
        int(v) for v in (auto_config.get("model_ids") or []) if str(v).isdigit()
    }
    auto_provider_model_ids = {
        int(v)
        for v in (auto_config.get("provider_model_ids") or [])
        if str(v).isdigit()
    }
    auto_enabled = auto_enabled and bool(auto_model_ids or auto_provider_model_ids)
    full_access = not allowed_pm_ids and not allowed_model_ids
    auto_requested_by_key = full_access or (
        auto_virtual_model_id is not None and auto_virtual_model_id in allowed_model_ids
    )
    regular_allowed_model_ids = [
        model_id for model_id in allowed_model_ids if model_id != auto_virtual_model_id
    ]

    if allowed_pm_ids:
        pm_result = await session.execute(
            select(ProviderModel).where(ProviderModel.id.in_(allowed_pm_ids))
        )
    elif regular_allowed_model_ids:
        pm_result = await session.execute(
            select(ProviderModel).where(ProviderModel.model_id.in_(regular_allowed_model_ids))
        )
    elif full_access:
        pm_result = await session.execute(select(ProviderModel))
    else:
        pm_result = None

    provider_models = pm_result.scalars().all() if pm_result is not None else []
    models_config = {}
    model_priority: dict[str, int] = {}
    accessible_auto_candidates = []

    if auto_enabled and auto_requested_by_key:
        if auto_provider_model_ids:
            auto_pm_result = await session.execute(
                select(ProviderModel).where(ProviderModel.id.in_(auto_provider_model_ids))
            )
        else:
            auto_pm_result = await session.execute(
                select(ProviderModel).where(ProviderModel.model_id.in_(auto_model_ids))
            )
        auto_provider_models = auto_pm_result.scalars().all()
    else:
        auto_provider_models = []

    for pm in provider_models:
        provider_result = await session.execute(
            select(Provider).where(Provider.id == pm.provider_id)
        )
        provider = provider_result.scalar_one_or_none()
        if not provider:
            continue

        model_result = await session.execute(
            select(Model).where(Model.id == pm.model_id)
        )
        model = model_result.scalar_one_or_none()
        if not model:
            continue

        if not pm.is_active:
            continue

        if auto_enabled and auto_requested_by_key:
            allowed_by_model_scope = not auto_model_ids or pm.model_id in auto_model_ids
            allowed_by_pm_scope = (
                not auto_provider_model_ids or pm.id in auto_provider_model_ids
            )
            if allowed_by_model_scope and allowed_by_pm_scope:
                accessible_auto_candidates.append((pm, model))

        model_key = model.name
        priority = pm.priority if hasattr(pm, "priority") else 0
        if model_key in models_config and priority < model_priority.get(model_key, 0):
            continue

        display_name = model.display_name or model.name
        max_output = model.max_tokens or 131072
        context_window = (
            getattr(model, "context_hard_limit", None)
            or model.context_length
            or 204800
        )

        input_modalities = ["text"]
        if model.is_multimodal:
            input_modalities.append("image")

        thinking_config = None
        if model.thinking_enabled:
            thinking_config = {
                "type": "enabled",
            }

        model_entry = {
            "name": display_name,
            "modalities": {"input": input_modalities, "output": ["text"]},
            "limit": {"context": context_window, "output": max_output},
        }
        if thinking_config:
            model_entry["options"] = {"thinking": thinking_config}

        reasoning_effort_raw = (model.reasoning_effort or "").strip()
        if reasoning_effort_raw:
            efforts = [
                e.strip()
                for e in reasoning_effort_raw.split(",")
                if e.strip()
            ]
        elif thinking_config:
            # Zhipu GLM-5.2+ maps low/medium->high and xhigh->max, so only
            # high/max are meaningful effort levels there.
            provider_hint = f"{provider.name} {provider.base_url or ''}".lower()
            if any(h in provider_hint for h in ("zhipu", "bigmodel", "z.ai", "glm")):
                efforts = ["high", "max"]
            else:
                efforts = ["low", "high", "max"]
        else:
            efforts = []
        if efforts:
            model_entry["variants"] = {
                effort: {"reasoningEffort": effort} for effort in efforts
            }

        models_config[model_key] = model_entry
        model_priority[model_key] = priority

    seen_auto_pm_ids = {pm.id for pm, _model in accessible_auto_candidates}
    for pm in auto_provider_models:
        if pm.id in seen_auto_pm_ids:
            continue
        provider_result = await session.execute(
            select(Provider).where(Provider.id == pm.provider_id)
        )
        provider = provider_result.scalar_one_or_none()
        if not provider or not pm.is_active:
            continue
        model_result = await session.execute(
            select(Model).where(Model.id == pm.model_id)
        )
        model = model_result.scalar_one_or_none()
        if model:
            accessible_auto_candidates.append((pm, model))
            seen_auto_pm_ids.add(pm.id)

    if auto_enabled and accessible_auto_candidates:
        auto_context = max(
            (
                getattr(model, "context_hard_limit", None)
                or model.context_length
                or 204800
            )
            for _pm, model in accessible_auto_candidates
        )
        auto_output = max(
            (model.max_tokens or 131072) for _pm, model in accessible_auto_candidates
        )
        auto_input_modalities = ["text"]
        if auto_config.get("is_multimodal") or any(
            model.is_multimodal for _pm, model in accessible_auto_candidates
        ):
            auto_input_modalities.append("image")
        models_config["auto"] = {
            "name": "Auto",
            "modalities": {"input": auto_input_modalities, "output": ["text"]},
            "limit": {"context": auto_context, "output": auto_output},
        }

    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "modelgate": {
                "name": "ModelGate",
                "options": {
                    "baseURL": base_url,
                    "apiKey": key.key,
                },
                "models": sort_opencode_models(models_config),
            }
        },
    }


def build_setup_markdown(config: dict) -> str:
    provider_config = config["provider"]["modelgate"]
    model_names = list(sort_opencode_models(provider_config.get("models", {})).keys())
    model_list = "\n".join(f"- `{model_name}`" for model_name in model_names)
    if not model_list:
        model_list = "- No models are currently available for this API key."

    return f"""# OpenCode Setup Instructions

Please update the OpenCode configuration for this machine.

Requirements:
- Preferred global config file: `~/.config/opencode/opencode.jsonc`
- If `~/.config/opencode/opencode.jsonc` does not exist, create it first.
- You can also place `opencode.jsonc` in the root of the current project if you prefer a project-specific config.
- Keep existing providers and other settings unchanged.
- **Fully replace the `modelgate` provider**: find `provider.modelgate` in the config, and overwrite its entire value with the JSON object shown below. Do NOT merge, do NOT add fields to the existing one — the `modelgate` block must become exactly the JSON below.
- If `provider.modelgate` does not exist yet, add it with the JSON below.
- After replacement, the `modelgate.models` object must contain exactly the models listed below — no extra, no missing.
- If OpenCode is not installed yet, download it from `https://opencode.ai/`.

Models included in this provider (must match exactly after replacement):
{model_list}

Use this provider config (replace `provider.modelgate` entirely with this JSON object):

```json
{json.dumps(config, ensure_ascii=False)}
```

After the config is updated:
1. Save the file.
2. **Restart OpenCode** for the changes to take effect.
3. Verify that the models above are available in OpenCode and that no stale models from a previous `modelgate` config remain."""


@router.get("/opencode/setup.md")
async def get_opencode_setup_markdown(
    request: Request,
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    if not api_key and not api_key_id:
        return PlainTextResponse("# Error\n\nAPI Key is required", status_code=400)

    async with async_session_maker() as session:
        base_url = build_opencode_base_url(request)
        config = await build_opencode_config(
            session, base_url, api_key=api_key, api_key_id=api_key_id
        )
        if not config:
            return PlainTextResponse("# Error\n\nInvalid API Key", status_code=401)

        md = build_setup_markdown(config)
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")


@router.post("/opencode/merge")
async def merge_opencode_config(
    request: Request,
    body_data: dict = Body(..., media_type="application/json"),
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    if not api_key and not api_key_id:
        return JSONResponse({"error": "API Key is required"}, status_code=400)

    user_config = body_data.get("config", {})
    if not isinstance(user_config, dict):
        return JSONResponse({"error": "config must be an object"}, status_code=400)

    async with async_session_maker() as session:
        base_url = build_opencode_base_url(request)
        modelgate_config = await build_opencode_config(
            session, base_url, api_key=api_key, api_key_id=api_key_id
        )
        if not modelgate_config:
            return JSONResponse({"error": "Invalid API Key"}, status_code=401)

        providers = user_config.get("provider", {})
        if not isinstance(providers, dict):
            providers = {}
        providers["modelgate"] = modelgate_config["provider"]["modelgate"]
        user_config["provider"] = providers

        return JSONResponse(user_config)


@router.post("/opencode/setup-file")
async def merge_opencode_config_file(
    request: Request,
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    """Merge the modelgate provider into a raw opencode.jsonc upload.

    Accepts the config file as-is (comments and trailing commas allowed);
    all JSON handling happens server-side so setup scripts only need curl.
    Returns the final config file body, with the model list in X-Models.
    """
    if not api_key and not api_key_id:
        return PlainTextResponse("API Key is required", status_code=400)

    raw = (await request.body()).decode("utf-8", errors="replace").strip()
    user_config = {}
    if raw:
        try:
            user_config = parse_jsonc(raw)
        except ValueError as exc:
            return PlainTextResponse(f"Existing config could not be parsed: {exc}", status_code=422)

    async with async_session_maker() as session:
        base_url = build_opencode_base_url(request)
        modelgate_config = await build_opencode_config(
            session, base_url, api_key=api_key, api_key_id=api_key_id
        )
        if not modelgate_config:
            return PlainTextResponse("Invalid API Key", status_code=401)

        providers = user_config.get("provider", {})
        if not isinstance(providers, dict):
            providers = {}
        providers["modelgate"] = modelgate_config["provider"]["modelgate"]
        user_config["provider"] = providers

        models = sort_opencode_models(
            modelgate_config["provider"]["modelgate"].get("models", {})
        ).keys()
        merged = json.dumps(user_config, ensure_ascii=False, indent=2)
        return PlainTextResponse(
            content=merged + "\n",
            media_type="application/json",
            headers={"X-Models": quote(",".join(models), safe=",.-_+/ ")},
        )


# ---------------------------------------------------------------------------
# One-liner setup scripts (PowerShell for Windows, bash for macOS/Linux).
# Pattern: `irm <url> | iex` or `curl -fsSL <url> | bash`.
# ---------------------------------------------------------------------------

def build_app_base_url(request: Request) -> str:
    """App base URL without the trailing /v1 (used by setup scripts)."""
    base_url = str(request.base_url).rstrip("/")
    app_base_path = get_app_base_path(request)
    if app_base_path and base_url.endswith(app_base_path):
        return base_url
    return f"{base_url}{app_base_path}"


_POWERSHELL_SCRIPT = r'''$ErrorActionPreference = "Stop"

# PowerShell 5.1 defaults may not include TLS 1.2.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

$BaseUrl = "__BASE_URL__"
$PresetApiKey = "__API_KEY__"

# Locate opencode config dir.
$HomeDir = if ($env:USERPROFILE) { $env:USERPROFILE } elseif ($env:HOME) { $env:HOME } else { (Get-Location).Path }
$ConfigDir = Join-Path $HomeDir ".config\opencode"
$ConfigFile = Join-Path $ConfigDir "opencode.jsonc"

# Resolve API key (priority: URL preset > env var > interactive prompt).
$ApiKey = $PresetApiKey
if (-not $ApiKey) { $ApiKey = $env:MODELGATE_API_KEY }
if (-not $ApiKey) {
    Write-Host "ModelGate API Key required (find it on your user dashboard)."
    $ApiKey = Read-Host "Enter API key (sk-...)"
}
if ($ApiKey -notmatch '^sk-') {
    Write-Host ("API key must start with 'sk-' (got: '" + $ApiKey.Substring(0,[Math]::Min(15,$ApiKey.Length)) + "').") -ForegroundColor Red
    exit 1
}

# Backup existing config.
if (Test-Path -LiteralPath $ConfigFile) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = "$ConfigFile.bak.$stamp"
    Copy-Item -LiteralPath $ConfigFile -Destination $backup
    Write-Host "Backed up existing config -> $backup" -ForegroundColor Yellow
}

# Load existing config (strip // line comments, /* */ comment lines and trailing commas).
$Existing = $null
if (Test-Path -LiteralPath $ConfigFile) {
    try {
        $raw = Get-Content -LiteralPath $ConfigFile -Raw
        $stripped = ($raw -split "`n" | Where-Object { $_ -notmatch '^\s*//' -and $_ -notmatch '^\s*\*' }) -join "`n"
        # Inline-comment stripper: only strip // NOT preceded by : " ' / or a
        # word char, so URLs like https:// and file:/// inside strings survive.
        $stripped = $stripped -replace '(?m)(?<![:"''/\w])//.*$', ''
        $stripped = $stripped -replace ',(\s*[}\]])', '$1'
        if (-not $stripped.Trim()) { $stripped = '{}' }
        $Existing = ConvertFrom-Json $stripped
    } catch {
        Write-Host "Existing config could not be parsed: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "Continuing with a fresh config would DROP your existing providers/settings (a backup was kept)." -ForegroundColor Yellow
        $answer = Read-Host "Continue with a fresh config anyway? (y/N)"
        if ($answer -notmatch '^[Yy]') { exit 1 }
        $Existing = $null
    }
}
if ($null -eq $Existing) { $Existing = ConvertFrom-Json '{}' }

# POST to /opencode/merge to get merged config back.
$body = @{ config = $Existing } | ConvertTo-Json -Depth 100 -Compress
$mergeUrl = "$BaseUrl/opencode/merge?api_key=" + [uri]::EscapeDataString($ApiKey)
try {
    $resp = Invoke-RestMethod -Method Post -Uri $mergeUrl -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($body))
} catch {
    Write-Host "Failed to fetch config from ModelGate." -ForegroundColor Red
    $msg = $_.Exception.Message
    if ($_.ErrorDetails) { $msg = $_.ErrorDetails.Message }
    Write-Host $msg -ForegroundColor Red
    exit 1
}

# Save merged config (UTF-8 without BOM so any JSON parser can read it).
if (-not (Test-Path -LiteralPath $ConfigDir)) {
    New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
}
$json = $resp | ConvertTo-Json -Depth 100
[IO.File]::WriteAllText($ConfigFile, $json)

Write-Host ""
Write-Host "ModelGate provider configured." -ForegroundColor Green
Write-Host "Config file: $ConfigFile"
$models = @($resp.provider.modelgate.models.PSObject.Properties.Name) | Sort-Object
Write-Host ("Available models ({0}):" -f $models.Count)
foreach ($m in $models) { Write-Host "  - $m" }
Write-Host ""
Write-Host "Restart opencode if it is running." -ForegroundColor Cyan
'''


_BASH_SCRIPT = r'''#!/usr/bin/env bash
set -euo pipefail

BASE_URL="__BASE_URL__"
PRESET_API_KEY="__API_KEY__"

# Dependencies: curl only — the server does all JSON parsing.
command -v curl >/dev/null 2>&1 || { echo "curl is required but not installed." >&2; exit 1; }

# Locate opencode config dir.
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
CONFIG_FILE="$CONFIG_DIR/opencode.jsonc"

# Resolve API key (priority: URL preset > env var > interactive prompt).
API_KEY="$PRESET_API_KEY"
if [ -z "$API_KEY" ]; then API_KEY="${MODELGATE_API_KEY:-}"; fi
if [ -z "$API_KEY" ]; then
    read -rp "ModelGate API Key (sk-...): " API_KEY
fi
case "$API_KEY" in
    sk-*) ;;
    *) echo "Error: API key must start with 'sk-'." >&2; exit 1 ;;
esac

# Backup existing config.
if [ -f "$CONFIG_FILE" ]; then
    stamp=$(date +%Y%m%d-%H%M%S)
    cp "$CONFIG_FILE" "$CONFIG_FILE.bak.$stamp"
    echo "Backed up existing config -> $CONFIG_FILE.bak.$stamp"
fi

# Upload the existing config as-is (comments/trailing commas are fine):
# the server parses it, merges the modelgate provider in, and returns the
# final config file plus the model list in the X-Models response header.
TMP_HDR=$(mktemp) || exit 1
TMP_NEW=$(mktemp) || { rm -f "$TMP_HDR"; exit 1; }
trap 'rm -f "$TMP_HDR" "$TMP_NEW"' EXIT

post_config() {
    # $1: file to upload ("$CONFIG_FILE" or /dev/null for a fresh start)
    curl -sS --max-time 60 -X POST "$BASE_URL/opencode/setup-file?api_key=$API_KEY" \
        -H "Content-Type: text/plain" \
        -H "Accept: application/json" \
        --data-binary "@$1" \
        -o "$TMP_NEW" -D "$TMP_HDR" -w '%{http_code}'
}

BODY_FILE=/dev/null
[ -f "$CONFIG_FILE" ] && BODY_FILE="$CONFIG_FILE"
STATUS=$(post_config "$BODY_FILE" || echo "000")

if [ "$STATUS" = "422" ]; then
    echo "Existing config could not be parsed: $(cat "$TMP_NEW")" >&2
    echo "Continuing with a fresh config would DROP your existing providers/settings." >&2
    read -rp "Continue with a fresh config anyway? (y/N) " answer
    case "$answer" in
        [yY]*) STATUS=$(post_config /dev/null || echo "000") ;;
        *) exit 1 ;;
    esac
fi

if [ "$STATUS" != "200" ]; then
    echo "Failed to fetch config from ModelGate (HTTP $STATUS): $(cat "$TMP_NEW")" >&2
    exit 1
fi

# Save merged config (server output is pretty-printed JSON).
mkdir -p "$CONFIG_DIR"
mv "$TMP_NEW" "$CONFIG_FILE"

echo ""
echo "ModelGate provider configured."
echo "Config file: $CONFIG_FILE"
MODELS=$(sed -n 's/^[[:space:]]*[xX]-[mM]odels:[[:space:]]*//p' "$TMP_HDR" | tr -d '\r' | tr ',' '\n' | sed '/^$/d')
if [ -n "$MODELS" ]; then
    echo "Available models:"
    printf '%s\n' "$MODELS" | sed 's/^/  - /'
else
    echo "No models are currently available for this API key."
fi
echo ""
echo "Restart opencode if it is running."
'''


def _render_setup_script(template: str, base_url: str, api_key: str) -> str:
    return (
        template
        .replace("__BASE_URL__", base_url)
        .replace("__API_KEY__", api_key or "")
    )


@router.get("/opencode/setup.ps1")
async def get_opencode_setup_ps1(request: Request, key: Optional[str] = None):
    base = build_app_base_url(request)
    script = _render_setup_script(_POWERSHELL_SCRIPT, base, key or "")
    return PlainTextResponse(
        content=script,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="modelgate-setup.ps1"'},
    )


@router.get("/opencode/setup.sh")
async def get_opencode_setup_sh(request: Request, key: Optional[str] = None):
    base = build_app_base_url(request)
    script = _render_setup_script(_BASH_SCRIPT, base, key or "")
    return PlainTextResponse(
        content=script,
        media_type="text/x-shellscript; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="modelgate-setup.sh"'},
    )
