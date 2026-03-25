from fastapi import APIRouter, Request
from fastapi.responses import Response

from services.proxy import proxy_request

router = APIRouter(tags=["proxy"])


@router.api_route("/v1/chat/completions", methods=["POST", "OPTIONS"])
async def chat_completions(request: Request):
    if request.method == "OPTIONS":
        return Response()
    return await proxy_request(request, "/chat/completions")


@router.api_route("/v1/embeddings", methods=["POST", "OPTIONS"])
async def embeddings(request: Request):
    if request.method == "OPTIONS":
        return Response()
    return await proxy_request(request, "/embeddings")


@router.api_route("/v1/models", methods=["GET"])
async def list_models():
    from core.config import providers_cache

    models = []
    for provider_name, cfg in providers_cache.items():
        for pm in cfg.get("models", []):
            model_name = pm.get("model_name") or pm.get("actual_model_name", "")
            models.append(
                {
                    "id": f"{provider_name}/{model_name}",
                    "object": "model",
                    "owned_by": provider_name,
                }
            )
    return {"object": "list", "data": models}
