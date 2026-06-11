import httpx

PROVIDER_REQUEST_TIMEOUT_SECONDS = 600.0
REPEATED_CHUNK_LIMIT = 10
_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=PROVIDER_REQUEST_TIMEOUT_SECONDS,
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
            http2=False,
        )
    return _http_client


async def close_http_client():
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None
