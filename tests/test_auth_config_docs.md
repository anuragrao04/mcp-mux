# test_auth_config.py

## Purpose

Unit tests for auth config parsing in `mcp_env_mux.config`. Validates that the `auth` block is correctly parsed into `AuthConfig`, `AzureConfig`, and `RoleConfig` dataclasses, including environment variable substitution and required-field validation.

## Test Classes

### `TestNoAuthBackwardCompat`

Tests backward compatibility: config without an `auth` key loads successfully with `config.auth == None`, and environments are still parsed.

### `TestValidAuthConfig`

Tests successful auth config parsing: `AuthConfig` instance created, `AzureConfig` fields populated, roles parsed into `RoleConfig` with correct `allowed_envs`, `token_minting_roles` list, default `token_max_expiry_days` (180), and custom expiry override.

### `TestAuthEnvVarSubstitution`

Tests `$VAR` substitution in `client_secret`: resolved from environment, and `ValueError` raised for missing env vars.

### `TestMissingAuthFields`

Tests required-field validation: missing `azure`, `signing_key_file`, `roles`, `token_minting_roles`, and `azure.tenant_id` each raise `ValueError` with the field name in the message.

## Dependencies

- `mcp_env_mux.config.AuthConfig`
- `mcp_env_mux.config.AzureConfig`
- `mcp_env_mux.config.Config`
- `mcp_env_mux.config.RoleConfig`
- `mcp_env_mux.config.load_config`
