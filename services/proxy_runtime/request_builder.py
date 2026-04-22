from core.config import OUTBOUND_USER_AGENT


def build_headers(provider_config: dict, api_key: str | None = None) -> dict:
    headers = {
        "content-type": "application/json",
        "user-agent": OUTBOUND_USER_AGENT,
        "connection": "keep-alive",
        "accept": "*/*",
    }
    key = api_key or provider_config.get("api_key") or ""
    if key:
        headers["authorization"] = f"Bearer {key}"
    return headers
