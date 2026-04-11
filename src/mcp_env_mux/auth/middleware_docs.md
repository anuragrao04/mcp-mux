# middleware.py

## Purpose

FastMCP RBAC middleware that intercepts every tool call and enforces role-based access control. Extracts the user's roles from the JWT and checks them against configured role definitions before allowing the call through.

## Public API

### `RBACMiddleware(Middleware)`

A FastMCP `Middleware` subclass. Instantiated with `role_definitions: dict[str, RoleConfig]`.

#### `on_call_tool(context: MiddlewareContext, call_next) -> Any`

Intercept logic:
1. Extracts `tool_name` and `env` from the call arguments.
2. If `env` is `None` (tool has no env param), passes through to `call_next`.
3. Attempts to read JWT roles via FastMCP's `get_access_token()`.
4. Fallback: decodes the JWT from the HTTP `Authorization` header directly (without signature verification — assumes `JWTVerifier` already validated it upstream).
5. Calls `rbac.is_allowed(roles, role_definitions, env, tool_name)`.
6. If denied, raises `ToolError` with a 403-style message.
7. If allowed, calls `call_next(context)`.

## Dependencies

- `fastmcp.server.middleware.Middleware`, `MiddlewareContext`
- `fastmcp.server.dependencies.get_access_token`, `get_http_request` (lazy imports)
- `fastmcp.exceptions.ToolError` (lazy import)
- `mcp_env_mux.auth.rbac.is_allowed`
- `mcp_env_mux.config.RoleConfig`
- `jwt` (PyJWT) for fallback token decoding

## Error Handling

- Role extraction failures (both primary and fallback paths) are caught silently; if roles cannot be determined, the empty role list will cause `is_allowed` to return `False`, and `ToolError` is raised.
- `ToolError` raised on access denial with tool name and environment in the message.
