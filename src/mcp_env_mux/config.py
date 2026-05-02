"""Config loading, validation, and environment variable substitution."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from mcp_env_mux.metrics.config import MetricsConfig


@dataclass
class EnvironmentConfig:
    description: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class AzureConfig:
    tenant_id: str
    client_id: str
    client_secret: str


@dataclass
class RoleConfig:
    allowed_envs: dict[str, list[str]]  # env_pattern -> [tool_patterns]


@dataclass
class AuthConfig:
    azure: AzureConfig
    base_url: str
    required_scopes: list[str]
    signing_key_file: str
    roles: dict[str, RoleConfig]
    token_minting_roles: list[str]
    token_max_expiry_days: int = 180


@dataclass
class Config:
    environments: dict[str, EnvironmentConfig]
    auth: AuthConfig | None = None  # None = auth disabled
    metrics: MetricsConfig | None = None


def resolve_env_vars(values: dict[str, str]) -> dict[str, str]:
    """Replace ${VAR} patterns in string values with os.environ values."""
    return {key: _resolve_string_env_vars(value) for key, value in values.items()}


def _resolve_string_env_vars(value: str) -> str:
    """Replace ${VAR} patterns in a single string value with os.environ values."""
    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        if var_name not in os.environ:
            raise ValueError(f"Environment variable {var_name!r} is not set")
        return os.environ[var_name]

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replacer, value)


def _resolve_env_vars_in_value(value: object) -> object:
    """Resolve ${VAR} patterns in parsed JSON values.

    Traverses nested dicts/lists so all string fields in config are handled,
    but each original string is substituted only once.
    """
    if isinstance(value, str):
        return _resolve_string_env_vars(value)
    if isinstance(value, list):
        return [_resolve_env_vars_in_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_env_vars_in_value(item) for key, item in value.items()}
    return value


def _parse_auth_config(auth_raw: dict) -> AuthConfig:
    """Parse and validate the auth block from config."""
    azure_raw = auth_raw.get("azure")
    if not azure_raw:
        raise ValueError("auth.azure is required")

    for field_name in ("tenant_id", "client_id", "client_secret"):
        if field_name not in azure_raw:
            raise ValueError(f"auth.azure.{field_name} is required")

    azure = AzureConfig(
        tenant_id=azure_raw["tenant_id"],
        client_id=azure_raw["client_id"],
        client_secret=azure_raw["client_secret"],
    )

    base_url = auth_raw.get("base_url")
    if not base_url or not isinstance(base_url, str):
        raise ValueError("auth.base_url is required")

    required_scopes = auth_raw.get("required_scopes")
    if required_scopes is None:
        raise ValueError("auth.required_scopes is required")
    if not isinstance(required_scopes, list):
        raise ValueError("auth.required_scopes must be a list of strings")
    if not required_scopes:
        raise ValueError("auth.required_scopes is required")
    for scope in required_scopes:
        if not isinstance(scope, str):
            raise ValueError("auth.required_scopes must be a list of strings")

    signing_key_file = auth_raw.get("signing_key_file")
    if not signing_key_file:
        raise ValueError("auth.signing_key_file is required")

    roles_raw = auth_raw.get("roles")
    if not roles_raw:
        raise ValueError("auth.roles is required")

    roles: dict[str, RoleConfig] = {}
    for role_name, role_data in roles_raw.items():
        allowed_envs_raw = role_data.get("allowed_envs", {})
        allowed_envs: dict[str, list[str]] = {}
        for env_pattern, tool_patterns in allowed_envs_raw.items():
            if not isinstance(tool_patterns, list):
                raise ValueError(
                    f"auth.roles.{role_name}.allowed_envs.{env_pattern} must be a list"
                )
            allowed_envs[env_pattern] = tool_patterns
        roles[role_name] = RoleConfig(allowed_envs=allowed_envs)

    token_minting_roles = auth_raw.get("token_minting_roles")
    if token_minting_roles is None:
        raise ValueError("auth.token_minting_roles is required")

    return AuthConfig(
        azure=azure,
        base_url=base_url,
        required_scopes=required_scopes,
        signing_key_file=signing_key_file,
        roles=roles,
        token_minting_roles=token_minting_roles,
        token_max_expiry_days=auth_raw.get("token_max_expiry_days", 180),
    )


def _parse_metrics_config(metrics_raw: dict | None) -> MetricsConfig:
    if metrics_raw is None:
        return MetricsConfig()
    path = metrics_raw.get("path", "/metrics")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("metrics.path must be a string starting with '/'")
    return MetricsConfig(
        enabled=bool(metrics_raw.get("enabled", True)),
        path=path,
        user_level_metrics=bool(metrics_raw.get("user_level_metrics", False)),
    )


def load_config(path: Path) -> Config:
    """Load and validate a config file, returning a Config instance."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = _resolve_env_vars_in_value(json.loads(path.read_text()))

    if "environments" not in raw:
        raise ValueError("Config must contain 'environments' key")

    envs_raw = raw["environments"]
    if not envs_raw:
        raise ValueError("'environments' must not be empty")

    environments: dict[str, EnvironmentConfig] = {}
    for name, env_data in envs_raw.items():
        if "url" not in env_data:
            raise ValueError(f"Environment {name!r} missing 'url'")
        if "description" not in env_data:
            raise ValueError(f"Environment {name!r} missing 'description'")

        headers = env_data.get("headers", {})
        environments[name] = EnvironmentConfig(
            description=env_data["description"],
            url=env_data["url"],
            headers=headers,
        )

    auth: AuthConfig | None = None
    if "auth" in raw:
        auth = _parse_auth_config(raw["auth"])

    metrics = _parse_metrics_config(raw.get("metrics"))

    return Config(environments=environments, auth=auth, metrics=metrics)
