import app.core.config as config

from app.services.proxy_runtime.adapters.base import ProviderAdapter


class OpenAIAdapter(ProviderAdapter):
    name = "openai"

    def build_headers(
        self,
        provider_config: dict,
        api_key: str | None = None,
        client_user_agent: str | None = None,
    ) -> dict[str, str]:
        key = api_key or provider_config.get("api_key") or ""
        headers = {
            "content-type": "application/json",
            "user-agent": config.outbound_user_agent(client_user_agent),
            "connection": "keep-alive",
            "accept": "*/*",
        }
        if key:
            headers["authorization"] = f"Bearer {key}"
        return headers
