# mcp-env-mux Auth Design (post-rework)

> **Status**: Authoritative spec for the auth rework that drops the hand-rolled
> OAuth implementation in favor of FastMCP's native `AzureProvider`.
> All agents and reviewers must follow this document.

## Why this rework

The previous implementation hand-rolled OAuth 2.1 endpoints in
`auth/oauth.py` (266 LOC). Failures observed in the wild:

1. `/.well-known/oauth-authorization-server` did not advertise a
   `registration_endpoint` → Claude Code reported
   `Incompatible auth server: does not support dynamic client registration`.
2. `/.well-known/oauth-protected-resource/mcp` returned 404 (only the
   un-suffixed path was registered) — RFC 9728 mandates path-prefixed
   discovery for non-root resources.
3. ~600 LOC of bespoke OAuth that FastMCP already provides natively.

FastMCP's `AzureProvider` (subclass of `OAuthProxy`) handles MS Entra ID
correctly out of the box: tenant-aware JWKS, Azure v2 token format,
`registration_endpoint` advertised via the local DCR proxy, all path-prefixed
discovery routes registered automatically.

## Two token types

Both are JWTs presented as `Authorization: Bearer <token>`. The server must
accept either.

| Token type | Issued by | Issuer (`iss`) | Audience (`aud`) | Signed with | Lifetime |
|---|---|---|---|---|---|
| **User** (interactive) | Microsoft Entra ID | `https://login.microsoftonline.com/{tenant}/v2.0` | `api://{client_id}` (or `{client_id}`) | Azure JWKS | Azure default (~1h) |
| **Bot** (headless) | mcp-env-mux itself | `mcp-env-mux` | `mcp-env-mux` | Local RSA private key (RS256) | Configurable, up to `token_max_expiry_days` |

User tokens flow: Claude Code → AzureProvider's DCR/login flow → Azure → token presented to `/mcp`.
Bot tokens flow: Admin user opens `/ui/tokens` (with their user token) → fills form → server mints a bot token → bot presents it on every request.

## Verification: HybridAzureProvider

The auth provider passed to `FastMCP(auth=...)` is **`HybridAzureProvider`** — a
subclass of `AzureProvider` that adds a second verification path for bot
tokens.

```python
class HybridAzureProvider(AzureProvider):
    """AzureProvider that also accepts locally-minted bot tokens.

    Inherits the full Azure OAuth flow (DCR proxy, login, callback, token
    endpoint, discovery routes, JWKS-based JWT verification). Adds a dispatch
    in verify_token() that routes tokens with iss == "mcp-env-mux" to a local
    JWTVerifier configured with the bot-signing public key.
    """

    def __init__(
        self,
        *args,
        local_public_key_pem: str,
        local_issuer: str = "mcp-env-mux",
        local_audience: str = "mcp-env-mux",
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        from fastmcp.server.auth.providers.jwt import JWTVerifier
        self._local_verifier = JWTVerifier(
            public_key=local_public_key_pem,
            issuer=local_issuer,
            audience=local_audience,
        )
        self._local_issuer = local_issuer

    async def verify_token(self, token: str):
        # Peek iss without verifying signature
        try:
            import jwt as pyjwt
            unverified = pyjwt.decode(token, options={"verify_signature": False})
            iss = unverified.get("iss", "")
        except Exception:
            iss = ""

        if iss == self._local_issuer:
            access_token = await self._local_verifier.verify_token(token)
            if access_token is None:
                return None
            # Bot tokens are locally-trusted by their RSA signature alone.
            # Grant the OAuth provider's required scopes so FastMCP's upstream
            # BearerAuth middleware does not reject with "insufficient_scope".
            granted = list(self.required_scopes or [])
            if granted:
                return access_token.model_copy(update={"scopes": granted})
            return access_token
        return await super().verify_token(token)
```

> **Bot scope grant**: Bot tokens carry no `scope`/`scp` claim. FastMCP's
> bearer-auth middleware enforces `OAuthProvider.required_scopes` against
> `AccessToken.scopes` and returns 403 `insufficient_scope` on mismatch.
> Because a valid local RSA signature is the trust anchor for bots, we
> override the resulting AccessToken's `scopes` to the provider's required
> scopes. Effectively: "valid bot signature → all scopes the OAuth provider
> needs". RBAC remains the only authorization gate.

Lives at `src/mcp_env_mux/auth/hybrid.py`.

## Config schema

```jsonc
{
  "auth": {
    "azure": {
      "tenant_id": "...",
      "client_id": "...",
      "client_secret": "$AZURE_CLIENT_SECRET"
    },
    "base_url": "http://localhost:8080",          // NEW — required by AzureProvider
    "required_scopes": ["access_as_user"],        // NEW — must match Azure app exposed scope
    "signing_key_file": "/etc/mcp-mux/private.pem",
    "token_max_expiry_days": 180,
    "token_minting_roles": ["admin"],
    "roles": {
      "admin": { "allowed_envs": { "*": ["*"] } }
    }
  }
}
```

### Field changes

| Field | Status | Notes |
|---|---|---|
| `auth.azure.tenant_id` | unchanged | |
| `auth.azure.client_id` | unchanged | |
| `auth.azure.client_secret` | unchanged | `$VAR` substitution still supported |
| `auth.base_url` | **NEW, required** | Must match Azure app redirect URI prefix (e.g. `http://localhost:8080`). AzureProvider appends `/auth/callback` itself. |
| `auth.required_scopes` | **NEW, required** | At least one custom scope defined under "Expose an API" in Azure. Used in upstream authorize request. |
| `auth.signing_key_file` | unchanged | RSA key for **bot** tokens only |
| `auth.token_minting_roles` | unchanged | |
| `auth.token_max_expiry_days` | unchanged | |
| `auth.roles` | unchanged | |

## Azure App Registration setup (operator action)

1. App registration → Web platform → redirect URI = `<base_url>/auth/callback`.
2. Expose an API → set Application ID URI to `api://{client_id}`.
3. Add scope (e.g. `access_as_user`).
4. App roles → define roles matching `auth.roles` keys (e.g. `admin`,
   `readonly`). Assign users via Enterprise Applications → Users and groups.
5. Manifest → set `"requestedAccessTokenVersion": 2`.
6. Create client secret.

## Server wiring

`src/mcp_env_mux/proxy.py::create_proxy_server` becomes:

```python
def create_proxy_server(
    merged_tools: list[MergedTool],
    clients: dict[str, Any],
    auth_config: AuthConfig | None = None,
    private_key: Any = None,
    public_key: Any = None,
) -> FastMCP:
    if auth_config is None:
        # Auth disabled — backward compat for tests
        server = FastMCP("mcp-env-mux")
    else:
        from cryptography.hazmat.primitives import serialization
        from mcp_env_mux.auth.hybrid import HybridAzureProvider
        from mcp_env_mux.auth.middleware import RBACMiddleware
        from mcp_env_mux.auth.ui import register_ui_routes

        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        auth = HybridAzureProvider(
            client_id=auth_config.azure.client_id,
            client_secret=auth_config.azure.client_secret,
            tenant_id=auth_config.azure.tenant_id,
            base_url=auth_config.base_url,
            required_scopes=auth_config.required_scopes,
            local_public_key_pem=public_key_pem,
        )
        server = FastMCP("mcp-env-mux", auth=auth)

        register_ui_routes(server, auth_config, private_key, auth)
        server.add_middleware(RBACMiddleware(auth_config.roles))

    # ... tool registration unchanged
```

No more `register_oauth_routes`. AzureProvider handles all OAuth/discovery routes.

## RBAC middleware (`auth/middleware.py`)

Source of roles changes per token type:

- **Bot token claims** — `roles` claim is the list of roles assigned at mint time.
- **Azure user token claims** — `roles` claim holds Azure App Roles assigned to the user.

Both reachable via `get_access_token().claims["roles"]`. The middleware should rely on this single path (drop the JWT-decode-from-header fallback — it was a workaround for buggy fastmcp v2 plumbing and is no longer needed).

```python
async def on_call_tool(self, context, call_next):
    tool_name = context.message.name
    arguments = getattr(context.message, "arguments", None) or {}
    env = arguments.get("env")
    if env is None:
        return await call_next(context)

    from fastmcp.server.dependencies import get_access_token
    token = get_access_token()
    roles = token.claims.get("roles", []) if token else []

    if not is_allowed(roles, self.role_definitions, env, tool_name):
        from fastmcp.exceptions import ToolError
        raise ToolError(
            f"Access denied: role does not permit calling tool {tool_name!r} "
            f"in environment {env!r}"
        )
    return await call_next(context)
```

## Bot token minting UI (`auth/ui.py`)

Remains in place — this is one of the things we explicitly keep. Changes:

1. UI routes are Starlette custom routes; FastMCP middleware does **not** run on them. They must verify the bearer themselves.
2. Receive the `HybridAzureProvider` instance (not a raw public key) and call
   `await auth_provider.verify_token(token)` — this accepts both Azure-issued
   user tokens and locally-minted bot tokens, so admins can access the UI
   using their normal Azure session.
3. Get the subject from `access_token.client_id` (or `claims["sub"]` /
   `claims["preferred_username"]` for Azure tokens).

```python
async def _verify_minting_access(token, auth_provider, auth_config):
    access_token = await auth_provider.verify_token(token)
    if access_token is None:
        return None
    claims = access_token.claims
    roles = claims.get("roles", [])
    if not any(r in auth_config.token_minting_roles for r in roles):
        return None
    subject = (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("sub", "unknown")
    )
    return subject, roles
```

## Files removed

- `src/mcp_env_mux/auth/oauth.py`
- `src/mcp_env_mux/auth/oauth_docs.md`
- `tests/test_oauth_routes.py`
- `tests/test_oauth_routes_docs.md`

## Files added

- `src/mcp_env_mux/auth/hybrid.py` — `HybridAzureProvider`
- `src/mcp_env_mux/auth/hybrid_docs.md`
- `tests/test_hybrid.py` — unit tests for the dispatch logic
- `AUTH_DESIGN.md` — this doc

## Files modified

| File | Change |
|---|---|
| `src/mcp_env_mux/proxy.py` | Use `HybridAzureProvider`; drop `register_oauth_routes` |
| `src/mcp_env_mux/cli.py` | No structural change (private/public key still loaded; pass through to proxy) |
| `src/mcp_env_mux/config.py` | `AuthConfig` gains `base_url: str`, `required_scopes: list[str]`; parse + validate them; require both |
| `src/mcp_env_mux/auth/middleware.py` | Drop the manual JWT-decode fallback; rely solely on `get_access_token()` |
| `src/mcp_env_mux/auth/ui.py` | Replace `_verify_minting_access` to use the auth provider's `verify_token` |
| `src/mcp_env_mux/auth/tokens.py` | **Remove `create_user_token`**; only `create_bot_token` remains |
| `src/mcp_env_mux/auth/keys.py` | Unchanged |
| `src/mcp_env_mux/auth/rbac.py` | Unchanged |
| `tests/test_auth_config.py` | Add tests for `base_url`, `required_scopes`; require both |
| `tests/test_tokens.py` | Drop user-token tests |
| `tests/test_auth_e2e.py` | Replace OAuth-flow assertions with `HybridAzureProvider` discovery checks + bot-token-on-/mcp checks |
| `tests/conftest.py` | Add a fixture that constructs an `HybridAzureProvider` with a mocked Azure JWKS / verify path so tests don't hit the network |
| `tests/test_rbac.py` | Unchanged |
| `tests/test_keys.py` | Unchanged |

## Test strategy

- **Unit**: `test_hybrid.py` constructs a `HybridAzureProvider` with a stub `super().verify_token` and a real local `JWTVerifier`. Assert that:
  - Bot token (`iss=mcp-env-mux`, valid local sig) → returns AccessToken from local verifier.
  - Bot token with bad sig → returns `None`.
  - Token with `iss` matching Azure tenant → routed to `super().verify_token` (mock and assert call).
  - Garbage token → `None`.
- **Integration**: `test_auth_e2e.py` boots a proxy with auth enabled, monkey-patches `HybridAzureProvider.verify_token` (or the underlying `super().verify_token`) to bypass the real Azure call. Verifies:
  - `/.well-known/oauth-protected-resource/mcp` returns 200 with correct metadata.
  - `/.well-known/oauth-authorization-server` advertises a `registration_endpoint` (DCR proxy is wired).
  - `POST /mcp` with no token → 401.
  - `POST /mcp` with a valid bot token but RBAC-denied env/tool → ToolError.
  - `POST /mcp` with a valid bot token + permitted role → 200 and call routed.
  - `GET /ui/tokens` with no token → 401.
  - `GET /ui/tokens` with a non-minting-role token → 403.
  - `POST /ui/tokens` with a minting-role bot token → returns a new bot token whose claims match the form input.

## What stays the same

- Bot token JWT format, claims, signing key handling, mint flow.
- RBAC permission model (`fnmatch` env/tool patterns).
- Backward compatibility: if `auth` block is absent from config, the proxy runs with no auth at all (existing tests rely on this).
- CLI flags and behavior.
