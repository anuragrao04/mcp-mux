"""FastMCP server setup, tool registration, and call routing."""

from __future__ import annotations

from typing import Any, Callable

import logging

from fastmcp import FastMCP
from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from fastmcp.tools.function_tool import FunctionTool

from mcp_env_mux.config import AuthConfig
from mcp_env_mux.merge import MergedTool
from mcp_env_mux.metrics.http import register_metrics_route
from mcp_env_mux.metrics.registry import Metrics
from mcp_env_mux.metrics.tooling import instrument_tool_call


def _make_handler(
    tool: MergedTool,
    clients: dict[str, Any],
    metrics: Metrics | None = None,
) -> Callable:
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

        async def invoke() -> Any:
            result = await client.call_tool(tool.name, args)
            if hasattr(result, "content"):
                return result.content
            return result

        return await instrument_tool_call(
            metrics,
            tool=tool.name,
            env=env,
            invoke=invoke,
        )

    return handler


def create_proxy_server(
    merged_tools: list[MergedTool],
    clients: dict[str, Any],
    auth_config: AuthConfig | None = None,
    private_key: Any = None,
    public_key: Any = None,
    metrics: Metrics | None = None,
) -> FastMCP:
    """Create a FastMCP server with tools registered for routing.

    When auth_config is provided, attaches a HybridAzureProvider (Azure OAuth
    + locally-signed bot JWT verification), token minting UI, and RBAC
    middleware. Otherwise creates a plain server (backward-compatible with
    all existing tests).
    """
    logger = logging.getLogger("mcp_env_mux")

    if auth_config is not None and public_key is not None:
        from cryptography.hazmat.primitives import serialization

        from mcp_env_mux.auth.hybrid import HybridAzureProvider
        from mcp_env_mux.auth.middleware import RBACMiddleware
        from mcp_env_mux.auth.ui import register_ui_routes

        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        auth = HybridAzureProvider(
            client_id=auth_config.azure.client_id,
            client_secret=auth_config.azure.client_secret,
            tenant_id=auth_config.azure.tenant_id,
            base_url=auth_config.base_url,
            required_scopes=auth_config.required_scopes,
            local_public_key_pem=public_key_pem,
            metrics=metrics,
        )
        server = FastMCP("mcp-env-mux", auth=auth)

        register_ui_routes(server, auth_config, private_key, auth, metrics=metrics)
        server.add_middleware(StructuredLoggingMiddleware(logger=logger))
        server.add_middleware(RBACMiddleware(auth_config.roles, {tool.name: tool for tool in merged_tools}, metrics=metrics))
    else:
        server = FastMCP("mcp-env-mux")
        server.add_middleware(StructuredLoggingMiddleware(logger=logger))

    if metrics is not None and metrics.enabled:
        register_metrics_route(server, metrics)

    for tool in merged_tools:
        handler = _make_handler(tool, clients, metrics=metrics)
        fn_tool = FunctionTool(
            fn=handler,
            name=tool.name,
            description=tool.description,
            parameters=tool.input_schema,
        )
        server.add_tool(fn_tool)

    return server
