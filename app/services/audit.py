import json
from datetime import datetime
from fastapi import Request
from app.core.database import AuditLog, async_session_maker
from app.core.config import validate_session, admin_users


_RESOURCE_MAP = {
    "providers": "provider",
    "provider_keys": "provider_key",
    "models": "model",
    "provider_models": "provider_model",
    "keys": "api_key",
    "api_key_time_rules": "time_rule",
    "mcp_servers": "mcp_server",
    "documents": "document",
    "document_files": "document_file",
    "system_config": "system_config",
    "notifications": "notification",
    "scheduler_tasks": "scheduler_task",
    "users": "user",
    "roles": "role",
    "role_permissions": "role_permission",
    "menus": "menu",
    "permissions": "permission",
    "user_roles": "user_role",
}

_SENSITIVE_FIELDS = {"password", "new_password", "password_hash", "api_key", "auth_token", "key"}

_MAX_BODY_SIZE = 4096


def _resolve_user(request: Request):
    session = request.cookies.get("session")
    if not session:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session = auth_header[7:]
    if session:
        if session.startswith("ey"):
            try:
                from app.services.rbac_auth import decode_access_token
                payload = decode_access_token(session)
                if payload:
                    return payload.get("user_id"), payload.get("username")
            except Exception:
                pass
            return None, None

        if validate_session(session):
            for uname in admin_users:
                return 0, uname

    user_session = request.cookies.get("user_session")
    if user_session:
        try:
            from app.routes.user import USER_SESSIONS
            info = USER_SESSIONS.get(user_session)
            if info:
                return info.get("api_key_id"), info.get("name")
        except Exception:
            pass

    return None, None


def _parse_resource(path: str):
    parts = [p for p in path.split("/") if p]
    resource = None
    resource_id = None

    for i, part in enumerate(parts):
        if part in _RESOURCE_MAP:
            resource = _RESOURCE_MAP[part]
            if i + 1 < len(parts):
                resource_id = parts[i + 1]
            break
        mapped = _RESOURCE_MAP.get(part)
        if mapped:
            resource = mapped
            if i + 1 < len(parts):
                resource_id = parts[i + 1]
            break

    if not resource and len(parts) >= 2:
        resource = parts[-2] if len(parts) >= 2 else parts[0]
        resource_id = parts[-1] if len(parts) >= 2 else None

    return resource, resource_id


def _sanitize_body(body: dict) -> dict:
    if not isinstance(body, dict):
        return body
    sanitized = {}
    for k, v in body.items():
        if any(sf in k.lower() for sf in _SENSITIVE_FIELDS):
            sanitized[k] = "***"
        else:
            sanitized[k] = v
    return sanitized


def _build_detail(action: str, resource: str, resource_id: str, body: dict) -> str:
    action_zh = {"create": "创建", "update": "更新", "delete": "删除"}.get(action, action)
    parts = [f"{action_zh} {resource}"]
    if resource_id:
        parts.append(f"#{resource_id}")
    if body:
        keys = [k for k in body.keys() if k not in _SENSITIVE_FIELDS]
        if keys:
            parts.append(f"({', '.join(keys[:5])})")
    return " ".join(parts)


async def write_audit_log(
    request: Request,
    action: str,
    resource: str,
    resource_id: str = None,
    detail: str = None,
    body: dict = None,
    status_code: int = None,
    username: str = None,
    user_id: int = None,
):
    if username is None and user_id is None:
        resolved_uid, resolved_uname = _resolve_user(request)
        if resolved_uid is None and resolved_uname is None:
            return
        user_id = user_id or resolved_uid
        username = username or resolved_uname
    else:
        if user_id is None:
            user_id = 0
        if username is None:
            _, username = _resolve_user(request)

    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    client_ip = client_ip.split(",")[0].strip()
    user_agent = request.headers.get("user-agent", "")

    if detail is None:
        detail = _build_detail(action, resource, resource_id, body)

    sanitized_body = _sanitize_body(body) if body else None
    if sanitized_body:
        body_str = json.dumps(sanitized_body, ensure_ascii=False, default=str)
        if len(body_str) > _MAX_BODY_SIZE:
            sanitized_body = {"_truncated": True}

    try:
        async with async_session_maker() as session:
            log = AuditLog(
                user_id=user_id,
                username=username,
                action=action,
                resource=resource,
                resource_id=str(resource_id) if resource_id else None,
                detail=detail,
                request_body=sanitized_body,
                client_ip=client_ip,
                user_agent=user_agent[:1024] if user_agent else None,
                status_code=status_code,
                created_at=datetime.now(),
            )
            session.add(log)
            await session.commit()
    except Exception:
        pass


WRITE_METHODS = {"POST", "PUT", "DELETE"}
SKIP_PATHS = {"/v1/", "/weixin", "/mcp-proxy", "/admin/api/auth/check", "/admin/api/audit"}


def should_audit(request: Request) -> bool:
    if request.method not in WRITE_METHODS:
        return False
    path = request.url.path
    for skip in SKIP_PATHS:
        if path.startswith(skip):
            return False
    if "/admin/" not in path and "/user/api/" not in path:
        return False
    if "/user/api/" in path and request.method == "GET":
        return False
    return True


async def audit_from_request(request: Request, status_code: int = 200):
    path = request.url.path
    action_map = {"POST": "create", "PUT": "update", "DELETE": "delete"}
    action = action_map.get(request.method, request.method.lower())
    resource, resource_id = _parse_resource(path)

    body = None
    if request.method in ("POST", "PUT"):
        try:
            body_bytes = await request.body()
            if body_bytes:
                body = json.loads(body_bytes)
        except Exception:
            body = None

    await write_audit_log(
        request=request,
        action=action,
        resource=resource,
        resource_id=resource_id,
        body=body,
        status_code=status_code,
    )
