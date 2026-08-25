import json
import tomllib
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.app_paths import get_app_base_path
from app.core.database import async_session_maker
from app.routes.opencode import (
    build_app_base_url,
    build_opencode_base_url,
    build_opencode_config,
    sort_opencode_models,
)
from app.routes.user import get_user_session

router = APIRouter(tags=["docs"])


# ---------------------------------------------------------------------------
# Codex catalog boilerplate (instructions template shared by every model).
#
# Codex refuses to load a models.json whose entries carry neither
# ``base_instructions`` nor ``model_messages.instructions_template`` — the
# agent would run with no system prompt. We mirror the official catalog's
# agent prompt (Apache-2.0, openai/codex models-manager) so third-party
# models behave like first-class Codex citizens.
# ---------------------------------------------------------------------------

_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "codex"
_CODEX_INSTRUCTIONS = (
    _ASSET_DIR / "instructions_template.md"
).read_text(encoding="utf-8")
_CODEX_TOKEN_BUDGET = json.loads(
    (_ASSET_DIR / "token_budget.json").read_text(encoding="utf-8")
)
_CODEX_AVAILABLE_IN_PLANS = json.loads(
    (_ASSET_DIR / "available_in_plans.json").read_text(encoding="utf-8")
)


# ---------------------------------------------------------------------------
# Config generation (config.toml + models.json)
# ---------------------------------------------------------------------------

TOML_MANAGED_KEYS = (
    "model",
    "model_provider",
    "preferred_auth_method",
    "forced_login_method",
    "model_reasoning_effort",
    "model_catalog_json",
)
PROVIDER_SECTION = "model_providers.modelgate"


def _codex_toml_key_lines(model: str, reasoning_effort: str = "high") -> list[str]:
    return [
        f'model = "{model}"',
        'model_provider = "modelgate"',
        'preferred_auth_method = "apikey"',
        'forced_login_method = "api"',
        f'model_reasoning_effort = "{reasoning_effort}"',
        'model_catalog_json = "~/.codex/models.json"',
    ]


def _codex_toml_provider_block(base_url: str, api_key: str) -> str:
    return (
        "[model_providers.modelgate]\n"
        'name = "ModelGate"\n'
        f'base_url = "{base_url}"\n'
        'wire_api = "responses"\n'
        f'experimental_bearer_token = "{api_key}"\n'
    )


def build_codex_toml(base_url: str, model: str, api_key: str, reasoning_effort: str = "high") -> str:
    return (
        "\n".join(_codex_toml_key_lines(model, reasoning_effort))
        + "\n\n"
        + _codex_toml_provider_block(base_url, api_key)
    )


def _codex_model_entry(slug: str, entry: dict) -> dict:
    """Map an opencode-style model entry to a Codex models.json entry.

    Boilerplate capability flags mirror the official catalog (openai/codex
    models-manager); per-model data (context window, modalities, reasoning
    levels) comes from the platform model metadata.
    """
    limit = entry.get("limit", {})
    context_window = limit.get("context", 204800)
    modalities = entry.get("modalities", {})
    input_modalities = modalities.get("input", ["text"])
    supports_image = "image" in input_modalities

    variants = entry.get("variants", {})
    efforts = list(variants.keys())
    default_effort = "high" if "high" in efforts else (efforts[-1] if efforts else "")

    out = {
        "slug": slug,
        "display_name": entry.get("name", slug),
        "description": entry.get("name", slug),
        "prefer_websockets": False,
        "support_verbosity": True,
        "default_verbosity": "low",
        "apply_patch_tool_type": "freeform",
        "web_search_tool_type": "text",
        "input_modalities": input_modalities,
        "supports_image_detail_original": supports_image,
        "truncation_policy": {"mode": "tokens", "limit": 10000},
        "supports_parallel_tool_calls": True,
        "tool_mode": None,
        "multi_agent_version": None,
        "use_responses_lite": False,
        "include_skills_usage_instructions": False,
        "include_apps_usage_instructions": False,
        "include_plugin_usage_instructions": False,
        "auto_review_model_override": None,
        "model_specialty": None,
        "context_window": context_window,
        "max_context_window": context_window,
        "auto_compact_token_limit": None,
        "comp_hash": "modelgate",
        "default_reasoning_summary": "none",
        "supports_reasoning_summary_parameter": True,
        "shell_type": "unified_exec",
        "visibility": "list",
        "supported_in_api": True,
        "priority": 0,
        "node_repl_auto_review_required": False,
        "node_repl_disabled": False,
        # Legacy instruction field: required by older Codex clients and by
        # the catalog loader when model_messages has no template.
        "base_instructions": _CODEX_INSTRUCTIONS,
        "model_messages": {
            "instructions_template": _CODEX_INSTRUCTIONS,
            "token_budget": _CODEX_TOKEN_BUDGET,
        },
        "minimal_client_version": "0.0.1",
        "availability_nux": None,
        "upgrade": None,
        "experimental_supported_tools": [],
        "available_in_plans": _CODEX_AVAILABLE_IN_PLANS,
        "supports_search_tool": False,
        "default_service_tier": None,
        "service_tiers": [],
        "additional_speed_tiers": [],
        "supports_reasoning_summaries": True,
    }
    if efforts:
        out["default_reasoning_level"] = default_effort
        out["supported_reasoning_levels"] = [
            {"effort": effort, "description": f"Reasoning effort {effort}"}
            for effort in efforts
        ]
    return out


def build_codex_models_catalog(models: dict) -> dict:
    entries = [
        _codex_model_entry(slug, entry) for slug, entry in sort_opencode_models(models).items()
    ]
    return {"models": entries}


def merge_codex_toml(
    existing_raw: str, base_url: str, model: str, api_key: str, reasoning_effort: str = "high"
) -> tuple[str, list[str]]:
    """Merge the ModelGate managed keys + provider section into a config.toml.

    Line-based so unrelated sections, comments and formatting survive.
    Both the input and the result are validated with tomllib; raises
    ValueError on invalid TOML. Returns (merged_toml, removed_lines).
    """
    if existing_raw.strip():
        try:
            tomllib.loads(existing_raw)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"invalid TOML: {exc}") from exc

    kept_lines: list[str] = []
    removed: list[str] = []
    in_managed_section = False
    for line in existing_raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().strip('"\'')
            in_managed_section = section == PROVIDER_SECTION
            if in_managed_section:
                removed.append(stripped)
                continue
        if in_managed_section:
            removed.append(stripped)
            continue
        if "=" in stripped and not stripped.startswith("["):
            key = stripped.split("=", 1)[0].strip()
            if key in TOML_MANAGED_KEYS and not _inside_section(kept_lines):
                removed.append(stripped)
                continue
        kept_lines.append(line)

    # Managed top-level keys must precede the first section header (TOML
    # scoping: bare keys after a header belong to that section).
    insert_at = len(kept_lines)
    for i, line in enumerate(kept_lines):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            insert_at = i
            break

    head = "\n".join(kept_lines[:insert_at]).strip("\n")
    tail = "\n".join(kept_lines[insert_at:]).strip("\n")
    chunks = [c for c in (head, "\n".join(_codex_toml_key_lines(model, reasoning_effort)), tail) if c]
    chunks.append(_codex_toml_provider_block(base_url, api_key).rstrip("\n"))
    merged = "\n\n".join(chunks) + "\n"

    try:
        tomllib.loads(merged)
    except tomllib.TOMLDecodeError as exc:  # pragma: no cover - defensive
        raise ValueError(f"merged TOML failed validation: {exc}") from exc
    return merged, removed


def _inside_section(lines: list[str]) -> bool:
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            return True
    return False


# ---------------------------------------------------------------------------
# Shared context (key visibility + model list), mirroring opencode.py
# ---------------------------------------------------------------------------

async def build_codex_context(
    request: Request, api_key: str = None, api_key_id: int = None
):
    async with async_session_maker() as session:
        base_url = build_opencode_base_url(request)
        config = await build_opencode_config(
            session, base_url, api_key=api_key, api_key_id=api_key_id
        )
        if not config:
            return None
        models = sort_opencode_models(
            config["provider"]["modelgate"].get("models", {})
        )
        model_names = list(models.keys())
        display_names = {
            name: entry.get("name", name) for name, entry in models.items()
        }
        default_model = next(
            (name for name in model_names if name != "auto"),
            model_names[0] if model_names else "",
        )
        provider = config["provider"]["modelgate"]
        return {
            "base_url": base_url,
            "models": model_names,
            "display_names": display_names,
            "default_model": default_model,
            "api_key": provider["options"]["apiKey"],
        }


def build_codex_setup_markdown(ctx: dict, api_key: str = None) -> str:
    models = ctx["models"] or []
    model_list = "\n".join(f"- `{name}`" for name in models)
    if not model_list:
        model_list = "- No models are currently available for this API key."

    model = ctx["default_model"] or "MODEL_NAME"
    token_note = (
        'Replace the `experimental_bearer_token` placeholder with the ModelGate API key.'
        if not api_key
        else 'The `experimental_bearer_token` value below already embeds the API key for this setup link.'
    )
    toml = build_codex_toml(ctx["base_url"], model, api_key or "sk-...")

    return f"""# Codex CLI Setup Instructions

Please configure Codex to use ModelGate as its model provider.

Requirements:
- Codex must be installed (`npm install -g @openai/codex`). Codex CLI, the ChatGPT desktop app and the VS Code Codex extension share the same config, so this only needs to be done once.
- Config file: `~/.codex/config.toml` (Windows: `%USERPROFILE%\\.codex\\config.toml`). Create the `.codex` folder and the file if they do not exist.
- Model catalog file: `~/.codex/models.json` (Windows: `%USERPROFILE%\\.codex\\models.json`). This tells Codex the context window, reasoning levels and input modalities of each ModelGate model.
- Keep all other settings in `config.toml` unchanged (MCP servers, trust level, profiles, etc.). Only add or update the entries below.

Steps:
1. Download <{ctx['base_url'].rsplit('/v1', 1)[0]}/codex/models.json> and save it as `~/.codex/models.json`.
2. Add the following to `~/.codex/config.toml` ({token_note}):

```toml
{toml}```

3. Restart Codex and pick a model with `/model`.

Models available through ModelGate:
{model_list}
"""


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@router.get("/codex/config")
async def get_codex_config(
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


@router.get("/codex/models.json")
async def get_codex_models_json(
    request: Request,
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    if not api_key and not api_key_id:
        return JSONResponse({"error": "API Key is required"}, status_code=400)

    async with async_session_maker() as session:
        config = await build_opencode_config(
            session, build_opencode_base_url(request),
            api_key=api_key, api_key_id=api_key_id,
        )
        if not config:
            return JSONResponse({"error": "Invalid API Key"}, status_code=401)
        catalog = build_codex_models_catalog(
            config["provider"]["modelgate"].get("models", {})
        )
    return PlainTextResponse(
        content=json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        media_type="application/json",
        headers={"Content-Disposition": 'inline; filename="models.json"'},
    )


@router.post("/codex/setup-file")
async def merge_codex_config_file(
    request: Request,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    """Merge ModelGate config into a raw config.toml upload.

    All TOML handling happens server-side so setup scripts only need curl.
    Returns the final config.toml body, with the model list in X-Models.
    """
    if not api_key and not api_key_id:
        return PlainTextResponse("API Key is required", status_code=400)

    raw = (await request.body()).decode("utf-8", errors="replace")

    ctx = await build_codex_context(request, api_key=api_key, api_key_id=api_key_id)
    if not ctx:
        return PlainTextResponse("Invalid API Key", status_code=401)

    chosen_model = model if model in ctx["models"] else ctx["default_model"]
    if not chosen_model:
        return PlainTextResponse("No models are currently available for this API key", status_code=400)

    try:
        merged, _removed = merge_codex_toml(
            raw, ctx["base_url"], chosen_model, ctx["api_key"]
        )
    except ValueError as exc:
        return PlainTextResponse(f"Existing config could not be parsed: {exc}", status_code=422)

    return PlainTextResponse(
        content=merged,
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Models": quote(",".join(ctx["models"]), safe=",.-_+/ "),
            "Content-Disposition": 'inline; filename="config.toml"',
        },
    )


@router.get("/codex/setup.md")
async def get_codex_setup_markdown(
    request: Request,
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    if not api_key and not api_key_id:
        return PlainTextResponse("# Error\n\nAPI Key is required", status_code=400)

    ctx = await build_codex_context(request, api_key=api_key, api_key_id=api_key_id)
    if not ctx:
        return PlainTextResponse("# Error\n\nInvalid API Key", status_code=401)

    md = build_codex_setup_markdown(ctx, api_key=ctx["api_key"])
    return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")


# ---------------------------------------------------------------------------
# One-liner setup scripts (PowerShell for Windows, bash for macOS/Linux).
# ---------------------------------------------------------------------------

_POWERSHELL_SCRIPT = r'''$ErrorActionPreference = "Stop"

# PowerShell 5.1 defaults may not include TLS 1.2.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

$BaseUrl = "__BASE_URL__"
$PresetApiKey = "__API_KEY__"

# Locate Codex config dir.
$HomeDir = if ($env:USERPROFILE) { $env:USERPROFILE } elseif ($env:HOME) { $env:HOME } else { (Get-Location).Path }
$ConfigDir = Join-Path $HomeDir ".codex"
$ConfigFile = Join-Path $ConfigDir "config.toml"
$CatalogFile = Join-Path $ConfigDir "models.json"

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
    $backup = Join-Path $BackupDir "config.toml.$stamp"
    Copy-Item -LiteralPath $ConfigFile -Destination $backup
    Write-Host "Backed up existing config -> $backup" -ForegroundColor Yellow
}

# Upload existing config as-is: the server parses it, merges the ModelGate
# entries in (keeping MCP servers etc. untouched), and returns the result.
$Body = ""
if (Test-Path -LiteralPath $ConfigFile) {
    $Body = Get-Content -LiteralPath $ConfigFile -Raw
}
$mergeUrl = "$BaseUrl/codex/setup-file?api_key=" + [uri]::EscapeDataString($ApiKey)
try {
    $resp = Invoke-WebRequest -Method Post -Uri $mergeUrl -ContentType "text/plain" -Body ([Text.Encoding]::UTF8.GetBytes($Body)) -UseBasicParsing
} catch {
    Write-Host "Failed to fetch config from ModelGate." -ForegroundColor Red
    $msg = $_.Exception.Message
    if ($_.ErrorDetails) { $msg = $_.ErrorDetails.Message }
    if ($resp -and $resp.StatusCode -eq 422) { $msg = $Body }
    Write-Host $msg -ForegroundColor Red
    exit 1
}

# Fetch the model catalog.
$catalogUrl = "$BaseUrl/codex/models.json?api_key=" + [uri]::EscapeDataString($ApiKey)
try {
    $catalog = Invoke-WebRequest -Method Get -Uri $catalogUrl -UseBasicParsing
} catch {
    Write-Host "Failed to fetch models.json from ModelGate." -ForegroundColor Red
    exit 1
}

# Save both files (UTF-8 without BOM).
if (-not (Test-Path -LiteralPath $ConfigDir)) {
    New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
}
[IO.File]::WriteAllText($ConfigFile, $resp.Content)
[IO.File]::WriteAllText($CatalogFile, $catalog.Content)

Write-Host ""
Write-Host "ModelGate configured for Codex." -ForegroundColor Green
Write-Host "Config file:  $ConfigFile"
Write-Host "Model catalog: $CatalogFile"
$models = ($resp.Headers["X-Models"] -split ",") | Sort-Object
Write-Host ("Available models ({0}):" -f $models.Count)
foreach ($m in $models) { Write-Host "  - $m" }
Write-Host ""
Write-Host "Restart Codex if it is running. Switch models with /model." -ForegroundColor Cyan
'''

_BASH_SCRIPT = r'''#!/usr/bin/env bash
set -euo pipefail

BASE_URL="__BASE_URL__"
PRESET_API_KEY="__API_KEY__"

command -v curl >/dev/null 2>&1 || { echo "curl is required but not installed." >&2; exit 1; }

CONFIG_DIR="$HOME/.codex"
CONFIG_FILE="$CONFIG_DIR/config.toml"
CATALOG_FILE="$CONFIG_DIR/models.json"

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
    cp "$CONFIG_FILE" "$BACKUP_DIR/config.toml.$stamp"
    echo "Backed up existing config -> $BACKUP_DIR/config.toml.$stamp"
fi

TMP_NEW=$(mktemp) || exit 1
TMP_HDR=$(mktemp) || { rm -f "$TMP_NEW"; exit 1; }
trap 'rm -f "$TMP_NEW" "$TMP_HDR"' EXIT

BODY_FILE=/dev/null
[ -f "$CONFIG_FILE" ] && BODY_FILE="$CONFIG_FILE"
STATUS=$(curl -sS --max-time 60 -X POST "$BASE_URL/codex/setup-file?api_key=$API_KEY" \
    -H "Content-Type: text/plain" \
    --data-binary "@$BODY_FILE" \
    -o "$TMP_NEW" -D "$TMP_HDR" -w '%{http_code}' || echo "000")

if [ "$STATUS" = "422" ]; then
    echo "Existing config.toml could not be parsed:" >&2
    cat "$TMP_NEW" >&2
    exit 1
fi
if [ "$STATUS" != "200" ]; then
    echo "Failed to fetch config from ModelGate (HTTP $STATUS): $(cat "$TMP_NEW")" >&2
    exit 1
fi
mv "$TMP_NEW" "$CONFIG_FILE"

STATUS=$(curl -sS --max-time 60 "$BASE_URL/codex/models.json?api_key=$API_KEY" \
    -o "$CATALOG_FILE.tmp" -w '%{http_code}' || echo "000")
if [ "$STATUS" != "200" ]; then
    echo "Failed to fetch models.json from ModelGate (HTTP $STATUS)." >&2
    exit 1
fi
mkdir -p "$CONFIG_DIR"
mv "$CATALOG_FILE.tmp" "$CATALOG_FILE"

echo ""
echo "ModelGate configured for Codex."
echo "Config file:   $CONFIG_FILE"
echo "Model catalog: $CATALOG_FILE"
MODELS=$(sed -n 's/^[[:space:]]*[xX]-[mM]odels:[[:space:]]*//p' "$TMP_HDR" | tr -d '\r' | tr ',' '\n' | sed '/^$/d')
if [ -n "$MODELS" ]; then
    echo "Available models:"
    printf '%s\n' "$MODELS" | sed 's/^/  - /'
else
    echo "No models are currently available for this API key."
fi
echo ""
echo "Restart Codex if it is running. Switch models with /model."
'''


def _render_setup_script(template: str, base_url: str, api_key: str) -> str:
    return (
        template
        .replace("__BASE_URL__", base_url)
        .replace("__API_KEY__", api_key or "")
    )


@router.get("/codex/setup.ps1")
async def get_codex_setup_ps1(request: Request, key: Optional[str] = None):
    base = build_app_base_url(request)
    script = _render_setup_script(_POWERSHELL_SCRIPT, base, key or "")
    return PlainTextResponse(
        content=script,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="modelgate-codex-setup.ps1"'},
    )


@router.get("/codex/setup.sh")
async def get_codex_setup_sh(request: Request, key: Optional[str] = None):
    base = build_app_base_url(request)
    script = _render_setup_script(_BASH_SCRIPT, base, key or "")
    return PlainTextResponse(
        content=script,
        media_type="text/x-shellscript; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="modelgate-codex-setup.sh"'},
    )
