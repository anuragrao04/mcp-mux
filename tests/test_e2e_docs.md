# test_e2e.py

## Purpose

End-to-end tests for mcp-env-mux. Validates external behavior by starting real FastMCP backend servers, launching the proxy as a subprocess, and connecting a client to verify merged tool lists and routed tool calls.

## Test Classes

### `TestToolMerging`

Starts two identical backends. Verifies merged tools have an `env` parameter with correct enum, original parameters are preserved, tools are not duplicated, and descriptions include environment info.

### `TestToolCallRouting`

Starts two backends with environment-identifying handlers. Verifies calls route to the correct backend based on `env`, the `env` parameter is stripped from forwarded arguments, and invalid/missing `env` values are rejected.

### `TestSchemaMismatch`

Verifies that description mismatches and parameter type mismatches across backends cause `--test-schema` to exit with a nonzero code.

### `TestSubsetTools`

One backend has two tools, the other has one. Verifies the common tool has all envs in its enum, the prod-only tool has a constrained enum, and calling the prod-only tool with the wrong env fails.

### `TestExtraParameters`

One backend has an extra `timeout` parameter. Verifies it appears as optional in the merged schema, is noted in the description, is forwarded to the supporting env, and is stripped for the non-supporting env.

### `TestSchemaValidationMode`

Tests the `--test-schema` CLI flag: clean schemas exit 0, description mismatches exit nonzero, and extra parameters are reported as warnings (exit 0).

### `TestEnvVarSubstitution`

Verifies that `$ENV_VAR` references in config headers are resolved from the process environment when starting the proxy.

### `TestThreeEnvironments`

Starts three backends. Verifies all three appear in the env enum and calls route correctly to each.

### `TestSingleEnvironment`

Verifies the proxy works with a single backend: tools still get an `env` parameter and calls succeed.

### `TestEmptyBackend`

Verifies that backends with no tools result in the proxy exposing zero tools.

### `TestUnreachableBackend`

Verifies that an unreachable backend causes `--test-schema` to fail.

### `TestToolWithNoParams`

Verifies tools with no original parameters only have `env` after merging and can be called successfully.

### `TestConfigValidation`

Tests config-level validation via `--test-schema`: missing file, invalid JSON, empty environments, and missing URL all cause nonzero exit.

## Dependencies

- `conftest.MockBackend`
- `conftest.find_free_port`
- `conftest.run_test_schema`
- `conftest.start_backend`
- `conftest.start_proxy`
- `conftest.write_config`
