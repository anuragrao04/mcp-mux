"""
Unit tests for mcp_env_mux.config module.

Tests config loading, validation, and environment variable substitution.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mcp_env_mux.config import Config, EnvironmentConfig, load_config, resolve_env_vars


# ===================================================================
# load_config — valid configs
# ===================================================================


class TestLoadConfigValid:
    """Test successful config loading scenarios."""

    def test_single_environment(self, tmp_path: Path):
        """A config with one environment should load correctly."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "environments": {
                "prod": {
                    "description": "Production.",
                    "url": "http://localhost:8000/mcp",
                }
            }
        }))

        config = load_config(config_path)

        assert isinstance(config, Config)
        assert "prod" in config.environments
        env = config.environments["prod"]
        assert isinstance(env, EnvironmentConfig)
        assert env.description == "Production."
        assert env.url == "http://localhost:8000/mcp"

    def test_multiple_environments(self, tmp_path: Path):
        """A config with multiple environments should load all of them."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "environments": {
                "prod": {
                    "description": "Production.",
                    "url": "http://prod:8000/mcp",
                },
                "staging": {
                    "description": "Staging.",
                    "url": "http://staging:8000/mcp",
                },
                "dev": {
                    "description": "Development.",
                    "url": "http://dev:8000/mcp",
                },
            }
        }))

        config = load_config(config_path)

        assert len(config.environments) == 3
        assert set(config.environments.keys()) == {"prod", "staging", "dev"}

    def test_environment_with_headers(self, tmp_path: Path):
        """An environment with headers should load them correctly."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "environments": {
                "prod": {
                    "description": "Production.",
                    "url": "http://localhost:8000/mcp",
                    "headers": {
                        "Authorization": "Bearer token123",
                        "X-Custom": "value",
                    },
                }
            }
        }))

        config = load_config(config_path)
        env = config.environments["prod"]

        assert env.headers == {
            "Authorization": "Bearer token123",
            "X-Custom": "value",
        }

    def test_environment_without_headers_defaults_to_empty(self, tmp_path: Path):
        """An environment without headers should default to an empty dict."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "environments": {
                "prod": {
                    "description": "Production.",
                    "url": "http://localhost:8000/mcp",
                }
            }
        }))

        config = load_config(config_path)
        env = config.environments["prod"]

        assert env.headers == {}


# ===================================================================
# load_config — invalid configs
# ===================================================================


class TestLoadConfigInvalid:
    """Test error handling for invalid configs."""

    def test_missing_config_file(self, tmp_path: Path):
        """Loading a nonexistent file should raise an error."""
        with pytest.raises(Exception):
            load_config(tmp_path / "nonexistent.json")

    def test_invalid_json(self, tmp_path: Path):
        """Loading a file with invalid JSON should raise an error."""
        config_path = tmp_path / "config.json"
        config_path.write_text("not valid json {{{")

        with pytest.raises(Exception):
            load_config(config_path)

    def test_empty_environments_dict(self, tmp_path: Path):
        """An empty environments dict should raise an error."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"environments": {}}))

        with pytest.raises(Exception):
            load_config(config_path)

    def test_missing_environments_key(self, tmp_path: Path):
        """A config without the 'environments' key should raise an error."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"something_else": {}}))

        with pytest.raises(Exception):
            load_config(config_path)

    def test_missing_url_in_environment(self, tmp_path: Path):
        """An environment without a 'url' field should raise an error."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "environments": {
                "prod": {"description": "Production."}
            }
        }))

        with pytest.raises(Exception):
            load_config(config_path)

    def test_missing_description_in_environment(self, tmp_path: Path):
        """An environment without a 'description' field should raise an error.

        Description is required because the merge module uses it to build
        the [Environments] header in tool descriptions.
        """
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "environments": {
                "prod": {"url": "http://localhost:8000/mcp"}
            }
        }))

        with pytest.raises(Exception):
            load_config(config_path)


# ===================================================================
# resolve_env_vars
# ===================================================================


class TestResolveEnvVars:
    """Test environment variable substitution in string values."""

    def test_single_var_replaced(self, monkeypatch):
        """A value of '${VAR}' should be replaced with the env var value."""
        monkeypatch.setenv("MY_API_KEY", "secret-123")

        result = resolve_env_vars({"Authorization": "${MY_API_KEY}"})

        assert result == {"Authorization": "secret-123"}

    def test_unset_var_raises(self, monkeypatch):
        """Referencing an unset env var should raise an error."""
        monkeypatch.delenv("DEFINITELY_NOT_SET", raising=False)

        with pytest.raises(Exception):
            resolve_env_vars({"Authorization": "${DEFINITELY_NOT_SET}"})

    def test_value_without_dollar_passes_through(self):
        """Values without '$' should pass through unchanged."""
        result = resolve_env_vars({"Content-Type": "application/json"})

        assert result == {"Content-Type": "application/json"}

    def test_bare_dollar_var_is_not_expanded(self, monkeypatch):
        """Bare $VAR syntax should remain literal."""
        monkeypatch.setenv("SECRET", "token-xyz")

        result = resolve_env_vars({"Authorization": "$SECRET"})

        assert result == {"Authorization": "$SECRET"}

    def test_multiple_vars_in_one_value(self, monkeypatch):
        """Multiple ${VAR} references in one value should all be replaced."""
        monkeypatch.setenv("SCHEME", "Bearer")
        monkeypatch.setenv("TOKEN", "abc123")

        result = resolve_env_vars({"Authorization": "${SCHEME} ${TOKEN}"})

        assert result == {"Authorization": "Bearer abc123"}

    def test_empty_headers_returns_empty(self):
        """An empty dict should return an empty dict."""
        result = resolve_env_vars({})

        assert result == {}

    def test_multiple_headers_resolved(self, monkeypatch):
        """Multiple values with env vars should all be resolved."""
        monkeypatch.setenv("KEY_A", "value-a")
        monkeypatch.setenv("KEY_B", "value-b")

        result = resolve_env_vars({
            "X-Header-A": "${KEY_A}",
            "X-Header-B": "${KEY_B}",
        })

        assert result == {
            "X-Header-A": "value-a",
            "X-Header-B": "value-b",
        }

    def test_mixed_static_and_var_values(self, monkeypatch):
        """Values with a mix of static and ${VAR} parts should work."""
        monkeypatch.setenv("SECRET", "token-xyz")

        result = resolve_env_vars({
            "Content-Type": "application/json",
            "Authorization": "Bearer ${SECRET}",
        })

        assert result == {
            "Content-Type": "application/json",
            "Authorization": "Bearer token-xyz",
        }


class TestLoadConfigEnvVarSubstitution:
    def test_resolves_all_string_fields_in_config(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("ENV_DESC", "Production")
        monkeypatch.setenv("HOST", "localhost")
        monkeypatch.setenv("PORT", "9000")
        monkeypatch.setenv("AUTHZ", "Bearer secret-123")
        monkeypatch.setenv("METRICS_PATH", "/custom-metrics")
        monkeypatch.setenv("TENANT_ID", "tenant-123")
        monkeypatch.setenv("CLIENT_ID", "client-456")
        monkeypatch.setenv("CLIENT_SECRET", "secret-789")
        monkeypatch.setenv("BASE_URL", "http://localhost:8080")
        monkeypatch.setenv("SCOPE", "access_as_user")
        monkeypatch.setenv("SIGNING_KEY_FILE", "/tmp/test_key.pem")
        monkeypatch.setenv("ROLE", "admin")

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "environments": {
                "prod": {
                    "description": "${ENV_DESC} environment.",
                    "url": "http://${HOST}:${PORT}/mcp",
                    "headers": {
                        "Authorization": "${AUTHZ}",
                    },
                }
            },
            "metrics": {
                "enabled": True,
                "path": "${METRICS_PATH}",
                "user_level_metrics": True,
            },
            "auth": {
                "azure": {
                    "tenant_id": "${TENANT_ID}",
                    "client_id": "${CLIENT_ID}",
                    "client_secret": "${CLIENT_SECRET}",
                },
                "base_url": "${BASE_URL}",
                "required_scopes": ["${SCOPE}"],
                "signing_key_file": "${SIGNING_KEY_FILE}",
                "roles": {
                    "${ROLE}": {"allowed_envs": {"*": ["*"]}},
                },
                "token_minting_roles": ["${ROLE}"],
            },
        }))

        config = load_config(config_path)

        env = config.environments["prod"]
        assert env.description == "Production environment."
        assert env.url == "http://localhost:9000/mcp"
        assert env.headers == {"Authorization": "Bearer secret-123"}
        assert config.metrics.path == "/custom-metrics"
        assert config.auth.azure.tenant_id == "tenant-123"
        assert config.auth.azure.client_id == "client-456"
        assert config.auth.azure.client_secret == "secret-789"
        assert config.auth.base_url == "http://localhost:8080"
        assert config.auth.required_scopes == ["access_as_user"]
        assert config.auth.signing_key_file == "/tmp/test_key.pem"
        assert config.auth.token_minting_roles == ["admin"]
        assert "${ROLE}" in config.auth.roles

    def test_missing_var_anywhere_in_config_raises(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("MISSING_URL_PART", raising=False)

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "environments": {
                "prod": {
                    "description": "Production.",
                    "url": "http://${MISSING_URL_PART}/mcp",
                }
            }
        }))

        with pytest.raises(ValueError, match="MISSING_URL_PART"):
            load_config(config_path)
