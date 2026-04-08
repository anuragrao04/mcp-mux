"""Token minting UI for mcp-env-mux."""

from __future__ import annotations

from typing import Any

import jwt as pyjwt
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response

from mcp_env_mux.auth.tokens import create_bot_token
from mcp_env_mux.config import AuthConfig

_ISSUER = "mcp-env-mux"
_AUDIENCE = "mcp-env-mux"


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _verify_minting_access(
    token: str,
    public_key: Any,
    auth_config: AuthConfig,
) -> tuple[str, list[str]] | None:
    """Verify token and check that the user holds a minting role.

    Returns (email, roles) on success, None on failure.
    """
    try:
        claims = pyjwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=_AUDIENCE,
            issuer=_ISSUER,
        )
    except pyjwt.PyJWTError:
        return None

    roles: list[str] = claims.get("roles", [])
    subject: str = claims.get("sub", "")

    # Must hold at least one minting role
    if not any(r in auth_config.token_minting_roles for r in roles):
        return None

    return subject, roles


def register_ui_routes(
    server: FastMCP,
    auth_config: AuthConfig,
    private_key: Any,
    public_key: Any,
) -> None:
    """Register token minting UI routes on the FastMCP server."""

    available_roles = list(auth_config.roles.keys())

    # -----------------------------------------------------------------------
    # GET /ui/tokens — show the minting form
    # -----------------------------------------------------------------------

    @server.custom_route("/ui/tokens", methods=["GET"])
    async def ui_tokens_get(request: Request) -> Response:
        raw_token = _extract_bearer(request)
        if raw_token is None:
            return HTMLResponse(_render_auth_required(), status_code=401)

        result = _verify_minting_access(raw_token, public_key, auth_config)
        if result is None:
            return HTMLResponse(_render_forbidden(), status_code=403)

        subject, _ = result
        return HTMLResponse(_render_form(subject, available_roles, auth_config.token_max_expiry_days))

    # -----------------------------------------------------------------------
    # POST /ui/tokens — mint a bot token and display it once
    # -----------------------------------------------------------------------

    @server.custom_route("/ui/tokens", methods=["POST"])
    async def ui_tokens_post(request: Request) -> Response:
        raw_token = _extract_bearer(request)
        if raw_token is None:
            return HTMLResponse(_render_auth_required(), status_code=401)

        result = _verify_minting_access(raw_token, public_key, auth_config)
        if result is None:
            return HTMLResponse(_render_forbidden(), status_code=403)

        creator, _ = result

        try:
            form = await request.form()
        except Exception:
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

        # Validate selected roles
        invalid_roles = [r for r in selected_roles if r not in auth_config.roles]
        if invalid_roles:
            errors.append(f"Unknown roles: {', '.join(invalid_roles)}")

        if errors:
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
        return HTMLResponse(_render_token_display(new_token, name))


# ---------------------------------------------------------------------------
# HTML templates (inline f-strings, no template engine)
# ---------------------------------------------------------------------------

def _render_auth_required() -> str:
    return """<!DOCTYPE html>
<html><head><title>Authentication Required</title></head>
<body>
<h1>401 — Authentication Required</h1>
<p>You must provide a valid Bearer token in the Authorization header.</p>
</body></html>"""


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
</body>
</html>"""


def _render_token_display(token: str, name: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head><title>Token Minted — mcp-env-mux</title></head>
<body>
<h1>Token Minted for <em>{name}</em></h1>
<p><strong>Copy this token now — it will not be shown again.</strong></p>
<textarea rows="6" cols="80" readonly onclick="this.select()">{token}</textarea>
<br><br>
<a href="/ui/tokens">Mint another token</a>
</body>
</html>"""
