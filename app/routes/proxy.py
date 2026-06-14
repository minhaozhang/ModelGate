from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.services.proxy import proxy_request

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
    from app.core.config import providers_cache
    from app.services.provider import AUTO_MODEL_NAME, is_auto_model_enabled

    model_names = set()
    for cfg in providers_cache.values():
        for pm in cfg.get("models", []):
            model_name = pm.get("model_name") or pm.get("actual_model_name", "")
            if model_name:
                model_names.add(model_name)
    if is_auto_model_enabled():
        model_names.add(AUTO_MODEL_NAME)
    models = [
        {"id": model_name, "object": "model", "owned_by": "modelgate"}
        for model_name in sorted(model_names)
    ]
    return {"object": "list", "data": models}
