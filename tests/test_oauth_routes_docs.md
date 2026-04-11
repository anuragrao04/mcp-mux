# test_oauth_routes.py

## Purpose

Unit tests for OAuth 2.1 PKCE verification and route registration smoke test in `mcp_env_mux.auth.oauth`.

## Test Classes

### `TestVerifyPKCE`

Tests the S256 PKCE `verify_pkce` function: correct verifier matches challenge, wrong verifier fails, empty verifier fails, and base64 padding is correctly stripped across multiple verifier lengths.

### `TestOAuthRouteRegistration`

Smoke test that `register_oauth_routes` can be called on a `FastMCP` server without raising. Creates a real RSA keypair and `AuthConfig` instance.

## Dependencies

- `mcp_env_mux.auth.oauth.verify_pkce`
- `mcp_env_mux.auth.oauth.register_oauth_routes`
- `mcp_env_mux.auth.keys.load_or_generate_key`
- `mcp_env_mux.auth.keys.get_public_key`
- `mcp_env_mux.config.AuthConfig`
- `mcp_env_mux.config.AzureConfig`
- `mcp_env_mux.config.RoleConfig`
