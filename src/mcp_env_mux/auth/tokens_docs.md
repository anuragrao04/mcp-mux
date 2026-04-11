# tokens.py

## Purpose

JWT token creation for mcp-env-mux. Creates RS256-signed JWTs for two token types: short-lived user tokens (from OAuth login) and long-lived bot tokens (for headless agents).

## Public API

### `create_user_token(private_key: RSAPrivateKey, subject: str, roles: list[str], expiry_seconds: int = 3600) -> str`

Creates a short-lived JWT for an authenticated employee.

Claims: `sub` (subject), `type` ("user"), `roles`, `created_by` (same as sub), `jti` (UUID), `iat`, `exp` (iat + expiry_seconds), `iss` ("mcp-env-mux"), `aud` ("mcp-env-mux").

### `create_bot_token(private_key: RSAPrivateKey, name: str, roles: list[str], created_by: str, expiry_days: int) -> str`

Creates a long-lived JWT for a headless agent.

Claims: `sub` (name), `type` ("bot"), `roles`, `created_by`, `jti` (UUID), `iat`, `exp` (iat + expiry_days * 86400), `iss` ("mcp-env-mux"), `aud` ("mcp-env-mux").

## Constants

- `_ISSUER` = `"mcp-env-mux"`
- `_AUDIENCE` = `"mcp-env-mux"`

## Dependencies

- `jwt` (PyJWT) for RS256 encoding
- `cryptography` types for key parameter typing

## Error Handling

No explicit error handling. If the private key is invalid, `jwt.encode` raises.
