# mcp_env_mux package

## Overview

mcp_env_mux is a proxy server that multiplexes multiple MCP backend environments behind a single MCP endpoint. It discovers tools from each configured backend, merges their schemas into unified tool definitions with an injected `env` parameter, and routes incoming tool calls to the correct backend based on that parameter.

## Module Summary

**cli.py** — CLI entrypoint. Parses arguments (`--config`, `--host`, `--port`, `--test-schema`), orchestrates the startup pipeline, and either runs schema validation or starts the proxy server. All other modules are driven from here.

**config.py** — Loads and validates a JSON configuration file that maps environment names to MCP backend URLs and HTTP headers. Resolves `$ENV_VAR` patterns in header values from the OS environment. Exports `Config` and `EnvironmentConfig` dataclasses.

**discovery.py** — Connects sequentially to each backend defined in `Config`, calls `list_tools()`, and returns a dict mapping environment names to lists of tool definition dicts. Each tool dict contains `name`, `description`, and `inputSchema`.

**merge.py** — Takes the discovered tool map and produces unified `MergedTool` definitions. Groups tools by name across environments, validates that descriptions and parameter types are consistent, injects an `env` enum parameter, and flags incompatibilities as `MergeError` or `MergeWarning` within a `MergeResult`.

**proxy.py** — Builds a `FastMCP` server from merged tools. Registers a handler per tool that extracts the `env` argument, strips env-specific parameters not supported by the target backend, forwards the call to the correct client, records Prometheus metrics when enabled, and exposes operational HTTP routes such as `/healthz` and `/readyz`.

**health.py** — Health and readiness routes plus readiness state shared from startup orchestration.

**metrics/** — Prometheus instrumentation package. Exposes `/metrics`, records tool-call, auth, RBAC, UI, discovery, and startup metrics, and supports optional user-level tool-call tracking.

**auth/** — Optional authentication and authorization package. When an `auth` block is present in the config, the proxy attaches FastMCP's `AzureProvider` (extended as `HybridAzureProvider`) for Microsoft Entra ID OAuth via the OAuth Proxy pattern (DCR locally, fixed credentials upstream). The same provider also accepts locally-minted RS256 bot JWTs (`iss=mcp-env-mux`) for headless agents, dispatched on the `iss` claim. Contains: `hybrid.py` (`HybridAzureProvider`), `keys.py` (RSA key management for bot tokens), `tokens.py` (bot JWT creation), `rbac.py` (permission logic), `middleware.py` (FastMCP RBAC middleware reading roles from access-token claims), `ui.py` (token minting UI). See `/AUTH_DESIGN.md` for the full design.

## Data Flow

```
cli.main()
  -> config.load_config(path)          -- parse JSON, resolve env vars, return Config
  -> discovery.discover_all(config)    -- connect to each backend, list tools, return {env: [tool_dicts]}
  -> merge.validate_and_merge(discovered, env_descriptions)
                                       -- diff schemas, produce MergeResult (tools, errors, warnings)
  -> proxy.create_proxy_server(merged_tools, clients)
                                       -- build FastMCP server with routing handlers
  -> server.run(host, port)            -- serve over HTTP
```

In `--test-schema` mode the pipeline stops after merge and prints diagnostics instead of starting the server.

## Key Types

- **`Config`** — Top-level config container. Holds `environments: dict[str, EnvironmentConfig]`.
- **`EnvironmentConfig`** — Per-backend config: `url`, `description`, `headers`.
- **`MergedTool`** — Unified tool definition: `name`, `description`, `input_schema`, `available_envs`, `env_params`.
- **`MergeResult`** — Output of the merge step: `tools: list[MergedTool]`, `errors: list[MergeError]`, `warnings: list[MergeWarning]`.
- **`MergeError`** / **`MergeWarning`** — Diagnostics with `tool_name` and `message` fields.

## Error Model

Config and discovery errors are raised as exceptions (`FileNotFoundError`, `ValueError`, `json.JSONDecodeError`, or client connection errors) and propagate unhandled to the CLI, which crashes with a traceback.

Merge errors are accumulated in `MergeResult` rather than raised. Tools with fatal incompatibilities (`MergeError`) are excluded from the merged tool list. The CLI inspects `MergeResult.errors` and exits with code 1 if any are present (in normal mode) or reports them to stdout (in `--test-schema` mode). Warnings are non-fatal and logged but do not block startup.

Proxy-time errors (missing or invalid `env` parameter) raise `ValueError` at call time. Backend call failures propagate unhandled from the client.
