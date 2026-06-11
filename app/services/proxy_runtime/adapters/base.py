from __future__ import annotations

import abc


class ProviderAdapter(abc.ABC):
    name: str = "base"

    def build_headers(
        self, provider_config: dict, api_key: str | None = None
    ) -> dict[str, str]:
        key = api_key or provider_config.get("api_key") or ""
        headers = {
            "content-type": "application/json",
            "user-agent": "modelgate/1.0",
            "connection": "keep-alive",
            "accept": "*/*",
        }
        if key:
            headers["authorization"] = f"Bearer {key}"
        return headers

    def transform_request(self, body: dict, provider_config: dict) -> dict:
        return body

    def get_target_path(self, endpoint: str) -> str:
        return endpoint

    def transform_response(self, resp_json: dict) -> dict:
        return resp_json

    def transform_error_response(self, resp_json: dict, status_code: int) -> dict:
        return resp_json

    def preprocess_body(self, body: dict, provider_config: dict) -> dict:
        return body

    async def transform_stream_chunk(
        self, raw_line: str, context: dict
    ) -> list[str]:
        return [raw_line]

    def create_stream_context(self) -> dict:
        return {}

    def transform_stream_done(self) -> str:
        return "data: [DONE]\n\n"
