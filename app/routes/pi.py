"""Pi coding agent configuration endpoints.

Pi (earendil-works/pi-coding-agent) reads custom OpenAI-compatible providers
from ``~/.pi/agent/models.json``:

    { "providers": { "modelgate": {
        "baseUrl": ".../modelgate/v1",
        "api": "openai-completions",
        "apiKey": "sk-...",
        "models": [ { "id": "model-name" } ]
    } } }

These endpoints mirror the Codex setup flow: context for the dashboard tab,
the generated models.json, a merge endpoint for setup scripts (other
providers survive), a markdown self-configuration guide, and one-liner
PowerShell / bash scripts.
"""

import json
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.app_paths import get_app_base_path
from app.routes.codex import build_codex_context
from app.routes.user import get_user_session

router = APIRouter(tags=["docs"])

PI_PROVIDER_NAME = "modelgate"


def _pi_provider_block(ctx: dict, api_key: str) -> dict:
    return {
        "baseUrl": ctx["base_url"],
        "api": "openai-completions",
        "apiKey": api_key,
        "models": [{"id": name} for name in (ctx["models"] or [])],
    }


def build_pi_models_json(ctx: dict, api_key: str) -> dict:
    return {"providers": {PI_PROVIDER_NAME: _pi_provider_block(ctx, api_key)}}


def merge_pi_models_json(existing_raw: str, ctx: dict, api_key: str) -> str:
    """Merge the modelgate provider into an existing pi models.json.

    Keeps unrelated top-level keys and other providers untouched.
    Returns the merged JSON text; raises ValueError on invalid JSON.
    """
    merged: dict = {}
    if existing_raw.strip():
        try:
            merged = json.loads(existing_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc
        if not isinstance(merged, dict):
            raise ValueError("models.json root must be a JSON object")

    providers = merged.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    providers[PI_PROVIDER_NAME] = _pi_provider_block(ctx, api_key)
    merged["providers"] = providers
    return json.dumps(merged, ensure_ascii=False, indent=2) + "\n"


def build_pi_setup_markdown(ctx: dict, api_key: str) -> str:
    models = ctx["models"] or []
    model_list = "\n".join(f"- `{name}`" for name in models)
    if not model_list:
        model_list = "- No models are currently available for this API key."

    sample = json.dumps(
        build_pi_models_json(ctx, api_key or "sk-..."),
        ensure_ascii=False,
        indent=2,
    )

    return f"""# Pi Coding Agent Setup Instructions

Please configure the Pi coding agent to use ModelGate as a model provider.

Requirements:
- Pi must be installed (https://pi.dev / `pi` command). Run it once so the agent directory exists.
- Config file: `~/.pi/agent/models.json` (Windows: `%USERPROFILE%\\.pi\\agent\\models.json`). Create the folders if missing.
- Keep all other providers in the file unchanged; only add or replace the `modelgate` entry.

Steps:
1. Merge the JSON below into `~/.pi/agent/models.json` under `providers.modelgate` (keep any other providers you already have):

```json
{sample}```

2. Restart Pi (or open `/model` which reloads the file).
3. Pick a model under the `modelgate` provider with `/model`.

The Pi config supports `$ENV_VAR` interpolation for `apiKey`, so `"$MODELGATE_API_KEY"` also works in place of a literal key.

Models available through ModelGate:
{model_list}
"""


@router.get("/pi/config")
async def get_pi_config(
    request: Request,
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    if not api_key and not api_key_id:
        return JSONResponse({"error": "API Key is required"}, status_code=400)

    ctx = await build_codex_context(request, api_key=api_key, api_key_id=api_key_id)
    if not ctx:
        return JSONResponse({"error": "Invalid API Key"}, status_code=401)
    return JSONResponse(ctx)


@router.get("/pi/models.json")
async def get_pi_models_json(
    request: Request,
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    if not api_key and not api_key_id:
        return PlainTextResponse("API Key is required", status_code=400)

    ctx = await build_codex_context(request, api_key=api_key, api_key_id=api_key_id)
    if not ctx:
        return PlainTextResponse("Invalid API Key", status_code=401)

    content = json.dumps(
        build_pi_models_json(ctx, ctx["api_key"]), ensure_ascii=False, indent=2
    ) + "\n"
    return PlainTextResponse(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": 'inline; filename="models.json"'},
    )


@router.post("/pi/setup-file")
async def merge_pi_config_file(
    request: Request,
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    """Merge ModelGate into a raw pi models.json upload.

    All JSON handling happens server-side so setup scripts only need curl.
    Returns the final models.json body, with the model list in X-Models.
    """
    if not api_key and not api_key_id:
        return PlainTextResponse("API Key is required", status_code=400)

    raw = (await request.body()).decode("utf-8", errors="replace")

    ctx = await build_codex_context(request, api_key=api_key, api_key_id=api_key_id)
    if not ctx:
        return PlainTextResponse("Invalid API Key", status_code=401)
    if not ctx["models"]:
        return PlainTextResponse(
            "No models are currently available for this API key", status_code=400
        )

    try:
        merged = merge_pi_models_json(raw, ctx, ctx["api_key"])
    except ValueError as exc:
        return PlainTextResponse(
            f"Existing models.json could not be parsed: {exc}", status_code=422
        )

    return PlainTextResponse(
        content=merged,
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Models": quote(",".join(ctx["models"]), safe=",.-_+/ "),
            "Content-Disposition": 'inline; filename="models.json"',
        },
    )


@router.get("/pi/setup.md")
async def get_pi_setup_markdown(
    request: Request,
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    if not api_key and not api_key_id:
        return PlainTextResponse("# Error\n\nAPI Key is required", status_code=400)

    ctx = await build_codex_context(request, api_key=api_key, api_key_id=api_key_id)
    if not ctx:
        return PlainTextResponse("# Error\n\nInvalid API Key", status_code=401)

    md = build_pi_setup_markdown(ctx, api_key=ctx["api_key"])
    return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")


# ---------------------------------------------------------------------------
# One-liner setup scripts (PowerShell for Windows, bash for macOS/Linux).
# ---------------------------------------------------------------------------

_POWERSHELL_SCRIPT = r'''$ErrorActionPreference = "Stop"

# PowerShell 5.1 defaults may not include TLS 1.2.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

$BaseUrl = "__BASE_URL__"
$PresetApiKey = "__API_KEY__"

# Locate the Pi agent directory.
$HomeDir = if ($env:USERPROFILE) { $env:USERPROFILE } elseif ($env:HOME) { $env:HOME } else { (Get-Location).Path }
$ConfigDir = Join-Path $HomeDir ".pi\agent"
$ConfigFile = Join-Path $ConfigDir "models.json"

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
    $BackupDir = Join-Path $ConfigDir "backup-modelgate"
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = Join-Path $BackupDir "models.json.$stamp"
    Copy-Item -LiteralPath $ConfigFile -Destination $backup
    Write-Host "Backed up existing config -> $backup" -ForegroundColor Yellow
}

# Upload existing config as-is: the server merges the ModelGate provider in
# (keeping other providers untouched) and returns the result.
$Body = ""
if (Test-Path -LiteralPath $ConfigFile) {
    $Body = Get-Content -LiteralPath $ConfigFile -Raw
}
$mergeUrl = "$BaseUrl/pi/setup-file?api_key=" + [uri]::EscapeDataString($ApiKey)
try {
    $resp = Invoke-WebRequest -Method Post -Uri $mergeUrl -ContentType "text/plain" -Body ([Text.Encoding]::UTF8.GetBytes($Body)) -UseBasicParsing
} catch {
    Write-Host "Failed to fetch config from ModelGate." -ForegroundColor Red
    $msg = $_.Exception.Message
    if ($_.ErrorDetails) { $msg = $_.ErrorDetails.Message }
    Write-Host $msg -ForegroundColor Red
    exit 1
}

# Save (UTF-8 without BOM).
New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
[IO.File]::WriteAllText($ConfigFile, $resp.Content)

Write-Host ""
Write-Host "ModelGate configured for Pi." -ForegroundColor Green
Write-Host "Config file: $ConfigFile"
$models = ($resp.Headers["X-Models"] -split ",") | Sort-Object
Write-Host ("Available models ({0}):" -f $models.Count)
foreach ($m in $models) { Write-Host "  - $m" }
Write-Host ""
Write-Host "Restart Pi if it is running. Open /model to reload and pick a model." -ForegroundColor Cyan
'''

_BASH_SCRIPT = r'''#!/usr/bin/env bash
set -euo pipefail

BASE_URL="__BASE_URL__"
PRESET_API_KEY="__API_KEY__"

command -v curl >/dev/null 2>&1 || { echo "curl is required but not installed." >&2; exit 1; }

CONFIG_DIR="$HOME/.pi/agent"
CONFIG_FILE="$CONFIG_DIR/models.json"

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
    BACKUP_DIR="$CONFIG_DIR/backup-modelgate"
    mkdir -p "$BACKUP_DIR"
    stamp=$(date +%Y%m%d-%H%M%S)
    cp "$CONFIG_FILE" "$BACKUP_DIR/models.json.$stamp"
    echo "Backed up existing config -> $BACKUP_DIR/models.json.$stamp"
fi

TMP_NEW=$(mktemp) || exit 1
TMP_HDR=$(mktemp) || { rm -f "$TMP_NEW"; exit 1; }
trap 'rm -f "$TMP_NEW" "$TMP_HDR"' EXIT

BODY_FILE=/dev/null
[ -f "$CONFIG_FILE" ] && BODY_FILE="$CONFIG_FILE"
STATUS=$(curl -sS --max-time 60 -X POST "$BASE_URL/pi/setup-file?api_key=$API_KEY" \
    -H "Content-Type: text/plain" \
    --data-binary "@$BODY_FILE" \
    -o "$TMP_NEW" -D "$TMP_HDR" -w '%{http_code}' || echo "000")

if [ "$STATUS" = "422" ]; then
    echo "Existing models.json could not be parsed:" >&2
    cat "$TMP_NEW" >&2
    exit 1
fi
if [ "$STATUS" != "200" ]; then
    echo "Failed to fetch config from ModelGate (HTTP $STATUS): $(cat "$TMP_NEW")" >&2
    exit 1
fi
mkdir -p "$CONFIG_DIR"
mv "$TMP_NEW" "$CONFIG_FILE"

echo ""
echo "ModelGate configured for Pi."
echo "Config file: $CONFIG_FILE"
MODELS=$(sed -n 's/^[[:space:]]*[xX]-[mM]odels:[[:space:]]*//p' "$TMP_HDR" | tr -d '\r' | tr ',' '\n' | sed '/^$/d')
if [ -n "$MODELS" ]; then
    echo "Available models:"
    printf '%s\n' "$MODELS" | sed 's/^/  - /'
else
    echo "No models are currently available for this API key."
fi
echo ""
echo "Restart Pi if it is running. Open /model to reload and pick a model."
'''


def _render_setup_script(template: str, base_url: str, api_key: str) -> str:
    return (
        template
        .replace("__BASE_URL__", base_url)
        .replace("__API_KEY__", api_key or "")
    )


@router.get("/pi/setup.ps1")
async def get_pi_setup_ps1(request: Request, key: Optional[str] = None):
    base = str(request.base_url).rstrip("/")
    app_base_path = get_app_base_path(request)
    if app_base_path and base.endswith(app_base_path):
        pass
    else:
        base = f"{base}{app_base_path}"
    script = _render_setup_script(_POWERSHELL_SCRIPT, base, key or "")
    return PlainTextResponse(
        content=script,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="modelgate-pi-setup.ps1"'},
    )


@router.get("/pi/setup.sh")
async def get_pi_setup_sh(request: Request, key: Optional[str] = None):
    base = str(request.base_url).rstrip("/")
    app_base_path = get_app_base_path(request)
    if app_base_path and base.endswith(app_base_path):
        pass
    else:
        base = f"{base}{app_base_path}"
    script = _render_setup_script(_BASH_SCRIPT, base, key or "")
    return PlainTextResponse(
        content=script,
        media_type="text/x-shellscript; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="modelgate-pi-setup.sh"'},
    )
