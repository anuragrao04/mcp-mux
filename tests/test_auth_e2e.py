"""End-to-end auth tests for the HybridAzureProvider proxy.

Strategy: subprocess proxy with auth enabled. Bot tokens flow through the local
JWTVerifier branch so we never hit real Azure. Tests that exercise unauth
endpoints (well-known, missing token, no-auth passthrough) need nothing special.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from conftest import start_backend, start_proxy, write_config


def _find_tool(tools, name: str):
    return next((t for t in tools if t.name == name), None)


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
# 5. Bot token list_tools is filtered by env authorization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tools_filters_envs_per_user(tmp_path, keypair):
    _, _, key_file = keypair
    prod = await start_backend(
        "prod-be",
        {
            "query": {
                "description": "Run a query.",
                "params": {"sql": {"type": str, "required": True}, "timeout": {"type": int, "required": False, "default": None}},
                "handler": lambda kw: f"prod:{kw['sql']}",
            }
        },
    )
    staging = await start_backend(
        "staging-be",
        {
            "query": {
                "description": "Run a query.",
                "params": {"sql": {"type": str, "required": True}},
                "handler": lambda kw: f"staging:{kw['sql']}",
            }
        },
    )
    roles_cfg = {
        "admin": {"allowed_envs": {"*": ["*"]}},
        "staging-reader": {"allowed_envs": {"staging": ["query"]}},
    }
    config = {
        "environments": {
            "prod": {"description": "Production environment.", "url": prod.url},
            "staging": {"description": "Staging environment.", "url": staging.url},
        },
        "auth": {
            "azure": {
                "tenant_id": "test-tenant",
                "client_id": "test-client",
                "client_secret": "test-secret",
            },
            "base_url": "http://localhost:8080",
            "required_scopes": ["access_as_user"],
            "signing_key_file": key_file,
            "token_minting_roles": ["admin"],
            "roles": roles_cfg,
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    proxy = start_proxy(config_path)
    token = _make_bot_token(keypair, ["staging-reader"])
    try:
        async with Client(proxy.url, auth=token) as client:
            tools = await client.list_tools()
            tool = _find_tool(tools, "query")
            assert tool is not None
            assert tool.inputSchema["properties"]["env"]["enum"] == ["staging"]
            assert "Staging environment." in tool.description
            assert "Production environment." not in tool.description
            assert "timeout" not in tool.description

            result = await client.call_tool("query", {"env": "staging", "sql": "select 1"})
            assert "staging:select 1" in result.content[0].text

            with pytest.raises(ToolError):
                await client.call_tool("query", {"env": "prod", "sql": "select 1"})
    finally:
        proxy.stop()



@pytest.mark.asyncio
async def test_list_tools_views_do_not_leak_between_callers(tmp_path, keypair):
    _, _, key_file = keypair
    prod = await start_backend(
        "prod-view-be",
        {
            "query": {
                "description": "Run a query.",
                "params": {"sql": {"type": str, "required": True}, "timeout": {"type": int, "required": False, "default": None}},
                "handler": lambda kw: f"prod:{kw['sql']}",
            }
        },
    )
    staging = await start_backend(
        "staging-view-be",
        {
            "query": {
                "description": "Run a query.",
                "params": {"sql": {"type": str, "required": True}},
                "handler": lambda kw: f"staging:{kw['sql']}",
            }
        },
    )
    roles_cfg = {
        "admin": {"allowed_envs": {"*": ["*"]}},
        "staging-reader": {"allowed_envs": {"staging": ["query"]}},
    }
    config = {
        "environments": {
            "prod": {"description": "Production environment.", "url": prod.url},
            "staging": {"description": "Staging environment.", "url": staging.url},
        },
        "auth": {
            "azure": {
                "tenant_id": "test-tenant",
                "client_id": "test-client",
                "client_secret": "test-secret",
            },
            "base_url": "http://localhost:8080",
            "required_scopes": ["access_as_user"],
            "signing_key_file": key_file,
            "token_minting_roles": ["admin"],
            "roles": roles_cfg,
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    proxy = start_proxy(config_path)
    staging_token = _make_bot_token(keypair, ["staging-reader"], name="staging-bot")
    admin_token = _make_bot_token(keypair, ["admin"], name="admin-bot")
    try:
        async with Client(proxy.url, auth=staging_token) as staging_client:
            staging_tools = await staging_client.list_tools()
            staging_tool = _find_tool(staging_tools, "query")
            assert staging_tool is not None
            assert staging_tool.inputSchema["properties"]["env"]["enum"] == ["staging"]
            assert "Production environment." not in staging_tool.description

        async with Client(proxy.url, auth=admin_token) as admin_client:
            admin_tools = await admin_client.list_tools()
            admin_tool = _find_tool(admin_tools, "query")
            assert admin_tool is not None
            assert admin_tool.inputSchema["properties"]["env"]["enum"] == ["prod", "staging"]
            assert "Production environment." in admin_tool.description
            assert "Staging environment." in admin_tool.description
            assert "timeout" in admin_tool.description
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# 6. Bot token with wrong role gets RBAC denial
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
# 6. UI redirects to login when unauthenticated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ui_redirects_to_login_when_unauthenticated(tmp_path, keypair):
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
        async with httpx.AsyncClient(follow_redirects=False) as client:
            r = await client.get(f"{base}/ui/tokens", timeout=10)
            assert r.status_code in (302, 307)
            assert r.headers["location"].startswith("/ui/login?next=%2Fui%2Ftokens")
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# 7. UI login redirects to Azure authorize URL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ui_login_redirects_to_azure_authorize(tmp_path, keypair):
    _, _, key_file = keypair
    backend = await start_backend(
        "ui-login-be",
        {"tool": {"description": "T", "params": {}, "handler": lambda kw: "ok"}},
    )
    roles_cfg = {"admin": {"allowed_envs": {"*": ["*"]}}}
    config_path = _write_auth_config(
        tmp_path, backend.url, key_file, roles_cfg, ["admin"]
    )
    proxy = start_proxy(config_path)
    try:
        base = f"http://127.0.0.1:{proxy.port}"
        async with httpx.AsyncClient(follow_redirects=False) as client:
            r = await client.get(f"{base}/ui/login?next=/ui/tokens", timeout=10)
            assert r.status_code in (302, 307)
            location = r.headers["location"]
            parsed = urlparse(location)
            assert parsed.netloc == "login.microsoftonline.com"
            qs = parse_qs(parsed.query)
            assert qs["redirect_uri"] == [f"{base}/ui/callback"]
            assert "state" in qs
            scopes = qs["scope"][0].split()
            assert "api://test-client/access_as_user" in scopes
            assert "offline_access" in scopes
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# 8. UI callback sets session and returns to form
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ui_callback_sets_session_and_renders_form(tmp_path, keypair):
    _, _, key_file = keypair
    backend = await start_backend(
        "ui-callback-be",
        {"tool": {"description": "T", "params": {}, "handler": lambda kw: "ok"}},
    )
    roles_cfg = {
        "admin": {"allowed_envs": {"*": ["*"]}},
        "readonly": {"allowed_envs": {"*": ["logs*"]}},
    }
    config_path = _write_auth_config(
        tmp_path, backend.url, key_file, roles_cfg, ["admin"]
    )
    proxy = start_proxy(
        config_path,
        env_vars={
            "MCP_ENV_MUX_TEST_UI_AUTH_SUBJECT": "admin@example.com",
            "MCP_ENV_MUX_TEST_UI_AUTH_ROLES": "admin",
        },
    )
    try:
        base = f"http://127.0.0.1:{proxy.port}"
        async with httpx.AsyncClient(follow_redirects=False) as client:
            login = await client.get(f"{base}/ui/login?next=/ui/tokens", timeout=10)
            location = login.headers["location"]
            state = parse_qs(urlparse(location).query)["state"][0]

            cb = await client.get(
                f"{base}/ui/callback?code=fake-code&state={state}", timeout=10
            )
            assert cb.status_code in (302, 307)
            assert cb.headers["location"] == "/ui/tokens"
            assert any(cookie.name == "mcp_env_mux_ui_session" for cookie in client.cookies.jar)
            assert not any(
                cookie.name == "mcp_env_mux_ui_login" for cookie in client.cookies.jar
            )

            form = await client.get(f"{base}/ui/tokens", timeout=10)
            assert form.status_code == 200
            assert "Mint Bot Token" in form.text
            assert "admin@example.com" in form.text
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# 9. UI callback rejects missing or mismatched login binding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ui_callback_rejects_missing_login_cookie(tmp_path, keypair):
    _, _, key_file = keypair
    backend = await start_backend(
        "ui-missing-cookie-be",
        {"tool": {"description": "T", "params": {}, "handler": lambda kw: "ok"}},
    )
    roles_cfg = {"admin": {"allowed_envs": {"*": ["*"]}}}
    config_path = _write_auth_config(
        tmp_path, backend.url, key_file, roles_cfg, ["admin"]
    )
    proxy = start_proxy(
        config_path,
        env_vars={
            "MCP_ENV_MUX_TEST_UI_AUTH_SUBJECT": "admin@example.com",
            "MCP_ENV_MUX_TEST_UI_AUTH_ROLES": "admin",
        },
    )
    try:
        base = f"http://127.0.0.1:{proxy.port}"
        async with httpx.AsyncClient(follow_redirects=False) as client:
            login = await client.get(f"{base}/ui/login?next=/ui/tokens", timeout=10)
            state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
            client.cookies.clear()
            cb = await client.get(
                f"{base}/ui/callback?code=fake-code&state={state}", timeout=10
            )
            assert cb.status_code == 400
            assert "Login session expired" in cb.text or "Invalid login state" in cb.text
    finally:
        proxy.stop()


@pytest.mark.asyncio
async def test_ui_callback_rejects_mismatched_state(tmp_path, keypair):
    _, _, key_file = keypair
    backend = await start_backend(
        "ui-mismatch-state-be",
        {"tool": {"description": "T", "params": {}, "handler": lambda kw: "ok"}},
    )
    roles_cfg = {"admin": {"allowed_envs": {"*": ["*"]}}}
    config_path = _write_auth_config(
        tmp_path, backend.url, key_file, roles_cfg, ["admin"]
    )
    proxy = start_proxy(
        config_path,
        env_vars={
            "MCP_ENV_MUX_TEST_UI_AUTH_SUBJECT": "admin@example.com",
            "MCP_ENV_MUX_TEST_UI_AUTH_ROLES": "admin",
        },
    )
    try:
        base = f"http://127.0.0.1:{proxy.port}"
        async with httpx.AsyncClient(follow_redirects=False) as client:
            await client.get(f"{base}/ui/login?next=/ui/tokens", timeout=10)
            cb = await client.get(
                f"{base}/ui/callback?code=fake-code&state=wrong-state", timeout=10
            )
            assert cb.status_code == 400
            assert "Invalid login state" in cb.text
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# 10. UI requires minting role from session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ui_requires_minting_role_from_session(tmp_path, keypair):
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
    proxy = start_proxy(
        config_path,
        env_vars={
            "MCP_ENV_MUX_TEST_UI_AUTH_SUBJECT": "reader@example.com",
            "MCP_ENV_MUX_TEST_UI_AUTH_ROLES": "readonly",
        },
    )
    try:
        base = f"http://127.0.0.1:{proxy.port}"
        async with httpx.AsyncClient(follow_redirects=False) as client:
            login = await client.get(f"{base}/ui/login?next=/ui/tokens", timeout=10)
            state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
            await client.get(f"{base}/ui/callback?code=fake-code&state={state}", timeout=10)
            r = await client.get(f"{base}/ui/tokens", timeout=10)
            assert r.status_code == 403
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# 11. UI requires minting role from session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ui_mints_bot_token_from_session(tmp_path, keypair):
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
    proxy = start_proxy(
        config_path,
        env_vars={
            "MCP_ENV_MUX_TEST_UI_AUTH_SUBJECT": "minter@example.com",
            "MCP_ENV_MUX_TEST_UI_AUTH_ROLES": "admin",
        },
    )
    try:
        base = f"http://127.0.0.1:{proxy.port}"
        form = {"name": "new-bot", "roles": "readonly", "expiry_days": "7"}
        async with httpx.AsyncClient(follow_redirects=False) as client:
            login = await client.get(f"{base}/ui/login?next=/ui/tokens", timeout=10)
            state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
            await client.get(f"{base}/ui/callback?code=fake-code&state={state}", timeout=10)
            r = await client.post(
                f"{base}/ui/tokens",
                content=urlencode(form),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            assert r.status_code == 200, r.text

        body = r.text
        import re
        m = re.search(r"<textarea[^>]*>([^<]+)</textarea>", body)
        assert m, f"No textarea in response: {body[:500]}"
        new_token = m.group(1).strip()
        assert new_token.count(".") == 2

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
        assert claims["created_by"] == "minter@example.com"
        assert claims["exp"] - claims["iat"] == 7 * 86400
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# 12. UI logout clears the session cookie
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ui_logout_clears_session(tmp_path, keypair):
    _, _, key_file = keypair
    backend = await start_backend(
        "ui-logout-be",
        {"tool": {"description": "T", "params": {}, "handler": lambda kw: "ok"}},
    )
    roles_cfg = {"admin": {"allowed_envs": {"*": ["*"]}}}
    config_path = _write_auth_config(
        tmp_path, backend.url, key_file, roles_cfg, ["admin"]
    )
    proxy = start_proxy(
        config_path,
        env_vars={
            "MCP_ENV_MUX_TEST_UI_AUTH_SUBJECT": "admin@example.com",
            "MCP_ENV_MUX_TEST_UI_AUTH_ROLES": "admin",
        },
    )
    try:
        base = f"http://127.0.0.1:{proxy.port}"
        async with httpx.AsyncClient(follow_redirects=False) as client:
            login = await client.get(f"{base}/ui/login?next=/ui/tokens", timeout=10)
            state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
            await client.get(f"{base}/ui/callback?code=fake-code&state={state}", timeout=10)
            assert any(cookie.name == "mcp_env_mux_ui_session" for cookie in client.cookies.jar)

            logout = await client.get(f"{base}/ui/logout", timeout=10)
            assert logout.status_code in (302, 307)
            assert logout.headers["location"] == "/ui/tokens"
            assert not any(cookie.name == "mcp_env_mux_ui_session" for cookie in client.cookies.jar)
    finally:
        proxy.stop()
