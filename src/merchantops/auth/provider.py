from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from merchantops.auth.oauth import ZohoOAuth, token_needs_refresh
from merchantops.auth.store import TokenStore
from merchantops.config import Settings
from merchantops.errors import ConfigError
from merchantops.models import TokenSet


class StaticTokenProvider:
    """Self-client mode: a pre-generated access token, refreshed only on 401 if possible."""

    def __init__(self, access_token: str) -> None:
        self._access_token = access_token

    async def access_token(self) -> str:
        return self._access_token

    async def refresh(self) -> str:
        raise ConfigError(
            "Zoho rejected the access token and no refresh token is configured. "
            "Set ZOHO_REFRESH_TOKEN or run merchantops-auth login."
        )


class RefreshingTokenProvider:
    def __init__(self, token: TokenSet, oauth: ZohoOAuth, store: TokenStore | None, *, now=None) -> None:
        self.token = token
        self.oauth = oauth
        self.store = store
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def access_token(self) -> str:
        if token_needs_refresh(self.token, self._now()):
            await self.refresh()
        return self.token.access_token

    async def refresh(self) -> str:
        if not self.token.refresh_token:
            raise ConfigError("Cannot refresh: the stored Zoho token has no refresh_token.")
        refreshed = await self.oauth.refresh(self.token.refresh_token, previous=self.token)
        self.token = refreshed
        if self.store is not None:
            self.store.save(refreshed)
        return refreshed.access_token


def provider_from_settings(settings: Settings, http: httpx.AsyncClient):
    store = None
    stored = None
    if settings.token_encryption_key:
        store = TokenStore(settings.token_store_path, settings.token_encryption_key)
        stored = store.load()
    if stored and stored.refresh_token and settings.client_id and settings.client_secret:
        oauth = ZohoOAuth(
            dc=settings.zoho_dc,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            redirect_uri=settings.redirect_uri,
            http=http,
        )
        return RefreshingTokenProvider(stored, oauth, store)
    if settings.refresh_token and settings.client_id and settings.client_secret:
        expires = (datetime.now(timezone.utc) + timedelta(minutes=50)).isoformat()
        token = TokenSet(
            access_token=settings.access_token or "pending-refresh",
            refresh_token=settings.refresh_token,
            expires_at=expires,
            dc=settings.zoho_dc,
        )
        oauth = ZohoOAuth(
            dc=settings.zoho_dc,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            redirect_uri=settings.redirect_uri,
            http=http,
        )
        # Force an early refresh when the env access token is missing.
        if not settings.access_token:
            token = TokenSet(
                access_token="pending-refresh",
                refresh_token=settings.refresh_token,
                expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                dc=settings.zoho_dc,
            )
        return RefreshingTokenProvider(token, oauth, store)
    if settings.access_token:
        return StaticTokenProvider(settings.access_token)
    raise ConfigError(
        "Live mode needs Zoho credentials. Set ZOHO_ACCESS_TOKEN (self-client), "
        "or ZOHO_REFRESH_TOKEN with the client id/secret, or run merchantops-auth login. "
        "Use ZOHO_MODE=demo to run the fixture merchant without credentials."
    )
