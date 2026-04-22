from core.config import OUTBOUND_USER_AGENT

from services.proxy_runtime.adapters.base import ProviderAdapter


class OpenAIAdapter(ProviderAdapter):
    name = "openai"

    def build_headers(
        self, provider_config: dict, api_key: str | None = None
    ) -> dict[str, str]:
        key = api_key or provider_config.get("api_key") or ""
        headers = {
            "content-type": "application/json",
            "user-agent": OUTBOUND_USER_AGENT,
            "connection": "keep-alive",
            "accept": "*/*",
        }
        if key:
            headers["authorization"] = f"Bearer {key}"
        return headers
