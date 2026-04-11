# rbac.py

## Purpose

RBAC permission logic for mcp-env-mux. Determines whether a user with a given set of roles is allowed to call a specific tool in a specific environment.

## Public API

### `is_allowed(user_roles: list[str], role_definitions: dict[str, RoleConfig], requested_env: str, requested_tool: str) -> bool`

Checks if a user holding `user_roles` may call `requested_tool` in `requested_env`.

Permission model:
1. For each role the user holds, look up its `allowed_envs` map in `role_definitions`.
2. For each env pattern that matches `requested_env` (via `fnmatch`), collect the tool patterns.
3. If `requested_tool` matches any collected tool pattern (via `fnmatch`) → allowed.
4. Multi-role permissions are unioned (pure allowlist, no deny override).
5. Unknown roles (not in `role_definitions`) grant nothing.

Examples:
- `allowed_envs: {"*": ["*"]}` → all tools in all envs.
- `allowed_envs: {"prod": ["logs*"]}` → only tools matching `logs*` in the `prod` env.

## Dependencies

- `mcp_env_mux.config.RoleConfig`
- `fnmatch` (stdlib) for glob-style pattern matching

## Error Handling

No exceptions raised. Returns `False` if no roles match or no patterns match.
