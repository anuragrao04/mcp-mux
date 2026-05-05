from __future__ import annotations

import logging
import sys
import types

import pytest

from mcp_env_mux.cli import _verify_redis_connection
from mcp_env_mux.config import AuthConfig, AzureConfig, Config, RedisAuthConfig
from mcp_env_mux.health import ReadinessState


class _StubEncryptedStore:
    def __init__(self, *args, **kwargs):
        self._value = None

    async def put(self, *, key, value, collection, ttl=None):
        self._value = value

    async def get(self, *, key, collection):
        return self._value

    async def delete(self, *, key, collection):
        self._value = None


class _StubRedisStore:
    def __init__(self, *, host, port):
        self.host = host
        self.port = port


@pytest.mark.asyncio
async def test_verify_redis_connection_updates_readiness_and_logs(monkeypatch):
    import mcp_env_mux.cli as cli

    fake_module = types.ModuleType("key_value.aio.stores.redis")
    fake_module.RedisStore = _StubRedisStore
    sys.modules["key_value.aio.stores.redis"] = fake_module
    monkeypatch.setattr(cli, "FernetEncryptionWrapper", _StubEncryptedStore, raising=False)

    config = Config(
        environments={},
        auth=AuthConfig(
            azure=AzureConfig(
                tenant_id="tenant",
                client_id="client",
                client_secret="secret",
            ),
            base_url="http://localhost:8080",
            required_scopes=["access_as_user"],
            signing_key_file="/tmp/key.pem",
            roles={},
            token_minting_roles=["admin"],
            redis=RedisAuthConfig(
                enabled=True,
                host="127.0.0.1",
                port=6379,
                encryption_key="l93Ip02KcEI0YEcToRBSJAnOMsxWF_t8CI9g6f7MJWA=",
            ),
        ),
    )
    readiness = ReadinessState()
    logger = logging.getLogger("mcp_env_mux")

    await _verify_redis_connection(config, logger, readiness)

    assert readiness.redis_enabled is True
    assert readiness.redis_verified is True
    assert readiness.redis_host == "127.0.0.1"
    assert readiness.redis_port == 6379


@pytest.mark.asyncio
async def test_verify_redis_connection_noop_when_disabled():
    config = Config(environments={}, auth=None)
    readiness = ReadinessState()
    logger = logging.getLogger("mcp_env_mux")

    await _verify_redis_connection(config, logger, readiness)

    assert readiness.redis_enabled is False
    assert readiness.redis_verified is False
    assert readiness.redis_host is None
    assert readiness.redis_port is None
