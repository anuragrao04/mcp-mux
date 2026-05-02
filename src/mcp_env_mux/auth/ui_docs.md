# ui.py

## Purpose

Token minting UI for mcp-env-mux. Provides a browser-oriented Azure login flow plus HTML routes for authenticated users with minting roles to create long-lived bot tokens via a web form.

## Public API

### `register_ui_routes(server: FastMCP, auth_config: AuthConfig, private_key: Any, auth_provider: HybridAzureProvider) -> None`

Registers token minting UI routes on the FastMCP server.

The UI is now session-based and human-only.

**`GET /ui/login`** — Starts the browser login flow. Validates a `next` target, starts a UI authorization transaction through `HybridAzureProvider`, stores a compact signed UI login cookie containing the transaction id plus `next`, and redirects to Azure with redirect URI `<base_url>/ui/callback`.

**`GET /ui/callback`** — Handles the Azure callback for the UI flow. Validates the signed UI login cookie, ensures callback `state` matches the transaction id, completes the authorization-code exchange and claim extraction through `HybridAzureProvider`, creates a short-lived signed UI session cookie, and redirects to the validated `next` path.

**`GET /ui/tokens`** — Shows the bot token minting form. Requires a valid UI session cookie and a role in `auth_config.token_minting_roles`. Redirects to `/ui/login` if no valid session is present. Returns 403 if the session is valid but lacks a minting role.

**`POST /ui/tokens`** — Mints a new bot token. Requires a valid UI session cookie. Validates form fields: `name` (required), `roles` (at least one, must be known), `expiry_days` (1 to `token_max_expiry_days`). On success, displays the token once. On validation failure, re-renders the form with error messages.

**`GET /ui/logout`** — Clears the UI session cookie and redirects back to `/ui/tokens`.

## Internal Functions

Key helpers include:

- `_validate_next_path(...)` — only allows safe local redirect targets
- `_create_ui_login_token(...)` / `_load_ui_login_token(...)` — sign and verify the compact UI login cookie that binds browser state to a transaction id
- `_create_ui_session_token(...)` — signs a short-lived UI session JWT
- `_load_ui_session(...)` — verifies and decodes the UI session JWT
- `_resolve_ui_principal(...)` — loads subject + roles from the UI session cookie
- `_set_ui_login_cookie(...)` / `_clear_ui_login_cookie(...)` — temporary browser login binding cookie handling
- `_set_ui_session_cookie(...)` / `_clear_ui_session_cookie(...)` — browser session handling

Authorization-transaction start/completion and Azure claim extraction are provided by `HybridAzureProvider`.

### HTML Renderers

Inline HTML strings (no template engine):
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

- Redirect to `/ui/login` if no valid UI session is present.
- 400 for invalid callback state, missing/expired login cookie, or other malformed browser-login input.
- 500 if provider-backed Azure code exchange fails during the UI callback.
- 403 if the UI session is valid but the user lacks a minting role.
- 400 for form validation errors (missing name, no roles, invalid expiry, unknown roles). Errors shown inline on the form.
