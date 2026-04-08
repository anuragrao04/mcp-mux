"""OAuth 2.1 endpoints for mcp-env-mux Azure AD OIDC flow."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt as pyjwt
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from mcp_env_mux.auth.tokens import create_user_token
from mcp_env_mux.config import AuthConfig

_ISSUER = "mcp-env-mux"
_AUDIENCE = "mcp-env-mux"
_CODE_TTL_SECONDS = 600  # auth codes expire after 10 min


# ---------------------------------------------------------------------------
# In-memory state stores
# ---------------------------------------------------------------------------

@dataclass
class _PendingAuth:
    redirect_uri: str
    client_state: str
    code_challenge: str
    nonce: str
    created_at: float = field(default_factory=time.time)


@dataclass
class _AuthCodeData:
    email: str
    roles: list[str]
    code_challenge: str
    created_at: float = field(default_factory=time.time)


_pending_auths: dict[str, _PendingAuth] = {}
_auth_codes: dict[str, _AuthCodeData] = {}


def _cleanup_expired() -> None:
    now = time.time()
    expired_pending = [k for k, v in _pending_auths.items() if now - v.created_at > _CODE_TTL_SECONDS]
    for k in expired_pending:
        del _pending_auths[k]
    expired_codes = [k for k, v in _auth_codes.items() if now - v.created_at > _CODE_TTL_SECONDS]
    for k in expired_codes:
        del _auth_codes[k]


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """Verify that code_verifier hashes (S256) to code_challenge."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return computed == code_challenge


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_oauth_routes(server: FastMCP, auth_config: AuthConfig, private_key: Any) -> None:
    """Register all OAuth 2.1 and discovery routes on the FastMCP server."""
    tenant = auth_config.azure.tenant_id
    client_id = auth_config.azure.client_id
    client_secret = auth_config.azure.client_secret

    # -----------------------------------------------------------------------
    # Discovery: /.well-known/oauth-protected-resource
    # -----------------------------------------------------------------------

    @server.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
    async def oauth_protected_resource(request: Request) -> JSONResponse:
        base = str(request.base_url).rstrip("/")
        return JSONResponse({
            "resource": base,
            "authorization_servers": [base],
            "bearer_methods_supported": ["header"],
            "resource_documentation": f"{base}/docs",
        })

    # -----------------------------------------------------------------------
    # Discovery: /.well-known/oauth-authorization-server
    # -----------------------------------------------------------------------

    @server.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
    async def oauth_authorization_server(request: Request) -> JSONResponse:
        base = str(request.base_url).rstrip("/")
        return JSONResponse({
            "issuer": base,
            "authorization_endpoint": f"{base}/auth/login",
            "token_endpoint": f"{base}/auth/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
        })

    # -----------------------------------------------------------------------
    # /auth/login — redirect to Azure AD
    # -----------------------------------------------------------------------

    @server.custom_route("/auth/login", methods=["GET"])
    async def auth_login(request: Request) -> Response:
        params = request.query_params
        redirect_uri = params.get("redirect_uri", "")
        state = params.get("state", "")
        code_challenge = params.get("code_challenge", "")
        code_challenge_method = params.get("code_challenge_method", "S256")

        if code_challenge_method != "S256":
            return Response("Only S256 code_challenge_method is supported", status_code=400)

        # Generate a nonce to correlate the Azure callback with our state
        nonce = secrets.token_urlsafe(32)
        _pending_auths[nonce] = _PendingAuth(
            redirect_uri=redirect_uri,
            client_state=state,
            code_challenge=code_challenge,
            nonce=nonce,
        )
        _cleanup_expired()

        base = str(request.base_url).rstrip("/")
        az_params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": f"{base}/auth/callback",
            "response_mode": "query",
            "scope": "openid email profile",
            "state": nonce,
        }
        az_url = (
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?"
            + urllib.parse.urlencode(az_params)
        )
        return RedirectResponse(az_url, status_code=302)

    # -----------------------------------------------------------------------
    # /auth/callback — Azure AD redirects here after login
    # -----------------------------------------------------------------------

    @server.custom_route("/auth/callback", methods=["GET"])
    async def auth_callback(request: Request) -> Response:
        params = request.query_params
        az_code = params.get("code")
        nonce = params.get("state")
        error = params.get("error")

        if error:
            return Response(f"Azure AD error: {error}", status_code=400)
        if not az_code or not nonce:
            return Response("Missing code or state", status_code=400)

        pending = _pending_auths.pop(nonce, None)
        if pending is None:
            return Response("Invalid or expired state", status_code=400)

        base = str(request.base_url).rstrip("/")

        # Exchange Azure code for ID token
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "authorization_code",
                    "code": az_code,
                    "redirect_uri": f"{base}/auth/callback",
                    "scope": "openid email profile",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )

        if resp.status_code != 200:
            return Response(f"Token exchange failed: {resp.text}", status_code=502)

        token_data = resp.json()
        id_token = token_data.get("id_token", "")

        # Decode ID token (Azure has already validated it; we just read claims)
        try:
            id_claims = pyjwt.decode(id_token, options={"verify_signature": False})
        except Exception as exc:
            return Response(f"Failed to decode ID token: {exc}", status_code=502)

        email = id_claims.get("email") or id_claims.get("preferred_username", "unknown")
        az_roles: list[str] = id_claims.get("roles", [])

        # Filter to only roles that exist in our config
        known_roles = [r for r in az_roles if r in auth_config.roles]

        # Store our own auth code for the client to exchange
        our_code = secrets.token_urlsafe(32)
        _auth_codes[our_code] = _AuthCodeData(
            email=email,
            roles=known_roles,
            code_challenge=pending.code_challenge,
        )
        _cleanup_expired()

        # Redirect back to the client
        if pending.redirect_uri:
            redirect_params = {"code": our_code, "state": pending.client_state}
            redirect_url = pending.redirect_uri + "?" + urllib.parse.urlencode(redirect_params)
            return RedirectResponse(redirect_url, status_code=302)

        return Response(
            f"Login successful. Code: {our_code}",
            status_code=200,
            media_type="text/plain",
        )

    # -----------------------------------------------------------------------
    # /auth/token — client POSTs to exchange code for JWT
    # -----------------------------------------------------------------------

    @server.custom_route("/auth/token", methods=["POST"])
    async def auth_token(request: Request) -> Response:
        try:
            body = await request.form()
        except Exception:
            body = {}

        code = body.get("code", "")
        code_verifier = body.get("code_verifier", "")
        grant_type = body.get("grant_type", "")

        if grant_type != "authorization_code":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        if not code:
            return JSONResponse({"error": "missing code"}, status_code=400)

        code_data = _auth_codes.pop(str(code), None)
        if code_data is None:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

        if time.time() - code_data.created_at > _CODE_TTL_SECONDS:
            return JSONResponse({"error": "invalid_grant", "error_description": "code expired"}, status_code=400)

        if not verify_pkce(str(code_verifier), code_data.code_challenge):
            return JSONResponse({"error": "invalid_grant", "error_description": "PKCE verification failed"}, status_code=400)

        access_token = create_user_token(private_key, code_data.email, code_data.roles)
        return JSONResponse({
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": 3600,
        })
