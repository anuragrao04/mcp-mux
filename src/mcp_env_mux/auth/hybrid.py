"""HybridAzureProvider: AzureProvider that also accepts locally-minted bot JWTs."""

from __future__ import annotations

from typing import Any

from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier


class HybridAzureProvider(AzureProvider):
    """AzureProvider that also accepts locally-minted bot tokens.

    Inherits the full Azure OAuth flow (DCR proxy, login, callback, token
    endpoint, discovery routes, JWKS-based JWT verification). Adds a dispatch
    in verify_token() that routes tokens with iss == local_issuer to a local
    JWTVerifier configured with the bot-signing public key.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        base_url: str,
        required_scopes: list[str],
        local_public_key_pem: str,
        local_issuer: str = "mcp-env-mux",
        local_audience: str = "mcp-env-mux",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            tenant_id=tenant_id,
            base_url=base_url,
            required_scopes=required_scopes,
            **kwargs,
        )
        self._local_verifier = JWTVerifier(
            public_key=local_public_key_pem,
            issuer=local_issuer,
            audience=local_audience,
        )
        self._local_issuer = local_issuer

    async def verify_token(self, token: str):  # type: ignore[override]
        """Verify a Bearer token. Returns AccessToken or None."""
        # Peek at iss claim without verifying signature, so we can dispatch
        # to the right verifier.
        iss = ""
        try:
            import jwt as pyjwt

            unverified = pyjwt.decode(token, options={"verify_signature": False})
            iss = unverified.get("iss", "") or ""
        except Exception:
            # Unparseable token — fall through to Azure path which will reject.
            iss = ""

        try:
            if iss == self._local_issuer:
                access_token = await self._local_verifier.verify_token(token)
                if access_token is None:
                    return None
                # Bot tokens are locally trusted — grant the OAuth provider's
                # required scopes so the upstream BearerAuth middleware does
                # not reject with "insufficient_scope". A valid local
                # signature is the trust anchor; scope checks at the OAuth
                # layer are bypassed for bot principals.
                granted_scopes = list(self.required_scopes or [])
                if granted_scopes:
                    return access_token.model_copy(update={"scopes": granted_scopes})
                return access_token
            return await super().verify_token(token)
        except Exception:
            # Defensive: never raise out of verify_token.
            return None
