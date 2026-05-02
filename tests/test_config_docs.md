# test_config.py

## Purpose

Unit tests for `mcp_env_mux.config`. Validates config loading, structural validation, and environment variable substitution across string values in config.

## Test Classes

### `TestLoadConfigValid`

Tests successful config loading: single environment, multiple environments, environments with headers, and default empty headers.

### `TestLoadConfigInvalid`

Tests error cases: missing file, invalid JSON, empty environments dict, missing `environments` key, missing `url`, and missing `description`.

### `TestResolveEnvVars`

Tests `${VAR}` substitution: single variable, unset variable (error), literal values without `$`, bare `$VAR` preservation, multiple variables in one value, empty inputs, multiple values, mixed static/variable values, and config-wide substitution beyond headers.

## Dependencies

- `mcp_env_mux.config.Config`
- `mcp_env_mux.config.EnvironmentConfig`
- `mcp_env_mux.config.load_config`
- `mcp_env_mux.config.resolve_env_vars`
