"""Token minting UI for mcp-env-mux."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import quote

import jwt
from cryptography.hazmat.primitives import serialization
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mcp_env_mux.auth.hybrid import HybridAzureProvider
from mcp_env_mux.auth.tokens import create_bot_token
from mcp_env_mux.config import AuthConfig
from mcp_env_mux.metrics.registry import Metrics
from mcp_env_mux.metrics.ui import instrument_ui_route, record_ui_login, record_ui_token_mint

_UI_SESSION_COOKIE = "mcp_env_mux_ui_session"
_UI_LOGIN_COOKIE = "mcp_env_mux_ui_login"
_UI_SESSION_ISSUER = "mcp-env-mux-ui"
_UI_SESSION_AUDIENCE = "mcp-env-mux-ui"
_UI_SESSION_TTL_SECONDS = 3600


def _validate_next_path(next_value: str | None) -> str:
    if not next_value:
        return "/ui/tokens"
    if not next_value.startswith("/"):
        return "/ui/tokens"
    if next_value.startswith("//"):
        return "/ui/tokens"
    return next_value


def _create_ui_session_token(
    *,
    private_key: Any,
    subject: str,
    roles: list[str],
    expires_in_seconds: int = _UI_SESSION_TTL_SECONDS,
) -> str:
    now = int(time.time())
    payload = {
        "sub": subject,
        "roles": roles,
        "type": "ui_session",
        "iss": _UI_SESSION_ISSUER,
        "aud": _UI_SESSION_AUDIENCE,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


def _load_ui_session(token: str, public_key_pem: str) -> dict[str, Any] | None:
    try:
        claims = jwt.decode(
            token,
            public_key_pem,
            algorithms=["RS256"],
            audience=_UI_SESSION_AUDIENCE,
            issuer=_UI_SESSION_ISSUER,
        )
    except Exception:
        return None
    if claims.get("type") != "ui_session":
        return None
    return claims


def _extract_ui_session(request: Request) -> str | None:
    return request.cookies.get(_UI_SESSION_COOKIE)


def _resolve_ui_principal(request: Request, public_key_pem: str) -> tuple[str, list[str]] | None:
    session_token = _extract_ui_session(request)
    if not session_token:
        return None
    claims = _load_ui_session(session_token, public_key_pem)
    if claims is None:
        return None
    roles = claims.get("roles", []) or []
    subject = claims.get("sub") or "unknown"
    return str(subject), list(roles)


def _set_ui_session_cookie(response: Response, session_token: str, secure: bool) -> None:
    response.set_cookie(
        _UI_SESSION_COOKIE,
        session_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=_UI_SESSION_TTL_SECONDS,
        path="/",
    )


def _clear_ui_session_cookie(response: Response, secure: bool) -> None:
    response.delete_cookie(
        _UI_SESSION_COOKIE,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def _set_ui_login_cookie(response: Response, login_token: str, secure: bool) -> None:
    response.set_cookie(
        _UI_LOGIN_COOKIE,
        login_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=600,
        path="/ui",
    )


def _clear_ui_login_cookie(response: Response, secure: bool) -> None:
    response.delete_cookie(
        _UI_LOGIN_COOKIE,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/ui",
    )


def _create_ui_login_token(
    private_key: Any,
    transaction_id: str,
    next_path: str,
    expires_in_seconds: int = 600,
) -> str:
    now = int(time.time())
    payload = {
        "type": "ui_login",
        "txn_id": transaction_id,
        "next": next_path,
        "iss": _UI_SESSION_ISSUER,
        "aud": _UI_SESSION_AUDIENCE,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


def _load_ui_login_token(token: str, public_key_pem: str) -> dict[str, Any] | None:
    try:
        claims = jwt.decode(
            token,
            public_key_pem,
            algorithms=["RS256"],
            audience=_UI_SESSION_AUDIENCE,
            issuer=_UI_SESSION_ISSUER,
        )
    except Exception:
        return None
    if claims.get("type") != "ui_login":
        return None
    return claims


def _wants_secure_cookies(auth_config: AuthConfig) -> bool:
    return auth_config.base_url.startswith("https://")


def _has_minting_role(roles: list[str], auth_config: AuthConfig) -> bool:
    return any(r in auth_config.token_minting_roles for r in roles)


def _build_ui_callback_url(auth_config: AuthConfig) -> str:
    return f"{auth_config.base_url.rstrip('/')}/ui/callback"


def register_ui_routes(
    server: FastMCP,
    auth_config: AuthConfig,
    private_key: Any,
    auth_provider: HybridAzureProvider,
    metrics: Metrics | None = None,
) -> None:
    """Register token minting UI routes on the FastMCP server."""

    available_roles = list(auth_config.roles.keys())
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    secure_cookies = _wants_secure_cookies(auth_config)

    @server.custom_route("/ui/login", methods=["GET"], name="ui_login")
    @instrument_ui_route(metrics, "ui_login")
    async def ui_login(request: Request) -> Response:
        next_path = _validate_next_path(request.query_params.get("next"))
        callback_url = _build_ui_callback_url(auth_config)
        authorize_url, transaction_id = await auth_provider.start_ui_authorization(
            callback_url=callback_url
        )
        login_token = _create_ui_login_token(private_key, transaction_id, next_path)
        response = RedirectResponse(authorize_url, status_code=302)
        _set_ui_login_cookie(response, login_token, secure_cookies)
        return response

    @server.custom_route("/ui/callback", methods=["GET"], name="ui_callback")
    @instrument_ui_route(metrics, "ui_callback")
    async def ui_callback(request: Request) -> Response:
        if request.query_params.get("error"):
            record_ui_login(metrics, "error")
            return HTMLResponse(
                _render_error(f"Azure login failed: {request.query_params.get('error')}"),
                status_code=400,
            )

        code = request.query_params.get("code")
        state = request.query_params.get("state")
        login_token = request.cookies.get(_UI_LOGIN_COOKIE)
        if not code or not state or not login_token:
            record_ui_login(metrics, "error")
            return HTMLResponse(_render_error("Invalid login state."), status_code=400)

        login_claims = _load_ui_login_token(login_token, public_key_pem)
        if login_claims is None:
            record_ui_login(metrics, "error")
            return HTMLResponse(_render_error("Login session expired."), status_code=400)
        if login_claims.get("txn_id") != state:
            record_ui_login(metrics, "error")
            return HTMLResponse(_render_error("Invalid login state."), status_code=400)

        next_path = _validate_next_path(login_claims.get("next"))
        callback_url = _build_ui_callback_url(auth_config)
        try:
            claims = await auth_provider.complete_ui_authorization(
                code=code,
                state=state,
                callback_url=callback_url,
            )
        except ValueError as exc:
            record_ui_login(metrics, "error")
            return HTMLResponse(_render_error(str(exc)), status_code=400)
        except Exception as exc:
            record_ui_login(metrics, "error")
            return HTMLResponse(_render_error(f"Azure token exchange failed: {exc}"), status_code=500)

        subject = (
            claims.get("preferred_username")
            or claims.get("email")
            or claims.get("sub")
            or "unknown"
        )
        roles: list[str] = claims.get("roles", []) or []
        session_token = _create_ui_session_token(
            private_key=private_key,
            subject=str(subject),
            roles=list(roles),
        )
        response = RedirectResponse(next_path, status_code=302)
        _set_ui_session_cookie(response, session_token, secure_cookies)
        _clear_ui_login_cookie(response, secure_cookies)
        record_ui_login(metrics, "success")
        return response

    @server.custom_route("/ui/tokens", methods=["GET"])
    @instrument_ui_route(metrics, "ui_tokens_get")
    async def ui_tokens_get(request: Request) -> Response:
        result = _resolve_ui_principal(request, public_key_pem)
        if result is None:
            return RedirectResponse(
                f"/ui/login?next={quote('/ui/tokens', safe='')}", status_code=302
            )

        subject, roles = result
        if not _has_minting_role(roles, auth_config):
            return HTMLResponse(_render_forbidden(), status_code=403)

        return HTMLResponse(_render_form(subject, available_roles, auth_config.token_max_expiry_days))

    @server.custom_route("/ui/tokens", methods=["POST"])
    @instrument_ui_route(metrics, "ui_tokens_post")
    async def ui_tokens_post(request: Request) -> Response:
        result = _resolve_ui_principal(request, public_key_pem)
        if result is None:
            return RedirectResponse(
                f"/ui/login?next={quote('/ui/tokens', safe='')}", status_code=302
            )

        creator, roles = result
        if not _has_minting_role(roles, auth_config):
            return HTMLResponse(_render_forbidden(), status_code=403)

        try:
            form = await request.form()
        except Exception:
            record_ui_token_mint(metrics, "error")
            return HTMLResponse(_render_error("Could not parse form data."), status_code=400)

        name = str(form.get("name", "")).strip()
        selected_roles = form.getlist("roles")  # type: ignore[attr-defined]
        expiry_str = str(form.get("expiry_days", "")).strip()

        errors = []
        if not name:
            errors.append("Name is required.")
        if not selected_roles:
            errors.append("At least one role is required.")

        expiry_days = 0
        try:
            expiry_days = int(expiry_str)
            if expiry_days < 1 or expiry_days > auth_config.token_max_expiry_days:
                errors.append(
                    f"Expiry must be between 1 and {auth_config.token_max_expiry_days} days."
                )
        except ValueError:
            errors.append("Expiry must be a number.")

        invalid_roles = [r for r in selected_roles if r not in auth_config.roles]
        if invalid_roles:
            errors.append(f"Unknown roles: {', '.join(invalid_roles)}")

        if errors:
            record_ui_token_mint(metrics, "error")
            return HTMLResponse(
                _render_form(
                    creator,
                    available_roles,
                    auth_config.token_max_expiry_days,
                    errors=errors,
                ),
                status_code=400,
            )

        new_token = create_bot_token(
            private_key=private_key,
            name=name,
            roles=list(selected_roles),
            created_by=creator,
            expiry_days=expiry_days,
        )
        record_ui_token_mint(metrics, "success")
        return HTMLResponse(_render_token_display(new_token, name))

    @server.custom_route("/ui/logout", methods=["GET"])
    @instrument_ui_route(metrics, "ui_logout")
    async def ui_logout(request: Request) -> Response:
        response = RedirectResponse("/ui/tokens", status_code=302)
        _clear_ui_session_cookie(response, secure_cookies)
        return response


# ---------------------------------------------------------------------------
# HTML templates (inline f-strings, no template engine)
# ---------------------------------------------------------------------------

def _render_forbidden() -> str:
    return """<!DOCTYPE html>
<html><head><title>Forbidden</title></head>
<body>
<h1>403 — Forbidden</h1>
<p>You do not have a role that permits token minting.</p>
</body></html>"""


def _render_error(message: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><title>Error</title></head>
<body>
<h1>Error</h1>
<p>{message}</p>
</body></html>"""


def _render_form(
    user: str,
    available_roles: list[str],
    max_expiry: int,
    errors: list[str] | None = None,
) -> str:
    role_checkboxes = "\n".join(
        f'<label><input type="checkbox" name="roles" value="{r}"> {r}</label><br>'
        for r in available_roles
    )
    error_html = ""
    if errors:
        items = "\n".join(f"<li>{e}</li>" for e in errors)
        error_html = f'<div style="color:red"><ul>{items}</ul></div>'

    return f"""<!DOCTYPE html>
<html>
<head><title>Mint Token — mcp-env-mux</title></head>
<body>
<h1>Mint Bot Token</h1>
<p>Logged in as: <strong>{user}</strong></p>
{error_html}
<form method="POST" action="/ui/tokens">
  <label>Name: <input type="text" name="name" required></label><br><br>
  <fieldset>
    <legend>Roles</legend>
    {role_checkboxes}
  </fieldset><br>
  <label>Expiry (days, 1–{max_expiry}): <input type="number" name="expiry_days" min="1" max="{max_expiry}" required></label><br><br>
  <button type="submit">Mint Token</button>
</form>
<p><a href="/ui/logout">Log out</a></p>
</body>
</html>"""


def _render_token_display(token: str, name: str) -> str:
    token_json = json.dumps(token)
    return f"""<!DOCTYPE html>
<html>
<head><title>Token Minted — mcp-env-mux</title></head>
<body>
<h1>Token Minted for <em>{name}</em></h1>
<p><strong>Copy this token now — it will not be shown again.</strong></p>
<textarea id="minted-token" rows="6" cols="80" readonly onclick="this.select()">{token}</textarea>
<br><br>
<button type="button" onclick='navigator.clipboard.writeText({token_json}).then(() => {{ this.textContent = "Copied!"; }}).catch(() => {{ const textarea = document.getElementById("minted-token"); textarea.focus(); textarea.select(); }});'>Copy token</button>
<br><br>
<a href="/ui/tokens">Mint another token</a>
</body>
</html>"""
