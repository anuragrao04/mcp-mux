# cli.py

## Purpose

CLI entrypoint for mcp-env-mux. Parses arguments, orchestrates config loading, backend discovery, schema merging, and either runs schema validation or starts the proxy server.

## Public API

### `main() -> None`

Parses CLI arguments and runs the async entrypoint. Calls `sys.exit()` with the appropriate exit code.

CLI arguments:
- `--config` (required) — Path to the JSON config file.
- `--host` (default: `0.0.0.0`) — Host to bind the proxy server to.
- `--port` (default: `8080`) — Port to bind the proxy server to.
- `--test-schema` — Discover and validate schemas, print results, then exit. Returns exit code 0 on success, 1 on errors.

## Data Flow

1. `load_config` parses the config file.
2. `discover_all` connects to backends and retrieves tool lists.
3. `validate_and_merge` merges tool schemas and checks for conflicts.
4. In `--test-schema` mode: prints errors/warnings and exits.
5. In normal mode: if there are merge errors, prints them to stderr and exits with code 1. Otherwise, opens persistent client connections to all backends, creates the proxy server, and runs it as an HTTP server.

Client connections are managed manually via `__aenter__`/`__aexit__` in a try/finally block.

## Dependencies

- `mcp_env_mux.config.load_config`
- `mcp_env_mux.discovery.discover_all`
- `mcp_env_mux.discovery._make_client` (imported lazily inside `_run`)
- `mcp_env_mux.merge.validate_and_merge`
- `mcp_env_mux.proxy.create_proxy_server`

## Error Handling

- Config and discovery errors propagate as unhandled exceptions (crash with traceback).
- Merge errors are printed to stderr and cause exit code 1.
- In `--test-schema` mode, errors and warnings are printed to stdout; exit code reflects whether errors exist.
