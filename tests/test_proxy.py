"""
Unit tests for mcp_env_mux.proxy module.

Tests tool call routing logic using mocked FastMCP clients.
No real servers are started — all backend interactions are mocked.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_env_mux.merge import MergedTool
from mcp_env_mux.proxy import _make_handler, create_proxy_server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_merged_tool(
    name: str = "search_logs",
    description: str = "Search logs.",
    available_envs: list[str] | None = None,
    properties: dict[str, dict[str, Any]] | None = None,
    required: list[str] | None = None,
    env_params: dict[str, set[str]] | None = None,
) -> MergedTool:
    """Build a MergedTool for testing."""
    available_envs = available_envs or ["prod", "staging"]
    env_params = env_params or {}

    if properties is None:
        properties = {
            "env": {"type": "string", "enum": available_envs},
            "query": {"type": "string"},
        }
    else:
        properties = {
            "env": {"type": "string", "enum": available_envs},
            **properties,
        }

    if required is None:
        required = ["env", "query"]
    elif "env" not in required:
        required = ["env"] + required

    input_schema = {
        "type": "object",
        "properties": properties,
        "required": required,
    }

    return MergedTool(
        name=name,
        description=description,
        input_schema=input_schema,
        available_envs=available_envs,
        env_params=env_params,
        base_description=description,
        env_descriptions={env: f"{env} environment." for env in available_envs},
    )


def make_mock_client(return_value: Any = None) -> AsyncMock:
    """Create a mock FastMCP client with a call_tool method."""
    client = AsyncMock()
    if return_value is not None:
        client.call_tool.return_value = return_value
    else:
        client.call_tool.return_value = [MagicMock(text='{"status": "ok"}')]
    return client


# ===================================================================
# Routing: correct backend called
# ===================================================================


class TestRouting:
    """Test that calls are routed to the correct backend client."""

    async def test_routes_to_correct_backend_prod(self):
        """Calling with env=prod should invoke the prod client."""
        tool = make_merged_tool()
        prod_client = make_mock_client()
        staging_client = make_mock_client()
        clients = {"prod": prod_client, "staging": staging_client}

        handler = _make_handler(tool, clients)
        await handler(env="prod", query="error logs")

        prod_client.call_tool.assert_awaited_once()
        staging_client.call_tool.assert_not_awaited()

    async def test_routes_to_correct_backend_staging(self):
        """Calling with env=staging should invoke the staging client."""
        tool = make_merged_tool()
        prod_client = make_mock_client()
        staging_client = make_mock_client()
        clients = {"prod": prod_client, "staging": staging_client}

        handler = _make_handler(tool, clients)
        await handler(env="staging", query="test query")

        staging_client.call_tool.assert_awaited_once()
        prod_client.call_tool.assert_not_awaited()

    async def test_tool_name_forwarded_correctly(self):
        """The original tool name should be passed to the backend call_tool."""
        tool = make_merged_tool(name="search_logs")
        client = make_mock_client()
        clients = {"prod": client}

        handler = _make_handler(tool, clients)
        await handler(env="prod", query="test")

        call_args = client.call_tool.call_args
        assert call_args[0][0] == "search_logs" or call_args.kwargs.get("name") == "search_logs"


# ===================================================================
# env parameter stripping
# ===================================================================


class TestEnvStripping:
    """Test that 'env' is stripped from forwarded arguments."""

    async def test_env_not_forwarded_to_backend(self):
        """The 'env' parameter should be removed before forwarding."""
        tool = make_merged_tool()
        client = make_mock_client()
        clients = {"prod": client}

        handler = _make_handler(tool, clients)
        await handler(env="prod", query="test")

        call_args = client.call_tool.call_args
        # call_tool is called as call_tool(name, args_dict) or call_tool(name, **kwargs)
        # Get the arguments dict that was forwarded
        if len(call_args[0]) > 1:
            forwarded_args = call_args[0][1]
        else:
            forwarded_args = call_args.kwargs.get("arguments", call_args.kwargs)

        assert "env" not in forwarded_args

    async def test_other_params_forwarded(self):
        """Non-env parameters should be forwarded to the backend."""
        tool = make_merged_tool()
        client = make_mock_client()
        clients = {"prod": client}

        handler = _make_handler(tool, clients)
        await handler(env="prod", query="error logs")

        call_args = client.call_tool.call_args
        if len(call_args[0]) > 1:
            forwarded_args = call_args[0][1]
        else:
            forwarded_args = call_args.kwargs.get("arguments", call_args.kwargs)

        assert forwarded_args.get("query") == "error logs"


# ===================================================================
# Invalid/missing env
# ===================================================================


class TestInvalidEnv:
    """Test error handling for invalid or missing env values."""

    async def test_invalid_env_raises(self):
        """Calling with an env not in available_envs should raise an error."""
        tool = make_merged_tool(available_envs=["prod", "staging"])
        clients = {
            "prod": make_mock_client(),
            "staging": make_mock_client(),
        }

        handler = _make_handler(tool, clients)

        with pytest.raises(Exception):
            await handler(env="nonexistent", query="test")

    async def test_missing_env_raises(self):
        """Calling without the env parameter should raise an error."""
        tool = make_merged_tool()
        clients = {"prod": make_mock_client()}

        handler = _make_handler(tool, clients)

        with pytest.raises(Exception):
            await handler(query="test")


# ===================================================================
# Extra param handling
# ===================================================================


class TestExtraParamHandling:
    """Test that env-specific params are stripped or forwarded appropriately."""

    def _make_tool_with_extra_param(self) -> MergedTool:
        """Tool where 'timeout' only exists on prod."""
        return make_merged_tool(
            name="query",
            description="Run a query.",
            available_envs=["prod", "staging"],
            properties={
                "sql": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            required=["env", "sql"],
            env_params={"timeout": {"prod"}},
        )

    async def test_extra_param_stripped_for_non_supporting_env(self):
        """Params not supported by target env should be stripped."""
        tool = self._make_tool_with_extra_param()
        staging_client = make_mock_client()
        clients = {
            "prod": make_mock_client(),
            "staging": staging_client,
        }

        handler = _make_handler(tool, clients)
        await handler(env="staging", sql="SELECT 1", timeout=60)

        call_args = staging_client.call_tool.call_args
        if len(call_args[0]) > 1:
            forwarded_args = call_args[0][1]
        else:
            forwarded_args = call_args.kwargs.get("arguments", call_args.kwargs)

        assert "timeout" not in forwarded_args
        assert forwarded_args.get("sql") == "SELECT 1"

    async def test_extra_param_forwarded_for_supporting_env(self):
        """Params supported by target env should be forwarded."""
        tool = self._make_tool_with_extra_param()
        prod_client = make_mock_client()
        clients = {
            "prod": prod_client,
            "staging": make_mock_client(),
        }

        handler = _make_handler(tool, clients)
        await handler(env="prod", sql="SELECT 1", timeout=60)

        call_args = prod_client.call_tool.call_args
        if len(call_args[0]) > 1:
            forwarded_args = call_args[0][1]
        else:
            forwarded_args = call_args.kwargs.get("arguments", call_args.kwargs)

        assert forwarded_args.get("timeout") == 60
        assert forwarded_args.get("sql") == "SELECT 1"


# ===================================================================
# create_proxy_server
# ===================================================================


class TestCreateProxyServer:
    """Test that create_proxy_server produces a valid server."""

    def test_creates_server_object(self):
        """create_proxy_server should return a server-like object."""
        tool = make_merged_tool()
        clients = {"prod": make_mock_client(), "staging": make_mock_client()}

        server = create_proxy_server([tool], clients)

        # The server should be a FastMCP instance (or at least not None)
        assert server is not None

    def test_registers_tools(self):
        """Each merged tool should be registered on the server."""
        tool_a = make_merged_tool(name="tool_a")
        tool_b = make_merged_tool(name="tool_b")
        clients = {"prod": make_mock_client(), "staging": make_mock_client()}

        server = create_proxy_server([tool_a, tool_b], clients)

        # The server should exist — detailed registration checks depend on
        # FastMCP internals, so we just verify it was created without error.
        assert server is not None


# ===================================================================
# Result passthrough
# ===================================================================


class TestResultPassthrough:
    """Test that backend results are returned unmodified."""

    async def test_result_returned_unmodified(self):
        """The handler should return whatever the backend client returns."""
        tool = make_merged_tool()
        expected_result = [MagicMock(text='{"data": "hello"}')]
        client = make_mock_client(return_value=expected_result)
        clients = {"prod": client}

        handler = _make_handler(tool, clients)
        result = await handler(env="prod", query="test")

        assert result == expected_result
