# hybrid.py

## Purpose

Provides `HybridAzureProvider`, the auth provider attached to the FastMCP
server when auth is enabled. It is a `fastmcp.server.auth.providers.azure.AzureProvider`
subclass that adds a second verification path so the same server can accept
**both** Azure-issued user tokens and locally-minted bot tokens.

## Public API

### `HybridAzureProvider(AzureProvider)`

```python
HybridAzureProvider(
    *,
    client_id: str,
    client_secret: str,
    tenant_id: str,
    base_url: str,
    required_scopes: list[str],
    local_public_key_pem: str,
    local_issuer: str = "mcp-env-mux",
    local_audience: str = "mcp-env-mux",
)
```

All `AzureProvider` keyword args are forwarded to `super().__init__`. The
`local_*` args configure the bot-token verifier.

#### `async verify_token(self, token: str) -> AccessToken | None`

Override of the parent's `verify_token`:

1. Decode `token` without verifying the signature (`pyjwt.decode(token, options={"verify_signature": False})`).
2. Read the `iss` claim.
3. If `iss == self._local_issuer`, delegate to a `JWTVerifier(public_key=local_public_key_pem, issuer=local_issuer, audience=local_audience)` (`fastmcp.server.auth.providers.jwt.JWTVerifier`). When this returns a non-None `AccessToken`, the override **replaces** its `scopes` field with the OAuth provider's `required_scopes`. Reason: bot tokens are trusted by their local RSA signature alone — a valid signature implies "may access everything the OAuth provider would normally require scopes for". This bypasses FastMCP's `insufficient_scope` 403 from the upstream bearer-auth middleware. RBAC remains the gate for fine-grained authorization.
4. Otherwise, delegate to `super().verify_token(token)` (Azure JWKS path).
5. Any exception during the iss-peek step → fall through to `super().verify_token`. Defensive: never throw out of this method; return `None` on unverifiable input.

## Why subclass

`AzureProvider` extends `OAuthProxy`, which registers all the OAuth flow
routes: `/register` (DCR proxy), `/authorize`, `/callback`, `/token`, and the
`/.well-known/*` discovery endpoints. We want all of that for free for the
interactive flow. Subclassing keeps every route and the Azure-side logic
intact while only intercepting the per-request token check.

## Dependencies

- `fastmcp.server.auth.providers.azure.AzureProvider`
- `fastmcp.server.auth.providers.jwt.JWTVerifier`
- `pyjwt` for unverified `iss` peek

## Error Handling

- Returns `None` for unverifiable tokens (consistent with FastMCP's
  TokenVerifier protocol).
- Never raises out of `verify_token`.
