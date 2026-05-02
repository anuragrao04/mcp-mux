# auth/

## Overview

The `auth` package adds optional authentication and authorization to mcp-env-mux. When an `auth` block is present in the config, the proxy requires JWT Bearer tokens on all MCP requests and enforces role-based access control per tool/environment. When the `auth` block is absent, the proxy operates without authentication (backward compatible).

> **See `/AUTH_DESIGN.md` at the repo root** for the auth architecture reference. This file summarizes the module layout.

## Two token types

| Token | Issuer | Used by | Verified by |
|---|---|---|---|
| **User** | Microsoft Entra ID | Interactive OAuth/MCP clients; browser login for `/ui/*` | Azure JWKS, via `HybridAzureProvider`'s parent `AzureProvider` and Azure token validation |
| **Bot** | mcp-env-mux itself (RS256, local key) | Headless agents | Local `JWTVerifier`, via `HybridAzureProvider`'s local-verifier branch |

For `/mcp`, both are presented as `Authorization: Bearer <token>` and dispatch is based on the `iss` claim.
For `/ui/*`, humans authenticate through Azure and receive a short-lived signed UI session cookie.

## Module Summary

**hybrid.py** — `HybridAzureProvider`. Subclass of `fastmcp.server.auth.providers.azure.AzureProvider`. Inherits the full Azure OAuth flow (DCR proxy, login, callback, token endpoint, all `/.well-known/*` discovery routes, JWKS-based JWT verification). Adds a `verify_token` override that routes tokens whose `iss == "mcp-env-mux"` to a local `JWTVerifier` configured with the bot-signing public key. Also exposes UI helpers for starting and completing the browser login flow used by `/ui/login` and `/ui/callback`, including provider transaction storage, Azure authorize URL construction, token exchange, and Azure claim extraction.

**keys.py** — RSA key management. Loads an existing PEM private key from disk or generates a new 2048-bit key. Used for **bot tokens only**.

**tokens.py** — JWT creation for **bot tokens only**. RS256-signed long-lived JWTs (configurable days, minted via UI). User tokens are issued by Azure.

**rbac.py** — Permission logic. Pure function `is_allowed` checks user roles against configured `allowed_envs` patterns using `fnmatch` glob matching. Multi-role permissions are unioned; no deny rules.

**middleware.py** — FastMCP middleware. Intercepts every `call_tool` request, reads roles from `get_access_token().claims["roles"]`, and calls `rbac.is_allowed`. Raises `ToolError` on denial. Passes through if the tool has no `env` parameter.

**ui.py** — Token minting UI. HTML routes at `/ui/login`, `/ui/callback`, `/ui/tokens`, and `/ui/logout`. Humans authenticate through Azure and the app establishes a short-lived signed UI login/session flow for browser use. `ui.py` handles browser-specific concerns: safe `next` handling, a short-lived signed UI login cookie, a short-lived signed UI session cookie, logout, and minting-role checks.

## Data Flow

```
Browser/Claude Code (interactive)
  |
  |-- /.well-known/oauth-protected-resource[/mcp] --> AzureProvider (built-in)
  |-- /.well-known/oauth-authorization-server     --> AzureProvider (advertises DCR)
  |-- /register, /authorize, /callback, /token    --> AzureProvider DCR proxy + Azure
  |-- /mcp (tool call)
  |     Authorization: Bearer <Azure access token>
  |     -> HybridAzureProvider.verify_token (delegates to super → Azure JWKS)
  |     -> RBACMiddleware.on_call_tool -> rbac.is_allowed
  |     -> proxy handler

Bot (headless)
  |
  |-- /mcp (tool call)
  |     Authorization: Bearer <bot JWT>  (iss=mcp-env-mux, signed by local RSA)
  |     -> HybridAzureProvider.verify_token (iss match → local JWTVerifier)
  |     -> RBACMiddleware.on_call_tool -> rbac.is_allowed
  |     -> proxy handler

Admin minting a bot token
  |
  |-- /ui/login -> Azure authorize
  |-- /ui/callback -> exchange Azure code, validate claims, set UI session cookie
  |-- /ui/tokens
  |     cookie: mcp_env_mux_ui_session=<signed session>
  |     -> ui resolves subject + roles from signed UI session
  |     -> if roles ∩ token_minting_roles is non-empty: render form / mint
  |     -> tokens.create_bot_token (RS256 with local private key)
```

## Key Types (from config.py)

- **`AuthConfig`** — Top-level: `azure: AzureConfig`, `base_url: str`, `required_scopes: list[str]`, `signing_key_file: str`, `roles: dict[str, RoleConfig]`, `token_minting_roles: list[str]`, `token_max_expiry_days: int`.
- **`AzureConfig`** — `tenant_id`, `client_id`, `client_secret`.
- **`RoleConfig`** — `allowed_envs: dict[str, list[str]]` mapping env patterns to tool patterns.

## Token Claims

| Claim | User Token (Azure-issued) | Bot Token (locally minted) |
|-------|---------------------------|----------------------------|
| `sub` | Azure user object ID | Bot name |
| `preferred_username` / `email` | User's UPN / email | not present |
| `roles` | Azure App Roles assigned to the user | Roles selected at mint time |
| `iss` | `https://login.microsoftonline.com/{tenant}/v2.0` | `"mcp-env-mux"` |
| `aud` | `api://{client_id}` (or `{client_id}`) | `"mcp-env-mux"` |
| `exp` | Azure default (~1h) | iat + N days |

## Error Model

- **No auth config** — All requests pass through. No middleware, no provider attached.
- **Missing/invalid Bearer** — HTTP 401 from FastMCP (the auth provider rejects).
- **Valid token, insufficient role** — `ToolError` raised by `RBACMiddleware`.
- **UI: no valid session** — redirect to `/ui/login` from `ui.py`.
- **UI: callback state/code failure** — HTTP 400/500 HTML error page from `ui.py`.
- **UI: valid session, no minting role** — HTTP 403 from `ui.py`.
- **UI: form validation** — HTTP 400 with errors re-rendered inline.
