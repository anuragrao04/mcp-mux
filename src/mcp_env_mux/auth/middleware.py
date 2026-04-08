"""FastMCP RBAC middleware for mcp-env-mux."""

from __future__ import annotations

from fastmcp.server.middleware import Middleware, MiddlewareContext

from mcp_env_mux.auth.rbac import is_allowed
from mcp_env_mux.config import RoleConfig


class RBACMiddleware(Middleware):
    """Enforce role-based access control on every tool call.

    Checks the authenticated user's roles (from the JWT) against the configured
    role definitions. Returns a ToolError with a 403 message if access is denied.
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

        # Attempt to get JWT claims via FastMCP's access-token context
        roles: list[str] = []
        try:
            from fastmcp.server.dependencies import get_access_token  # type: ignore[import]

            token = get_access_token()
            if token is not None:
                roles = token.claims.get("roles", [])
        except Exception:
            # Fallback: try to decode JWT from HTTP request directly
            try:
                from fastmcp.server.dependencies import get_http_request  # type: ignore[import]
                import jwt as pyjwt

                request = get_http_request()
                auth_header = request.headers.get("authorization", "")
                raw_token = auth_header.removeprefix("Bearer ").strip()
                if raw_token:
                    # Decode without verifying — JWTVerifier already did that
                    claims = pyjwt.decode(raw_token, options={"verify_signature": False})
                    roles = claims.get("roles", [])
            except Exception:
                pass  # Cannot determine roles; deny below

        if not is_allowed(roles, self.role_definitions, env, tool_name):
            from fastmcp.exceptions import ToolError  # type: ignore[import]

            raise ToolError(
                f"Access denied: role does not permit calling tool {tool_name!r} "
                f"in environment {env!r}"
            )

        return await call_next(context)
