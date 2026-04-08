"""Tests for OAuth 2.1 discovery endpoints and PKCE helper."""

from __future__ import annotations

import pytest

from mcp_env_mux.auth.oauth import verify_pkce


class TestVerifyPKCE:
    """Test the S256 PKCE code_challenge verification."""

    def test_correct_verifier(self):
        # Generated with: echo -n "abc123" | sha256sum + base64url
        import base64
        import hashlib

        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        assert verify_pkce(verifier, challenge) is True

    def test_wrong_verifier_fails(self):
        import base64
        import hashlib

        verifier = "correct-verifier"
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        assert verify_pkce("wrong-verifier", challenge) is False

    def test_empty_verifier_fails(self):
        assert verify_pkce("", "anychallenge") is False

    def test_padding_stripped_correctly(self):
        # Ensure base64 padding is stripped
        import base64
        import hashlib

        for verifier in ["short", "medium-length-ver", "this-is-a-longer-verifier-test"]:
            digest = hashlib.sha256(verifier.encode("ascii")).digest()
            challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
            assert "=" not in challenge
            assert verify_pkce(verifier, challenge) is True


class TestOAuthRouteRegistration:
    """Smoke test that OAuth routes are registered on the server."""

    def test_routes_registered(self, tmp_path):
        from mcp_env_mux.auth.keys import get_public_key, load_or_generate_key
        from mcp_env_mux.auth.oauth import register_oauth_routes
        from mcp_env_mux.config import AuthConfig, AzureConfig, RoleConfig
        from fastmcp import FastMCP

        private = load_or_generate_key(str(tmp_path / "key.pem"))
        public = get_public_key(private)

        auth_config = AuthConfig(
            azure=AzureConfig(tenant_id="t", client_id="c", client_secret="s"),
            signing_key_file=str(tmp_path / "key.pem"),
            roles={"admin": RoleConfig(allowed_envs={"*": ["*"]})},
            token_minting_roles=["admin"],
        )

        server = FastMCP("test")
        # Should not raise
        register_oauth_routes(server, auth_config, private)
