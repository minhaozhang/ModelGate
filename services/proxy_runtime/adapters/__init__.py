from services.proxy_runtime.adapters.base import ProviderAdapter
from services.proxy_runtime.adapters.openai import OpenAIAdapter
from services.proxy_runtime.adapters.anthropic import AnthropicAdapter

_ADAPTERS: dict[str, ProviderAdapter] = {
    "openai": OpenAIAdapter(),
    "anthropic": AnthropicAdapter(),
}
_DEFAULT_ADAPTER = OpenAIAdapter()


def get_adapter(protocol: str = "openai") -> ProviderAdapter:
    return _ADAPTERS.get(protocol, _DEFAULT_ADAPTER)


__all__ = [
    "ProviderAdapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "get_adapter",
]
