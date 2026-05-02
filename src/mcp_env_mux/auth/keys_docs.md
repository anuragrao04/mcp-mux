# keys.py

## Purpose

RSA key management: loads an existing PEM private key from disk, or if absent loads PEM content from `MCP_ENV_MUX_SIGNING_KEY_PEM` and writes it to disk, or generates a new 2048-bit RSA key and writes it to the specified path. Also extracts the public key from a private key.

## Public API

### `load_or_generate_key(path: str) -> RSAPrivateKey`

Loads an RSA private key from PEM file at `path`. Resolution order:
1. If the file exists, load it.
2. Else if `MCP_ENV_MUX_SIGNING_KEY_PEM` is set, write that PEM content to `path` and load it.
3. Else generate a new 2048-bit RSA key (exponent 65537), create parent directories, write the key in PEM format (TraditionalOpenSSL, no encryption), and return it.

When a new key is generated, the module logs warning-level events loudly so operators notice implicit key creation.

### `get_public_key(private_key: RSAPrivateKey) -> RSAPublicKey`

Extracts and returns the public key from a private key.

## Dependencies

- `cryptography` (hazmat primitives for RSA and PEM serialization)

## Error Handling

- If the PEM file exists but is malformed, `serialization.load_pem_private_key` raises an exception from the `cryptography` library.
- If parent directory creation fails, standard `OSError` propagates.
