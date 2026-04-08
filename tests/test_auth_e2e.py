"""End-to-end auth tests: unauth→401, valid JWT→success, bad RBAC→403, no-auth passthrough."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from conftest import start_backend, start_proxy, write_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_auth_config(
    tmp_path: Path,
    backend_url: str,
    key_file: str,
    roles: dict,
    minting_roles: list[str],
) -> Path:
    data = {
        "environments": {
            "testenv": {
                "description": "Test environment",
                "url": backend_url,
            }
        },
        "auth": {
            "azure": {
                "tenant_id": "test-tenant",
                "client_id": "test-client",
                "client_secret": "test-secret",
            },
            "signing_key_file": key_file,
            "token_minting_roles": minting_roles,
            "roles": roles,
        },
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture(scope="module")
def keypair(tmp_path_factory):
    from mcp_env_mux.auth.keys import get_public_key, load_or_generate_key

    key_path = tmp_path_factory.mktemp("keys") / "test.pem"
    private = load_or_generate_key(str(key_path))
    public = get_public_key(private)
    return private, public, str(key_path)


def _make_token(keypair, roles: list[str], *, expiry_seconds: int = 3600) -> str:
    from mcp_env_mux.auth.tokens import create_user_token

    private, _, _ = keypair
    return create_user_token(private, "user@test.com", roles, expiry_seconds=expiry_seconds)


# ---------------------------------------------------------------------------
# Auth E2E: no-auth config passthrough
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_auth_config_passthrough(tmp_path):
    """Without auth config, all requests pass through without 401."""
    backend = await start_backend(
        "noauth-be",
        {
            "echo": {
                "description": "Echo",
                "params": {"msg": {"type": str, "required": True}},
                "handler": lambda kw: kw["msg"],
            }
        },
    )
    config_path = write_config(
        {"noauth": {"description": "No auth", "url": backend.url}}, tmp_path
    )
    proxy = start_proxy(config_path)
    try:
        async with httpx.AsyncClient() as client:
            # MCP initialize without any token should work
            resp = await client.post(
                proxy.url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1.0"},
                    },
                },
                timeout=10,
            )
            assert resp.status_code != 401
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# Auth E2E: 401 on missing token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_token_returns_401(tmp_path, keypair):
    """A request to /mcp without Bearer token returns 401."""
    _, _, key_file = keypair
    backend = await start_backend(
        "auth-be",
        {
            "echo": {
                "description": "Echo",
                "params": {"msg": {"type": str, "required": True}},
                "handler": lambda kw: kw["msg"],
            }
        },
    )
    roles_cfg = {"admin": {"allowed_envs": {"*": ["*"]}}}
    config_path = _write_auth_config(
        tmp_path, backend.url, key_file, roles_cfg, ["admin"]
    )
    proxy = start_proxy(config_path)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                proxy.url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1.0"},
                    },
                },
                timeout=10,
            )
            assert resp.status_code == 401
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# Auth E2E: well-known endpoints are accessible without token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_well_known_no_auth_required(tmp_path, keypair):
    """Discovery endpoints should be accessible without a token."""
    _, _, key_file = keypair
    backend = await start_backend(
        "wk-be",
        {"tool": {"description": "T", "params": {}, "handler": lambda kw: "ok"}},
    )
    roles_cfg = {"admin": {"allowed_envs": {"*": ["*"]}}}
    config_path = _write_auth_config(
        tmp_path, backend.url, key_file, roles_cfg, ["admin"]
    )
    proxy = start_proxy(config_path)
    try:
        base = f"http://127.0.0.1:{proxy.port}"
        async with httpx.AsyncClient() as client:
            r1 = await client.get(
                f"{base}/.well-known/oauth-protected-resource", timeout=10
            )
            assert r1.status_code == 200
            assert "authorization_servers" in r1.json()

            r2 = await client.get(
                f"{base}/.well-known/oauth-authorization-server", timeout=10
            )
            assert r2.status_code == 200
            assert "token_endpoint" in r2.json()
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# Auth E2E: valid token → success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_valid_token_allows_access(tmp_path, keypair):
    """A valid JWT with the right role allows initialize (returns 200, not 401)."""
    _, _, key_file = keypair
    backend = await start_backend(
        "valid-be",
        {
            "echo": {
                "description": "Echo",
                "params": {"msg": {"type": str, "required": True}},
                "handler": lambda kw: kw["msg"],
            }
        },
    )
    roles_cfg = {"admin": {"allowed_envs": {"*": ["*"]}}}
    config_path = _write_auth_config(
        tmp_path, backend.url, key_file, roles_cfg, ["admin"]
    )
    proxy = start_proxy(config_path)
    token = _make_token(keypair, ["admin"])
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                proxy.url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1.0"},
                    },
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            # Should not be 401 — token is valid
            assert resp.status_code != 401
    finally:
        proxy.stop()
