# ui.py

## Purpose

Token minting UI for mcp-env-mux. Provides HTML routes for authenticated users with minting roles to create long-lived bot tokens via a web form.

## Public API

### `register_ui_routes(server: FastMCP, auth_config: AuthConfig, private_key: Any, public_key: Any) -> None`

Registers token minting UI routes on the FastMCP server:

**`GET /ui/tokens`** — Shows the bot token minting form. Requires a valid Bearer token with a minting role (`auth_config.token_minting_roles`). Returns 401 if no token, 403 if token lacks minting role.

**`POST /ui/tokens`** — Mints a new bot token. Validates form fields: `name` (required), `roles` (at least one, must be known), `expiry_days` (1 to `token_max_expiry_days`). On success, displays the token once. On validation failure, re-renders the form with error messages.

## Internal Functions

### `_extract_bearer(request: Request) -> str | None`

Extracts the Bearer token from the `Authorization` header.

### `_verify_minting_access(token: str, public_key: Any, auth_config: AuthConfig) -> tuple[str, list[str]] | None`

Verifies the JWT (RS256, audience/issuer = "mcp-env-mux") and checks that the user holds at least one role in `auth_config.token_minting_roles`. Returns `(email, roles)` on success, `None` on failure.

### HTML Renderers

All render functions return inline HTML strings (no template engine):
- `_render_auth_required()` — 401 page
- `_render_forbidden()` — 403 page
- `_render_error(message)` — Generic error page
- `_render_form(user, available_roles, max_expiry, errors=None)` — Minting form with checkboxes for roles
- `_render_token_display(token, name)` — Shows the minted token in a textarea (copy-once pattern)

## Dependencies

- `jwt` (PyJWT) for token verification
- `mcp_env_mux.auth.tokens.create_bot_token`
- `mcp_env_mux.config.AuthConfig`
- `starlette` for Request/Response types
- `fastmcp.FastMCP` for route registration

## Error Handling

- 401 if no Bearer token provided.
- 403 if token is invalid or user lacks minting role.
- 400 for form validation errors (missing name, no roles, invalid expiry, unknown roles). Errors shown inline on the form.
