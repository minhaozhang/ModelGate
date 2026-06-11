from ipaddress import ip_address

from fastapi import Request


def _normalize_ip(value: str | None) -> str | None:
    if not value:
        return None

    candidate = value.strip().strip('"').strip("'")
    if not candidate or candidate.lower() == "unknown":
        return None

    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1 : candidate.index("]")]
    elif candidate.count(":") == 1 and "." in candidate:
        candidate = candidate.split(":", 1)[0]

    try:
        return str(ip_address(candidate))
    except ValueError:
        return None


def _extract_forwarded_for(forwarded: str | None) -> str | None:
    if not forwarded:
        return None

    for segment in forwarded.split(","):
        for part in segment.split(";"):
            key, _, value = part.strip().partition("=")
            if key.lower() != "for":
                continue
            normalized = _normalize_ip(value)
            if normalized:
                return normalized
    return None


def get_client_ip(request: Request) -> str | None:
    header_candidates = [
        request.headers.get("cf-connecting-ip"),
        request.headers.get("true-client-ip"),
        _extract_forwarded_for(request.headers.get("forwarded")),
    ]

    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        for raw_ip in x_forwarded_for.split(","):
            normalized = _normalize_ip(raw_ip)
            if normalized:
                return normalized

    header_candidates.extend(
        [
            request.headers.get("x-real-ip"),
            request.headers.get("x-client-ip"),
        ]
    )

    for candidate in header_candidates:
        normalized = _normalize_ip(candidate)
        if normalized:
            return normalized

    if request.client and request.client.host:
        return _normalize_ip(request.client.host) or request.client.host
    return None
