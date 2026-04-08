"""Unit tests for auth/tokens.py."""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest

from mcp_env_mux.auth.keys import get_public_key, load_or_generate_key
from mcp_env_mux.auth.tokens import create_bot_token, create_user_token

_ISSUER = "mcp-env-mux"
_AUDIENCE = "mcp-env-mux"


@pytest.fixture(scope="module")
def keypair(tmp_path_factory):
    key_path = tmp_path_factory.mktemp("keys") / "test.pem"
    private = load_or_generate_key(str(key_path))
    public = get_public_key(private)
    return private, public


def _decode(token: str, public_key) -> dict:
    return pyjwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        audience=_AUDIENCE,
        issuer=_ISSUER,
    )


class TestCreateUserToken:
    def test_returns_string(self, keypair):
        private, _ = keypair
        token = create_user_token(private, "user@example.com", ["admin"])
        assert isinstance(token, str)

    def test_verifies_with_public_key(self, keypair):
        private, public = keypair
        token = create_user_token(private, "user@example.com", ["admin"])
        claims = _decode(token, public)
        assert claims["sub"] == "user@example.com"

    def test_required_claims_present(self, keypair):
        private, public = keypair
        token = create_user_token(private, "user@example.com", ["admin"])
        claims = _decode(token, public)
        for field in ("sub", "type", "roles", "created_by", "jti", "iat", "exp", "iss", "aud"):
            assert field in claims, f"Missing claim: {field}"

    def test_type_is_user(self, keypair):
        private, public = keypair
        token = create_user_token(private, "user@example.com", ["admin"])
        assert _decode(token, public)["type"] == "user"

    def test_created_by_equals_sub(self, keypair):
        private, public = keypair
        token = create_user_token(private, "user@example.com", ["admin"])
        claims = _decode(token, public)
        assert claims["created_by"] == claims["sub"]

    def test_roles_embedded(self, keypair):
        private, public = keypair
        token = create_user_token(private, "user@example.com", ["admin", "readonly"])
        claims = _decode(token, public)
        assert set(claims["roles"]) == {"admin", "readonly"}

    def test_jti_is_unique(self, keypair):
        private, _ = keypair
        t1 = create_user_token(private, "user@example.com", [])
        t2 = create_user_token(private, "user@example.com", [])
        c1 = pyjwt.decode(t1, options={"verify_signature": False})
        c2 = pyjwt.decode(t2, options={"verify_signature": False})
        assert c1["jti"] != c2["jti"]

    def test_default_expiry_is_one_hour(self, keypair):
        private, public = keypair
        before = int(time.time())
        token = create_user_token(private, "user@example.com", [])
        claims = _decode(token, public)
        delta = claims["exp"] - claims["iat"]
        assert delta == 3600

    def test_custom_expiry(self, keypair):
        private, public = keypair
        token = create_user_token(private, "user@example.com", [], expiry_seconds=7200)
        claims = _decode(token, public)
        assert claims["exp"] - claims["iat"] == 7200


class TestCreateBotToken:
    def test_returns_string(self, keypair):
        private, _ = keypair
        token = create_bot_token(private, "my-bot", ["readonly"], "admin@example.com", 30)
        assert isinstance(token, str)

    def test_type_is_bot(self, keypair):
        private, public = keypair
        token = create_bot_token(private, "my-bot", ["readonly"], "admin@example.com", 30)
        assert _decode(token, public)["type"] == "bot"

    def test_sub_is_name(self, keypair):
        private, public = keypair
        token = create_bot_token(private, "my-bot", ["readonly"], "admin@example.com", 30)
        assert _decode(token, public)["sub"] == "my-bot"

    def test_created_by_set(self, keypair):
        private, public = keypair
        token = create_bot_token(private, "my-bot", ["readonly"], "admin@example.com", 30)
        assert _decode(token, public)["created_by"] == "admin@example.com"

    def test_expiry_in_days(self, keypair):
        private, public = keypair
        token = create_bot_token(private, "my-bot", [], "admin@example.com", 7)
        claims = _decode(token, public)
        expected_delta = 7 * 86400
        actual_delta = claims["exp"] - claims["iat"]
        assert actual_delta == expected_delta
