"""Schema diffing, merging, and env parameter injection."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MergeError:
    tool_name: str
    message: str


@dataclass
class MergeWarning:
    tool_name: str
    message: str


@dataclass
class MergedTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    available_envs: list[str]
    env_params: dict[str, set[str]]
    base_description: str
    env_descriptions: dict[str, str]


@dataclass
class MergeResult:
    tools: list[MergedTool] = field(default_factory=list)
    errors: list[MergeError] = field(default_factory=list)
    warnings: list[MergeWarning] = field(default_factory=list)


def _build_description(
    base_description: str,
    visible_envs: list[str],
    env_descriptions: dict[str, str],
    env_params: dict[str, set[str]],
) -> str:
    desc_parts = ["[Environments]"]
    for env in visible_envs:
        env_desc = env_descriptions.get(env, "")
        desc_parts.append(f"- {env}: {env_desc}")

    visible_param_notes: list[str] = []
    for param, param_env_set in sorted(env_params.items()):
        visible_param_envs = [env for env in visible_envs if env in param_env_set]
        if visible_param_envs:
            visible_param_notes.append(
                f"- {param}: Only supported on {', '.join(visible_param_envs)}."
            )

    if visible_param_notes:
        desc_parts.append("")
        desc_parts.append("[Parameter Notes]")
        desc_parts.extend(visible_param_notes)

    desc_parts.append("")
    desc_parts.append(base_description)
    return "\n".join(desc_parts)


def build_visible_tool_view(tool: MergedTool, visible_envs: list[str]) -> MergedTool | None:
    visible_envs = [env for env in tool.available_envs if env in set(visible_envs)]
    if not visible_envs:
        return None

    properties = {
        **tool.input_schema.get("properties", {}),
        "env": {
            **tool.input_schema.get("properties", {}).get("env", {}),
            "enum": visible_envs,
        },
    }
    schema = {
        **tool.input_schema,
        "properties": properties,
        "required": list(tool.input_schema.get("required", [])),
    }
    filtered_env_params = {
        param: {env for env in envs if env in visible_envs}
        for param, envs in tool.env_params.items()
        if any(env in visible_envs for env in envs)
    }
    return MergedTool(
        name=tool.name,
        description=_build_description(
            tool.base_description,
            visible_envs,
            tool.env_descriptions,
            filtered_env_params,
        ),
        input_schema=schema,
        available_envs=visible_envs,
        env_params=filtered_env_params,
        base_description=tool.base_description,
        env_descriptions={env: tool.env_descriptions.get(env, "") for env in visible_envs},
    )


def validate_and_merge(
    discovered: dict[str, list[dict[str, Any]]],
    env_descriptions: dict[str, str],
) -> MergeResult:
    """Merge tool definitions from multiple environments."""
    result = MergeResult()

    # Group tools by name across envs
    tool_envs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for env_name, tools in discovered.items():
        for tool in tools:
            tool_envs[tool["name"]][env_name] = tool

    for tool_name, env_tool_map in tool_envs.items():
        envs = sorted(env_tool_map.keys())

        # Check description consistency
        descriptions = {env: env_tool_map[env]["description"] for env in envs}
        unique_descs = set(descriptions.values())
        if len(unique_descs) > 1:
            result.errors.append(MergeError(
                tool_name=tool_name,
                message=f"Description mismatch across environments: {descriptions}",
            ))
            continue

        original_description = next(iter(unique_descs))

        # Gather all properties and required sets per env
        env_properties: dict[str, dict[str, Any]] = {}
        env_required: dict[str, set[str]] = {}
        for env in envs:
            schema = env_tool_map[env]["inputSchema"]
            env_properties[env] = schema.get("properties", {})
            env_required[env] = set(schema.get("required", []))

        # Find all param names across all envs
        all_params: set[str] = set()
        for props in env_properties.values():
            all_params.update(props.keys())

        # For each param, determine which envs have it
        param_envs: dict[str, set[str]] = {}
        for param in all_params:
            param_envs[param] = {env for env in envs if param in env_properties[env]}

        # Check type consistency for shared params
        has_error = False
        for param in all_params:
            owning_envs = param_envs[param]
            if len(owning_envs) < 2:
                continue
            schemas = {env: env_properties[env][param] for env in owning_envs}
            types = {env: s.get("type") for env, s in schemas.items()}
            # Make types hashable for comparison (lists like ["string", "null"] aren't)
            def _hashable(v: Any) -> Any:
                if isinstance(v, list):
                    return tuple(v)
                if isinstance(v, dict):
                    return tuple(sorted(v.items()))
                return v
            unique_types = set(_hashable(v) for v in types.values())
            if len(unique_types) > 1:
                result.errors.append(MergeError(
                    tool_name=tool_name,
                    message=f"Type mismatch for parameter '{param}': {types}",
                ))
                has_error = True

        if has_error:
            continue

        # Identify extra params (on some envs but not all)
        env_specific_params: dict[str, set[str]] = {}
        for param in all_params:
            if param_envs[param] != set(envs):
                env_specific_params[param] = param_envs[param]
                result.warnings.append(MergeWarning(
                    tool_name=tool_name,
                    message=f"Parameter '{param}' only available on: {sorted(param_envs[param])}",
                ))

        # Build merged properties
        merged_properties: dict[str, Any] = {}
        for param in all_params:
            # Take schema from any env that has it
            source_env = next(iter(param_envs[param]))
            merged_properties[param] = dict(env_properties[source_env][param])

        # Build merged required: params required on ALL envs that have them,
        # but only if they exist on ALL envs
        merged_required: list[str] = []
        for param in all_params:
            if param in env_specific_params:
                # Extra params are always optional
                continue
            # Check if required on all envs
            if all(param in env_required[env] for env in envs):
                merged_required.append(param)

        # Add env parameter
        merged_properties["env"] = {
            "type": "string",
            "enum": envs,
        }
        merged_required.append("env")

        merged_description = _build_description(
            original_description,
            envs,
            {env: env_descriptions.get(env, "") for env in envs},
            env_specific_params,
        )

        merged_schema = {
            "type": "object",
            "properties": merged_properties,
            "required": merged_required,
        }

        result.tools.append(MergedTool(
            name=tool_name,
            description=merged_description,
            input_schema=merged_schema,
            available_envs=envs,
            env_params=env_specific_params,
            base_description=original_description,
            env_descriptions={env: env_descriptions.get(env, "") for env in envs},
        ))

    return result
