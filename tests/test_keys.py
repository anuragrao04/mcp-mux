"""Unit tests for auth/keys.py."""

from __future__ import annotations

from pathlib import Path

import pytest
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


class TestGetPublicKey:
    def test_returns_rsa_public_key(self, tmp_path):
        private = load_or_generate_key(str(tmp_path / "test.pem"))
        public = get_public_key(private)
        assert isinstance(public, RSAPublicKey)

    def test_public_key_size_matches(self, tmp_path):
        private = load_or_generate_key(str(tmp_path / "test.pem"))
        public = get_public_key(private)
        assert public.key_size == private.key_size
