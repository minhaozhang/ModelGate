"""Claude Code configuration endpoints.

Claude Code (Anthropic's CLI agent) points at custom gateways through
environment variables:

    ANTHROPIC_BASE_URL=https://gw.example/modelgate      (no /v1 suffix)
    ANTHROPIC_AUTH_TOKEN=sk-...                          (sent as Bearer)
    ANTHROPIC_MODEL=glm-5.3

Persisted in ``~/.claude/settings.json`` under the ``env`` key:

    { "env": { "ANTHROPIC_BASE_URL": "...", "ANTHROPIC_AUTH_TOKEN": "..." } }

ModelGate speaks the Anthropic Messages protocol at ``<base>/v1/messages``
(see app/routes/anthropic_proxy.py) and accepts both ``x-api-key`` and
``Authorization: Bearer`` credentials, so Claude Code works against it
directly. These endpoints mirror the Codex/Pi setup flow: dashboard context,
generated settings.json, a merge endpoint for setup scripts, a markdown
self-configuration guide, and one-liner PowerShell / bash scripts.
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


def _claude_env_block(ctx: dict, api_key: str) -> dict:
    """Env vars Claude Code reads for a custom gateway (base has no /v1)."""
    base = ctx["base_url"]
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    env = {
        "ANTHROPIC_BASE_URL": base,
        "ANTHROPIC_AUTH_TOKEN": api_key,
    }
    if ctx.get("default_model"):
        env["ANTHROPIC_MODEL"] = ctx["default_model"]
    return env


def build_claude_settings(ctx: dict, api_key: str) -> dict:
    return {"env": _claude_env_block(ctx, api_key)}


def merge_claude_settings(existing_raw: str, ctx: dict, api_key: str) -> str:
    """Merge the ModelGate env vars into an existing claude settings.json.

    Keeps unrelated top-level keys (permissions, model, statusLine, ...) and
    unrelated env vars untouched. Returns the merged JSON text; raises
    ValueError on invalid JSON.
    """
    merged: dict = {}
    if existing_raw.strip():
        try:
            merged = json.loads(existing_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc
        if not isinstance(merged, dict):
            raise ValueError("settings.json root must be a JSON object")

    env = merged.get("env")
    if not isinstance(env, dict):
        env = {}
    env.update(_claude_env_block(ctx, api_key))
    merged["env"] = env
    return json.dumps(merged, ensure_ascii=False, indent=2) + "\n"


def build_claude_setup_markdown(ctx: dict, api_key: str) -> str:
    models = ctx["models"] or []
    model_list = "\n".join(f"- `{name}`" for name in models)
    if not model_list:
        model_list = "- No models are currently available for this API key."

    base = ctx["base_url"]
    if base.endswith("/v1"):
        base = base[: -len("/v1")]

    settings = json.dumps(
        build_claude_settings(ctx, api_key or "sk-..."),
        ensure_ascii=False,
        indent=2,
    )

    return f"""# Claude Code Setup Instructions

Please configure Claude Code to use ModelGate as its Anthropic-compatible gateway.

Requirements:
- Claude Code must be installed: `npm install -g @anthropic-ai/claude-code` (command `claude`).
- Config file: `~/.claude/settings.json` (Windows: `%USERPROFILE%\\.claude\\settings.json`). Create the folders if missing.
- ModelGate serves the Anthropic Messages API at `{base}/v1/messages` and accepts both `x-api-key` and `Authorization: Bearer` headers.

Option 1 - persist into settings.json (survives restarts):

1. Merge the JSON below into `~/.claude/settings.json` under `env` (keep every other key you already have):

```json
{settings}```

2. Restart Claude Code if it is running.
3. Pick a model with `/model`, or rely on the `ANTHROPIC_MODEL` default set above.

Option 2 - temporary environment variables for one shell session:

PowerShell:

    $env:ANTHROPIC_BASE_URL = "{base}"
    $env:ANTHROPIC_AUTH_TOKEN = "<your ModelGate API key>"

bash / zsh:

    export ANTHROPIC_BASE_URL="{base}"
    export ANTHROPIC_AUTH_TOKEN="<your ModelGate API key>"

Notes:
- `ANTHROPIC_AUTH_TOKEN` is sent as `Authorization: Bearer` (recommended for gateways). `ANTHROPIC_API_KEY` (sent as `x-api-key`) also works with ModelGate.
- The base URL has no `/v1` suffix: the Anthropic SDK appends `/v1/messages` itself.

Models available through ModelGate:
{model_list}
"""


@router.get("/claude/config")
async def get_claude_config(
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


@router.get("/claude/settings.json")
async def get_claude_settings_json(
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
        build_claude_settings(ctx, ctx["api_key"]), ensure_ascii=False, indent=2
    ) + "\n"
    return PlainTextResponse(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": 'inline; filename="settings.json"'},
    )


@router.post("/claude/setup-file")
async def merge_claude_config_file(
    request: Request,
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    """Merge ModelGate env vars into a raw claude settings.json upload.

    All JSON handling happens server-side so setup scripts only need curl.
    Returns the final settings.json body, with the model list in X-Models.
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
        merged = merge_claude_settings(raw, ctx, ctx["api_key"])
    except ValueError as exc:
        return PlainTextResponse(
            f"Existing settings.json could not be parsed: {exc}", status_code=422
        )

    return PlainTextResponse(
        content=merged,
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Models": quote(",".join(ctx["models"]), safe=",.-_+/ "),
            "Content-Disposition": 'inline; filename="settings.json"',
        },
    )


@router.get("/claude/setup.md")
async def get_claude_setup_markdown(
    request: Request,
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    if not api_key and not api_key_id:
        return PlainTextResponse("# Error\n\nAPI Key is required", status_code=400)

    ctx = await build_codex_context(request, api_key=api_key, api_key_id=api_key_id)
    if not ctx:
        return PlainTextResponse("# Error\n\nInvalid API Key", status_code=401)

    md = build_claude_setup_markdown(ctx, api_key=ctx["api_key"])
    return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")


# ---------------------------------------------------------------------------
# One-liner setup scripts (PowerShell for Windows, bash for macOS/Linux).
# ---------------------------------------------------------------------------

_POWERSHELL_SCRIPT = r'''$ErrorActionPreference = "Stop"

# PowerShell 5.1 defaults may not include TLS 1.2.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

$BaseUrl = "__BASE_URL__"
$PresetApiKey = "__API_KEY__"

# Locate the Claude Code config directory.
$HomeDir = if ($env:USERPROFILE) { $env:USERPROFILE } elseif ($env:HOME) { $env:HOME } else { (Get-Location).Path }
$ConfigDir = Join-Path $HomeDir ".claude"
$ConfigFile = Join-Path $ConfigDir "settings.json"

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
    $backup = Join-Path $BackupDir "settings.json.$stamp"
    Copy-Item -LiteralPath $ConfigFile -Destination $backup
    Write-Host "Backed up existing config -> $backup" -ForegroundColor Yellow
}

# Upload existing config as-is: the server merges the ModelGate env vars in
# (keeping every other key untouched) and returns the result.
$Body = ""
if (Test-Path -LiteralPath $ConfigFile) {
    $Body = Get-Content -LiteralPath $ConfigFile -Raw
}
$mergeUrl = "$BaseUrl/claude/setup-file?api_key=" + [uri]::EscapeDataString($ApiKey)
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
Write-Host "ModelGate configured for Claude Code." -ForegroundColor Green
Write-Host "Config file: $ConfigFile"
$models = ($resp.Headers["X-Models"] -split ",") | Sort-Object
Write-Host ("Available models ({0}):" -f $models.Count)
foreach ($m in $models) { Write-Host "  - $m" }
Write-Host ""
Write-Host "Restart Claude Code if it is running, then pick a model with /model." -ForegroundColor Cyan
'''

_BASH_SCRIPT = r'''#!/usr/bin/env bash
set -euo pipefail

BASE_URL="__BASE_URL__"
PRESET_API_KEY="__API_KEY__"

command -v curl >/dev/null 2>&1 || { echo "curl is required but not installed." >&2; exit 1; }

CONFIG_DIR="$HOME/.claude"
CONFIG_FILE="$CONFIG_DIR/settings.json"

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
    cp "$CONFIG_FILE" "$BACKUP_DIR/settings.json.$stamp"
    echo "Backed up existing config -> $BACKUP_DIR/settings.json.$stamp"
fi

TMP_NEW=$(mktemp) || exit 1
TMP_HDR=$(mktemp) || { rm -f "$TMP_NEW"; exit 1; }
trap 'rm -f "$TMP_NEW" "$TMP_HDR"' EXIT

BODY_FILE=/dev/null
[ -f "$CONFIG_FILE" ] && BODY_FILE="$CONFIG_FILE"
STATUS=$(curl -sS --max-time 60 -X POST "$BASE_URL/claude/setup-file?api_key=$API_KEY" \
    -H "Content-Type: text/plain" \
    --data-binary "@$BODY_FILE" \
    -o "$TMP_NEW" -D "$TMP_HDR" -w '%{http_code}' || echo "000")

if [ "$STATUS" = "422" ]; then
    echo "Existing settings.json could not be parsed:" >&2
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
echo "ModelGate configured for Claude Code."
echo "Config file: $CONFIG_FILE"
MODELS=$(sed -n 's/^[[:space:]]*[xX]-[mM]odels:[[:space:]]*//p' "$TMP_HDR" | tr -d '\r' | tr ',' '\n' | sed '/^$/d')
if [ -n "$MODELS" ]; then
    echo "Available models:"
    printf '%s\n' "$MODELS" | sed 's/^/  - /'
else
    echo "No models are currently available for this API key."
fi
echo ""
echo "Restart Claude Code if it is running, then pick a model with /model."
'''


def _render_setup_script(template: str, base_url: str, api_key: str) -> str:
    return (
        template
        .replace("__BASE_URL__", base_url)
        .replace("__API_KEY__", api_key or "")
    )


@router.get("/claude/setup.ps1")
async def get_claude_setup_ps1(request: Request, key: Optional[str] = None):
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
        headers={"Content-Disposition": 'inline; filename="modelgate-claude-setup.ps1"'},
    )


@router.get("/claude/setup.sh")
async def get_claude_setup_sh(request: Request, key: Optional[str] = None):
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
        headers={"Content-Disposition": 'inline; filename="modelgate-claude-setup.sh"'},
    )
