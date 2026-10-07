from app.services.proxy_runtime.adapters import get_adapter


def build_headers(
    provider_config: dict,
    api_key: str | None = None,
    protocol: str = "openai",
    client_user_agent: str | None = None,
) -> dict:
    adapter = get_adapter(protocol)
    return adapter.build_headers(
        provider_config, api_key=api_key, client_user_agent=client_user_agent
    )
