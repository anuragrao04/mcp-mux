# tests/

## Overview

The test suite validates the mcp-env-mux proxy at two levels: unit tests that exercise individual modules in isolation (config loading, schema merging, call routing) and end-to-end tests that start real backend servers, launch the proxy as a subprocess, and connect a client to verify external behavior. All tests use pytest and asyncio.

## Test File Summary

**conftest.py** provides shared fixtures and helpers used by the E2E tests. It can spin up mock FastMCP backend servers in daemon threads, write proxy config files to temporary directories, launch the mcp-env-mux proxy as a subprocess, and wait for it to become ready. Key abstractions are `MockBackend` (a running backend handle), `ProxyProcess` (a running proxy handle with `stop()`), and helpers like `find_free_port`, `write_config`, and `run_test_schema`.

**test_config.py** contains unit tests for `mcp_env_mux.config`. It validates successful config loading (single/multiple environments, headers, defaults), error cases (missing file, invalid JSON, missing required fields), and environment variable substitution across string fields in config (`${VAR}` syntax with single, multiple, mixed, literal `$VAR`, and unset variable scenarios).

**test_merge.py** contains unit tests for `mcp_env_mux.merge`. It tests schema merging logic using raw dicts with no I/O: merging identical tools across two or three environments, subset tools with constrained `env` enums, validation errors for description and type mismatches, extra parameter handling (optional inclusion, warnings, description notes, `env_params` tracking), merged schema structure (`env` always required, enum correctness), and description formatting with `[Environments]` and `[Parameter Notes]` sections.

**test_proxy.py** contains unit tests for `mcp_env_mux.proxy`. It tests call routing logic using mocked `fastmcp.Client` instances (no real servers). Coverage includes routing to the correct backend by `env` parameter, stripping `env` before forwarding, error handling for invalid or missing `env`, stripping unsupported extra parameters per environment, `create_proxy_server` construction, and result passthrough.

**test_auth_config.py** contains unit tests for auth config parsing in `mcp_env_mux.config`. Validates backward compatibility (no `auth` key), successful parsing of `AuthConfig`/`AzureConfig`/`RoleConfig`, `${VAR}` substitution in auth string fields, literal `$VAR` preservation, and required-field validation errors.

**test_hybrid.py** contains unit tests for `HybridAzureProvider`. Verifies that `verify_token` dispatches to the local `JWTVerifier` when `iss == "mcp-env-mux"` and to the Azure (super) path otherwise; verifies that bot tokens with bad signatures return `None`; verifies that garbage / malformed tokens never raise.

**test_auth_e2e.py** contains end-to-end auth tests. Starts real backends with auth config and verifies: no-auth passthrough, 401 on missing token, well-known endpoints (`/.well-known/oauth-protected-resource`, `/.well-known/oauth-protected-resource/mcp`, `/.well-known/oauth-authorization-server`) all reachable, that `oauth-authorization-server` advertises a `registration_endpoint` (DCR proxy is wired), bot-token authentication, RBAC denial path, and token minting UI auth checks.

**test_e2e.py** contains end-to-end tests that exercise the full system. Each test starts real FastMCP backends, writes a config, launches the proxy subprocess, and connects a client. Scenarios include tool merging verification, call routing across environments, schema mismatch detection, subset tools, extra parameters, `--test-schema` validation mode, environment variable substitution in config strings, three-environment setups, single-environment setups, empty backends, unreachable backends, tools with no parameters, and config validation errors.

## Test Infrastructure

`conftest.py` provides all shared infrastructure. `create_backend_server` dynamically registers tools on a `FastMCP` instance using `exec` to build functions with correct signatures for schema introspection. `start_backend` runs each backend in a daemon thread and returns a `MockBackend` dataclass. `write_config` serializes environment definitions to a JSON config file. `start_proxy` launches the proxy as a subprocess, optionally blocking until the port accepts connections (10-second timeout). `run_test_schema` runs the proxy with `--test-schema` and captures the result. `ProxyProcess.stop()` sends SIGTERM then SIGKILL if needed. The `free_port` fixture exposes `find_free_port` for tests that need arbitrary ports. `conftest.py` has no imports from project source modules; it interacts with the proxy only through its CLI and network interfaces.

## Coverage Map

| Source Module | Covered By |
|---|---|
| `mcp_env_mux.config` (`Config`, `EnvironmentConfig`, `load_config`, `resolve_env_vars`) | `test_config.py`, `test_e2e.py` (config validation scenarios) |
| `mcp_env_mux.merge` (`validate_and_merge`, `MergedTool`, `MergeError`, `MergeWarning`, `MergeResult`) | `test_merge.py`, `test_e2e.py` (merging and schema mismatch scenarios) |
| `mcp_env_mux.proxy` (`_make_handler`, `create_proxy_server`) | `test_proxy.py`, `test_e2e.py` (routing and call scenarios) |
| `mcp_env_mux.discovery` (`discover_all`, `_make_client`) | `test_e2e.py` only (no dedicated unit tests) |
| CLI (`--test-schema` flag, subprocess entry point) | `test_e2e.py` |
| `mcp_env_mux.auth.keys` (`load_or_generate_key`, `get_public_key`) | `test_keys.py`, `test_auth_e2e.py` (fixture) |
| `mcp_env_mux.auth.tokens` (`create_bot_token`) | `test_tokens.py`, `test_auth_e2e.py` (via `_make_bot_token` helper) |
| `mcp_env_mux.auth.hybrid` (`HybridAzureProvider`) | `test_hybrid.py`, `test_auth_e2e.py` |
| `mcp_env_mux.auth.rbac` (`is_allowed`) | `test_rbac.py`, `test_auth_e2e.py` (indirectly via middleware) |
| `mcp_env_mux.auth.middleware` (`RBACMiddleware`) | `test_auth_e2e.py` (indirectly via proxy) |
| `mcp_env_mux.auth.ui` (`register_ui_routes`) | `test_auth_e2e.py` (UI auth + minting flow) |
| `mcp_env_mux.config` (auth parsing: `AuthConfig`, `AzureConfig`, `RoleConfig`) | `test_auth_config.py` |

## Running Tests

Run all tests:

```
pytest tests/ -v
```

Run unit tests only (exclude E2E):

```
pytest tests/ -v --ignore=tests/test_e2e.py
```

Run E2E tests only (with extended timeout for subprocess startup):

```
pytest tests/test_e2e.py -v --timeout=120
```

Run all tests with a timeout to catch hangs:

```
pytest tests/ -v --timeout=120
```
