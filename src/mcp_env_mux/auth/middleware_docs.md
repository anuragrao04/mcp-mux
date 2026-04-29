# middleware.py

## Purpose

FastMCP RBAC middleware that intercepts every tool call and enforces role-based access control. Reads the authenticated principal's roles from `get_access_token().claims["roles"]` and checks them against configured role definitions.

## Public API

### `RBACMiddleware(Middleware)`

A FastMCP `Middleware` subclass. Instantiated with `role_definitions: dict[str, RoleConfig]`.

#### `on_call_tool(context: MiddlewareContext, call_next) -> Any`

Logic:

1. Extract `tool_name` from `context.message.name`.
2. Extract `env` from `context.message.arguments`. If absent (tool has no `env` param), passthrough — the handler will raise its own validation error.
3. `token = get_access_token()` — populated by FastMCP after the auth provider verifies the bearer.
4. `roles = token.claims.get("roles", []) if token else []`.
5. If `rbac.is_allowed(roles, self.role_definitions, env, tool_name)` is False, raise `ToolError` with a 403-style message.
6. Otherwise, `await call_next(context)`.

The previous implementation had a fallback that decoded the JWT directly from the request header on top of `get_access_token()`. **Removed.** With `HybridAzureProvider` populating the access-token context correctly for both user and bot tokens, the fallback is unnecessary. Keep this module focused.

## Dependencies

- `fastmcp.server.middleware.Middleware`, `MiddlewareContext`
- `fastmcp.server.dependencies.get_access_token`
- `fastmcp.exceptions.ToolError`
- `mcp_env_mux.auth.rbac.is_allowed`
- `mcp_env_mux.config.RoleConfig`

## Error Handling

- If no access token in context (auth was disabled or failed upstream), `roles` is empty and `is_allowed` returns False → `ToolError`.
- `ToolError` raised on access denial; message includes tool name and environment.
