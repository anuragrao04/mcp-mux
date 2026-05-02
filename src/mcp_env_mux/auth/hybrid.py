"""HybridAzureProvider: AzureProvider that also accepts locally-minted bot JWTs."""

from __future__ import annotations

import os
import secrets
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastmcp.server.auth.oauth_proxy.models import OAuthTransaction
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

    async def start_ui_authorization(self, *, callback_url: str) -> tuple[str, str]:
        """Start a provider-backed UI authorization flow.

        Reuses OAuthProxy transaction storage plus AzureProvider authorize URL
        construction, but targets the UI callback instead of the MCP OAuth flow.
        """
        txn_id = secrets.token_urlsafe(32)
        transaction = OAuthTransaction(
            txn_id=txn_id,
            client_id="ui-session",
            client_redirect_uri=callback_url,
            client_state="",
            code_challenge=None,
            code_challenge_method="S256",
            scopes=list(self.required_scopes or []),
            created_at=time.time(),
            resource=None,
            proxy_code_verifier=None,
        )
        await self._transaction_store.put(
            key=txn_id,
            value=transaction,
            ttl=15 * 60,
        )
        authorize_url = self._build_upstream_authorize_url(txn_id, transaction.model_dump())
        parsed = urlparse(authorize_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["redirect_uri"] = callback_url
        authorize_url = urlunparse(parsed._replace(query=urlencode(query)))
        return authorize_url, txn_id

    async def complete_ui_authorization(
        self, *, code: str, state: str, callback_url: str
    ) -> dict[str, Any]:
        """Complete a provider-backed UI authorization flow and return claims."""
        transaction_model = await self._transaction_store.get(key=state)
        if not transaction_model:
            raise ValueError("Invalid login state.")

        if transaction_model.client_redirect_uri != callback_url:
            raise ValueError("Invalid login callback.")

        if os.getenv("MCP_ENV_MUX_TEST_UI_AUTH_SUBJECT"):
            await self._transaction_store.delete(key=state)
            subject = os.getenv("MCP_ENV_MUX_TEST_UI_AUTH_SUBJECT", "")
            roles_raw = os.getenv("MCP_ENV_MUX_TEST_UI_AUTH_ROLES", "")
            roles = [r.strip() for r in roles_raw.split(",") if r.strip()]
            return {
                "preferred_username": subject,
                "email": subject,
                "sub": subject,
                "roles": roles,
            }

        oauth_client = self._create_upstream_oauth_client()
        exchange_scopes = self._prepare_scopes_for_token_exchange(
            transaction_model.scopes or []
        )
        token_params: dict[str, Any] = {
            "url": self._upstream_token_endpoint,
            "code": code,
            "redirect_uri": callback_url,
        }
        if exchange_scopes:
            token_params["scope"] = " ".join(exchange_scopes)
        if self._extra_token_params:
            token_params.update(self._extra_token_params)

        idp_tokens: dict[str, Any] = await oauth_client.fetch_token(**token_params)
        await self._transaction_store.delete(key=state)
        claims = await self._extract_upstream_claims(idp_tokens)
        return claims or {}

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
