"""RSA key management: load or generate signing key."""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey


def load_or_generate_key(path: str) -> RSAPrivateKey:
    """Load an RSA private key from PEM file, or generate one if the file doesn't exist.

    Creates parent directories as needed. Writes the key in PEM format.
    """
    key_path = Path(path)

    if key_path.exists():
        pem_data = key_path.read_bytes()
        return serialization.load_pem_private_key(pem_data, password=None)

    # Generate a new 2048-bit RSA key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Write to file (create parent dirs)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    pem_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.write_bytes(pem_bytes)

    return private_key


def get_public_key(private_key: RSAPrivateKey) -> RSAPublicKey:
    """Extract the public key from a private key."""
    return private_key.public_key()
