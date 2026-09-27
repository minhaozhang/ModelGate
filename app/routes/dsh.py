"""DeepSeek Harness (dsh) configuration endpoints.

DeepSeek Harness (https://github.com/deepseek-ai/deepseek-harness, command
``dsh`` / ``npx @deepseek-ai/dsh web``) speaks to custom OpenAI-compatible
gateways in two ways:

1. Web UI: Settings -> Models -> Add model provider -> Custom model API
   (Provider ID, base URL, API protocol ``openai-completions``, API key,
   then "Fetch available models" which calls ``GET {baseURL}/models``).
2. Profile config: ``$DSH_HOME/profiles/web/cordis.patch.yml`` (the Settings
   header's "Open configuration file" button reveals the exact path), plugin
   ``@deepseek-ai/dsh-llm-pi-ai`` -> ``providers.<id>`` with ``apiKeyEnv``
   credential references so the key never enters the YAML.

Model discovery and chat both work against ModelGate's OpenAI-compatible
``/v1`` endpoints, so no inbound protocol translation is needed here. There
is no setup-file merge endpoint: YAML merging is not done in the container
(no PyYAML in requirements), and the Web UI form is the documented primary
path anyway.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.routes.codex import build_codex_context
from app.routes.user import get_user_session

router = APIRouter(tags=["docs"])

DSH_PROVIDER_NAME = "modelgate"
DSH_API_KEY_ENV = "MODELGATE_API_KEY"


def _yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_dsh_patch_yml(ctx: dict) -> str:
    """cordis.patch.yml fragment wiring ModelGate into dsh's llm-pi-ai plugin.

    The key is referenced through ``apiKeyEnv`` (set MODELGATE_API_KEY in the
    environment) instead of being written into the file. compat switches keep
    the request shape gateway-friendly per dsh's troubleshooting guide.
    """
    models = ctx["models"] or []
    model_lines = "\n".join(f"          - id: {name}" for name in models)
    if not model_lines:
        model_lines = "          - id: model-not-found"
    return f"""- name: '@deepseek-ai/dsh-llm-pi-ai'
  config:
    providers:
      {DSH_PROVIDER_NAME}:
        displayName: ModelGate
        apiKeyEnv: {DSH_API_KEY_ENV}
        api: openai-completions
        baseURL: {_yaml_quote(ctx["base_url"])}
        compat:
          supportsDeveloperRole: false
          maxTokensField: max_tokens
        models:
{model_lines}
"""


def build_dsh_setup_markdown(ctx: dict, api_key: str) -> str:
    models = ctx["models"] or []
    model_list = "\n".join(f"- `{name}`" for name in models)
    if not model_list:
        model_list = "- No models are currently available for this API key."

    patch = build_dsh_patch_yml(ctx).rstrip("\n")
    base = ctx["base_url"]
    key_hint = api_key or "<your ModelGate API key>"

    return f"""# DeepSeek Harness (dsh) Setup Instructions

Please configure DeepSeek Harness to use ModelGate as a model provider.

Requirements:
- Node.js installed. Start the Web UI with `npx @deepseek-ai/dsh web` (opens http://127.0.0.1:3080).
- ModelGate serves the OpenAI Chat Completions API at `{base}` and model discovery at `{base}/models`.

Option 1 - Web UI (recommended):

1. Start dsh and open **Settings -> Models**.
2. Choose **Add model provider**, switch the card to **Custom model API**.
3. Fill in:
   - Provider ID: `{DSH_PROVIDER_NAME}` (lowercase, permanent)
   - Display name: `ModelGate`
   - Base URL: `{base}`
   - API protocol: `OpenAI Chat Completions`
   - API key: `{key_hint}`
4. Under **Model catalog** choose **Fetch available models** (calls `GET {base}/models`), tick the models you want, then save.
5. Pick the model in the session composer's model picker.

Option 2 - profile YAML (advanced):

dsh stores provider routes in `$DSH_HOME/profiles/web/cordis.patch.yml`; the Settings header's **Open configuration file** button reveals the exact path on your machine.

1. Export the API key in the environment that runs dsh (the YAML references it, the key itself never enters the file):

PowerShell:

    $env:{DSH_API_KEY_ENV} = "{key_hint}"

bash / zsh:

    export {DSH_API_KEY_ENV}="{key_hint}"

2. Add (or merge into the existing `@deepseek-ai/dsh-llm-pi-ai` entry's `providers`) the fragment below. A Cordis config override replaces the complete entry config, so preserve other providers and fields when editing an existing override:

```yaml
{patch}
```

3. Changes take effect on the next request; no restart needed.

Notes:
- One wire protocol per provider: `openai-completions` here. If you also need the Anthropic Messages protocol, add a second provider with a different ID and `api: anthropic-messages`.
- The `compat` switches above keep requests gateway-friendly (system prompt as `user`-style role, `max_tokens` spelling); remove them only if you know your upstream requires the OpenAI-native shape.

Models available through ModelGate:
{model_list}
"""


@router.get("/dsh/config")
async def get_dsh_config(
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


@router.get("/dsh/cordis.patch.yml")
async def get_dsh_patch_yml(
    request: Request,
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    if not api_key and not api_key_id:
        return PlainTextResponse("API Key is required", status_code=400)

    ctx = await build_codex_context(request, api_key=api_key, api_key_id=api_key_id)
    if not ctx:
        return PlainTextResponse("Invalid API Key", status_code=401)

    return PlainTextResponse(
        content=build_dsh_patch_yml(ctx),
        media_type="text/yaml; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="cordis.patch.yml"'},
    )


@router.get("/dsh/setup.md")
async def get_dsh_setup_markdown(
    request: Request,
    api_key: Optional[str] = None,
    api_key_id: Optional[int] = Depends(get_user_session),
):
    if not api_key and not api_key_id:
        return PlainTextResponse("# Error\n\nAPI Key is required", status_code=400)

    ctx = await build_codex_context(request, api_key=api_key, api_key_id=api_key_id)
    if not ctx:
        return PlainTextResponse("# Error\n\nInvalid API Key", status_code=401)

    md = build_dsh_setup_markdown(ctx, api_key=ctx["api_key"])
    return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")
