# test_hybrid.py

## Purpose

Unit tests for `mcp_env_mux.auth.hybrid.HybridAzureProvider`. Exercises the
`verify_token` dispatch logic without making real Azure network calls.

## Test Functions

### `test_bot_token_dispatched_to_local_verifier`

Mints a bot JWT with the local RSA private key, presents it to a
`HybridAzureProvider` whose `super().verify_token` is patched to raise (so the
test fails if the wrong branch is taken). Asserts the returned `AccessToken`
carries the bot's roles and `sub`.

### `test_bad_bot_signature_returns_none`

Mints a JWT with a different RSA key, presents it, asserts `verify_token`
returns `None`.

### `test_azure_token_dispatched_to_super`

Builds a JWT with `iss="https://login.microsoftonline.com/<tenant>/v2.0"`, patches
`AzureProvider.verify_token` (the super) to return a sentinel `AccessToken`, asserts
the sentinel is returned (proving the super path was used).

### `test_garbage_token_returns_none`

Presents a non-JWT string and a JWT with no `iss` claim. Both return `None`
without raising.

### `test_unknown_issuer_falls_through_to_super`

Token with an `iss` that's neither `"mcp-env-mux"` nor Azure: still routed to
super (which will reject). Asserts `super().verify_token` is invoked.

## Dependencies

- `mcp_env_mux.auth.hybrid.HybridAzureProvider`
- `mcp_env_mux.auth.tokens.create_bot_token`
- `mcp_env_mux.auth.keys.load_or_generate_key`
- `pytest-asyncio`
- `unittest.mock` (patching the super path)
