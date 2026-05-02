# mcp-env-mux

Merge multiple instances of the same MCP server across environments into a single endpoint with a unified `env` parameter.

## Problem

When you connect the same MCP server (e.g., Coralogix, Datadog) from multiple environments (prod, staging, dev), each instance exposes identical tool definitions. Your MCP client sees every tool duplicated per environment, wasting context window tokens and creating a confusing tool list.

## Solution

mcp-env-mux sits in front of your MCP backends as a proxy. It discovers tools from each backend, merges identical definitions into a single tool with an injected `env` parameter, and routes calls to the correct backend based on the caller's `env` selection. One tool instead of N copies.

## Quick Start

### Without auth

```bash
# Install
pip install -e .

# Set your API keys as environment variables
export BACKEND_PROD_API_KEY="your-prod-key"
export BACKEND_STAGING_API_KEY="your-staging-key"

# Create a config file (see Configuration below)

# Validate your config and check for schema mismatches
mcp-env-mux --config config.json --test-schema

# Start the proxy
mcp-env-mux --config config.json
```

### With auth enabled

```bash
# Optional: set Azure client secret via env var
export AZURE_CLIENT_SECRET="your-azure-client-secret"

# Start the proxy with an auth-enabled config
mcp-env-mux --config config.json
```

When the `auth` block is present in the config, the proxy enables JWT Bearer auth, OAuth login routes, RBAC enforcement for tool calls, and a UI for minting long-lived bot tokens.

The proxy also exposes operational HTTP endpoints:
- `/metrics` (or your configured metrics path) for Prometheus metrics
- `/healthz` for process liveness
- `/readyz` for startup readiness

> For Azure / Microsoft Entra ID setup from scratch, including **both** required redirect URIs (`/auth/callback` and `/ui/callback`), see **`AZURE_SETUP.md`**.

## Configuration

The config file is JSON with a required `environments` object and an optional `auth` object.

Header values and selected auth values support `$VAR` substitution -- any value matching `$SOME_NAME` is resolved from the OS environment at startup.

### Basic config

```json
{
  "environments": {
    "Prod": {
      "description": "Production environment",
      "url": "https://api.example.com/mcp",
      "headers": {
        "Authorization": "$PROD_API_KEY"
      }
    },
    "Staging": {
      "description": "Staging environment",
      "url": "https://api-staging.example.com/mcp",
      "headers": {
        "Authorization": "$STAGING_API_KEY"
      }
    }
  }
}
```

### Auth-enabled config

```json
{
  "environments": {
    "Prod": {
      "description": "Production environment",
      "url": "https://api.example.com/mcp",
      "headers": {
        "Authorization": "$PROD_API_KEY"
      }
    },
    "Staging": {
      "description": "Staging environment",
      "url": "https://api-staging.example.com/mcp",
      "headers": {
        "Authorization": "$STAGING_API_KEY"
      }
    }
  },
  "auth": {
    "azure": {
      "tenant_id": "your-tenant-id",
      "client_id": "your-client-id",
      "client_secret": "$AZURE_CLIENT_SECRET"
    },
    "signing_key_file": ".keys/mcp-env-mux.pem",
    "roles": {
      "admin": {
        "allowed_envs": {
          "*": ["*"]
        }
      },
      "staging-reader": {
        "allowed_envs": {
          "Staging": ["*"]
        }
      },
      "prod-logs": {
        "allowed_envs": {
          "Prod": ["logs*"]
        }
      }
    },
    "token_minting_roles": ["admin"],
    "token_max_expiry_days": 180
  }
}
```

### Fields

Top-level fields:

- `environments` (required) -- Map of environment name to backend configuration.
- `metrics` (optional) -- Enables Prometheus metrics exposition and optional user-level call metrics.
- `auth` (optional) -- Enables authentication, OAuth routes, RBAC, and token minting UI. If omitted, the proxy remains unauthenticated for backward compatibility.

Environment fields:

- `url` (required) -- The MCP backend's HTTP endpoint.
- `description` (required) -- Human-readable label shown in the merged tool's `env` parameter description.
- `headers` (optional) -- HTTP headers sent to this backend. Use `$ENV_VAR` for secrets.

Metrics fields:

- `enabled` (optional, default `true`) -- Enables metrics collection and exposition.
- `path` (optional, default `/metrics`) -- HTTP path exposing Prometheus metrics.
- `user_level_metrics` (optional, default `false`) -- Enables per-user/per-bot total tool-call counts using the principal identity as a label.

Metrics include request counts, success/error counts, latency, in-flight requests, and response-size histograms at both tool and environment level. Response-size metrics use lightweight best-effort estimation for common response types rather than full JSON serialization.

Auth fields:

- `azure` (required when `auth` is present) -- Azure AD OAuth client config.
- `azure.tenant_id` (required) -- Azure tenant ID.
- `azure.client_id` (required) -- Azure app client ID.
- `azure.client_secret` (required) -- Azure app client secret. Supports `$ENV_VAR` substitution.
- `signing_key_file` (required) -- Path to the RSA private key used to sign local JWTs. Resolution order: if the file exists it is loaded; otherwise, if `MCP_ENV_MUX_SIGNING_KEY_PEM` is set, that PEM content is written to this path and loaded; otherwise a new key is generated on first start and written here.
- `roles` (required) -- Map of role name to RBAC config.
- `roles.<role>.allowed_envs` -- Map of environment glob pattern to list of tool glob patterns.
- `token_minting_roles` (required) -- Roles allowed to access the token minting UI.
- `token_max_expiry_days` (optional, default `180`) -- Maximum bot token lifetime allowed by the UI.

## How It Works

1. **Discovery** -- Connects to each backend and calls `list_tools()` to collect tool definitions.
2. **Merge** -- Groups tools by name across environments. For each group:
   - Descriptions must match across environments (mismatch is an error).
   - Parameter types must match (mismatch is an error).
   - Tools available in only a subset of environments get a constrained `env` enum.
   - Extra parameters present in some environments but not others are included as optional, with warnings.
3. **Proxy** -- Builds a FastMCP server with one handler per merged tool. Each handler extracts the `env` argument, strips parameters not supported by the target backend, and forwards the call.
4. **Optional auth** -- If `auth` is configured:
   - MCP requests require a valid JWT Bearer token.
   - OAuth 2.1 routes are exposed for Azure AD login with PKCE.
   - Tool calls are checked against role-based allowlists for environment and tool name.
   - A web UI can mint long-lived bot tokens for approved users.

## Horizontal scaling

The proxy runs FastMCP HTTP transport with `stateless_http=True`.

This matters for multi-replica deployments behind a load balancer:
- requests do not depend on replica-local MCP session affinity
- `list_tools()` and `call_tool()` can be served by any replica
- per-user tool visibility is derived from the presented token and in-memory merged tool metadata, not from sticky server-side MCP session state

Each replica still performs backend discovery at startup and keeps its own backend client connections, so replicas should be started with the same config and auth/signing setup.

## CLI Reference

```
mcp-env-mux [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--config PATH` | (required) | Path to the JSON configuration file. |
| `--host HOST` | `0.0.0.0` | Host to bind the proxy server to. |
| `--port PORT` | `8080` | Port to bind the proxy server to. |
| `--test-schema` | off | Validate config and tool schemas, print diagnostics, then exit. Also validates auth config shape if present. |

## Schema Validation (CI Mode)

Use `--test-schema` to check for configuration errors and tool schema mismatches without starting the server. This connects to all backends, runs the merge, and reports errors and warnings to stdout.

```bash
mcp-env-mux --config config.json --test-schema
```

Exit code 0 means all tools merged cleanly. Exit code 1 means there are merge errors (description or type mismatches). Integrate this into your CI pipeline to catch schema drift between environments.

## Authentication and Authorization

Authentication is optional and fully config-driven.

### What gets enabled

When the `auth` block is present:

- `/mcp` requires a valid Bearer token.
- `/.well-known/oauth-protected-resource` is exposed for resource metadata.
- `/.well-known/oauth-authorization-server` is exposed for auth server metadata.
- `/auth/login`, `/auth/callback`, and `/auth/token` implement an Azure AD OAuth 2.1 PKCE flow for MCP/OAuth clients.
- `/ui/login`, `/ui/callback`, and `/ui/tokens` implement a browser-based login flow and token minting UI for human operators.
  The UI uses Azure authentication together with an app-controlled short-lived UI session cookie.

When the `auth` block is absent, requests pass through without auth.

### RBAC model

RBAC is allowlist-only and role-based:

- Users can have multiple roles.
- Each role maps environment glob patterns to tool glob patterns.
- Access is allowed if any assigned role matches both the requested environment and tool.
- Unknown roles grant no access.
- There are no explicit deny rules.

Examples:

- `"*": ["*"]` allows all tools in all environments.
- `"Prod": ["logs*"]` allows only tools matching `logs*` in `Prod`.

### Token types

The auth module works with two token types:

- **User tokens** -- Azure-issued tokens used for interactive OAuth/MCP access.
- **Bot tokens** -- Longer-lived locally-signed tokens created via the `/ui/tokens` page by users with minting permission.

Both token types carry roles and are accepted by the MCP endpoint.

### Key management

`signing_key_file` points to the RSA private key used to sign local JWTs.

Resolution order:
- If the file exists, it is loaded.
- Else if `MCP_ENV_MUX_SIGNING_KEY_PEM` is set, that PEM content is written to the configured file path and loaded.
- Else a new 2048-bit RSA key is generated and written automatically.

The server logs where it sourced the signing key from in all cases:
- existing file
- `MCP_ENV_MUX_SIGNING_KEY_PEM`
- newly generated key

When a new signing key is generated automatically, the server logs warning-level messages loudly so the event is visible to operators. The warning explicitly calls out that horizontal scaling and rolling restarts will not work correctly unless all replicas share the same signing key.

Protect this file appropriately in production. The private PEM is a secret. Prefer a mounted secret file or injecting `MCP_ENV_MUX_SIGNING_KEY_PEM` in environments where baking keys into images is undesirable.

## OAuth Endpoints

When auth is enabled, the proxy exposes:

- `GET /.well-known/oauth-protected-resource`
- `GET /.well-known/oauth-authorization-server`
- `GET /auth/login`
- `GET /auth/callback`
- `POST /auth/token`
- `GET /ui/login`
- `GET /ui/callback`
- `GET /ui/tokens`
- `POST /ui/tokens`
- `GET /ui/logout`

The OAuth flow uses Azure AD / Microsoft Entra ID as the identity provider.

## Operational Endpoints

- `GET /healthz` -- Liveness endpoint. Returns `200` when the process is up.
- `GET /readyz` -- Readiness endpoint. Returns `200` after successful startup and `503` while startup is incomplete.
- `GET /metrics` -- Prometheus metrics endpoint when metrics are enabled.

- `/auth/*` is the OAuth/API-facing surface used by MCP/OAuth clients.
- `/ui/*` is a browser-session-based flow used by humans to log in and mint bot tokens.
- `/ui/login` and `/ui/callback` use Azure authentication with a dedicated `/ui/callback` redirect URI and create an app-controlled UI session for the token-minting experience.

See `AZURE_SETUP.md` for the full Azure app-registration setup from scratch.

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v --timeout=120

# Run unit tests only
pytest tests/ -v --ignore=tests/test_e2e.py --ignore=tests/test_auth_e2e.py

# Run core E2E tests only
pytest tests/test_e2e.py -v --timeout=120

# Run auth unit tests
pytest tests/test_auth_config.py tests/test_hybrid.py tests/test_ui_session.py -v

# Run auth E2E tests
pytest tests/test_auth_e2e.py -v --timeout=120
```

Requires Python >= 3.11.

## Architecture

The package is organized into six top-level areas under `src/mcp_env_mux/`: `cli`, `config`, `discovery`, `merge`, `proxy`, and `auth`.

The main data flow is:

1. CLI parses args.
2. Config is loaded and environment variables are resolved.
3. If auth is configured, signing keys are loaded/generated.
4. Backends are discovered.
5. Schemas are merged.
6. The proxy server is built and started.
7. If auth is enabled, OAuth routes, RBAC middleware, and token UI routes are registered.

For detailed module documentation, see `src/mcp_env_mux/mcp_env_mux_docs.md`, `src/mcp_env_mux/auth/auth_docs.md`, and the per-module `*_docs.md` files. For test documentation and coverage mapping, see `tests/tests_docs.md` and the auth-specific test docs in `tests/test_auth_config_docs.md`, `tests/test_auth_e2e_docs.md`, and `tests/test_oauth_routes_docs.md`.

## Project Structure

```
mcp-env-mux/
  pyproject.toml                       -- Package metadata, dependencies, CLI entrypoint
  config.json                          -- Example configuration file
  src/mcp_env_mux/
    __init__.py                        -- Package init
    cli.py                             -- CLI entrypoint and startup orchestration
    config.py                          -- Config loading, validation, env var resolution
    discovery.py                       -- Backend connection and tool discovery
    merge.py                           -- Schema diffing and tool merging
    proxy.py                           -- FastMCP server construction and call routing
    auth/
      keys.py                          -- RSA key loading/generation and public key extraction
      tokens.py                        -- User and bot JWT creation
      rbac.py                          -- Role-based allowlist checks
      middleware.py                    -- RBAC enforcement on MCP tool calls
      oauth.py                         -- Azure AD OAuth 2.1 PKCE endpoints
      ui.py                            -- Bot token minting web UI
      auth_docs.md                     -- Auth package overview
    mcp_env_mux_docs.md                -- Detailed package documentation
  tests/
    conftest.py                        -- Shared fixtures: mock backends, proxy lifecycle
    test_config.py                     -- Unit tests for config loading and env var substitution
    test_merge.py                      -- Unit tests for schema merging logic
    test_proxy.py                      -- Unit tests for call routing and parameter stripping
    test_e2e.py                        -- End-to-end tests with real backends and proxy
    test_auth_config.py                -- Unit tests for auth config parsing and validation
    test_oauth_routes.py               -- Unit tests for PKCE verification and OAuth route registration
    test_auth_e2e.py                   -- End-to-end auth tests over HTTP
    tests_docs.md                      -- Test suite documentation
```
