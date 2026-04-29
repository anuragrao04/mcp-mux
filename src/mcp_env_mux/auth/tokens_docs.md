# tokens.py

## Purpose

JWT creation for **bot tokens** (long-lived, locally signed). User tokens are
issued by Microsoft Entra ID directly — they are no longer minted here.

## Public API

### `create_bot_token(private_key: RSAPrivateKey, name: str, roles: list[str], created_by: str, expiry_days: int) -> str`

Creates a long-lived RS256-signed JWT for a headless agent.

Claims: `sub` (= `name`), `type` (`"bot"`), `roles`, `created_by` (email of minting user), `jti` (UUID), `iat`, `exp` (= `iat + expiry_days * 86400`), `iss` (`"mcp-env-mux"`), `aud` (`"mcp-env-mux"`).

## Constants

- `_ISSUER = "mcp-env-mux"`
- `_AUDIENCE = "mcp-env-mux"`

## Dependencies

- `jwt` (PyJWT) for RS256 encoding
- `cryptography` types for key parameter typing

## Error Handling

No explicit error handling. If the private key is invalid, `jwt.encode` raises.

## Removed

`create_user_token` was removed. User tokens come from Azure now and are
verified by `HybridAzureProvider`'s parent path.
