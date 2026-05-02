"""Unit tests for auth/keys.py."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from mcp_env_mux.auth.keys import get_public_key, load_or_generate_key


class TestLoadOrGenerateKey:
    def test_generates_key_when_missing(self, tmp_path):
        key_path = tmp_path / "test.pem"
        key = load_or_generate_key(str(key_path))
        assert isinstance(key, RSAPrivateKey)
        assert key_path.exists()

    def test_generated_key_is_2048_bit(self, tmp_path):
        key = load_or_generate_key(str(tmp_path / "test.pem"))
        assert key.key_size == 2048

    def test_loads_existing_key(self, tmp_path):
        key_path = tmp_path / "test.pem"
        # Generate first
        original = load_or_generate_key(str(key_path))
        # Load again
        loaded = load_or_generate_key(str(key_path))
        assert isinstance(loaded, RSAPrivateKey)
        # Same key material
        assert original.private_numbers() == loaded.private_numbers()

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c" / "key.pem"
        assert not nested.parent.exists()
        load_or_generate_key(str(nested))
        assert nested.exists()

    def test_written_file_is_pem(self, tmp_path):
        key_path = tmp_path / "test.pem"
        load_or_generate_key(str(key_path))
        content = key_path.read_text()
        assert "BEGIN" in content and "PRIVATE KEY" in content

    def test_loads_key_from_env_when_file_missing(self, tmp_path, monkeypatch):
        source_path = tmp_path / "source.pem"
        source_key = load_or_generate_key(str(source_path))
        source_pem = source_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        target_path = tmp_path / "from-env.pem"
        monkeypatch.setenv("MCP_ENV_MUX_SIGNING_KEY_PEM", source_pem)
        loaded = load_or_generate_key(str(target_path))

        assert target_path.exists()
        assert loaded.private_numbers() == source_key.private_numbers()

    def test_prefers_existing_file_over_env(self, tmp_path, monkeypatch):
        existing_path = tmp_path / "existing.pem"
        existing_key = load_or_generate_key(str(existing_path))

        other_path = tmp_path / "other.pem"
        other_key = load_or_generate_key(str(other_path))
        other_pem = other_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
        monkeypatch.setenv("MCP_ENV_MUX_SIGNING_KEY_PEM", other_pem)

        loaded = load_or_generate_key(str(existing_path))
        assert loaded.private_numbers() == existing_key.private_numbers()


class TestGetPublicKey:
    def test_returns_rsa_public_key(self, tmp_path):
        private = load_or_generate_key(str(tmp_path / "test.pem"))
        public = get_public_key(private)
        assert isinstance(public, RSAPublicKey)

    def test_public_key_size_matches(self, tmp_path):
        private = load_or_generate_key(str(tmp_path / "test.pem"))
        public = get_public_key(private)
        assert public.key_size == private.key_size
