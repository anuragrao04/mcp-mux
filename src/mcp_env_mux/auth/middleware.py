"""FastMCP RBAC middleware for mcp-env-mux."""

from __future__ import annotations

from fastmcp.server.middleware import Middleware, MiddlewareContext

from mcp_env_mux.auth.rbac import is_allowed
from mcp_env_mux.config import RoleConfig


class RBACMiddleware(Middleware):
    """Enforce role-based access control on every tool call.

    Reads the authenticated principal's roles from
    ``get_access_token().claims["roles"]`` (populated by the auth provider)
    and checks them against the configured role definitions. Raises
    ``ToolError`` on denial.
    """

    def __init__(self, role_definitions: dict[str, RoleConfig]) -> None:
        self.role_definitions = role_definitions

    async def on_call_tool(self, context: MiddlewareContext, call_next):  # type: ignore[override]
        tool_name = context.message.name
        arguments = getattr(context.message, "arguments", None) or {}
        env = arguments.get("env")

        if env is None:
            # Tool has no env parameter — let it through (handler will error)
            return await call_next(context)

        from fastmcp.server.dependencies import get_access_token  # type: ignore[import]

        token = get_access_token()
        roles = token.claims.get("roles", []) if token else []

        if not is_allowed(roles, self.role_definitions, env, tool_name):
            from fastmcp.exceptions import ToolError  # type: ignore[import]

            raise ToolError(
                f"Access denied: role does not permit calling tool {tool_name!r} "
                f"in environment {env!r}"
            )

        return await call_next(context)
