# config.py

## Purpose

Loads, validates, and parses a JSON configuration file that defines MCP backend environments. Resolves `$ENV_VAR` patterns in header values from the OS environment.

## Public API

### `EnvironmentConfig` (dataclass)

Fields:
- `description: str` — Human-readable description of this environment.
- `url: str` — The MCP endpoint URL for this backend.
- `headers: dict[str, str]` — HTTP headers to send with requests (default: empty dict).

### `Config` (dataclass)

Fields:
- `environments: dict[str, EnvironmentConfig]` — Map of environment name to its configuration.

### `resolve_env_vars(headers: dict[str, str]) -> dict[str, str]`

Replaces `$VAR` patterns in header values with values from `os.environ`. Pattern matched: `\$([A-Za-z_][A-Za-z0-9_]*)`. Multiple variables in a single value are supported (e.g., `"$SCHEME $TOKEN"` becomes `"Bearer abc123"`).

Only the `$VAR` syntax is supported. The `${VAR}` brace syntax is **not** supported.

Raises `ValueError` if a referenced environment variable is not set.

### `load_config(path: Path) -> Config`

Reads a JSON file and returns a validated `Config` instance. Environment variable substitution is applied to headers during loading.

Raises:
- `FileNotFoundError` if the file does not exist.
- `json.JSONDecodeError` if the file is not valid JSON.
- `ValueError` if the `environments` key is missing, the environments dict is empty, or any environment is missing `url` or `description`.

## Data Flow

`load_config` reads raw JSON, validates structure, calls `resolve_env_vars` on each environment's headers, and constructs `EnvironmentConfig` / `Config` dataclasses.

## Dependencies

None (no imports from other project modules).

## Error Handling

All validation errors are raised immediately as exceptions. There is no partial-success mode; if any environment is invalid, the entire load fails.
