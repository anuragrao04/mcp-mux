from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mcp_env_mux.auth.middleware import RBACMiddleware
from mcp_env_mux.config import RoleConfig
from mcp_env_mux.merge import MergedTool


class DummyTool:
    def __init__(self, name: str, description: str, input_schema: dict):
        self.name = name
        self.description = description
        self.inputSchema = input_schema


def make_merged_tool() -> MergedTool:
    return MergedTool(
        name="query",
        description="[Environments]\n- prod: Production.\n- staging: Staging.\n\n[Parameter Notes]\n- timeout: Only supported on prod.\n\nRun a query.",
        input_schema={
            "type": "object",
            "properties": {
                "env": {"type": "string", "enum": ["prod", "staging"]},
                "sql": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["env", "sql"],
        },
        available_envs=["prod", "staging"],
        env_params={"timeout": {"prod"}},
        base_description="Run a query.",
        env_descriptions={"prod": "Production.", "staging": "Staging."},
    )


def make_roles() -> dict[str, RoleConfig]:
    return {
        "admin": RoleConfig(allowed_envs={"*": ["*"]}),
        "staging-reader": RoleConfig(allowed_envs={"staging": ["query"]}),
    }


@pytest.mark.asyncio
async def test_on_list_tools_filters_envs_and_description():
    merged = make_merged_tool()
    middleware = RBACMiddleware(make_roles(), {"query": merged})
    context = SimpleNamespace(message=None)
    original_tool = DummyTool("query", merged.description, merged.input_schema)

    async def call_next(_context):
        return [original_tool]

    token = SimpleNamespace(claims={"roles": ["staging-reader"]})
    with patch("fastmcp.server.dependencies.get_access_token", return_value=token):
        tools = await middleware.on_list_tools(context, call_next)

    assert len(tools) == 1
    tool = tools[0]
    assert tool.inputSchema["properties"]["env"]["enum"] == ["staging"]
    assert "staging" in tool.description
    assert "prod" not in tool.description
    assert "timeout" not in tool.description


@pytest.mark.asyncio
async def test_on_list_tools_omits_tool_when_no_visible_envs():
    merged = make_merged_tool()
    middleware = RBACMiddleware(make_roles(), {"query": merged})
    context = SimpleNamespace(message=None)
    original_tool = DummyTool("query", merged.description, merged.input_schema)

    async def call_next(_context):
        return [original_tool]

    token = SimpleNamespace(claims={"roles": ["unknown"]})
    with patch("fastmcp.server.dependencies.get_access_token", return_value=token):
        tools = await middleware.on_list_tools(context, call_next)

    assert tools == []


@pytest.mark.asyncio
async def test_on_list_tools_does_not_mutate_shared_tool_object():
    merged = make_merged_tool()
    middleware = RBACMiddleware(make_roles(), {"query": merged})
    context = SimpleNamespace(message=None)
    original_tool = DummyTool("query", merged.description, merged.input_schema)

    async def call_next(_context):
        return [original_tool]

    token = SimpleNamespace(claims={"roles": ["staging-reader"]})
    with patch("fastmcp.server.dependencies.get_access_token", return_value=token):
        tools = await middleware.on_list_tools(context, call_next)

    assert tools[0] is not original_tool
    assert original_tool.inputSchema["properties"]["env"]["enum"] == ["prod", "staging"]
    assert "prod" in original_tool.description
