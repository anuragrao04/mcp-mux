# mcp-env-mux

Merge multiple instances of the same MCP server across environments into a single endpoint with a unified `env` parameter.

## Problem

When you connect the same MCP server (e.g., Coralogix, Datadog) from multiple environments (prod, staging, dev), each instance exposes identical tool definitions. Your MCP client sees every tool duplicated per environment, wasting context window tokens and creating a confusing tool list.

## Solution

mcp-env-mux sits in front of your MCP backends as a proxy. It discovers tools from each backend, merges identical definitions into a single tool with an injected `env` parameter, and routes calls to the correct backend based on the caller's `env` selection. One tool instead of N copies.

## Quick Start

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

## Configuration

The config file is JSON with a single `environments` object. Each key is an environment name, and each value specifies the backend URL, a description, and optional HTTP headers.

Header values support `$VAR` substitution -- any value matching `$SOME_NAME` is resolved from the OS environment at startup.

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

Fields:

- `url` (required) -- The MCP backend's HTTP endpoint.
- `description` (required) -- Human-readable label shown in the merged tool's `env` parameter description.
- `headers` (optional) -- HTTP headers sent to this backend. Use `$ENV_VAR` for secrets.

## How It Works

1. **Discovery** -- Connects to each backend and calls `list_tools()` to collect tool definitions.
2. **Merge** -- Groups tools by name across environments. For each group:
   - Descriptions must match across environments (mismatch is an error).
   - Parameter types must match (mismatch is an error).
   - Tools available in only a subset of environments get a constrained `env` enum.
   - Extra parameters present in some environments but not others are included as optional, with warnings.
3. **Proxy** -- Builds a FastMCP server with one handler per merged tool. Each handler extracts the `env` argument, strips parameters not supported by the target backend, and forwards the call.

## CLI Reference

```
mcp-env-mux [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--config PATH` | (required) | Path to the JSON configuration file. |
| `--host HOST` | `0.0.0.0` | Host to bind the proxy server to. |
| `--port PORT` | `8080` | Port to bind the proxy server to. |
| `--test-schema` | off | Validate config and tool schemas, print diagnostics, then exit. |

## Schema Validation (CI Mode)

Use `--test-schema` to check for configuration errors and tool schema mismatches without starting the server. This connects to all backends, runs the merge, and reports errors and warnings to stdout.

```bash
mcp-env-mux --config config.json --test-schema
```

Exit code 0 means all tools merged cleanly. Exit code 1 means there are merge errors (description or type mismatches). Integrate this into your CI pipeline to catch schema drift between environments.

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v --timeout=120

# Run unit tests only
pytest tests/ -v --ignore=tests/test_e2e.py

# Run E2E tests only (starts real backends and proxy subprocesses)
pytest tests/test_e2e.py -v --timeout=120
```

Requires Python >= 3.11.

## Architecture

The package is organized into five modules under `src/mcp_env_mux/`: `cli`, `config`, `discovery`, `merge`, and `proxy`. The data flow is linear: CLI parses args, config is loaded, backends are discovered, schemas are merged, and the proxy server is built and started.

For detailed module documentation, see `src/mcp_env_mux/mcp_env_mux_docs.md`. For test documentation and coverage mapping, see `tests/tests_docs.md`.

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
    mcp_env_mux_docs.md               -- Detailed package documentation
  tests/
    conftest.py                        -- Shared fixtures: mock backends, proxy lifecycle
    test_config.py                     -- Unit tests for config loading and env var substitution
    test_merge.py                      -- Unit tests for schema merging logic
    test_proxy.py                      -- Unit tests for call routing and parameter stripping
    test_e2e.py                        -- End-to-end tests with real backends and proxy
    tests_docs.md                      -- Test suite documentation
```
