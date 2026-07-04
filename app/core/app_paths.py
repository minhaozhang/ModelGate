APP_BASE_PATH = "/modelgate"


def get_app_base_path(request) -> str:
    return request.scope.get("root_path") or ""


def build_app_url(request, path: str) -> str:
    normalized = path if path.startswith("/") else f"/{path}"
    return f"{get_app_base_path(request)}{normalized}"
