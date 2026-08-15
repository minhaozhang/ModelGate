import json

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
async def list_models(request: Request):
    from app.services.api_key_access import resolve_visible_models_for_api_key

    auth = request.headers.get("authorization") or ""
    api_key = auth[7:].strip() if auth.lower().startswith("bearer ") else auth.strip()
    model_names, error = await resolve_visible_models_for_api_key(api_key)
    if error:
        return Response(
            content=json.dumps(
                {
                    "error": {
                        "message": error,
                        "type": "invalid_request_error",
                        "code": "invalid_api_key",
                    }
                }
            ),
            status_code=401,
            media_type="application/json",
        )
    models = [
        {"id": model_name, "object": "model", "owned_by": "modelgate"}
        for model_name in sorted(model_names)
    ]
    return {"object": "list", "data": models}
