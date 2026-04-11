# keys.py

## Purpose

RSA key management: loads an existing PEM private key from disk, or generates a new 2048-bit RSA key and writes it to the specified path. Also extracts the public key from a private key.

## Public API

### `load_or_generate_key(path: str) -> RSAPrivateKey`

Loads an RSA private key from PEM file at `path`. If the file does not exist, generates a new 2048-bit RSA key (exponent 65537), creates parent directories, writes the key in PEM format (TraditionalOpenSSL, no encryption), and returns it.

### `get_public_key(private_key: RSAPrivateKey) -> RSAPublicKey`

Extracts and returns the public key from a private key.

## Dependencies

- `cryptography` (hazmat primitives for RSA and PEM serialization)

## Error Handling

- If the PEM file exists but is malformed, `serialization.load_pem_private_key` raises an exception from the `cryptography` library.
- If parent directory creation fails, standard `OSError` propagates.
