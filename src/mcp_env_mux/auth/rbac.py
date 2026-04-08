"""RBAC permission logic for mcp-env-mux."""

from __future__ import annotations

from fnmatch import fnmatch

from mcp_env_mux.config import RoleConfig


def is_allowed(
    user_roles: list[str],
    role_definitions: dict[str, RoleConfig],
    requested_env: str,
    requested_tool: str,
) -> bool:
    """Check if a user with the given roles may call requested_tool in requested_env.

    Permission model:
    - For each role the user holds, look up its allowed_envs map
    - For each env_pattern that matches requested_env (via fnmatch), collect
      the corresponding tool patterns into a union set
    - If requested_tool matches any pattern in the union → allowed
    - Multi-role permissions are unioned (pure allowlist, no deny override)
    """
    unified_tool_patterns: list[str] = []

    for role_name in user_roles:
        role_cfg = role_definitions.get(role_name)
        if role_cfg is None:
            continue  # unknown role grants nothing
        for env_pattern, tool_patterns in role_cfg.allowed_envs.items():
            if fnmatch(requested_env, env_pattern):
                unified_tool_patterns.extend(tool_patterns)

    return any(fnmatch(requested_tool, pattern) for pattern in unified_tool_patterns)
