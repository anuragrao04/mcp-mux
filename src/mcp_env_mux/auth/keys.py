"""RSA key management: load or generate signing key."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey


def load_or_generate_key(path: str) -> RSAPrivateKey:
    """Load an RSA private key from PEM file, env var, or generate one.

    Resolution order:
    1. If the file exists, load it.
    2. Else if MCP_ENV_MUX_SIGNING_KEY_PEM is set, write it to the file and load it.
    3. Else generate a new 2048-bit RSA key, write it to the file, and log loudly.

    Creates parent directories as needed. Writes the key in PEM format.
    """
    logger = logging.getLogger("mcp_env_mux")
    key_path = Path(path)

    if key_path.exists():
        logger.info(
            "loading_signing_key_from_file",
            extra={"path": str(key_path), "source": "file"},
        )
        pem_data = key_path.read_bytes()
        return serialization.load_pem_private_key(pem_data, password=None)

    env_pem = os.getenv("MCP_ENV_MUX_SIGNING_KEY_PEM")
    if env_pem:
        logger.info(
            "loading_signing_key_from_env",
            extra={"source": "env", "source_env_var": "MCP_ENV_MUX_SIGNING_KEY_PEM", "path": str(key_path)},
        )
        pem_bytes = env_pem.encode("utf-8")
        private_key = serialization.load_pem_private_key(pem_bytes, password=None)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(pem_bytes)
        logger.warning(
            "signing_key_loaded_from_env_and_written_to_file",
            extra={"path": str(key_path), "source": "env", "source_env_var": "MCP_ENV_MUX_SIGNING_KEY_PEM"},
        )
        return private_key

    logger.warning(
        "generating_new_signing_key_horizontal_scaling_warning",
        extra={
            "path": str(key_path),
            "source": "generated",
            "reason": "signing key file missing and MCP_ENV_MUX_SIGNING_KEY_PEM not set",
            "warning": "a new signing key is being generated automatically; horizontal scaling and rolling restarts will not work correctly unless all replicas share the same signing key",
        },
    )
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    key_path.parent.mkdir(parents=True, exist_ok=True)
    pem_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.write_bytes(pem_bytes)

    logger.warning(
        "new_signing_key_written_to_file",
        extra={"path": str(key_path), "source": "generated"},
    )
    return private_key


def get_public_key(private_key: RSAPrivateKey) -> RSAPublicKey:
    """Extract the public key from a private key."""
    return private_key.public_key()
