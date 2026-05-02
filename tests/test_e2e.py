"""
End-to-end tests for mcp-env-mux.

These tests validate the external behavior of the proxy by:
1. Starting real FastMCP backend servers with known tool schemas.
2. Starting the mcp-env-mux proxy pointed at those backends.
3. Connecting a FastMCP client to the proxy.
4. Asserting on the merged tool list and tool call results.
"""

from __future__ import annotations

import asyncio
import json
import os
import textwrap
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from conftest import (
    MockBackend,
    find_free_port,
    run_test_schema,
    start_backend,
    start_proxy,
    write_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ECHO_HANDLER = lambda kw: json.dumps({"echoed": kw})  # noqa: E731


def tool_def(
    description: str,
    params: dict[str, dict[str, Any]] | None = None,
    handler: Any = None,
) -> dict[str, Any]:
    return {
        "description": description,
        "params": params or {},
        "handler": handler or ECHO_HANDLER,
    }


def find_tool(tools: list, name: str):
    """Find a tool by name in a list of Tool objects."""
    for t in tools:
        if t.name == name:
            return t
    return None


def get_input_schema(tool) -> dict:
    """Extract the inputSchema dict from a tool object."""
    return tool.inputSchema if hasattr(tool, "inputSchema") else tool.model_dump().get("inputSchema", {})


# ===================================================================
# Test: Basic tool merging
# ===================================================================


class TestToolMerging:
    """Verify that tools from multiple backends are merged with an env parameter."""

    @pytest.fixture(autouse=True)
    async def setup_backends(self, tmp_path):
        """Start two identical backends and the proxy."""
        self.backends: list[MockBackend] = []

        tools = {
            "search_logs": tool_def(
                description="Search logs by query string.",
                params={
                    "query": {"type": str, "required": True},
                    "limit": {"type": int, "required": False, "default": 100},
                },
            ),
            "get_alert": tool_def(
                description="Get alert by ID.",
                params={"alert_id": {"type": str, "required": True}},
            ),
        }

        for env_name in ("prod", "staging"):
            backend = await start_backend(f"backend-{env_name}", tools)
            self.backends.append(backend)

        config_path = write_config(
            {
                "prod": {
                    "description": "Production environment.",
                    "url": self.backends[0].url,
                },
                "staging": {
                    "description": "Staging environment.",
                    "url": self.backends[1].url,
                },
            },
            tmp_path,
        )

        self.proxy = start_proxy(config_path)
        yield
        self.proxy.stop()

    async def test_merged_tools_have_env_parameter(self):
        """Each merged tool should have a required 'env' parameter with enum values."""
        async with Client(self.proxy.url) as client:
            tools = await client.list_tools()
            tool_names = {t.name for t in tools}

            # Both tools should be present (not duplicated per environment)
            assert "search_logs" in tool_names
            assert "get_alert" in tool_names

            # Should NOT have duplicates — each tool appears once
            assert len([t for t in tools if t.name == "search_logs"]) == 1
            assert len([t for t in tools if t.name == "get_alert"]) == 1

    async def test_env_parameter_schema(self):
        """The env parameter should be a required string enum listing all environments."""
        async with Client(self.proxy.url) as client:
            tools = await client.list_tools()
            search_tool = find_tool(tools, "search_logs")
            schema = get_input_schema(search_tool)

            properties = schema.get("properties", {})
            assert "env" in properties, "Merged tool must have an 'env' parameter"

            env_prop = properties["env"]
            assert env_prop["type"] == "string"
            assert set(env_prop["enum"]) == {"prod", "staging"}

            # env should be required
            required = schema.get("required", [])
            assert "env" in required

    async def test_original_parameters_preserved(self):
        """Original tool parameters should still be present in the merged schema."""
        async with Client(self.proxy.url) as client:
            tools = await client.list_tools()
            search_tool = find_tool(tools, "search_logs")
            schema = get_input_schema(search_tool)
            properties = schema.get("properties", {})

            assert "query" in properties
            assert "limit" in properties

    async def test_description_includes_environment_info(self):
        """Merged tool description should include environment descriptions."""
        async with Client(self.proxy.url) as client:
            tools = await client.list_tools()
            search_tool = find_tool(tools, "search_logs")

            assert "prod" in search_tool.description.lower() or "prod" in search_tool.description
            assert "staging" in search_tool.description.lower() or "staging" in search_tool.description
            assert "Production environment." in search_tool.description
            assert "Staging environment." in search_tool.description


# ===================================================================
# Test: Tool call routing
# ===================================================================


class TestToolCallRouting:
    """Verify that tool calls are routed to the correct backend based on env."""

    @pytest.fixture(autouse=True)
    async def setup_backends(self, tmp_path):
        self.backends: list[MockBackend] = []

        def make_handler(env_name: str):
            return lambda kw: json.dumps({"from": env_name, "args": kw})

        for env_name in ("prod", "staging"):
            tools = {
                "get_status": tool_def(
                    description="Get system status.",
                    params={"service": {"type": str, "required": True}},
                    handler=make_handler(env_name),
                ),
            }
            backend = await start_backend(f"backend-{env_name}", tools)
            self.backends.append(backend)

        config_path = write_config(
            {
                "prod": {"description": "Prod.", "url": self.backends[0].url},
                "staging": {"description": "Staging.", "url": self.backends[1].url},
            },
            tmp_path,
        )

        self.proxy = start_proxy(config_path)
        yield
        self.proxy.stop()

    async def test_routes_to_prod(self):
        """Calling with env=prod should hit the prod backend."""
        async with Client(self.proxy.url) as client:
            result = await client.call_tool(
                "get_status", {"env": "prod", "service": "api"}
            )
            data = json.loads(result.content[0].text if hasattr(result, "content") else str(result))
            assert data["from"] == "prod"
            assert data["args"]["service"] == "api"

    async def test_routes_to_staging(self):
        """Calling with env=staging should hit the staging backend."""
        async with Client(self.proxy.url) as client:
            result = await client.call_tool(
                "get_status", {"env": "staging", "service": "api"}
            )
            data = json.loads(result.content[0].text if hasattr(result, "content") else str(result))
            assert data["from"] == "staging"
            assert data["args"]["service"] == "api"

    async def test_env_parameter_stripped_from_backend_call(self):
        """The env parameter should NOT be forwarded to the backend."""
        async with Client(self.proxy.url) as client:
            result = await client.call_tool(
                "get_status", {"env": "prod", "service": "db"}
            )
            data = json.loads(result.content[0].text if hasattr(result, "content") else str(result))
            # The handler echoes its kwargs — env should not be among them
            assert "env" not in data["args"]

    async def test_invalid_env_rejected(self):
        """Calling with an env not in the enum should fail."""
        async with Client(self.proxy.url) as client:
            with pytest.raises(Exception):
                await client.call_tool(
                    "get_status", {"env": "nonexistent", "service": "api"}
                )

    async def test_missing_env_rejected(self):
        """Calling without the required env parameter should fail."""
        async with Client(self.proxy.url) as client:
            with pytest.raises(Exception):
                await client.call_tool("get_status", {"service": "api"})


# ===================================================================
# Test: Horizontal scaling / stateless HTTP behavior
# ===================================================================


class TestJsonLogging:
    """Verify proxy emits JSON-only logs."""

    async def test_proxy_logs_are_json_only(self, tmp_path):
        backend = await start_backend(
            "json-log-be",
            {
                "echo": tool_def(
                    description="Echo a message.",
                    params={"msg": {"type": str, "required": True}},
                    handler=lambda kw: json.dumps({"echoed": kw["msg"]}),
                )
            },
        )
        config_path = write_config(
            {
                "prod": {
                    "description": "Production environment.",
                    "url": backend.url,
                }
            },
            tmp_path,
        )

        proxy = start_proxy(config_path, capture_logs=True)
        try:
            async with Client(proxy.url) as client:
                await client.list_tools()
                await client.call_tool("echo", {"env": "prod", "msg": "hello"})

            assert proxy.stdout_path is not None
            assert proxy.stderr_path is not None
            stdout_lines = [line.strip() for line in proxy.stdout_path.read_text().splitlines() if line.strip()]
            stderr_lines = [line.strip() for line in proxy.stderr_path.read_text().splitlines() if line.strip()]
            all_lines = stdout_lines + stderr_lines
            assert all_lines, "expected proxy to emit logs"
            for line in all_lines:
                json.loads(line)
        finally:
            proxy.stop()


class TestHorizontalScalingBehavior:
    """Verify proxy requests are safe without replica-local MCP session affinity."""

    async def test_repeated_fresh_clients_work_against_same_proxy(self, tmp_path):
        backend = await start_backend(
            "stateless-be",
            {
                "echo": tool_def(
                    description="Echo a message.",
                    params={"msg": {"type": str, "required": True}},
                    handler=lambda kw: json.dumps({"echoed": kw["msg"]}),
                )
            },
        )
        config_path = write_config(
            {
                "prod": {
                    "description": "Production environment.",
                    "url": backend.url,
                }
            },
            tmp_path,
        )

        proxy = start_proxy(config_path)
        try:
            for value in ("one", "two", "three"):
                async with Client(proxy.url) as client:
                    tools = await client.list_tools()
                    tool = find_tool(tools, "echo")
                    assert tool is not None
                    result = await client.call_tool("echo", {"env": "prod", "msg": value})
                    data = json.loads(result.content[0].text)
                    assert data["echoed"] == value
        finally:
            proxy.stop()

    async def test_multiple_proxy_replicas_behave_identically(self, tmp_path):
        backend = await start_backend(
            "replica-be",
            {
                "echo": tool_def(
                    description="Echo a message.",
                    params={"msg": {"type": str, "required": True}},
                    handler=lambda kw: json.dumps({"echoed": kw["msg"]}),
                )
            },
        )
        config_path = write_config(
            {
                "prod": {
                    "description": "Production environment.",
                    "url": backend.url,
                }
            },
            tmp_path,
        )

        proxy_a = start_proxy(config_path)
        proxy_b = start_proxy(config_path)
        try:
            async with Client(proxy_a.url) as client_a:
                tools_a = await client_a.list_tools()
                tool_a = find_tool(tools_a, "echo")
                assert tool_a is not None
                assert get_input_schema(tool_a)["properties"]["env"]["enum"] == ["prod"]
                result_a = await client_a.call_tool("echo", {"env": "prod", "msg": "from-a"})
                assert json.loads(result_a.content[0].text)["echoed"] == "from-a"

            async with Client(proxy_b.url) as client_b:
                tools_b = await client_b.list_tools()
                tool_b = find_tool(tools_b, "echo")
                assert tool_b is not None
                assert get_input_schema(tool_b)["properties"]["env"]["enum"] == ["prod"]
                result_b = await client_b.call_tool("echo", {"env": "prod", "msg": "from-b"})
                assert json.loads(result_b.content[0].text)["echoed"] == "from-b"
        finally:
            proxy_a.stop()
            proxy_b.stop()


# ===================================================================
# Test: Schema mismatch detection
# ===================================================================


class TestSchemaMismatch:
    """Verify that the proxy rejects backends with incompatible tool schemas."""

    async def test_description_mismatch_fails_startup(self, tmp_path):
        """Backends with the same tool name but different descriptions should fail."""
        backends = []
        for env_name, desc in [("prod", "Search logs."), ("staging", "Query log data.")]:
            tools = {
                "search": tool_def(
                    description=desc,
                    params={"q": {"type": str, "required": True}},
                ),
            }
            backend = await start_backend(f"backend-{env_name}", tools)
            backends.append(backend)

        config_path = write_config(
            {
                "prod": {"description": "Prod.", "url": backends[0].url},
                "staging": {"description": "Staging.", "url": backends[1].url},
            },
            tmp_path,
        )

        result = run_test_schema(config_path)
        assert result.returncode != 0, "Should fail when descriptions mismatch"
        assert "description" in result.stderr.lower() or "description" in result.stdout.lower()

    async def test_parameter_type_mismatch_fails_startup(self, tmp_path):
        """Same param name with different types across environments should fail."""
        backends = []
        for env_name, param_type in [("prod", str), ("staging", int)]:
            tools = {
                "lookup": tool_def(
                    description="Look up a record.",
                    params={"record_id": {"type": param_type, "required": True}},
                ),
            }
            backend = await start_backend(f"backend-{env_name}", tools)
            backends.append(backend)

        config_path = write_config(
            {
                "prod": {"description": "Prod.", "url": backends[0].url},
                "staging": {"description": "Staging.", "url": backends[1].url},
            },
            tmp_path,
        )

        result = run_test_schema(config_path)
        assert result.returncode != 0, "Should fail when parameter types mismatch"
        assert "type" in result.stderr.lower() or "type" in result.stdout.lower()


# ===================================================================
# Test: Subset tools (tool exists on some environments but not others)
# ===================================================================


class TestSubsetTools:
    """Verify tools available on a subset of environments get constrained env enums."""

    @pytest.fixture(autouse=True)
    async def setup_backends(self, tmp_path):
        # prod has both tools, staging only has "common_tool"
        prod_tools = {
            "common_tool": tool_def(
                description="Available everywhere.",
                params={"x": {"type": str, "required": True}},
            ),
            "prod_only_tool": tool_def(
                description="Only on prod.",
                params={"y": {"type": int, "required": True}},
            ),
        }
        staging_tools = {
            "common_tool": tool_def(
                description="Available everywhere.",
                params={"x": {"type": str, "required": True}},
            ),
        }

        self.prod = await start_backend("prod", prod_tools)
        self.staging = await start_backend("staging", staging_tools)

        config_path = write_config(
            {
                "prod": {"description": "Prod.", "url": self.prod.url},
                "staging": {"description": "Staging.", "url": self.staging.url},
            },
            tmp_path,
        )

        self.proxy = start_proxy(config_path)
        yield
        self.proxy.stop()

    async def test_common_tool_has_all_envs(self):
        """A tool present on all backends has all envs in its enum."""
        async with Client(self.proxy.url) as client:
            tools = await client.list_tools()
            common = find_tool(tools, "common_tool")
            schema = get_input_schema(common)
            env_enum = set(schema["properties"]["env"]["enum"])
            assert env_enum == {"prod", "staging"}

    async def test_subset_tool_has_constrained_env(self):
        """A tool only on prod should have env enum constrained to ['prod']."""
        async with Client(self.proxy.url) as client:
            tools = await client.list_tools()
            prod_only = find_tool(tools, "prod_only_tool")
            assert prod_only is not None, "prod_only_tool should be exposed"
            schema = get_input_schema(prod_only)
            env_enum = set(schema["properties"]["env"]["enum"])
            assert env_enum == {"prod"}

    async def test_subset_tool_rejects_wrong_env(self):
        """Calling a prod-only tool with env=staging should fail."""
        async with Client(self.proxy.url) as client:
            with pytest.raises(Exception):
                await client.call_tool(
                    "prod_only_tool", {"env": "staging", "y": 42}
                )


# ===================================================================
# Test: Extra parameters on some environments
# ===================================================================


class TestExtraParameters:
    """Verify that parameters unique to some environments are handled correctly."""

    @pytest.fixture(autouse=True)
    async def setup_backends(self, tmp_path):
        # prod has an extra "timeout" param, staging does not
        prod_tools = {
            "query": tool_def(
                description="Run a query.",
                params={
                    "sql": {"type": str, "required": True},
                    "timeout": {"type": int, "required": False, "default": 30},
                },
            ),
        }
        staging_tools = {
            "query": tool_def(
                description="Run a query.",
                params={
                    "sql": {"type": str, "required": True},
                },
            ),
        }

        self.prod = await start_backend("prod", prod_tools)
        self.staging = await start_backend("staging", staging_tools)

        config_path = write_config(
            {
                "prod": {"description": "Prod.", "url": self.prod.url},
                "staging": {"description": "Staging.", "url": self.staging.url},
            },
            tmp_path,
        )

        self.proxy = start_proxy(config_path)
        yield
        self.proxy.stop()

    async def test_extra_param_included_as_optional(self):
        """Extra parameters should appear in merged schema as optional."""
        async with Client(self.proxy.url) as client:
            tools = await client.list_tools()
            query_tool = find_tool(tools, "query")
            schema = get_input_schema(query_tool)

            properties = schema.get("properties", {})
            assert "timeout" in properties, "Extra param 'timeout' should be in merged schema"

            required = schema.get("required", [])
            assert "timeout" not in required, "Extra param should not be required"

    async def test_extra_param_noted_in_description(self):
        """Description should note which environments support extra params."""
        async with Client(self.proxy.url) as client:
            tools = await client.list_tools()
            query_tool = find_tool(tools, "query")
            desc = query_tool.description

            assert "timeout" in desc
            assert "prod" in desc.lower()

    async def test_extra_param_forwarded_to_supporting_env(self):
        """When calling an env that supports the extra param, it should be forwarded."""
        async with Client(self.proxy.url) as client:
            result = await client.call_tool(
                "query", {"env": "prod", "sql": "SELECT 1", "timeout": 60}
            )
            data = json.loads(result.content[0].text if hasattr(result, "content") else str(result))
            echoed = data.get("echoed", data.get("args", data))
            assert echoed.get("timeout") == 60

    async def test_extra_param_stripped_for_non_supporting_env(self):
        """When calling an env that doesn't support the extra param, it should be stripped."""
        async with Client(self.proxy.url) as client:
            result = await client.call_tool(
                "query", {"env": "staging", "sql": "SELECT 1", "timeout": 60}
            )
            data = json.loads(result.content[0].text if hasattr(result, "content") else str(result))
            echoed = data.get("echoed", data.get("args", data))
            assert "timeout" not in echoed


# ===================================================================
# Test: --test-schema CLI mode
# ===================================================================


class TestSchemaValidationMode:
    """Verify the --test-schema CLI mode for CI/CD integration."""

    async def test_clean_schema_exits_zero(self, tmp_path):
        """Matching schemas across environments should exit 0."""
        tools = {
            "ping": tool_def(
                description="Ping the service.",
                params={"host": {"type": str, "required": True}},
            ),
        }

        backends = []
        for env_name in ("prod", "staging"):
            backend = await start_backend(f"backend-{env_name}", tools)
            backends.append(backend)

        config_path = write_config(
            {
                "prod": {"description": "Prod.", "url": backends[0].url},
                "staging": {"description": "Staging.", "url": backends[1].url},
            },
            tmp_path,
        )

        result = run_test_schema(config_path)
        assert result.returncode == 0

    async def test_description_mismatch_exits_nonzero(self, tmp_path):
        """Description mismatches should cause nonzero exit."""
        backends = []
        for env_name, desc in [("prod", "Ping server."), ("staging", "Check server health.")]:
            tools = {
                "ping": tool_def(
                    description=desc,
                    params={"host": {"type": str, "required": True}},
                ),
            }
            backend = await start_backend(f"backend-{env_name}", tools)
            backends.append(backend)

        config_path = write_config(
            {
                "prod": {"description": "Prod.", "url": backends[0].url},
                "staging": {"description": "Staging.", "url": backends[1].url},
            },
            tmp_path,
        )

        result = run_test_schema(config_path)
        assert result.returncode != 0

    async def test_extra_params_reported_as_warnings(self, tmp_path):
        """Extra params on some envs should be reported as warnings, not errors."""
        prod_tools = {
            "fetch": tool_def(
                description="Fetch data.",
                params={
                    "url": {"type": str, "required": True},
                    "timeout": {"type": int, "required": False, "default": 30},
                },
            ),
        }
        staging_tools = {
            "fetch": tool_def(
                description="Fetch data.",
                params={"url": {"type": str, "required": True}},
            ),
        }

        prod = await start_backend("prod", prod_tools)
        staging = await start_backend("staging", staging_tools)

        config_path = write_config(
            {
                "prod": {"description": "Prod.", "url": prod.url},
                "staging": {"description": "Staging.", "url": staging.url},
            },
            tmp_path,
        )

        result = run_test_schema(config_path)
        # Extra params are warnings, not hard errors — should still exit 0
        assert result.returncode == 0

        output = result.stdout + result.stderr
        # Should mention the extra parameter as a warning
        assert "timeout" in output.lower()
        assert "warning" in output.lower() or "warn" in output.lower()


# ===================================================================
# Test: Environment variable substitution in config
# ===================================================================


class TestEnvVarSubstitution:
    """Verify that ${ENV_VAR} references in config strings are resolved."""

    async def test_env_var_in_headers(self, tmp_path):
        """Header values with ${VAR} syntax should be substituted from environment."""

        def make_handler(env_name: str):
            return lambda kw: json.dumps({"from": env_name})

        backend = await start_backend(
            "prod",
            {
                "whoami": tool_def(
                    description="Return identity.",
                    handler=make_handler("prod"),
                ),
            },
        )

        # Write config with ${ENV_VAR} reference
        config_path = write_config(
            {
                "prod": {
                    "description": "Prod.",
                    "url": backend.url,
                    "headers": {
                        "Authorization": "${TEST_API_KEY}",
                    },
                },
            },
            tmp_path,
        )

        # The proxy should substitute the env var
        proxy = start_proxy(
            config_path,
            env_vars={"TEST_API_KEY": "Bearer secret-token-123"},
        )
        try:
            async with Client(proxy.url) as client:
                tools = await client.list_tools()
                assert any(t.name == "whoami" for t in tools)
        finally:
            proxy.stop()

    async def test_bare_dollar_var_in_headers_is_not_expanded(self, tmp_path):
        """Header values using bare $VAR syntax should remain literal."""

        backend = await start_backend(
            "prod",
            {
                "whoami": tool_def(
                    description="Return identity.",
                    handler=lambda kw: json.dumps({"from": "prod"}),
                ),
            },
        )

        config_path = write_config(
            {
                "prod": {
                    "description": "Prod.",
                    "url": backend.url,
                    "headers": {
                        "Authorization": "$TEST_API_KEY",
                    },
                },
            },
            tmp_path,
        )

        proxy = start_proxy(
            config_path,
            env_vars={"TEST_API_KEY": "Bearer secret-token-123"},
        )
        try:
            async with Client(proxy.url) as client:
                tools = await client.list_tools()
                assert any(t.name == "whoami" for t in tools)
        finally:
            proxy.stop()


# ===================================================================
# Test: Multiple environments (3+)
# ===================================================================


class TestThreeEnvironments:
    """Verify correct behavior with three backend environments."""

    @pytest.fixture(autouse=True)
    async def setup_backends(self, tmp_path):
        self.env_names = ["prod", "staging", "dev"]
        self.backends = []

        for env_name in self.env_names:
            handler = (lambda en: lambda kw: json.dumps({"from": en, "args": kw}))(env_name)
            tools = {
                "run_query": tool_def(
                    description="Execute a query.",
                    params={"q": {"type": str, "required": True}},
                    handler=handler,
                ),
            }
            backend = await start_backend(f"backend-{env_name}", tools)
            self.backends.append(backend)

        config_path = write_config(
            {
                env_name: {
                    "description": f"{env_name.title()} environment.",
                    "url": self.backends[i].url,
                }
                for i, env_name in enumerate(self.env_names)
            },
            tmp_path,
        )

        self.proxy = start_proxy(config_path)
        yield
        self.proxy.stop()

    async def test_all_three_envs_in_enum(self):
        """All three environments should appear in the env enum."""
        async with Client(self.proxy.url) as client:
            tools = await client.list_tools()
            query_tool = find_tool(tools, "run_query")
            schema = get_input_schema(query_tool)
            env_enum = set(schema["properties"]["env"]["enum"])
            assert env_enum == {"prod", "staging", "dev"}

    async def test_routes_to_each_env(self):
        """Each env should route to its corresponding backend."""
        async with Client(self.proxy.url) as client:
            for env_name in self.env_names:
                result = await client.call_tool(
                    "run_query", {"env": env_name, "q": "test"}
                )
                data = json.loads(
                    result.content[0].text if hasattr(result, "content") else str(result)
                )
                assert data["from"] == env_name, f"Expected route to {env_name}"


# ===================================================================
# Test: Single environment (degenerate case)
# ===================================================================


class TestSingleEnvironment:
    """Verify the proxy works with a single backend environment."""

    @pytest.fixture(autouse=True)
    async def setup_backends(self, tmp_path):
        tools = {
            "hello": tool_def(
                description="Say hello.",
                params={"name": {"type": str, "required": True}},
                handler=lambda kw: f"Hello, {kw['name']}!",
            ),
        }
        self.backend = await start_backend("prod", tools)

        config_path = write_config(
            {"prod": {"description": "The only env.", "url": self.backend.url}},
            tmp_path,
        )

        self.proxy = start_proxy(config_path)
        yield
        self.proxy.stop()

    async def test_single_env_still_has_env_param(self):
        """Even with one env, tools should have the env parameter."""
        async with Client(self.proxy.url) as client:
            tools = await client.list_tools()
            hello = find_tool(tools, "hello")
            schema = get_input_schema(hello)
            assert "env" in schema["properties"]
            assert schema["properties"]["env"]["enum"] == ["prod"]

    async def test_single_env_call_works(self):
        """Tool calls should work with a single environment."""
        async with Client(self.proxy.url) as client:
            result = await client.call_tool("hello", {"env": "prod", "name": "World"})
            text = result.content[0].text if hasattr(result, "content") else str(result)
            assert "Hello, World!" in text


# ===================================================================
# Test: No tools on backend
# ===================================================================


class TestEmptyBackend:
    """Verify behavior when backends have no tools."""

    async def test_no_tools_results_in_empty_list(self, tmp_path):
        """If all backends have zero tools, the proxy should expose zero tools."""
        backends = []
        for env_name in ("prod", "staging"):
            backend = await start_backend(f"backend-{env_name}", {})
            backends.append(backend)

        config_path = write_config(
            {
                "prod": {"description": "Prod.", "url": backends[0].url},
                "staging": {"description": "Staging.", "url": backends[1].url},
            },
            tmp_path,
        )

        proxy = start_proxy(config_path)
        try:
            async with Client(proxy.url) as client:
                tools = await client.list_tools()
                assert len(tools) == 0
        finally:
            proxy.stop()


# ===================================================================
# Test: Unreachable backend at startup
# ===================================================================


class TestUnreachableBackend:
    """Verify behavior when a backend is unreachable."""

    async def test_unreachable_backend_prevents_startup(self, tmp_path):
        """If a backend is unreachable, the proxy should fail to start (default behavior)."""
        # Use a port that nothing is listening on
        dead_port = find_free_port()

        config_path = write_config(
            {
                "prod": {
                    "description": "Prod.",
                    "url": f"http://127.0.0.1:{dead_port}/mcp",
                },
            },
            tmp_path,
        )

        result = run_test_schema(config_path)
        assert result.returncode != 0


# ===================================================================
# Test: Tool with no parameters
# ===================================================================


class TestToolWithNoParams:
    """Verify tools that have no parameters (except the injected env)."""

    @pytest.fixture(autouse=True)
    async def setup_backends(self, tmp_path):
        tools = {
            "health_check": tool_def(
                description="Check service health.",
                params={},
                handler=lambda kw: json.dumps({"status": "ok"}),
            ),
        }

        self.prod = await start_backend("prod", tools)
        self.staging = await start_backend("staging", tools)

        config_path = write_config(
            {
                "prod": {"description": "Prod.", "url": self.prod.url},
                "staging": {"description": "Staging.", "url": self.staging.url},
            },
            tmp_path,
        )

        self.proxy = start_proxy(config_path)
        yield
        self.proxy.stop()

    async def test_no_param_tool_only_has_env(self):
        """A tool with no original params should only have 'env' after merging."""
        async with Client(self.proxy.url) as client:
            tools = await client.list_tools()
            health = find_tool(tools, "health_check")
            schema = get_input_schema(health)
            properties = schema.get("properties", {})
            # Only 'env' should be present
            assert set(properties.keys()) == {"env"}

    async def test_no_param_tool_call_works(self):
        """Calling a no-param tool with just env should work."""
        async with Client(self.proxy.url) as client:
            result = await client.call_tool("health_check", {"env": "prod"})
            data = json.loads(result.content[0].text if hasattr(result, "content") else str(result))
            assert data["status"] == "ok"


# ===================================================================
# Test: Config validation
# ===================================================================


class TestConfigValidation:
    """Verify the proxy validates its config file."""

    def test_missing_config_file(self, tmp_path):
        """Proxy should fail if config file doesn't exist."""
        result = run_test_schema(tmp_path / "nonexistent.json")
        assert result.returncode != 0

    def test_invalid_json_config(self, tmp_path):
        """Proxy should fail on invalid JSON."""
        config_path = tmp_path / "config.json"
        config_path.write_text("not valid json {{{")
        result = run_test_schema(config_path)
        assert result.returncode != 0

    def test_empty_environments(self, tmp_path):
        """Proxy should fail if environments dict is empty."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"environments": {}}))
        result = run_test_schema(config_path)
        assert result.returncode != 0

    def test_missing_url(self, tmp_path):
        """Proxy should fail if an environment is missing a url."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "environments": {
                "prod": {"description": "Prod."}
            }
        }))
        result = run_test_schema(config_path)
        assert result.returncode != 0
