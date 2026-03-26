"""FastMCP server setup, tool registration, and call routing."""

from __future__ import annotations

from typing import Any, Callable

from fastmcp import FastMCP
from fastmcp.tools.function_tool import FunctionTool

from mcp_env_mux.merge import MergedTool


def _make_handler(tool: MergedTool, clients: dict[str, Any]) -> Callable:
    """Create an async handler that routes calls to the correct backend."""

    async def handler(**kwargs: Any) -> Any:
        env = kwargs.get("env")
        if env is None:
            raise ValueError(f"Missing required parameter 'env' for tool '{tool.name}'")
        if env not in tool.available_envs:
            raise ValueError(
                f"Invalid env '{env}' for tool '{tool.name}'. "
                f"Available: {tool.available_envs}"
            )

        # Strip env from forwarded args
        args = {k: v for k, v in kwargs.items() if k != "env"}

        # Strip params not supported by the target env
        for param, param_envs in tool.env_params.items():
            if env not in param_envs and param in args:
                del args[param]

        client = clients[env]
        result = await client.call_tool(tool.name, args)
        # Return the content list for proper FastMCP serialization
        if hasattr(result, "content"):
            return result.content
        return result

    return handler


def create_proxy_server(
    merged_tools: list[MergedTool],
    clients: dict[str, Any],
) -> FastMCP:
    """Create a FastMCP server with tools registered for routing."""
    server = FastMCP("mcp-env-mux")

    for tool in merged_tools:
        handler = _make_handler(tool, clients)
        fn_tool = FunctionTool(
            fn=handler,
            name=tool.name,
            description=tool.description,
            parameters=tool.input_schema,
        )
        server.add_tool(fn_tool)

    return server
