# test_auth_e2e.py

## Purpose

End-to-end auth tests for mcp-env-mux. Starts real FastMCP backends, launches the proxy subprocess with auth config, and verifies authentication and authorization behavior over HTTP.

## Test Functions

### `test_no_auth_config_passthrough`

Without an `auth` block in config, MCP requests pass through without 401 (backward compatibility).

### `test_missing_token_returns_401`

With auth enabled, a request to `/mcp` without a Bearer token returns HTTP 401.

### `test_well_known_no_auth_required`

Discovery endpoints (`/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server`) are accessible without a token and return correct metadata.

### `test_valid_token_allows_access`

A valid JWT with the right role allows `initialize` (returns non-401 status).

## Infrastructure

Uses `conftest.py` fixtures: `start_backend`, `start_proxy`, `write_config`. Auth-specific helper `_write_auth_config` builds config with `auth` block. `keypair` fixture (module-scoped) generates an RSA key pair. `_make_token` creates test JWTs via `create_user_token`.

## Dependencies

- `conftest.start_backend`
- `conftest.start_proxy`
- `conftest.write_config`
- `mcp_env_mux.auth.keys.load_or_generate_key`
- `mcp_env_mux.auth.keys.get_public_key`
- `mcp_env_mux.auth.tokens.create_user_token`
