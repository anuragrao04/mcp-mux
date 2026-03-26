"""Config loading, validation, and environment variable substitution."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EnvironmentConfig:
    description: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    environments: dict[str, EnvironmentConfig]


def resolve_env_vars(headers: dict[str, str]) -> dict[str, str]:
    """Replace $VAR patterns in header values with os.environ values."""
    result = {}
    for key, value in headers.items():
        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            if var_name not in os.environ:
                raise ValueError(f"Environment variable {var_name!r} is not set")
            return os.environ[var_name]

        result[key] = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", replacer, value)
    return result


def load_config(path: Path) -> Config:
    """Load and validate a config file, returning a Config instance."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = json.loads(path.read_text())

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

        headers = resolve_env_vars(env_data.get("headers", {}))
        environments[name] = EnvironmentConfig(
            description=env_data["description"],
            url=env_data["url"],
            headers=headers,
        )

    return Config(environments=environments)
