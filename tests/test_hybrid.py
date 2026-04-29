"""Unit tests for HybridAzureProvider verify_token dispatch."""

from __future__ import annotations

import time
import uuid
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization

from mcp_env_mux.auth.keys import get_public_key, load_or_generate_key
from mcp_env_mux.auth.tokens import create_bot_token


_AZURE_KW = {
    "client_id": "test-client-id",
    "client_secret": "test-client-secret",
    "tenant_id": "test-tenant-id",
    "base_url": "http://localhost:8080",
    "required_scopes": ["access_as_user"],
}


@pytest.fixture
def keypair(tmp_path):
    key_path = tmp_path / "test.pem"
    private = load_or_generate_key(str(key_path))
    public = get_public_key(private)
    public_pem = public.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private, public, public_pem


@pytest.fixture
def alt_keypair(tmp_path):
    """A second, unrelated RSA key (for bad-signature tests)."""
    key_path = tmp_path / "alt.pem"
    private = load_or_generate_key(str(key_path))
    return private


@pytest.fixture
def hybrid(keypair):
    from mcp_env_mux.auth.hybrid import HybridAzureProvider

    _, _, public_pem = keypair
    return HybridAzureProvider(
        **_AZURE_KW,
        local_public_key_pem=public_pem,
    )


def _sentinel_access_token():
    """Build a real AccessToken object to use as a sentinel."""
    from fastmcp.server.auth.auth import AccessToken

    return AccessToken(
        token="sentinel",
        client_id="azure-user",
        scopes=["access_as_user"],
        expires_at=int(time.time()) + 3600,
        claims={"sub": "azure-user", "iss": "https://login.microsoftonline.com/x/v2.0"},
    )


# ---------------------------------------------------------------------------
# Bot path
# ---------------------------------------------------------------------------

async def test_bot_token_dispatched_to_local_verifier(hybrid, keypair, monkeypatch):
    """Bot token (iss=mcp-env-mux, valid sig) routed to local verifier."""
    private, _, _ = keypair

    async def _boom(self, token):
        raise AssertionError("super().verify_token should not be called for bot tokens")

    from fastmcp.server.auth.providers.azure import AzureProvider
    monkeypatch.setattr(AzureProvider, "verify_token", _boom)

    token = create_bot_token(private, "my-bot", ["admin"], "creator", 30)

    access = await hybrid.verify_token(token)
    assert access is not None
    assert access.claims.get("sub") == "my-bot"
    assert access.claims.get("iss") == "mcp-env-mux"
    assert "admin" in access.claims.get("roles", [])


async def test_bad_bot_signature_returns_none(hybrid, alt_keypair):
    """Bot-issuer JWT signed with an unrelated key returns None."""
    token = create_bot_token(alt_keypair, "evil-bot", ["admin"], "x", 30)
    access = await hybrid.verify_token(token)
    assert access is None


# ---------------------------------------------------------------------------
# Azure / super path
# ---------------------------------------------------------------------------

async def test_azure_token_dispatched_to_super(hybrid, monkeypatch):
    """JWT with Azure issuer routed to AzureProvider.verify_token (super)."""
    sentinel = _sentinel_access_token()
    calls: list[str] = []

    async def _stub(self, token):
        calls.append(token)
        return sentinel

    from fastmcp.server.auth.providers.azure import AzureProvider
    monkeypatch.setattr(AzureProvider, "verify_token", _stub)

    payload = {
        "iss": f"https://login.microsoftonline.com/{_AZURE_KW['tenant_id']}/v2.0",
        "aud": f"api://{_AZURE_KW['client_id']}",
        "sub": "user@example.com",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "jti": str(uuid.uuid4()),
    }
    # Sign with a throwaway HMAC; super() is stubbed so signature won't be checked here.
    fake_token = pyjwt.encode(payload, "irrelevant-secret", algorithm="HS256")

    access = await hybrid.verify_token(fake_token)
    assert access is sentinel
    assert calls == [fake_token]


async def test_unknown_issuer_falls_through_to_super(hybrid, monkeypatch):
    """Token with iss != mcp-env-mux still routed to super (which may reject)."""
    calls: list[str] = []

    async def _stub(self, token):
        calls.append(token)
        return None

    from fastmcp.server.auth.providers.azure import AzureProvider
    monkeypatch.setattr(AzureProvider, "verify_token", _stub)

    payload = {
        "iss": "https://some.other.idp/issuer",
        "aud": "whatever",
        "sub": "x",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }
    token = pyjwt.encode(payload, "irrelevant", algorithm="HS256")

    access = await hybrid.verify_token(token)
    assert access is None
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Garbage handling
# ---------------------------------------------------------------------------

async def test_garbage_token_returns_none(hybrid, monkeypatch):
    """Non-JWT strings and JWTs with no iss claim never raise; both return None."""
    async def _stub(self, token):
        return None

    from fastmcp.server.auth.providers.azure import AzureProvider
    monkeypatch.setattr(AzureProvider, "verify_token", _stub)

    # 1) total garbage
    assert await hybrid.verify_token("not-a-jwt-at-all") is None

    # 2) JWT-shaped but no iss claim
    payload = {
        "sub": "x",
        "aud": "y",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }
    no_iss = pyjwt.encode(payload, "irrelevant", algorithm="HS256")
    assert await hybrid.verify_token(no_iss) is None
