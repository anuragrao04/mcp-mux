# merge.py

## Purpose

Diffs and merges tool schemas discovered from multiple backend environments into unified tool definitions. Injects an `env` parameter so callers can select which environment to target. Detects incompatibilities and reports them as errors or warnings.

## Public API

### `MergeError` (dataclass)

Fields:
- `tool_name: str`
- `message: str`

Represents a fatal incompatibility that prevents a tool from being merged (e.g., description mismatch, type mismatch).

### `MergeWarning` (dataclass)

Fields:
- `tool_name: str`
- `message: str`

Represents a non-fatal inconsistency (e.g., a parameter that exists on some environments but not others).

### `MergedTool` (dataclass)

Fields:
- `name: str` — Original tool name.
- `description: str` — Merged description including `[Environments]` and optional `[Parameter Notes]` sections.
- `input_schema: dict[str, Any]` — JSON Schema with all parameters from all environments, plus the injected `env` parameter.
- `available_envs: list[str]` — Sorted list of environments that expose this tool.
- `env_params: dict[str, set[str]]` — Maps parameter names to the set of environments that support them, only for parameters that are not present on all environments.

### `MergeResult` (dataclass)

Fields:
- `tools: list[MergedTool]` — Successfully merged tools.
- `errors: list[MergeError]` — Fatal errors (tools with errors are excluded from `tools`).
- `warnings: list[MergeWarning]` — Non-fatal warnings.

### `validate_and_merge(discovered: dict[str, list[dict[str, Any]]], env_descriptions: dict[str, str]) -> MergeResult`

Merges tool definitions from multiple environments into a single set of `MergedTool` objects.

Behavior:
- Groups tools by name across environments.
- Rejects tools where descriptions differ across environments (produces `MergeError`).
- Rejects tools where the same parameter has different types across environments (produces `MergeError`).
- Parameters present on some but not all environments are included as optional and generate a `MergeWarning`.
- A parameter is required in the merged schema only if it is required on all environments and present on all environments.
- An `env` parameter (string enum of available environment names) is injected into every merged schema and marked required.
- The merged description includes an `[Environments]` section listing each env and its description, an optional `[Parameter Notes]` section for env-specific parameters, and the original tool description.

## Data Flow

`discovered` dict (env -> tool list) -> group by tool name -> validate descriptions -> validate types -> build merged properties/required -> inject `env` param -> build description -> return `MergeResult`.

## Dependencies

None (no imports from other project modules).

## Error Handling

Errors and warnings are accumulated in the `MergeResult` rather than raised as exceptions. Tools with errors are skipped (not added to `result.tools`). The caller decides whether to abort or continue.
