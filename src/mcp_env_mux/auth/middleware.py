"""FastMCP RBAC middleware for mcp-env-mux."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from fastmcp.server.middleware import Middleware, MiddlewareContext

from mcp_env_mux.auth.rbac import is_allowed
from mcp_env_mux.config import RoleConfig
from mcp_env_mux.merge import MergedTool, build_visible_tool_view
from mcp_env_mux.metrics.auth import record_rbac_decision
from mcp_env_mux.metrics.helpers import principal_type_from_claims
from mcp_env_mux.metrics.registry import Metrics


class RBACMiddleware(Middleware):
    """Enforce role-based access control on every tool call.

    Reads the authenticated principal's roles from
    ``get_access_token().claims["roles"]`` (populated by the auth provider)
    and checks them against the configured role definitions. Raises
    ``ToolError`` on denial.
    """

    def __init__(
        self,
        role_definitions: dict[str, RoleConfig],
        merged_tools: dict[str, MergedTool] | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self.role_definitions = role_definitions
        self.merged_tools = merged_tools or {}
        self.metrics = metrics

    def _get_roles(self) -> list[str]:
        from fastmcp.server.dependencies import get_access_token  # type: ignore[import]

        token = get_access_token()
        return token.claims.get("roles", []) if token else []

    def _visible_envs_for_tool(self, roles: list[str], tool: MergedTool) -> list[str]:
        return [
            env for env in tool.available_envs
            if is_allowed(roles, self.role_definitions, env, tool.name)
        ]

    async def on_list_tools(self, context: MiddlewareContext, call_next):  # type: ignore[override]
        tools = await call_next(context)
        if not self.merged_tools:
            return tools

        roles = self._get_roles()
        filtered_tools = []
        for tool in tools:
            merged = self.merged_tools.get(tool.name)
            if merged is None:
                filtered_tools.append(tool)
                continue

            visible_envs = self._visible_envs_for_tool(roles, merged)
            visible_tool = build_visible_tool_view(merged, visible_envs)
            if visible_tool is None:
                continue

            cloned = deepcopy(tool)
            cloned.description = visible_tool.description
            if hasattr(cloned, "inputSchema"):
                cloned.inputSchema = visible_tool.input_schema
            elif hasattr(cloned, "parameters"):
                cloned.parameters = visible_tool.input_schema
            else:
                cloned = SimpleNamespace(
                    name=tool.name,
                    description=visible_tool.description,
                    inputSchema=visible_tool.input_schema,
                )
            filtered_tools.append(cloned)
        return filtered_tools

    async def on_call_tool(self, context: MiddlewareContext, call_next):  # type: ignore[override]
        tool_name = context.message.name
        arguments = getattr(context.message, "arguments", None) or {}
        env = arguments.get("env")

        if env is None:
            # Tool has no env parameter — let it through (handler will error)
            return await call_next(context)

        roles = self._get_roles()
        principal_type = "unknown"
        try:
            from fastmcp.server.dependencies import get_access_token  # type: ignore[import]

            token = get_access_token()
            principal_type = principal_type_from_claims(token.claims if token else None)
        except Exception:
            principal_type = "unknown"

        if not is_allowed(roles, self.role_definitions, env, tool_name):
            record_rbac_decision(
                self.metrics,
                tool=tool_name,
                env=env,
                decision="deny",
                principal_type=principal_type,
            )
            from fastmcp.exceptions import ToolError  # type: ignore[import]

            raise ToolError(
                f"Access denied: role does not permit calling tool {tool_name!r} "
                f"in environment {env!r}"
            )

        record_rbac_decision(
            self.metrics,
            tool=tool_name,
            env=env,
            decision="allow",
            principal_type=principal_type,
        )
        return await call_next(context)
