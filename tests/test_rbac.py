"""Unit tests for auth/rbac.py — pure permission logic."""

from __future__ import annotations

import pytest

from mcp_env_mux.auth.rbac import is_allowed
from mcp_env_mux.config import RoleConfig


def _roles(**envs_to_tools: list[str]) -> dict[str, RoleConfig]:
    """Quick helper: _roles(prod=['logs*', 'status*'])."""
    return {
        "role": RoleConfig(allowed_envs={env: tools for env, tools in envs_to_tools.items()})
    }


class TestExactMatch:
    def test_exact_env_and_tool(self):
        defs = _roles(prod=["deploy"])
        assert is_allowed(["role"], defs, "prod", "deploy") is True

    def test_wrong_env_denied(self):
        defs = _roles(prod=["deploy"])
        assert is_allowed(["role"], defs, "staging", "deploy") is False

    def test_wrong_tool_denied(self):
        defs = _roles(prod=["deploy"])
        assert is_allowed(["role"], defs, "prod", "rollback") is False


class TestGlobPatterns:
    def test_env_wildcard_matches_any(self):
        defs = _roles(**{"*": ["logs"]})
        assert is_allowed(["role"], defs, "prod", "logs") is True
        assert is_allowed(["role"], defs, "staging", "logs") is True

    def test_env_prefix_glob(self):
        defs = _roles(**{"prod*": ["deploy"]})
        assert is_allowed(["role"], defs, "prod", "deploy") is True
        assert is_allowed(["role"], defs, "prod-us", "deploy") is True
        assert is_allowed(["role"], defs, "staging", "deploy") is False

    def test_tool_wildcard_matches_any(self):
        defs = _roles(staging=["*"])
        assert is_allowed(["role"], defs, "staging", "anything") is True

    def test_tool_prefix_glob(self):
        defs = _roles(prod=["logs*"])
        assert is_allowed(["role"], defs, "prod", "logs") is True
        assert is_allowed(["role"], defs, "prod", "logs_get") is True
        assert is_allowed(["role"], defs, "prod", "deploy") is False


class TestMultiRoleUnion:
    def test_union_allows_if_any_role_allows(self):
        defs = {
            "dev": RoleConfig(allowed_envs={"dev": ["*"]}),
            "readonly": RoleConfig(allowed_envs={"*": ["logs*"]}),
        }
        # readonly role allows logs* in all envs
        assert is_allowed(["readonly"], defs, "prod", "logs_tail") is True
        # dev role allows nothing in prod
        assert is_allowed(["dev"], defs, "prod", "logs_tail") is False
        # both roles: union → allowed
        assert is_allowed(["dev", "readonly"], defs, "prod", "logs_tail") is True

    def test_multi_role_more_specific_wins(self):
        defs = {
            "admin": RoleConfig(allowed_envs={"prod*": ["deploy*", "rollback*"]}),
            "readonly": RoleConfig(allowed_envs={"*": ["logs*"]}),
        }
        # admin role grants deploy in prod
        assert is_allowed(["admin", "readonly"], defs, "prod", "deploy_service") is True
        # readonly does NOT grant deploy
        assert is_allowed(["readonly"], defs, "prod", "deploy_service") is False


class TestEdgeCases:
    def test_empty_roles_denied(self):
        defs = _roles(prod=["*"])
        assert is_allowed([], defs, "prod", "tool") is False

    def test_unknown_role_grants_nothing(self):
        defs = _roles(prod=["*"])
        assert is_allowed(["unknown_role"], defs, "prod", "tool") is False

    def test_empty_role_definitions(self):
        assert is_allowed(["admin"], {}, "prod", "tool") is False

    def test_case_sensitive_env_matching(self):
        defs = _roles(Prod=["deploy"])
        assert is_allowed(["role"], defs, "prod", "deploy") is False
        assert is_allowed(["role"], defs, "Prod", "deploy") is True

    def test_multiple_env_patterns_in_one_role(self):
        defs = {
            "plat": RoleConfig(
                allowed_envs={
                    "prod*": ["logs*"],
                    "prod-us*": ["deploy*"],
                    "staging": ["*"],
                }
            )
        }
        assert is_allowed(["plat"], defs, "prod-eu", "logs_fetch") is True
        # prod-us* matches, deploy allowed
        assert is_allowed(["plat"], defs, "prod-us-east", "deploy_service") is True
        # prod-us* also matches prod* → logs* also in union
        assert is_allowed(["plat"], defs, "prod-us-east", "logs_tail") is True
        assert is_allowed(["plat"], defs, "staging", "anything") is True
        assert is_allowed(["plat"], defs, "dev", "logs_fetch") is False
