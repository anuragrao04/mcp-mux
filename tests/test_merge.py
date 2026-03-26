"""
Unit tests for mcp_env_mux.merge module.

Tests schema validation, merging logic, env parameter injection,
and description formatting. All tests use raw dicts — no I/O.
"""

from __future__ import annotations

from typing import Any

import pytest

from mcp_env_mux.merge import (
    MergedTool,
    MergeError,
    MergeResult,
    MergeWarning,
    validate_and_merge,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tool(
    name: str,
    description: str,
    properties: dict[str, dict[str, Any]] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Build a tool definition dict matching the structure from list_tools()."""
    schema: dict[str, Any] = {"type": "object"}
    if properties is not None:
        schema["properties"] = properties
    else:
        schema["properties"] = {}
    if required is not None:
        schema["required"] = required
    else:
        schema["required"] = []
    return {
        "name": name,
        "description": description,
        "inputSchema": schema,
    }


ENV_DESCRIPTIONS = {
    "prod": "Production Coralogix team.",
    "staging": "Pre-production.",
}

ENV_DESCRIPTIONS_3 = {
    **ENV_DESCRIPTIONS,
    "dev": "Development environment.",
}


# ===================================================================
# Basic merging
# ===================================================================


class TestBasicMerging:
    """Test merging identical tools from multiple environments."""

    def test_two_envs_identical_tools(self):
        """Two envs with the same tool produce a merged tool with both in env enum."""
        tool = make_tool(
            "search_logs",
            "Search logs by query.",
            properties={"query": {"type": "string"}},
            required=["query"],
        )
        discovered = {
            "prod": [tool],
            "staging": [tool],
        }

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        assert isinstance(result, MergeResult)
        assert len(result.tools) == 1
        assert len(result.errors) == 0

        merged = result.tools[0]
        assert merged.name == "search_logs"
        assert set(merged.available_envs) == {"prod", "staging"}

        # Check env param in schema
        env_prop = merged.input_schema["properties"]["env"]
        assert env_prop["type"] == "string"
        assert set(env_prop["enum"]) == {"prod", "staging"}
        assert "env" in merged.input_schema["required"]

    def test_three_envs_identical_tools(self):
        """Three envs with the same tool produce a merged tool with all three in enum."""
        tool = make_tool(
            "get_alert",
            "Get alert by ID.",
            properties={"alert_id": {"type": "string"}},
            required=["alert_id"],
        )
        discovered = {
            "prod": [tool],
            "staging": [tool],
            "dev": [tool],
        }

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS_3)

        assert len(result.tools) == 1
        merged = result.tools[0]
        assert set(merged.available_envs) == {"prod", "staging", "dev"}
        assert set(merged.input_schema["properties"]["env"]["enum"]) == {
            "prod", "staging", "dev"
        }

    def test_single_env(self):
        """A tool on a single env produces a merged tool with one-value env enum."""
        tool = make_tool(
            "deploy",
            "Deploy the service.",
            properties={"version": {"type": "string"}},
            required=["version"],
        )
        discovered = {"prod": [tool]}

        result = validate_and_merge(discovered, {"prod": "Production."})

        assert len(result.tools) == 1
        merged = result.tools[0]
        assert merged.available_envs == ["prod"]
        assert merged.input_schema["properties"]["env"]["enum"] == ["prod"]

    def test_multiple_tools_merged_independently(self):
        """Multiple distinct tools should each be merged independently."""
        tool_a = make_tool("tool_a", "Tool A.", properties={"x": {"type": "string"}}, required=["x"])
        tool_b = make_tool("tool_b", "Tool B.", properties={"y": {"type": "integer"}}, required=["y"])

        discovered = {
            "prod": [tool_a, tool_b],
            "staging": [tool_a, tool_b],
        }

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        assert len(result.tools) == 2
        names = {t.name for t in result.tools}
        assert names == {"tool_a", "tool_b"}

    def test_empty_discovered_returns_empty_result(self):
        """An empty discovered dict should return an empty MergeResult."""
        result = validate_and_merge({}, {})

        assert len(result.tools) == 0
        assert len(result.errors) == 0
        assert len(result.warnings) == 0


# ===================================================================
# Subset tools
# ===================================================================


class TestSubsetTools:
    """Test tools that exist on only some environments."""

    def test_tool_on_subset_of_envs(self):
        """A tool on only one env gets a constrained env enum."""
        common = make_tool("common", "Common tool.", properties={"a": {"type": "string"}}, required=["a"])
        prod_only = make_tool("prod_only", "Prod only.", properties={"b": {"type": "integer"}}, required=["b"])

        discovered = {
            "prod": [common, prod_only],
            "staging": [common],
        }

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        assert len(result.tools) == 2
        assert len(result.errors) == 0

        merged_common = next(t for t in result.tools if t.name == "common")
        merged_prod_only = next(t for t in result.tools if t.name == "prod_only")

        assert set(merged_common.available_envs) == {"prod", "staging"}
        assert merged_prod_only.available_envs == ["prod"]
        assert merged_prod_only.input_schema["properties"]["env"]["enum"] == ["prod"]


# ===================================================================
# Validation errors
# ===================================================================


class TestValidationErrors:
    """Test that validation errors are detected."""

    def test_description_mismatch_produces_error(self):
        """Tools with mismatched descriptions should produce a MergeError."""
        tool_prod = make_tool("search", "Search logs.", properties={"q": {"type": "string"}}, required=["q"])
        tool_staging = make_tool("search", "Query log data.", properties={"q": {"type": "string"}}, required=["q"])

        discovered = {
            "prod": [tool_prod],
            "staging": [tool_staging],
        }

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        assert len(result.errors) > 0
        error_messages = [e.message for e in result.errors]
        assert any("description" in msg.lower() for msg in error_messages)
        assert any(e.tool_name == "search" for e in result.errors)

    def test_parameter_type_mismatch_produces_error(self):
        """Same param name with different types across envs should produce a MergeError."""
        tool_prod = make_tool(
            "lookup",
            "Look up a record.",
            properties={"record_id": {"type": "string"}},
            required=["record_id"],
        )
        tool_staging = make_tool(
            "lookup",
            "Look up a record.",
            properties={"record_id": {"type": "integer"}},
            required=["record_id"],
        )

        discovered = {
            "prod": [tool_prod],
            "staging": [tool_staging],
        }

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        assert len(result.errors) > 0
        error_messages = [e.message for e in result.errors]
        assert any("type" in msg.lower() for msg in error_messages)
        assert any(e.tool_name == "lookup" for e in result.errors)


# ===================================================================
# Extra parameters
# ===================================================================


class TestExtraParameters:
    """Test handling of parameters that exist on some envs but not others."""

    def _make_discovered(self):
        """Helper: prod has extra 'timeout' param, staging does not."""
        tool_prod = make_tool(
            "query",
            "Run a query.",
            properties={
                "sql": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            required=["sql"],
        )
        tool_staging = make_tool(
            "query",
            "Run a query.",
            properties={"sql": {"type": "string"}},
            required=["sql"],
        )
        return {
            "prod": [tool_prod],
            "staging": [tool_staging],
        }

    def test_extra_param_included_as_optional(self):
        """Extra params should appear in merged schema but not be required."""
        result = validate_and_merge(self._make_discovered(), ENV_DESCRIPTIONS)

        merged = result.tools[0]
        props = merged.input_schema["properties"]
        assert "timeout" in props
        assert "timeout" not in merged.input_schema.get("required", [])

    def test_extra_param_generates_warning(self):
        """Extra params should produce a MergeWarning."""
        result = validate_and_merge(self._make_discovered(), ENV_DESCRIPTIONS)

        assert len(result.warnings) > 0
        warning_messages = [w.message for w in result.warnings]
        assert any("timeout" in msg for msg in warning_messages)

    def test_extra_param_noted_in_description(self):
        """Merged description should note which envs support the extra param.

        Spec format: '- timeout: Only supported on prod.'
        """
        result = validate_and_merge(self._make_discovered(), ENV_DESCRIPTIONS)

        merged = result.tools[0]
        assert "- timeout: Only supported on prod." in merged.description

    def test_env_params_tracks_which_envs_have_extra_param(self):
        """env_params should correctly map params to the envs that support them."""
        result = validate_and_merge(self._make_discovered(), ENV_DESCRIPTIONS)

        merged = result.tools[0]
        # timeout only on prod
        assert "timeout" in merged.env_params
        assert "prod" in merged.env_params["timeout"]
        assert "staging" not in merged.env_params["timeout"]

    def test_shared_params_stay_required(self):
        """Originally required params shared across all envs should remain required."""
        result = validate_and_merge(self._make_discovered(), ENV_DESCRIPTIONS)

        merged = result.tools[0]
        assert "sql" in merged.input_schema["required"]

    def test_originally_optional_params_stay_optional(self):
        """Params that are optional on all envs should remain optional."""
        tool_prod = make_tool(
            "fetch",
            "Fetch data.",
            properties={
                "url": {"type": "string"},
                "limit": {"type": "integer"},
            },
            required=["url"],  # limit is optional
        )
        tool_staging = make_tool(
            "fetch",
            "Fetch data.",
            properties={
                "url": {"type": "string"},
                "limit": {"type": "integer"},
            },
            required=["url"],  # limit is optional
        )
        discovered = {"prod": [tool_prod], "staging": [tool_staging]}

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        merged = result.tools[0]
        assert "limit" not in merged.input_schema["required"]


# ===================================================================
# Schema structure
# ===================================================================


class TestSchemaStructure:
    """Test the structure of the merged tool schemas."""

    def test_env_is_always_required(self):
        """The 'env' parameter should always be required in the merged schema."""
        tool = make_tool("ping", "Ping.", properties={"host": {"type": "string"}}, required=["host"])
        discovered = {"prod": [tool], "staging": [tool]}

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        merged = result.tools[0]
        assert "env" in merged.input_schema["required"]

    def test_env_param_is_string_with_enum(self):
        """The 'env' param should be a string type with an enum."""
        tool = make_tool("ping", "Ping.", properties={}, required=[])
        discovered = {"prod": [tool], "staging": [tool]}

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        merged = result.tools[0]
        env_prop = merged.input_schema["properties"]["env"]
        assert env_prop["type"] == "string"
        assert "enum" in env_prop

    def test_tool_with_no_params_only_has_env(self):
        """A tool with no original params should only have 'env' in merged schema."""
        tool = make_tool("health_check", "Check health.", properties={}, required=[])
        discovered = {"prod": [tool], "staging": [tool]}

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        merged = result.tools[0]
        assert set(merged.input_schema["properties"].keys()) == {"env"}

    def test_original_param_properties_preserved(self):
        """Original parameter properties (type, etc.) should be preserved."""
        tool = make_tool(
            "search",
            "Search.",
            properties={
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 100},
            },
            required=["query"],
        )
        discovered = {"prod": [tool], "staging": [tool]}

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        merged = result.tools[0]
        props = merged.input_schema["properties"]
        assert props["query"]["type"] == "string"
        assert props["limit"]["type"] == "integer"


# ===================================================================
# Description formatting
# ===================================================================


class TestDescriptionFormatting:
    """Test the format of merged tool descriptions."""

    def test_description_includes_environments_header(self):
        """Merged description should include [Environments] section."""
        tool = make_tool("ping", "Ping the service.", properties={}, required=[])
        discovered = {"prod": [tool], "staging": [tool]}

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        merged = result.tools[0]
        assert "[Environments]" in merged.description

    def test_description_includes_env_names_and_descriptions(self):
        """Each env name and its description should appear in the merged description."""
        tool = make_tool("ping", "Ping the service.", properties={}, required=[])
        discovered = {"prod": [tool], "staging": [tool]}

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        merged = result.tools[0]
        assert "prod" in merged.description
        assert "Production Coralogix team." in merged.description
        assert "staging" in merged.description
        assert "Pre-production." in merged.description

    def test_description_includes_original_description(self):
        """The original tool description should be preserved in the merged description."""
        tool = make_tool("ping", "Ping the service.", properties={}, required=[])
        discovered = {"prod": [tool], "staging": [tool]}

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        merged = result.tools[0]
        assert "Ping the service." in merged.description

    def test_description_includes_parameter_notes_for_extra_params(self):
        """When extra params exist, description should include [Parameter Notes]."""
        tool_prod = make_tool(
            "query",
            "Run a query.",
            properties={
                "sql": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            required=["sql"],
        )
        tool_staging = make_tool(
            "query",
            "Run a query.",
            properties={"sql": {"type": "string"}},
            required=["sql"],
        )
        discovered = {"prod": [tool_prod], "staging": [tool_staging]}

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        merged = result.tools[0]
        assert "[Parameter Notes]" in merged.description
        assert "- timeout: Only supported on prod." in merged.description

    def test_description_omits_parameter_notes_when_no_extra_params(self):
        """When all params are shared, [Parameter Notes] should not appear."""
        tool = make_tool(
            "search",
            "Search logs.",
            properties={"query": {"type": "string"}},
            required=["query"],
        )
        discovered = {"prod": [tool], "staging": [tool]}

        result = validate_and_merge(discovered, ENV_DESCRIPTIONS)

        merged = result.tools[0]
        assert "[Parameter Notes]" not in merged.description


# ===================================================================
# MergeResult types
# ===================================================================


class TestMergeResultTypes:
    """Test the structure of MergeResult, MergeError, MergeWarning."""

    def test_merge_error_has_tool_name_and_message(self):
        """MergeError should have tool_name and message attributes."""
        err = MergeError(tool_name="search", message="Descriptions differ")
        assert err.tool_name == "search"
        assert err.message == "Descriptions differ"

    def test_merge_warning_has_tool_name_and_message(self):
        """MergeWarning should have tool_name and message attributes."""
        warn = MergeWarning(tool_name="query", message="Extra param: timeout")
        assert warn.tool_name == "query"
        assert warn.message == "Extra param: timeout"

    def test_merged_tool_has_expected_fields(self):
        """MergedTool should have all expected fields."""
        merged = MergedTool(
            name="test",
            description="Test tool.",
            input_schema={"type": "object", "properties": {"env": {"type": "string", "enum": ["prod"]}}},
            available_envs=["prod"],
            env_params={"timeout": {"prod"}},
        )
        assert merged.name == "test"
        assert merged.description == "Test tool."
        assert merged.input_schema is not None
        assert merged.available_envs == ["prod"]
        assert merged.env_params == {"timeout": {"prod"}}
