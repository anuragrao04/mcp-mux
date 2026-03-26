# conftest.py

## Purpose

Shared test fixtures and helpers for spinning up mock MCP backend servers, writing proxy config files, and launching the mcp-env-mux proxy as a subprocess.

## Public API

### `find_free_port() -> int`

Returns a free TCP port on localhost by binding to port 0 and reading the assigned port.

### `MockBackend` (dataclass)

Fields:
- `name: str` — Backend identifier.
- `server: FastMCP` — The FastMCP server instance.
- `port: int` — Port the server is listening on.
- `url: str` — Full MCP endpoint URL.

### `create_backend_server(name: str, tools: dict[str, dict[str, Any]]) -> FastMCP`

Creates a `FastMCP` server with dynamically registered tools. Each tool entry maps a name to a dict with keys:
- `description` — Tool description string.
- `params` — Dict of parameter definitions, each with `type` (Python type), `required` (bool), and optional `default`.
- `handler` — Callable receiving a kwargs dict and returning the tool result. Defaults to JSON-serializing the kwargs.

Tools are registered using `exec` to dynamically build functions with the correct signatures for FastMCP schema introspection.

### `start_backend(name: str, tools: dict[str, dict[str, Any]], port: int | None = None) -> MockBackend`

Async function. Creates a backend server and starts it in a daemon thread on the given port (or a free port). Returns a `MockBackend` handle after a brief startup delay.

### `write_config(environments: dict[str, dict[str, Any]], tmpdir: Path | str) -> Path`

Writes a proxy config JSON file to `tmpdir/config.json` and returns the path.

### `ProxyProcess` (dataclass)

Fields:
- `process: subprocess.Popen` — The subprocess handle.
- `port: int` — Port the proxy is bound to.
- `url: str` — Full MCP endpoint URL.
- `config_path: Path` — Path to the config file used.

Methods:
- `stop()` — Sends SIGTERM, waits up to 5 seconds, then SIGKILL if needed.
- `returncode` (property) — The process return code or None.

### `start_proxy(config_path: Path, port: int | None = None, extra_args: list[str] | None = None, wait_for_ready: bool = True, env_vars: dict[str, str] | None = None) -> ProxyProcess`

Starts the mcp-env-mux proxy as a subprocess. By default, blocks until the port is accepting connections (up to 10 seconds). The caller must call `.stop()`.

### `run_test_schema(config_path: Path, env_vars: dict[str, str] | None = None) -> subprocess.CompletedProcess`

Runs mcp-env-mux with `--test-schema` and returns the completed process result. Times out after 30 seconds.

### Fixtures

- `tmp_path_factory_unique` — Alias for pytest's `tmp_path`.
- `free_port` — Returns the `find_free_port` function.

## Dependencies

None (no imports from project source modules).

## Error Handling

- `start_proxy` raises `RuntimeError` if the proxy process exits before becoming ready.
- `start_proxy` raises `TimeoutError` if the port is not accepting connections within the timeout.
