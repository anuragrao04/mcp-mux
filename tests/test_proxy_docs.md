# test_proxy.py

## Purpose

Unit tests for `mcp_env_mux.proxy`. Tests tool call routing logic using mocked `fastmcp.Client` instances. No real servers are started.

## Test Classes

### `TestRouting`

Tests that calls are routed to the correct backend based on the `env` parameter (prod vs staging) and that the original tool name is forwarded.

### `TestEnvStripping`

Tests that the `env` parameter is removed from arguments before forwarding to the backend, while other parameters are preserved.

### `TestInvalidEnv`

Tests that calling with an invalid `env` value or a missing `env` parameter raises an error.

### `TestExtraParamHandling`

Tests env-specific parameter handling: parameters not supported by the target environment are stripped, while parameters supported by the target environment are forwarded.

### `TestCreateProxyServer`

Tests that `create_proxy_server` returns a non-None server object and accepts multiple tools without error.

### `TestResultPassthrough`

Tests that the handler returns the backend client's result unmodified.

## Dependencies

- `mcp_env_mux.merge.MergedTool`
- `mcp_env_mux.proxy._make_handler`
- `mcp_env_mux.proxy.create_proxy_server`
