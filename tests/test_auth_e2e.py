"""End-to-end auth tests for the HybridAzureProvider proxy.

Strategy: subprocess proxy with auth enabled. Bot tokens flow through the local
JWTVerifier branch so we never hit real Azure. Tests that exercise unauth
endpoints (well-known, missing token, no-auth passthrough) need nothing special.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from conftest import start_backend, start_proxy, write_config


# ---------------------------------------------------------------------------
# Auth-config helper
# ---------------------------------------------------------------------------

def _write_auth_config(
    tmp_path: Path,
    backend_url: str,
    key_file: str,
    roles: dict,
    minting_roles: list[str],
    *,
    base_url: str = "http://localhost:8080",
    required_scopes: list[str] | None = None,
    token_max_expiry_days: int = 180,
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
            "base_url": base_url,
            "required_scopes": required_scopes or ["access_as_user"],
            "signing_key_file": key_file,
            "token_minting_roles": minting_roles,
            "roles": roles,
            "token_max_expiry_days": token_max_expiry_days,
        },
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def keypair(tmp_path_factory):
    from mcp_env_mux.auth.keys import get_public_key, load_or_generate_key

    key_path = tmp_path_factory.mktemp("keys") / "test.pem"
    private = load_or_generate_key(str(key_path))
    public = get_public_key(private)
    return private, public, str(key_path)


def _make_bot_token(
    keypair,
    roles: list[str],
    *,
    name: str = "test-bot",
    created_by: str = "admin@test.com",
    expiry_days: int = 30,
) -> str:
    from mcp_env_mux.auth.tokens import create_bot_token

    private, _, _ = keypair
    return create_bot_token(private, name, roles, created_by, expiry_days)


# ---------------------------------------------------------------------------
# 1. No-auth passthrough
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_auth_config_passthrough(tmp_path):
    """Without an auth block in config, MCP requests pass through (no 401)."""
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
# 2. Missing token returns 401
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
# 3. Well-known endpoints advertise DCR
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_well_known_endpoints_advertise_dcr(tmp_path, keypair):
    """RFC 9728 path-prefixed protected-resource discovery + DCR registration_endpoint."""
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
            # Path-prefixed protected-resource discovery is canonical per RFC
            # 9728 when the resource has a path segment ("/mcp"). The bare
            # path may or may not be registered — we don't assert on it.
            r2 = await client.get(
                f"{base}/.well-known/oauth-protected-resource/mcp", timeout=10
            )
            assert r2.status_code == 200, r2.text

            r3 = await client.get(
                f"{base}/.well-known/oauth-authorization-server", timeout=10
            )
            assert r3.status_code == 200, r3.text
            meta = r3.json()
            assert "registration_endpoint" in meta, (
                f"Expected registration_endpoint in metadata, got: {meta}"
            )
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# 4. Bot token allows access
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bot_token_allows_access(tmp_path, keypair):
    """Bot JWT with right roles allows MCP initialize."""
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
    token = _make_bot_token(keypair, ["admin"])
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
            assert resp.status_code != 401, resp.text
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# 5. Bot token with wrong role gets RBAC denial
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bot_token_wrong_role_returns_403(tmp_path, keypair):
    """Bot token whose roles don't satisfy allowed_envs raises a ToolError."""
    _, _, key_file = keypair
    backend = await start_backend(
        "rbac-be",
        {
            "deploy": {
                "description": "Deploy",
                "params": {"service": {"type": str, "required": True}},
                "handler": lambda kw: f"deployed {kw['service']}",
            }
        },
    )
    # readonly role only allowed logs* tools, not deploy
    roles_cfg = {
        "admin": {"allowed_envs": {"*": ["*"]}},
        "readonly": {"allowed_envs": {"*": ["logs*"]}},
    }
    config_path = _write_auth_config(
        tmp_path, backend.url, key_file, roles_cfg, ["admin"]
    )
    proxy = start_proxy(config_path)
    token = _make_bot_token(keypair, ["readonly"])
    try:
        async with Client(proxy.url, auth=token) as client:
            with pytest.raises(ToolError):
                await client.call_tool(
                    "deploy", {"env": "testenv", "service": "api"}
                )
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# 6. UI requires token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ui_requires_token(tmp_path, keypair):
    """GET /ui/tokens without a Bearer returns 401."""
    _, _, key_file = keypair
    backend = await start_backend(
        "ui-be",
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
            r = await client.get(f"{base}/ui/tokens", timeout=10)
            assert r.status_code == 401
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# 7. UI requires minting role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ui_requires_minting_role(tmp_path, keypair):
    """GET /ui/tokens with a non-minting-role bot token returns 403."""
    _, _, key_file = keypair
    backend = await start_backend(
        "ui-role-be",
        {"tool": {"description": "T", "params": {}, "handler": lambda kw: "ok"}},
    )
    roles_cfg = {
        "admin": {"allowed_envs": {"*": ["*"]}},
        "readonly": {"allowed_envs": {"*": ["logs*"]}},
    }
    config_path = _write_auth_config(
        tmp_path, backend.url, key_file, roles_cfg, ["admin"]
    )
    proxy = start_proxy(config_path)
    token = _make_bot_token(keypair, ["readonly"])
    try:
        base = f"http://127.0.0.1:{proxy.port}"
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{base}/ui/tokens",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            assert r.status_code == 403
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# 8. UI mints a bot token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ui_mints_bot_token(tmp_path, keypair):
    """POST /ui/tokens with a minting-role bot token returns a fresh JWT."""
    _, public, key_file = keypair
    backend = await start_backend(
        "mint-be",
        {"tool": {"description": "T", "params": {}, "handler": lambda kw: "ok"}},
    )
    roles_cfg = {
        "admin": {"allowed_envs": {"*": ["*"]}},
        "readonly": {"allowed_envs": {"*": ["logs*"]}},
    }
    config_path = _write_auth_config(
        tmp_path, backend.url, key_file, roles_cfg, ["admin"], token_max_expiry_days=90
    )
    proxy = start_proxy(config_path)
    minter_token = _make_bot_token(keypair, ["admin"], name="minter")
    try:
        base = f"http://127.0.0.1:{proxy.port}"
        form = {"name": "new-bot", "roles": "readonly", "expiry_days": "7"}
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{base}/ui/tokens",
                content=urlencode(form),
                headers={
                    "Authorization": f"Bearer {minter_token}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=10,
            )
            assert r.status_code == 200, r.text

        # Body must contain a JWT (3 base64 segments separated by dots).
        # Extract from the textarea.
        body = r.text
        import re

        m = re.search(r"<textarea[^>]*>([^<]+)</textarea>", body)
        assert m, f"No textarea in response: {body[:500]}"
        new_token = m.group(1).strip()
        assert new_token.count(".") == 2

        # Verify the minted token's claims
        import jwt as pyjwt

        claims = pyjwt.decode(
            new_token,
            public,
            algorithms=["RS256"],
            audience="mcp-env-mux",
            issuer="mcp-env-mux",
        )
        assert claims["sub"] == "new-bot"
        assert "readonly" in claims["roles"]
        # Expiry math: 7 days
        assert claims["exp"] - claims["iat"] == 7 * 86400
    finally:
        proxy.stop()
