# test_merge.py

## Purpose

Unit tests for `mcp_env_mux.merge`. Tests schema validation, merging logic, `env` parameter injection, extra parameter handling, and description formatting. All tests use raw dicts with no I/O.

## Test Classes

### `TestBasicMerging`

Tests merging identical tools from two environments, three environments, a single environment, multiple independent tools, and empty input.

### `TestSubsetTools`

Tests tools that exist on only a subset of environments, verifying constrained `env` enums.

### `TestValidationErrors`

Tests that description mismatches and parameter type mismatches produce `MergeError` entries.

### `TestExtraParameters`

Tests parameters present on some environments but not others: included as optional, generate warnings, noted in description, tracked in `env_params`, shared required params stay required, and originally optional params stay optional.

### `TestSchemaStructure`

Tests merged schema structure: `env` is always required, `env` is a string with enum, tools with no params only have `env`, and original parameter properties are preserved.

### `TestDescriptionFormatting`

Tests merged description format: includes `[Environments]` header, env names with descriptions, original description, `[Parameter Notes]` for extra params, and omits `[Parameter Notes]` when not needed.

### `TestMergeResultTypes`

Tests dataclass field access on `MergeError`, `MergeWarning`, and `MergedTool`.

## Dependencies

- `mcp_env_mux.merge.MergedTool`
- `mcp_env_mux.merge.MergeError`
- `mcp_env_mux.merge.MergeResult`
- `mcp_env_mux.merge.MergeWarning`
- `mcp_env_mux.merge.validate_and_merge`
