# proxy.py

## Purpose

Creates a FastMCP server that registers merged tools and routes incoming tool calls to the correct backend client based on the `env` parameter. The server is served over HTTP using Streamable HTTP transport via `server.run_http_async()`.

## Public API

### `create_proxy_server(merged_tools: list[MergedTool], clients: dict[str, Any]) -> FastMCP`

Creates and returns a `FastMCP` server instance with one `FunctionTool` registered per merged tool. Each tool's handler routes calls to the appropriate backend client.

Parameters:
- `merged_tools` — List of merged tool definitions from the merge module.
- `clients` — Map of environment name to connected `fastmcp.Client` instances.

The returned server is started by the caller (`cli.py`) via `server.run_http_async(host=..., port=...)`, which serves over Streamable HTTP transport.

### `_make_handler(tool: MergedTool, clients: dict[str, Any]) -> Callable`

Creates an async handler closure for a single merged tool. The handler is the core routing function that bridges client requests to the correct backend.

Parameters:
- `tool` — The merged tool definition containing `name`, `available_envs`, and `env_params`.
- `clients` — Map of environment name to connected `fastmcp.Client` instances.

Returns an `async def handler(**kwargs) -> Any` that:
1. Extracts the `env` parameter from kwargs. Raises `ValueError` if missing.
2. Validates `env` against `tool.available_envs`. Raises `ValueError` if invalid.
3. Strips `env` from the forwarded arguments.
4. Strips parameters not supported by the target environment (any param in `tool.env_params` where the target env is not in that param's env set).
5. Calls `clients[env].call_tool(tool.name, args)`.
6. Returns `result.content` if the result has a `.content` attribute, otherwise returns the result as-is.

This function is internal but is also imported directly by `test_proxy.py` for unit testing the routing logic without starting a server.

## Data Flow

For each `MergedTool`, `_make_handler` creates a handler closure. That handler is wrapped in a `FunctionTool` (from `fastmcp.tools.function_tool`) with the merged tool's `name`, `description`, and `input_schema` (preserving enum constraints and type details), then added to the server via `server.add_tool()`.

## Concurrency

The proxy handles concurrent incoming requests via FastMCP's underlying uvicorn HTTP server. Each tool call handler is an independent async function. Backend client calls are awaited individually — there is no request batching or connection pooling beyond what `fastmcp.Client` provides.

## Dependencies

- `mcp_env_mux.merge.MergedTool`

## Error Handling

- Raises `ValueError` if `env` is missing from the call arguments.
- Raises `ValueError` if `env` is not in the tool's `available_envs` list.
- Backend call errors propagate unhandled from the client.
