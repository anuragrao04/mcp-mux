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
