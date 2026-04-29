# test_auth_e2e.py

## Purpose

End-to-end auth tests for mcp-env-mux. Starts real FastMCP backends, launches the proxy subprocess with auth config (using a `HybridAzureProvider` whose Azure-side `verify_token` is monkey-patched to avoid real network calls), and verifies authentication, RBAC, and the bot-token minting UI over HTTP.

## Test Functions

### `test_no_auth_config_passthrough`

Without an `auth` block in config, MCP requests pass through without 401 (backward compatibility).

### `test_missing_token_returns_401`

With auth enabled, a request to `/mcp` without a Bearer token returns HTTP 401.

### `test_well_known_endpoints_advertise_dcr`

Both `/.well-known/oauth-protected-resource` **and** `/.well-known/oauth-protected-resource/mcp` return 200 (path-prefixed discovery is wired). `/.well-known/oauth-authorization-server` returns metadata that contains a `registration_endpoint` field — proves DCR proxy is enabled.

### `test_bot_token_allows_access`

A bot JWT minted with `create_bot_token` and the right roles allows `initialize` (returns non-401 status). Verifies the local-verifier branch of `HybridAzureProvider`.

### `test_bot_token_wrong_role_returns_403`

A bot JWT whose roles do not satisfy any `allowed_envs` rule for the requested env/tool causes the call to fail with a `ToolError` (RBAC denial).

### `test_ui_requires_token`

`GET /ui/tokens` without a Bearer returns 401.

### `test_ui_requires_minting_role`

`GET /ui/tokens` with a bot token that lacks any `token_minting_roles` entry returns 403.

### `test_ui_mints_bot_token`

`POST /ui/tokens` with a minting-role bot token returns 200 and the response body contains a JWT whose decoded claims match the form input (name → `sub`, selected roles → `roles`, expiry math correct).

## Infrastructure

Uses `conftest.py` fixtures: `start_backend`, `start_proxy`, `write_config`. Auth-specific helper `_write_auth_config` builds config with `auth` block (including `base_url` and `required_scopes`). `keypair` fixture (module-scoped) generates an RSA key pair. `_make_bot_token` creates test bot JWTs via `create_bot_token`.

For tests that need to bypass real Azure verification, the test patches `HybridAzureProvider.verify_token`'s super path (the Azure JWKS check) to return a stub `AccessToken`. Bot-token tests do not need this patch — they exercise the local-verifier branch directly.

## Dependencies

- `conftest.start_backend`
- `conftest.start_proxy`
- `conftest.write_config`
- `mcp_env_mux.auth.keys.load_or_generate_key`
- `mcp_env_mux.auth.keys.get_public_key`
- `mcp_env_mux.auth.tokens.create_bot_token`
- `mcp_env_mux.auth.hybrid.HybridAzureProvider`
