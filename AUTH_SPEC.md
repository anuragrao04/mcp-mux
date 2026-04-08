# mcp-env-mux Auth Spec

## Overview

mcp-env-mux supports two classes of clients:

- **Employee clients** (e.g. Claude Code CLI on a laptop) — authenticate via Azure AD browser-based OIDC login
- **Headless clients** (e.g. agents running in EKS) — authenticate using a long-lived token minted via the mcp-env-mux UI

All clients ultimately present a JWT as a Bearer token on every MCP request. The server verifies the JWT signature using its own public key and enforces RBAC based on the claims.

---

## Config Schema

Auth is configured under a top-level `auth` key in the existing config JSON:

```json
{
  "auth": {
    "azure": {
      "tenant_id": "...",
      "client_id": "...",
      "client_secret": "$AZURE_CLIENT_SECRET"
    },
    "signing_key_file": "/etc/mcp-mux/private.pem",
    "token_max_expiry_days": 180,
    "token_minting_roles": ["admin", "platform-engineer"],
    "roles": {
      "platform-engineer": {
        "allowed_envs": {
          "prod*":    ["logs*"],
          "prod-us*": ["deploy*", "rollback*"],
          "staging":  ["*"]
        }
      },
      "readonly": {
        "allowed_envs": {
          "*": ["logs*", "status*"]
        }
      }
    }
  },
  "environments": { "..." }
}
```

### Fields

| Field | Required | Description |
|---|---|---|
| `azure.tenant_id` | Yes | Azure AD tenant ID |
| `azure.client_id` | Yes | App Registration client ID for mcp-env-mux |
| `azure.client_secret` | Yes | Client secret (supports `$ENV_VAR` substitution) |
| `signing_key_file` | Yes | Path to RSA private key (PEM). Auto-generated on first run if missing. |
| `token_max_expiry_days` | No | Maximum allowed expiry when minting a token. Default: 180 |
| `token_minting_roles` | Yes | Users must hold at least one of these roles (from Azure AD) to access the minting UI |
| `roles` | Yes | Role definitions — see RBAC section |

---

## Authentication Flows

### Employee clients (browser-based)

Follows the MCP OAuth 2.1 discovery flow:

1. Client connects to `/mcp` without a token → `401` with `WWW-Authenticate: Bearer resource_metadata="https://<server>/.well-known/oauth-protected-resource"`
2. Client fetches `/.well-known/oauth-protected-resource` → receives JSON listing mcp-env-mux as the authorization server
3. Client fetches `/.well-known/oauth-authorization-server` → receives OAuth metadata including `authorization_endpoint` and `token_endpoint`
4. Client opens browser to `authorization_endpoint` → redirected to Azure AD for login
5. After login, Azure AD redirects to `/auth/callback` with an authorization code
6. mcp-env-mux exchanges the code with Azure AD, reads the `roles` claim, issues a signed JWT from its own key
7. Client receives the JWT at the `token_endpoint` and sends it as `Authorization: Bearer <token>` on all subsequent requests

Clients discover everything from the well-known endpoints — no hardcoded paths required.

Tokens issued via this flow have a short expiry (1 hour). Clients must re-authenticate when the token expires.

### Headless clients (long-lived token)

1. An authorized employee mints a token via the UI (see Token Minting UI section)
2. The token is provided to the headless client out-of-band (e.g. injected as a k8s secret)
3. The client sends `Authorization: Bearer <token>` on every MCP request
4. mcp-env-mux verifies the signature and enforces RBAC from the embedded claims

No Azure AD interaction happens at request time for headless clients.

---

## Token Minting UI

### Access

`GET /ui/tokens` — requires the user to be logged in via Azure AD and hold at least one role listed in `token_minting_roles`.

Employees without a qualifying role receive a `403` page.

### Minting a token

The UI presents a form with:

| Field | Description |
|---|---|
| Name | Human-readable label for the token (e.g. `prod-agent-1`) |
| Roles | Multiselect from roles defined in config |
| Expiry | Number of days until expiry (required). Must be between 1 and `token_max_expiry_days` (default: 180). |

On submission, the server issues a JWT and **displays it once**. It is not stored. The user must copy it immediately.

> **v1 scope**: minting only. No listing or revocation UI in v1.

---

## JWT Format

All JWTs issued by mcp-env-mux (both employee and headless) share the same shape:

```json
{
  "sub": "user@company.com",
  "type": "user | bot",
  "roles": ["platform-engineer", "readonly"],
  "created_by": "admin@company.com",
  "jti": "<uuid>",
  "iat": 1700000000,
  "exp": 1700003600
}
```

| Claim | Description |
|---|---|
| `sub` | For users: Azure AD email. For bots: the name given at minting time |
| `type` | `user` or `bot` |
| `roles` | List of role names from config |
| `created_by` | For bots: email of the employee who minted the token. For users: same as `sub` |
| `jti` | Unique token ID (UUID). Reserved for future revocation support |
| `iat` | Issued at (unix timestamp) |
| `exp` | Expiry (unix timestamp). Always present — bot tokens require expiry at minting time |

Tokens are signed RS256 using the key at `signing_key_file`.

---

## RBAC

### Permission model

Permissions are defined per role as a map of env patterns to tool patterns:

```json
"platform-engineer": {
  "allowed_envs": {
    "prod*":    ["logs*"],
    "prod-us*": ["deploy*", "rollback*"],
    "staging":  ["*"]
  }
}
```

**Env key matching**: both literal names and `fnmatch`-style wildcard patterns are supported (`*`, `?`, `[seq]`). `*` alone matches all envs.

**Tool value matching**: each entry in the tools list is an `fnmatch`-style pattern. `*` matches all tools.

### Multi-role union

When a user holds multiple roles, permissions are unioned:

- All env patterns across all roles are evaluated against the requested env
- All matching tool pattern lists are unioned
- If any matching rule grants `*` for tools in that env, all tools are permitted

There is no deny or override mechanic — this is a pure allowlist. A more specific pattern never restricts what a broader pattern already allows.

### Enforcement

Every tool call through `/mcp` is checked before routing:

1. Extract `roles` from the JWT
2. Determine the requested `env` and `tool` from the call arguments
3. Evaluate all role permissions — collect all env patterns that match the requested env, union their tool pattern lists
4. If the requested tool matches any pattern in the unioned list → allow. Otherwise → `403`

Requests with an invalid or expired JWT receive `401`. Requests with a valid JWT but insufficient permissions receive `403`.

---

## Endpoints

| Method | Path | Auth required | Description |
|---|---|---|---|
| `GET` | `/.well-known/oauth-protected-resource` | None | MCP OAuth discovery — lists mcp-env-mux as the authorization server |
| `GET` | `/.well-known/oauth-authorization-server` | None | OAuth 2.1 server metadata — advertises `authorization_endpoint`, `token_endpoint`, supported grant types |
| `GET` | `/auth/login` | None | Authorization endpoint — redirects to Azure AD for login |
| `GET` | `/auth/callback` | None | Azure AD callback — exchanges code, issues signed JWT |
| `POST` | `/auth/token` | None | Token endpoint — returns JWT after successful authorization code exchange |
| `GET` | `/ui/tokens` | Valid JWT + minting role | Token minting UI |
| `POST` | `/ui/tokens` | Valid JWT + minting role | Mint a new bot token; returns JWT once |
| `GET/POST` | `/mcp` | Any valid JWT | MCP endpoint — all tool calls go here |

---

## Signing Key

If `signing_key_file` does not exist at startup, mcp-env-mux generates a 2048-bit RSA key pair and writes it to that path. The public key is derived from it at runtime — no separate public key file is needed.

Rotating the signing key invalidates all previously issued tokens. There is no grace period in v1.

---

## What is NOT in scope (v1)

- Token revocation
- Token listing in UI
- Multiple simultaneous signing keys (for zero-downtime rotation)
- Per-token rate limiting
- Audit log of token usage
