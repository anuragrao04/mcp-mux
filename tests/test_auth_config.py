"""Unit tests for auth config parsing in mcp_env_mux.config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_env_mux.config import AuthConfig, AzureConfig, Config, RedisAuthConfig, RoleConfig, load_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


_BASE_ENVS = {
    "environments": {
        "prod": {"description": "Production", "url": "http://localhost:9000/mcp"}
    }
}

_VALID_REDIS_KEY = "oGxj4kV8P1A1M6h1h7JtI6Rr8J8e2mQq5m7Q2f4f4mI="

_VALID_AUTH = {
    "azure": {
        "tenant_id": "tenant-123",
        "client_id": "client-456",
        "client_secret": "secret-789",
    },
    "base_url": "http://localhost:8080",
    "required_scopes": ["access_as_user"],
    "signing_key_file": "/tmp/test_key.pem",
    "token_minting_roles": ["admin"],
    "roles": {
        "admin": {"allowed_envs": {"*": ["*"]}},
        "readonly": {"allowed_envs": {"*": ["logs*"]}},
    },
}


# ---------------------------------------------------------------------------
# Backward compatibility: no auth key
# ---------------------------------------------------------------------------

class TestNoAuthBackwardCompat:
    def test_config_without_auth_loads_fine(self, tmp_path):
        p = _write_config(tmp_path, _BASE_ENVS)
        config = load_config(p)
        assert isinstance(config, Config)
        assert config.auth is None

    def test_config_without_auth_has_environments(self, tmp_path):
        p = _write_config(tmp_path, _BASE_ENVS)
        config = load_config(p)
        assert "prod" in config.environments


# ---------------------------------------------------------------------------
# Valid auth block
# ---------------------------------------------------------------------------

class TestValidAuthConfig:
    def test_auth_parsed(self, tmp_path):
        data = {**_BASE_ENVS, "auth": _VALID_AUTH}
        config = load_config(_write_config(tmp_path, data))
        assert isinstance(config.auth, AuthConfig)

    def test_azure_config(self, tmp_path):
        data = {**_BASE_ENVS, "auth": _VALID_AUTH}
        config = load_config(_write_config(tmp_path, data))
        az = config.auth.azure
        assert isinstance(az, AzureConfig)
        assert az.tenant_id == "tenant-123"
        assert az.client_id == "client-456"
        assert az.client_secret == "secret-789"

    def test_base_url_parsed(self, tmp_path):
        data = {**_BASE_ENVS, "auth": _VALID_AUTH}
        config = load_config(_write_config(tmp_path, data))
        assert config.auth.base_url == "http://localhost:8080"

    def test_required_scopes_parsed(self, tmp_path):
        data = {**_BASE_ENVS, "auth": _VALID_AUTH}
        config = load_config(_write_config(tmp_path, data))
        assert config.auth.required_scopes == ["access_as_user"]
        assert isinstance(config.auth.required_scopes, list)

    def test_required_scopes_multiple(self, tmp_path):
        auth = {**_VALID_AUTH, "required_scopes": ["scope_a", "scope_b"]}
        data = {**_BASE_ENVS, "auth": auth}
        config = load_config(_write_config(tmp_path, data))
        assert config.auth.required_scopes == ["scope_a", "scope_b"]

    def test_roles_parsed(self, tmp_path):
        data = {**_BASE_ENVS, "auth": _VALID_AUTH}
        config = load_config(_write_config(tmp_path, data))
        roles = config.auth.roles
        assert "admin" in roles
        assert "readonly" in roles
        assert isinstance(roles["admin"], RoleConfig)
        assert roles["admin"].allowed_envs == {"*": ["*"]}

    def test_token_minting_roles(self, tmp_path):
        data = {**_BASE_ENVS, "auth": _VALID_AUTH}
        config = load_config(_write_config(tmp_path, data))
        assert config.auth.token_minting_roles == ["admin"]

    def test_default_token_max_expiry(self, tmp_path):
        data = {**_BASE_ENVS, "auth": _VALID_AUTH}
        config = load_config(_write_config(tmp_path, data))
        assert config.auth.token_max_expiry_days == 180

    def test_custom_token_max_expiry(self, tmp_path):
        auth = {**_VALID_AUTH, "token_max_expiry_days": 30}
        data = {**_BASE_ENVS, "auth": auth}
        config = load_config(_write_config(tmp_path, data))
        assert config.auth.token_max_expiry_days == 30

    def test_redis_defaults(self, tmp_path):
        data = {**_BASE_ENVS, "auth": _VALID_AUTH}
        config = load_config(_write_config(tmp_path, data))
        assert isinstance(config.auth.redis, RedisAuthConfig)
        assert config.auth.redis.enabled is False
        assert config.auth.redis.host == "localhost"
        assert config.auth.redis.port == 6379
        assert config.auth.redis.encryption_key is None

    def test_redis_config_parsed(self, tmp_path):
        auth = {
            **_VALID_AUTH,
            "redis": {
                "enabled": True,
                "host": "redis.internal",
                "port": 6380,
                "encryption_key": _VALID_REDIS_KEY,
            },
        }
        data = {**_BASE_ENVS, "auth": auth}
        config = load_config(_write_config(tmp_path, data))
        assert config.auth.redis.enabled is True
        assert config.auth.redis.host == "redis.internal"
        assert config.auth.redis.port == 6380
        assert config.auth.redis.encryption_key == _VALID_REDIS_KEY


# ---------------------------------------------------------------------------
# ${ENV_VAR} substitution in auth strings
# ---------------------------------------------------------------------------

class TestAuthEnvVarSubstitution:
    def test_client_secret_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_SECRET", "resolved-value")
        auth = {
            **_VALID_AUTH,
            "azure": {**_VALID_AUTH["azure"], "client_secret": "${MY_SECRET}"},
        }
        data = {**_BASE_ENVS, "auth": auth}
        config = load_config(_write_config(tmp_path, data))
        assert config.auth.azure.client_secret == "resolved-value"

    def test_other_auth_string_fields_are_resolved(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TENANT", "tenant-from-env")
        monkeypatch.setenv("CLIENT", "client-from-env")
        monkeypatch.setenv("BASE_URL", "http://localhost:9090")
        monkeypatch.setenv("SCOPE", "scope-from-env")
        monkeypatch.setenv("KEY_FILE", "/tmp/from-env.pem")
        monkeypatch.setenv("ROLE", "admin")
        monkeypatch.setenv("REDIS_HOST", "redis-from-env")
        monkeypatch.setenv("REDIS_KEY", _VALID_REDIS_KEY)
        auth = {
            **_VALID_AUTH,
            "azure": {
                "tenant_id": "${TENANT}",
                "client_id": "${CLIENT}",
                "client_secret": "secret-789",
            },
            "base_url": "${BASE_URL}",
            "required_scopes": ["${SCOPE}"],
            "signing_key_file": "${KEY_FILE}",
            "token_minting_roles": ["${ROLE}"],
            "redis": {
                "enabled": True,
                "host": "${REDIS_HOST}",
                "port": 6381,
                "encryption_key": "${REDIS_KEY}"
            },
        }
        data = {**_BASE_ENVS, "auth": auth}
        config = load_config(_write_config(tmp_path, data))
        assert config.auth.azure.tenant_id == "tenant-from-env"
        assert config.auth.azure.client_id == "client-from-env"
        assert config.auth.base_url == "http://localhost:9090"
        assert config.auth.required_scopes == ["scope-from-env"]
        assert config.auth.signing_key_file == "/tmp/from-env.pem"
        assert config.auth.token_minting_roles == ["admin"]
        assert config.auth.redis.enabled is True
        assert config.auth.redis.host == "redis-from-env"
        assert config.auth.redis.port == 6381
        assert config.auth.redis.encryption_key == _VALID_REDIS_KEY

    def test_bare_dollar_var_in_auth_remains_literal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_SECRET", "resolved-value")
        auth = {
            **_VALID_AUTH,
            "azure": {**_VALID_AUTH["azure"], "client_secret": "$MY_SECRET"},
        }
        data = {**_BASE_ENVS, "auth": auth}
        config = load_config(_write_config(tmp_path, data))
        assert config.auth.azure.client_secret == "$MY_SECRET"

    def test_missing_env_var_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        auth = {
            **_VALID_AUTH,
            "azure": {**_VALID_AUTH["azure"], "client_secret": "${MISSING_VAR}"},
        }
        data = {**_BASE_ENVS, "auth": auth}
        with pytest.raises(ValueError):
            load_config(_write_config(tmp_path, data))


# ---------------------------------------------------------------------------
# Missing required auth fields
# ---------------------------------------------------------------------------

class TestMissingAuthFields:
    def test_missing_azure_raises(self, tmp_path):
        auth = {k: v for k, v in _VALID_AUTH.items() if k != "azure"}
        with pytest.raises(ValueError, match="azure"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))

    def test_missing_base_url_raises(self, tmp_path):
        auth = {k: v for k, v in _VALID_AUTH.items() if k != "base_url"}
        with pytest.raises(ValueError, match="base_url"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))

    def test_missing_required_scopes_raises(self, tmp_path):
        auth = {k: v for k, v in _VALID_AUTH.items() if k != "required_scopes"}
        with pytest.raises(ValueError, match="required_scopes"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))

    def test_missing_signing_key_raises(self, tmp_path):
        auth = {k: v for k, v in _VALID_AUTH.items() if k != "signing_key_file"}
        with pytest.raises(ValueError, match="signing_key_file"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))

    def test_missing_roles_raises(self, tmp_path):
        auth = {k: v for k, v in _VALID_AUTH.items() if k != "roles"}
        with pytest.raises(ValueError, match="roles"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))

    def test_missing_token_minting_roles_raises(self, tmp_path):
        auth = {k: v for k, v in _VALID_AUTH.items() if k != "token_minting_roles"}
        with pytest.raises(ValueError, match="token_minting_roles"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))

    def test_missing_azure_tenant_id_raises(self, tmp_path):
        azure = {k: v for k, v in _VALID_AUTH["azure"].items() if k != "tenant_id"}
        auth = {**_VALID_AUTH, "azure": azure}
        with pytest.raises(ValueError, match="tenant_id"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))


# ---------------------------------------------------------------------------
# required_scopes type/non-empty validation
# ---------------------------------------------------------------------------

class TestRedisValidation:
    def test_non_object_redis_raises(self, tmp_path):
        auth = {**_VALID_AUTH, "redis": True}
        with pytest.raises(ValueError, match="auth.redis"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))

    def test_invalid_redis_host_raises(self, tmp_path):
        auth = {**_VALID_AUTH, "redis": {"enabled": True, "host": "", "port": 6379}}
        with pytest.raises(ValueError, match="auth.redis.host"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))

    def test_invalid_redis_port_raises(self, tmp_path):
        auth = {**_VALID_AUTH, "redis": {"enabled": True, "host": "localhost", "port": "6379"}}
        with pytest.raises(ValueError, match="auth.redis.port"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))

    def test_missing_redis_encryption_key_raises_when_enabled(self, tmp_path):
        auth = {**_VALID_AUTH, "redis": {"enabled": True, "host": "localhost", "port": 6379}}
        with pytest.raises(ValueError, match="auth.redis.encryption_key"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))

    def test_invalid_redis_encryption_key_type_raises(self, tmp_path):
        auth = {
            **_VALID_AUTH,
            "redis": {"enabled": True, "host": "localhost", "port": 6379, "encryption_key": 123},
        }
        with pytest.raises(ValueError, match="auth.redis.encryption_key"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))

    def test_invalid_redis_encryption_key_value_raises(self, tmp_path):
        auth = {
            **_VALID_AUTH,
            "redis": {"enabled": True, "host": "localhost", "port": 6379, "encryption_key": "not-a-valid-fernet-key"},
        }
        with pytest.raises(ValueError, match="valid Fernet key"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))


class TestRequiredScopesValidation:
    def test_empty_list_raises(self, tmp_path):
        auth = {**_VALID_AUTH, "required_scopes": []}
        with pytest.raises(ValueError, match="required_scopes"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))

    def test_dict_type_raises(self, tmp_path):
        auth = {**_VALID_AUTH, "required_scopes": {"scope": "x"}}
        with pytest.raises(ValueError, match="required_scopes"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))

    def test_string_type_raises(self, tmp_path):
        auth = {**_VALID_AUTH, "required_scopes": "access_as_user"}
        with pytest.raises(ValueError, match="required_scopes"):
            load_config(_write_config(tmp_path, {**_BASE_ENVS, "auth": auth}))
