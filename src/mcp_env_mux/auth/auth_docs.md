# auth/

## Overview

The `auth` package adds optional authentication and authorization to mcp-env-mux. When an `auth` block is present in the config, the proxy requires JWT Bearer tokens on all MCP requests and enforces role-based access control per tool/environment. When the `auth` block is absent, the proxy operates without authentication (backward compatible).

## Module Summary

**keys.py** — RSA key management. Loads an existing PEM private key from disk or generates a new 2048-bit key. Also extracts the corresponding public key.

**tokens.py** — JWT creation. Produces RS256-signed tokens in two flavors: short-lived user tokens (1 hour default, from OAuth login) and long-lived bot tokens (configurable days, minted via UI).

**rbac.py** — Permission logic. Pure function `is_allowed` checks user roles against configured `allowed_envs` patterns using `fnmatch` glob matching. Multi-role permissions are unioned; no deny rules.

**middleware.py** — FastMCP middleware. Intercepts every `call_tool` request, extracts roles from the JWT, and calls `rbac.is_allowed`. Raises `ToolError` on denial. Passes through if the tool has no `env` parameter.

**oauth.py** — OAuth 2.1 endpoints. Implements Azure AD OIDC flow with PKCE (S256). Registers `/.well-known/*` discovery, `/auth/login`, `/auth/callback`, and `/auth/token` routes. Exchanges Azure auth codes for local JWTs.

**ui.py** — Token minting UI. HTML routes at `/ui/tokens` (GET form, POST mint) for creating bot tokens. Requires a valid JWT with a minting role.

## Data Flow

```
Browser/Client
  |
  |-- /.well-known/* --> oauth.py (discovery metadata)
  |
  |-- /auth/login -----> oauth.py --> Azure AD --> /auth/callback --> oauth.py
  |                                                (exchange Azure code, issue local code)
  |-- /auth/token -----> oauth.py --> tokens.py (mint user JWT)
  |
  |-- /mcp (tool call) --> middleware.py --> rbac.py --> is_allowed?
  |                            |                         |
  |                            | yes --> proxy handler   | no --> ToolError (403)
  |
  |-- /ui/tokens -------> ui.py --> tokens.py (mint bot JWT)
```

## Key Types (from config.py)

- **`AuthConfig`** — Top-level auth config: `azure: AzureConfig`, `signing_key_file`, `roles: dict[str, RoleConfig]`, `token_minting_roles: list[str]`, `token_max_expiry_days: int`.
- **`AzureConfig`** — Azure AD credentials: `tenant_id`, `client_id`, `client_secret`.
- **`RoleConfig`** — Per-role permissions: `allowed_envs: dict[str, list[str]]` mapping env patterns to tool patterns.

## Token Claims

Both user and bot tokens share the same claim structure:

| Claim | User Token | Bot Token |
|-------|-----------|-----------|
| `sub` | User email | Bot name |
| `type` | `"user"` | `"bot"` |
| `roles` | From Azure ID token (filtered) | Selected at mint time |
| `created_by` | Same as `sub` | Minting user's email |
| `exp` | iat + 3600s (default) | iat + N days |
| `iss` | `"mcp-env-mux"` | `"mcp-env-mux"` |
| `aud` | `"mcp-env-mux"` | `"mcp-env-mux"` |

## Error Model

- **No auth config** — All requests pass through. No middleware, no routes registered.
- **Missing/invalid JWT** — HTTP 401 from the JWT verifier (upstream of middleware).
- **Valid JWT, insufficient role** — `ToolError` raised by `RBACMiddleware` (403-style message).
- **OAuth flow errors** — HTTP 400/502 from `oauth.py` routes.
- **Minting errors** — HTTP 401/403/400 from `ui.py` routes.
