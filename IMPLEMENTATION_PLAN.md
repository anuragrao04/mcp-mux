# Auth + RBAC Implementation Plan for mcp-env-mux

## Context

mcp-env-mux is a Python MCP proxy (FastMCP >=2.0.0) that merges tool schemas from multiple backend environments into a single endpoint. It currently has no authentication or authorization — any client can call any tool in any environment. AUTH_SPEC.md defines the desired external behavior: Azure AD OIDC for employees, long-lived tokens for headless agents, and fnmatch-based RBAC. This plan implements that spec while keeping auth **optional** (no `auth` key in config = no auth, existing tests pass unchanged).

### Key correction to AUTH_SPEC.md

The spec's OAuth flow description is broadly correct, but the implementation should use **FastMCP's built-in auth primitives** rather than building everything from scratch:
- **`JWTVerifier`** (`from fastmcp.server.auth import JWTVerifier`) handles Bearer token verification on `/mcp` automatically (401 for missing/invalid)
- **`@mcp.custom_route()`** for OAuth endpoints and minting UI (these are NOT behind MCP auth)
- **`Middleware` subclass** (`from fastmcp.server.middleware import Middleware, MiddlewareContext`) for RBAC enforcement on tool calls
- We use `cryptography` + `PyJWT` directly (not `RSAKeyPair`) for full control over custom JWT claims

The spec's well-known endpoint paths and OAuth flow are correct for MCP OAuth 2.1 compliance.

---

## New Dependencies (pyproject.toml)

```toml
"cryptography>=42.0"   # RSA key generation/loading
"PyJWT[crypto]>=2.8"   # JWT creation with custom claims
```
(`httpx` is already a transitive dep of `fastmcp` but promote to explicit runtime dep)

---

## Phase 1: Config Schema + Signing Key Management

**Files:** `src/mcp_env_mux/config.py` (modify), `src/mcp_env_mux/auth/__init__.py` (new), `src/mcp_env_mux/auth/keys.py` (new)

### config.py — add dataclasses

```python
@dataclass
class AzureConfig:
    tenant_id: str
    client_id: str
    client_secret: str  # supports $ENV_VAR via existing resolve_env_vars

@dataclass
class RoleConfig:
    allowed_envs: dict[str, list[str]]  # env_pattern -> [tool_patterns]

@dataclass
class AuthConfig:
    azure: AzureConfig
    signing_key_file: str
    roles: dict[str, RoleConfig]
    token_minting_roles: list[str]
    token_max_expiry_days: int = 180

# Extend existing Config:
@dataclass
class Config:
    environments: dict[str, EnvironmentConfig]
    auth: AuthConfig | None = None  # None = auth disabled
```

In `load_config`: parse `auth` block if present, validate required fields, resolve `$ENV_VAR` in `azure.client_secret`. Reuse existing `resolve_env_vars()`.

### auth/keys.py

- `load_or_generate_key(path: str) -> rsa.RSAPrivateKey` — load PEM if exists, else generate 2048-bit RSA, write to path (create parent dirs), return key
- `get_public_key(private_key) -> rsa.RSAPublicKey` — `private_key.public_key()`

---

## Phase 2: JWT Issuance

**Files:** `src/mcp_env_mux/auth/tokens.py` (new)

Two functions using PyJWT (not `RSAKeyPair.create_token` — we need custom claims):

- `create_user_token(private_key, subject, roles, expiry_seconds=3600) -> str`
  - Claims: `sub`, `type: "user"`, `roles`, `created_by` (=sub), `jti` (uuid4), `iat`, `exp`, `iss: "mcp-env-mux"`, `aud: "mcp-env-mux"`
- `create_bot_token(private_key, name, roles, created_by, expiry_days) -> str`
  - Claims: `sub` (=name), `type: "bot"`, `roles`, `created_by`, `jti`, `iat`, `exp` (=iat + days*86400), `iss`, `aud`

Both sign RS256. The `iss`/`aud` claims are additions over AUTH_SPEC — needed for `JWTVerifier` validation.

---

## Phase 3: OAuth Endpoints (custom routes)

**Files:** `src/mcp_env_mux/auth/oauth.py` (new)

Exports: `register_oauth_routes(server: FastMCP, auth_config: AuthConfig, private_key)`

All registered via `@server.custom_route(...)` — these are plain HTTP routes, NOT behind MCP auth.

### Endpoints

| Route | Method | Description |
|-------|--------|-------------|
| `/.well-known/oauth-protected-resource` | GET | MCP OAuth discovery — lists self as auth server |
| `/.well-known/oauth-authorization-server` | GET | OAuth 2.1 metadata (authorization_endpoint, token_endpoint, etc.) |
| `/auth/login` | GET | Stores PKCE params, redirects to Azure AD |
| `/auth/callback` | GET | Exchanges Azure AD code, stores our auth code, redirects to client |
| `/auth/token` | POST | Verifies PKCE, issues JWT, returns `{access_token, token_type}` |

### State management

In-memory dicts with TTL cleanup (acceptable for v1 single-process):
- `_pending_auths: dict[nonce, PendingAuth]` — stores redirect_uri, client_state, code_challenge
- `_auth_codes: dict[code, AuthCodeData]` — stores email, roles, code_challenge, created_at

### Azure AD interaction

- `/auth/login` → redirect to `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize`
- `/auth/callback` → POST to `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token` with httpx, extract email + roles from ID token

### PKCE verification

```python
def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return computed == code_challenge
```

---

## Phase 4: RBAC (can parallelize with Phase 3)

**Files:** `src/mcp_env_mux/auth/rbac.py` (new), `src/mcp_env_mux/auth/middleware.py` (new)

### rbac.py — pure logic, no server deps

```python
def is_allowed(
    user_roles: list[str],
    role_definitions: dict[str, RoleConfig],
    requested_env: str,
    requested_tool: str,
) -> bool:
```

Logic: for each user role → for each env pattern in role's `allowed_envs` → if `fnmatch(requested_env, pattern)` → union tool patterns. Then check `fnmatch(requested_tool, any_pattern)`.

### middleware.py — FastMCP Middleware subclass

```python
class RBACMiddleware(Middleware):
    def __init__(self, role_definitions: dict[str, RoleConfig]):
        self.role_definitions = role_definitions

    async def on_message(self, context: MiddlewareContext, call_next):
        # Intercept tools/call, extract env+tool from arguments
        # Get roles from JWT claims (via context or request.state)
        # Call is_allowed() → raise error or pass through
```

**Risk: accessing JWT claims from middleware.** If `JWTVerifier` doesn't expose claims to `MiddlewareContext`, fallback is:
1. Starlette-level ASGI middleware that decodes JWT with PyJWT and stores claims in `request.state`
2. Worst case: inline RBAC check in `_make_handler` in proxy.py

---

## Phase 5: Token Minting UI

**Files:** `src/mcp_env_mux/auth/ui.py` (new)

Exports: `register_ui_routes(server: FastMCP, auth_config: AuthConfig, private_key, public_key)`

### Endpoints

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/ui/tokens` | GET | JWT + minting role | HTML form (name, roles checkboxes, expiry) |
| `/ui/tokens` | POST | JWT + minting role | Mint bot token, display once |

Auth check: extract Bearer token from header, decode with PyJWT, verify user holds a role in `token_minting_roles`. Return 401/403 HTML if not.

HTML: inline f-string templates (no template engine for v1).

---

## Phase 6: Integration

**Files:** `src/mcp_env_mux/proxy.py` (modify), `src/mcp_env_mux/cli.py` (modify)

### proxy.py

```python
def create_proxy_server(
    merged_tools: list[MergedTool],
    clients: dict[str, Any],
    auth_config: AuthConfig | None = None,  # NEW
    private_key=None,                        # NEW
    public_key=None,                         # NEW
) -> FastMCP:
    if auth_config:
        from fastmcp.server.auth import JWTVerifier
        auth = JWTVerifier(public_key=public_key, issuer="mcp-env-mux", audience="mcp-env-mux")
        server = FastMCP("mcp-env-mux", auth=auth)
        register_oauth_routes(server, auth_config, private_key)
        register_ui_routes(server, auth_config, private_key, public_key)
        server.add_middleware(RBACMiddleware(auth_config.roles))
    else:
        server = FastMCP("mcp-env-mux")
    # ... register tools as before ...
```

### cli.py

```python
async def _run(args):
    config = load_config(Path(args.config))

    # NEW: auth setup
    private_key = public_key = None
    if config.auth:
        from mcp_env_mux.auth.keys import load_or_generate_key, get_public_key
        private_key = load_or_generate_key(config.auth.signing_key_file)
        public_key = get_public_key(private_key)

    # ... existing discovery + merge ...

    server = create_proxy_server(
        result.tools, clients,
        auth_config=config.auth, private_key=private_key, public_key=public_key,
    )
    await server.run_http_async(host=args.host, port=args.port)
```

**Backward compat guarantee:** No `auth` key → `config.auth is None` → no auth code runs → all existing tests pass unchanged.

---

## Phase 7: Tests

### New test files

| File | What it tests | Key cases |
|------|---------------|-----------|
| `tests/test_auth_config.py` | Config parsing | Valid auth block, missing fields, $ENV_VAR resolution, backward compat (no auth key) |
| `tests/test_keys.py` | Key management | Auto-generate, load existing, parent dir creation |
| `tests/test_tokens.py` | JWT creation | All claims present, correct types, unique jti, expiry math |
| `tests/test_rbac.py` | Permission logic | Exact match, glob patterns, wildcards, multi-role union, deny cases, unknown roles |
| `tests/test_oauth_routes.py` | OAuth endpoints | Well-known responses, login redirect, PKCE verification |
| `tests/test_auth_e2e.py` | Full integration | Unauth→401, valid JWT→success, bad RBAC→403, expired→401, no-auth config→passthrough |

### conftest.py additions

- `generate_test_keypair()` → `(private_key, public_key)`
- `create_test_token(private_key, roles, ...)` → JWT string
- `write_auth_config(environments, auth_block, tmpdir)` → config Path

---

## Dependency Graph

```
Phase 1 (Config + Keys)
    ↓
Phase 2 (JWT Tokens)
    ↓
   ┌────────┴────────┐
Phase 3 (OAuth)   Phase 4 (RBAC)    ← can parallelize
   └────────┬────────┘
    ↓
Phase 5 (Minting UI)
    ↓
Phase 6 (Integration)
    ↓
Phase 7 (E2E Tests)
```

Unit tests for each phase can be written alongside that phase.

---

## Open Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| JWT claims not accessible from MCP Middleware | RBAC can't read roles | Fallback: Starlette ASGI middleware decodes JWT into `request.state`, or inline RBAC in `_make_handler` |
| In-memory OAuth state lost on restart | Pending logins fail | Acceptable for v1 single-process; document limitation |
| Azure AD role claim name varies | Wrong roles extracted | Make claim name configurable in AzureConfig (default: `roles`) |
| FastMCP `JWTVerifier` API differs from docs | Auth setup fails | Verify import paths early in Phase 6; fallback to manual Starlette auth middleware |

---

## Verification

1. **Unit tests:** `pytest tests/test_auth_config.py tests/test_keys.py tests/test_tokens.py tests/test_rbac.py` — all pass
2. **Existing tests:** `pytest tests/test_config.py tests/test_merge.py tests/test_proxy.py` — still pass (backward compat)
3. **Integration:** Start server with auth config, verify:
   - `GET /.well-known/oauth-protected-resource` → 200 JSON
   - `GET /mcp` without token → 401
   - `GET /mcp` with valid JWT + permitted role → tool call succeeds
   - `GET /mcp` with valid JWT + wrong role → 403
4. **No-auth mode:** Start server without `auth` in config → all requests pass through as before
