from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from merchantops.datacenters import resolve_datacenter, validate_api_domain
from merchantops.errors import ConfigError, UnauthorizedError
from merchantops.models import TokenSet

# Granular read scopes. ZohoInventory.FullAccess.ALL is intentionally absent.
READ_SCOPES = (
    "ZohoInventory.salesorders.READ",
    "ZohoInventory.items.READ",
    "ZohoInventory.invoices.READ",
    "ZohoInventory.contacts.READ",
    "ZohoInventory.settings.READ",
    "ZohoInventory.shipmentorders.READ",
    "ZohoInventory.packages.READ",
)

REFRESH_SKEW = timedelta(seconds=60)


def build_authorization_url(
    *,
    dc: str,
    client_id: str,
    redirect_uri: str,
    state: str | None = None,
) -> tuple[str, str]:
    if not client_id:
        raise ConfigError("ZOHO_CLIENT_ID is required to start the OAuth flow.")
    accounts, _api = resolve_datacenter(dc)
    csrf = state or secrets.token_urlsafe(24)
    query = urlencode(
        {
            "scope": ",".join(READ_SCOPES),
            "client_id": client_id,
            "response_type": "code",
            "access_type": "offline",
            "redirect_uri": redirect_uri,
            "prompt": "consent",
            "state": csrf,
        }
    )
    return f"{accounts}/oauth/v2/auth?{query}", csrf


def _expires_at(expires_in: int, now: datetime | None = None) -> str:
    base = now or datetime.now(timezone.utc)
    return (base + timedelta(seconds=int(expires_in))).isoformat()


def token_from_response(payload: dict[str, Any], *, dc: str, previous: TokenSet | None = None) -> TokenSet:
    access = payload.get("access_token")
    if not access:
        raise UnauthorizedError(payload.get("error") or "Zoho token response did not include an access_token.")
    refresh = payload.get("refresh_token") or (previous.refresh_token if previous else None)
    api_domain = payload.get("api_domain")
    if api_domain:
        api_domain = validate_api_domain(str(api_domain))
    return TokenSet(
        access_token=str(access),
        refresh_token=str(refresh) if refresh else None,
        expires_at=_expires_at(int(payload.get("expires_in") or 3600)),
        api_domain=api_domain,
        dc=dc,
    )


class ZohoOAuth:
    def __init__(self, *, dc: str, client_id: str, client_secret: str, redirect_uri: str, http: httpx.AsyncClient) -> None:
        self.dc = dc
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.http = http
        self.accounts, _api = resolve_datacenter(dc)

    async def exchange_code(self, code: str) -> TokenSet:
        return await self._token(
            {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "code": code,
            }
        )

    async def refresh(self, refresh_token: str, previous: TokenSet | None = None) -> TokenSet:
        return await self._token(
            {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
            },
            previous=previous,
        )

    async def _token(self, form: dict[str, str], previous: TokenSet | None = None) -> TokenSet:
        if not self.client_id or not self.client_secret:
            raise ConfigError("ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET are required to refresh tokens.")
        response = await self.http.post(f"{self.accounts}/oauth/v2/token", data=form, timeout=20)
        try:
            payload = response.json()
        except ValueError as exc:
            raise UnauthorizedError("Zoho token endpoint returned a non-JSON body.") from exc
        if response.status_code >= 400 or payload.get("error"):
            raise UnauthorizedError(str(payload.get("error") or payload.get("message") or "Token request failed."))
        return token_from_response(payload, dc=self.dc, previous=previous)


def token_needs_refresh(token: TokenSet, now: datetime, *, skew: timedelta = REFRESH_SKEW) -> bool:
    expires = datetime.fromisoformat(token.expires_at)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires - now <= skew
