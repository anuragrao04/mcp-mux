# oauth.py

## Purpose

OAuth 2.1 endpoints for mcp-env-mux implementing Azure AD OIDC flow with PKCE (S256). Registers discovery, login, callback, and token exchange routes on the FastMCP server.

## Public API

### `register_oauth_routes(server: FastMCP, auth_config: AuthConfig, private_key: Any) -> None`

Registers all OAuth 2.1 and discovery routes on the FastMCP server:

**`GET /.well-known/oauth-protected-resource`** — Returns resource metadata: `resource`, `authorization_servers`, `bearer_methods_supported`, `resource_documentation`.

**`GET /.well-known/oauth-authorization-server`** — Returns authorization server metadata: `issuer`, `authorization_endpoint`, `token_endpoint`, `response_types_supported` (code), `grant_types_supported` (authorization_code), `code_challenge_methods_supported` (S256), `token_endpoint_auth_methods_supported` (none).

**`GET /auth/login`** — Initiates the OAuth flow. Accepts `redirect_uri`, `state`, `code_challenge`, `code_challenge_method` (must be S256). Stores pending auth state with a nonce, redirects the browser to Azure AD's `/oauth2/v2.0/authorize` endpoint. Scopes: `openid email profile`.

**`GET /auth/callback`** — Azure AD redirects here after login. Exchanges the Azure auth code for an ID token via Azure's token endpoint. Extracts email and roles from the ID token, filters to roles known in `auth_config.roles`, generates a local auth code, and redirects back to the client's `redirect_uri` with `code` and `state`.

**`POST /auth/token`** — Client exchanges the local auth code for a JWT. Requires `grant_type=authorization_code`, `code`, and `code_verifier`. Verifies PKCE (S256), then mints a user JWT via `create_user_token`. Returns `access_token`, `token_type`, `expires_in`.

### `verify_pkce(code_verifier: str, code_challenge: str) -> bool`

Verifies that `code_verifier` hashes (SHA-256, base64url-encoded, padding stripped) to `code_challenge`.

## Internal State

- `_pending_auths: dict[str, _PendingAuth]` — In-memory map of nonce → pending auth data (redirect_uri, client_state, code_challenge). Cleaned on each login/callback.
- `_auth_codes: dict[str, _AuthCodeData]` — In-memory map of auth code → user data (email, roles, code_challenge). Cleaned on each login/callback.
- `_CODE_TTL_SECONDS = 600` — Both pending auths and auth codes expire after 10 minutes.

## Data Flow

```
Client                    mcp-env-mux                    Azure AD
  |                           |                              |
  |-- GET /auth/login ------->|                              |
  |                           |-- 302 to Azure /authorize -->|
  |                           |                              |
  |                           |<-- GET /auth/callback -------|
  |                           |-- POST Azure /token -------->|
  |                           |<-- id_token -----------------|
  |<-- 302 with code ---------|                              |
  |                           |                              |
  |-- POST /auth/token ------>|                              |
  |<-- { access_token } ------|                              |
```

## Dependencies

- `httpx` for async HTTP calls to Azure token endpoint
- `jwt` (PyJWT) for decoding Azure ID tokens (without signature verification)
- `mcp_env_mux.auth.tokens.create_user_token`
- `mcp_env_mux.config.AuthConfig`
- `starlette` for Request/Response types

## Error Handling

- Returns HTTP 400 for: non-S256 challenge method, Azure AD error, missing code/state, invalid/expired state, unsupported grant type, missing code, invalid grant, expired code, PKCE failure.
- Returns HTTP 502 for: Azure token exchange failure, ID token decode failure.
- Expired entries cleaned lazily via `_cleanup_expired()` on each login and callback.
