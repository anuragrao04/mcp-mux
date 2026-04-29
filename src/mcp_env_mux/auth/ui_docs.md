# ui.py

## Purpose

Token minting UI for mcp-env-mux. Provides HTML routes for authenticated users with minting roles to create long-lived bot tokens via a web form.

## Public API

### `register_ui_routes(server: FastMCP, auth_config: AuthConfig, private_key: Any, auth_provider: HybridAzureProvider) -> None`

Registers token minting UI routes on the FastMCP server.

> **Signature change**: takes a `HybridAzureProvider` instance instead of a raw public key. This lets the UI accept either an Azure-issued user token (admins logging in with their Microsoft session) or a previously-minted admin bot token.

**`GET /ui/tokens`** — Shows the bot token minting form. Requires a valid Bearer token and a role in `auth_config.token_minting_roles`. Returns 401 if no token, 403 if token lacks minting role.

**`POST /ui/tokens`** — Mints a new bot token. Validates form fields: `name` (required), `roles` (at least one, must be known), `expiry_days` (1 to `token_max_expiry_days`). On success, displays the token once. On validation failure, re-renders the form with error messages.

## Internal Functions

### `_extract_bearer(request: Request) -> str | None`

Extracts the Bearer token from the `Authorization` header.

### `async _verify_minting_access(token: str, auth_provider: HybridAzureProvider, auth_config: AuthConfig) -> tuple[str, list[str]] | None`

Calls `await auth_provider.verify_token(token)`. If the result is `None`, returns `None`. Otherwise reads `roles` from `claims`, requires at least one to be in `auth_config.token_minting_roles`, and returns `(subject, roles)` where `subject` is the first available of: `claims["preferred_username"]`, `claims["email"]`, `claims["sub"]`.

### HTML Renderers

Inline HTML strings (no template engine), unchanged from previous version:
- `_render_auth_required()` — 401 page
- `_render_forbidden()` — 403 page
- `_render_error(message)` — Generic error page
- `_render_form(user, available_roles, max_expiry, errors=None)` — Minting form
- `_render_token_display(token, name)` — Shows the minted token in a textarea (copy-once pattern)

## Dependencies

- `mcp_env_mux.auth.hybrid.HybridAzureProvider`
- `mcp_env_mux.auth.tokens.create_bot_token`
- `mcp_env_mux.config.AuthConfig`
- `starlette` for Request/Response types
- `fastmcp.FastMCP` for route registration

## Error Handling

- 401 if no Bearer token provided.
- 403 if token is invalid or user lacks minting role.
- 400 for form validation errors (missing name, no roles, invalid expiry, unknown roles). Errors shown inline on the form.
