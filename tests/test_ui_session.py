from __future__ import annotations

import time

from mcp_env_mux.auth.keys import get_public_key, load_or_generate_key
from mcp_env_mux.auth.ui import (
    _create_ui_login_token,
    _create_ui_session_token,
    _load_ui_login_token,
    _load_ui_session,
    _validate_next_path,
)


def test_validate_next_path_accepts_safe_relative_paths():
    assert _validate_next_path("/ui/tokens") == "/ui/tokens"
    assert _validate_next_path("/ui/tokens?foo=bar") == "/ui/tokens?foo=bar"
    assert _validate_next_path("/nested/path") == "/nested/path"


def test_validate_next_path_rejects_unsafe_values():
    assert _validate_next_path(None) == "/ui/tokens"
    assert _validate_next_path("") == "/ui/tokens"
    assert _validate_next_path("https://evil.example") == "/ui/tokens"
    assert _validate_next_path("//evil.example") == "/ui/tokens"
    assert _validate_next_path("relative/path") == "/ui/tokens"


def test_ui_session_round_trip(tmp_path):
    private = load_or_generate_key(str(tmp_path / "ui.pem"))
    public = get_public_key(private)
    public_pem = public.public_bytes_raw().decode() if hasattr(public, "public_bytes_raw") else None
    if public_pem is None:
        from cryptography.hazmat.primitives import serialization

        public_pem = public.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    token = _create_ui_session_token(
        private_key=private,
        subject="user@example.com",
        roles=["admin"],
        expires_in_seconds=3600,
    )
    session = _load_ui_session(token, public_pem)
    assert session is not None
    assert session["sub"] == "user@example.com"
    assert session["roles"] == ["admin"]
    assert session["type"] == "ui_session"


def test_ui_login_token_round_trip(tmp_path):
    private = load_or_generate_key(str(tmp_path / "ui-login.pem"))
    public = get_public_key(private)
    from cryptography.hazmat.primitives import serialization

    public_pem = public.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    token = _create_ui_login_token(
        private_key=private,
        transaction_id="txn-123",
        next_path="/ui/tokens",
        expires_in_seconds=600,
    )
    claims = _load_ui_login_token(token, public_pem)
    assert claims is not None
    assert claims["txn_id"] == "txn-123"
    assert claims["next"] == "/ui/tokens"
    assert claims["type"] == "ui_login"


def test_ui_login_token_rejects_tampered_or_expired_token(tmp_path):
    private = load_or_generate_key(str(tmp_path / "ui-login-expired.pem"))
    public = get_public_key(private)
    from cryptography.hazmat.primitives import serialization

    public_pem = public.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    expired = _create_ui_login_token(
        private_key=private,
        transaction_id="txn-123",
        next_path="/ui/tokens",
        expires_in_seconds=-1,
    )
    assert _load_ui_login_token(expired, public_pem) is None

    parts = expired.split(".")
    tampered = parts[0] + "." + parts[1] + ".broken"
    assert _load_ui_login_token(tampered, public_pem) is None


def test_ui_session_rejects_tampered_or_expired_token(tmp_path):
    private = load_or_generate_key(str(tmp_path / "ui-expired.pem"))
    public = get_public_key(private)
    from cryptography.hazmat.primitives import serialization

    public_pem = public.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    expired = _create_ui_session_token(
        private_key=private,
        subject="user@example.com",
        roles=["admin"],
        expires_in_seconds=-1,
    )
    assert _load_ui_session(expired, public_pem) is None

    parts = expired.split(".")
    tampered = parts[0] + "." + parts[1] + ".broken"
    assert _load_ui_session(tampered, public_pem) is None
