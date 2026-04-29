"""JWT token creation for mcp-env-mux bot tokens."""

from __future__ import annotations

import time
import uuid

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

_ISSUER = "mcp-env-mux"
_AUDIENCE = "mcp-env-mux"


def create_bot_token(
    private_key: RSAPrivateKey,
    name: str,
    roles: list[str],
    created_by: str,
    expiry_days: int,
) -> str:
    """Create a long-lived JWT for a headless agent.

    Claims: sub=name, type=bot, roles, created_by, jti, iat, exp, iss, aud
    """
    now = int(time.time())
    payload = {
        "sub": name,
        "type": "bot",
        "roles": roles,
        "created_by": created_by,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + expiry_days * 86400,
        "iss": _ISSUER,
        "aud": _AUDIENCE,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")
