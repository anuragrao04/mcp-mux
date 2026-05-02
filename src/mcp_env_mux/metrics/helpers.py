from __future__ import annotations

from typing import Any


def principal_type_from_claims(claims: dict[str, Any] | None) -> str:
    if not claims:
        return "unknown"
    token_type = claims.get("type")
    if token_type == "bot":
        return "bot"
    return "user"


def principal_name_from_claims(claims: dict[str, Any] | None) -> str:
    if not claims:
        return "unknown"
    return str(
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("sub")
        or "unknown"
    )


def classify_tool_error(exc: Exception) -> str:
    message = str(exc)
    if isinstance(exc, ValueError):
        if "Missing required parameter 'env'" in message:
            return "missing_env"
        if "Invalid env '" in message:
            return "invalid_env"
    cls_name = exc.__class__.__name__.lower()
    if "timeout" in cls_name or "timeout" in message.lower():
        return "backend_timeout"
    if "transport" in cls_name or "connect" in cls_name or "network" in cls_name:
        return "backend_transport_error"
    if "toolerror" == cls_name or "access denied" in message.lower():
        return "rbac_denied"
    if cls_name:
        return "backend_error"
    return "unknown"


def classify_discovery_error(exc: Exception) -> str:
    cls_name = exc.__class__.__name__.lower()
    if "transport" in cls_name or "connect" in cls_name or "network" in cls_name:
        return "backend_transport_error"
    return "unknown"


def token_type_from_issuer(issuer: str) -> str:
    if issuer == "mcp-env-mux":
        return "bot"
    if issuer:
        return "user"
    return "unknown"


def estimate_response_size_bytes(value: Any) -> int | None:
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, list):
        total = 0
        saw_known = False
        for item in value:
            if isinstance(item, bytes):
                total += len(item)
                saw_known = True
                continue
            if isinstance(item, str):
                total += len(item.encode("utf-8"))
                saw_known = True
                continue

            text = getattr(item, "text", None)
            if isinstance(text, str):
                total += len(text.encode("utf-8"))
                saw_known = True
                continue

            data = getattr(item, "data", None)
            if isinstance(data, bytes):
                total += len(data)
                saw_known = True
                continue
            if isinstance(data, str):
                total += len(data.encode("utf-8"))
                saw_known = True
                continue

            mime_type = getattr(item, "mimeType", None)
            if mime_type is not None:
                saw_known = True

        if saw_known:
            return total
        return None

    text = getattr(value, "text", None)
    if isinstance(text, str):
        return len(text.encode("utf-8"))

    data = getattr(value, "data", None)
    if isinstance(data, bytes):
        return len(data)
    if isinstance(data, str):
        return len(data.encode("utf-8"))

    return None
