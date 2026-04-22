from services.proxy_runtime.adapters import get_adapter


def build_headers(
    provider_config: dict, api_key: str | None = None, protocol: str = "openai"
) -> dict:
    adapter = get_adapter(protocol)
    return adapter.build_headers(provider_config, api_key=api_key)
