# discovery.py

## Purpose

Connects to each configured MCP backend and discovers the tools it exposes, returning a unified map of environment names to tool definitions.

## Public API

### `discover_all(config: Config) -> dict[str, list[dict[str, Any]]]`

Iterates over all environments in the config, connects to each backend via `StreamableHttpTransport`, calls `list_tools()`, and returns a dict mapping environment names to lists of tool definition dicts. Each tool dict has keys: `name`, `description`, `inputSchema`.

Connections are opened and closed sequentially (one environment at a time).

### `_make_client(url: str, headers: dict[str, str]) -> Client`

Creates a `fastmcp.Client` backed by a `StreamableHttpTransport`. This is an internal helper but is also imported by `cli.py` to create persistent client connections for the proxy server (as opposed to the short-lived connections used during discovery).

Parameters:
- `url` — The MCP backend endpoint URL.
- `headers` — HTTP headers to include in requests. If empty, `None` is passed to the transport.

Returns an unconnected `Client` instance. The caller must manage the connection lifecycle via `async with client:` or manual `__aenter__`/`__aexit__`.

## Data Flow

`Config` -> for each environment, `_make_client` creates a `Client` with `StreamableHttpTransport` -> `list_tools()` -> normalize into dicts -> return aggregated map.

## Dependencies

- `mcp_env_mux.config.Config`

## Error Handling

Connection errors from `fastmcp.Client` propagate unhandled. If any backend is unreachable, the entire discovery fails with a `RuntimeError` from the FastMCP client layer.
