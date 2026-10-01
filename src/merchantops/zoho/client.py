from __future__ import annotations

import asyncio
import random
from typing import Any
from urllib.parse import urlencode

import httpx

from merchantops.datacenters import resolve_datacenter, validate_api_domain
from merchantops.errors import (
    NotFoundError,
    RateLimited,
    UnauthorizedError,
    UpstreamError,
    classify_429,
)
from merchantops.infrastructure.cache import TtlCache
from merchantops.infrastructure.limiter import BudgetMeter, TokenBucket
from merchantops.models import Contact, Invoice, Item, Package, Page, SalesOrder, Shipment, Warehouse
from merchantops.security import assert_http_read
from merchantops.zoho.normalize import (
    normalize_contact,
    normalize_invoice,
    normalize_item,
    normalize_order,
    normalize_package,
    normalize_shipment,
    normalize_warehouse,
)


class ZohoClient:
    """Read-only Zoho Inventory client with budget, retry, and cache."""

    name = "zoho"

    def __init__(
        self,
        *,
        token_provider,
        organization_id: str,
        dc: str,
        meter: BudgetMeter,
        bucket: TokenBucket,
        cache: TtlCache,
        concurrency: int = 5,
        cache_ttl: float = 45,
        warehouse_cache_ttl: float = 600,
        http: httpx.AsyncClient | None = None,
        sleeper=asyncio.sleep,
        rng: random.Random | None = None,
        max_retries: int = 3,
        api_domain: str | None = None,
    ) -> None:
        if not organization_id:
            raise UpstreamError("ZOHO_ORGANIZATION_ID is required in live mode. Zoho expects it on every call.")
        _accounts, default_api = resolve_datacenter(dc)
        self.token_provider = token_provider
        self.organization_id = organization_id
        self.api_base = validate_api_domain(api_domain) if api_domain else default_api
        self.meter = meter
        self.bucket = bucket
        self.cache = cache
        self.cache_ttl = cache_ttl
        self.warehouse_cache_ttl = warehouse_cache_ttl
        self._http = http
        self._owns_http = http is None
        self.sleeper = sleeper
        self.rng = rng or random.Random()
        self.max_retries = max_retries
        self._semaphore = asyncio.Semaphore(concurrency)
        self._refreshed_for_401 = False

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=20)
        return self._http

    def _cache_key(self, path: str, params: dict[str, Any]) -> str:
        query = urlencode(sorted((key, "" if value is None else str(value)) for key, value in params.items()))
        return f"{self.api_base}{path}?{query}"

    async def get_json(self, path: str, params: dict[str, Any] | None = None, *, ttl: float | None = None) -> dict[str, Any]:
        merged = {"organization_id": self.organization_id, **(params or {})}
        key = self._cache_key(path, merged)
        value, _hit = await self.cache.get_or_set(
            key,
            ttl if ttl is not None else self.cache_ttl,
            lambda: self._fetch(path, merged),
        )
        return value

    async def _fetch(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.meter.daily_exhausted or self.meter.daily_used >= self.meter.daily_limit:
            await self.meter.mark_daily_exhausted()
            raise RateLimited(
                "Zoho daily API quota is exhausted for this organization. "
                "Tell the merchant and stop. Retrying will not succeed until the quota resets.",
                scope="daily",
                retry_after=None,
            )
        attempt = 0
        refreshed = False
        while True:
            await self.bucket.acquire()
            response, body = await self._send("GET", path, params)
            if response.status_code == 401:
                if not refreshed:
                    refreshed = True
                    await self.token_provider.refresh()
                    continue
                raise UnauthorizedError("Zoho rejected the access token after a refresh.")
            if response.status_code == 429:
                scope = classify_429(body)
                if scope == "daily":
                    await self.meter.mark_daily_exhausted()
                    raise RateLimited(
                        str(body.get("message") or "Zoho daily API quota is exhausted."),
                        scope="daily",
                        retry_after=None,
                    )
                retry_after = _retry_after(response) or _backoff(attempt, self.rng)
                if attempt >= self.max_retries:
                    raise RateLimited(
                        str(body.get("message") or "Zoho per-minute limit reached."),
                        scope="per_minute",
                        retry_after=retry_after,
                    )
                attempt += 1
                await self.sleeper(retry_after)
                continue
            if response.status_code == 404:
                raise NotFoundError(str(body.get("message") or "Zoho resource was not found."))
            if response.status_code >= 400:
                raise UpstreamError(
                    str(body.get("message") or f"Zoho returned HTTP {response.status_code}."),
                    status=response.status_code,
                )
            if body.get("code") not in (0, None, "0"):
                raise UpstreamError(str(body.get("message") or "Zoho returned an error payload."))
            return body

    async def _send(self, method: str, path: str, params: dict[str, Any]) -> tuple[httpx.Response, dict[str, Any]]:
        assert_http_read(method)
        token = await self.token_provider.access_token()
        headers = {"Authorization": f"Zoho-oauthtoken {token}"}
        async with self._semaphore:
            await self.meter.record()
            client = await self._client()
            response = await client.request(method, f"{self.api_base}/inventory/v1{path}", params=params, headers=headers)
        try:
            body = response.json()
        except ValueError:
            body = {"message": response.text[:300]}
        if not isinstance(body, dict):
            body = {"message": "Zoho returned a non-object JSON body."}
        return response, body

    async def list_items(self, *, page: int, per_page: int, search_text: str | None = None) -> Page:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if search_text:
            params["search_text"] = search_text
        body = await self.get_json("/items", params)
        return _page(body, "items", normalize_item, page, per_page)

    async def get_item(self, item_id: str) -> Item:
        body = await self.get_json(f"/items/{item_id}", ttl=self.cache_ttl)
        raw = body.get("item") or body
        return normalize_item(raw)

    async def list_orders(
        self,
        *,
        page: int,
        per_page: int,
        status: str | None = None,
        search_text: str | None = None,
        customer_id: str | None = None,
    ) -> Page:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if status:
            params["status"] = status
        if search_text:
            params["search_text"] = search_text
        if customer_id:
            params["customer_id"] = customer_id
        body = await self.get_json("/salesorders", params)
        return _page(body, "salesorders", normalize_order, page, per_page)

    async def get_order(self, order_id: str) -> SalesOrder:
        body = await self.get_json(f"/salesorders/{order_id}")
        raw = body.get("salesorder") or body
        return normalize_order(raw)

    async def list_invoices(
        self,
        *,
        page: int,
        per_page: int,
        status: str | None = None,
        search_text: str | None = None,
        customer_id: str | None = None,
    ) -> Page:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if status:
            params["status"] = status
        if search_text:
            params["search_text"] = search_text
        if customer_id:
            params["customer_id"] = customer_id
        body = await self.get_json("/invoices", params)
        return _page(body, "invoices", normalize_invoice, page, per_page)

    async def list_shipments(self, *, page: int, per_page: int, search_text: str | None = None) -> Page:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if search_text:
            params["search_text"] = search_text
        body = await self.get_json("/shipmentorders", params)
        return _page(body, "shipmentorders", normalize_shipment, page, per_page)

    async def list_packages(self, *, page: int, per_page: int, search_text: str | None = None) -> Page:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if search_text:
            params["search_text"] = search_text
        body = await self.get_json("/packages", params)
        return _page(body, "packages", normalize_package, page, per_page)

    async def list_warehouses(self) -> list[Warehouse]:
        body = await self.get_json("/settings/warehouses", ttl=self.warehouse_cache_ttl)
        rows = body.get("warehouses") or []
        return [normalize_warehouse(row) for row in rows]

    async def get_contact(self, contact_id: str) -> Contact:
        body = await self.get_json(f"/contacts/{contact_id}")
        raw = body.get("contact") or body
        return normalize_contact(raw)


def _page(body: dict[str, Any], key: str, normalizer, page: int, per_page: int) -> Page:
    context = body.get("page_context") or {}
    has_more = bool(context.get("has_more_page"))
    items = [normalizer(row) for row in body.get(key) or []]
    return Page(items=items, page=page, per_page=per_page, has_more=has_more)


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _backoff(attempt: int, rng: random.Random) -> float:
    delay = min(0.5 * (2**attempt), 8.0)
    return delay + rng.uniform(0, delay * 0.3)
