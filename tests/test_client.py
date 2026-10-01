import asyncio

import httpx
import pytest
import respx

from merchantops.errors import RateLimited, ReadOnlyViolation
from merchantops.infrastructure.cache import TtlCache
from merchantops.infrastructure.clock import Clock, ManualClock
from merchantops.infrastructure.limiter import BudgetMeter, TokenBucket
from merchantops.zoho.client import ZohoClient
from merchantops.zoho.normalize import normalize_order


class Tokens:
    def __init__(self, token="test-token"):
        self.token = token
        self.refreshes = 0

    async def access_token(self):
        return self.token

    async def refresh(self):
        self.refreshes += 1
        self.token = "refreshed-token"
        return self.token


def _client(http, *, meter=None, clock=None, sleeper=None, max_retries=2, rng_seed=1):
    import random

    clock = clock or Clock()
    meter = meter or BudgetMeter(daily_limit=1000, per_minute_limit=100, clock=clock)

    async def default_sleep(seconds):
        return None

    return ZohoClient(
        token_provider=Tokens(),
        organization_id="org_1",
        dc="in",
        meter=meter,
        bucket=TokenBucket(rate_per_minute=80, capacity=80, clock=clock, sleeper=sleeper or default_sleep),
        cache=TtlCache(clock),
        http=http,
        sleeper=sleeper or default_sleep,
        rng=random.Random(rng_seed),
        max_retries=max_retries,
    )


ITEM = {
    "code": 0,
    "item": {
        "item_id": "it_1",
        "sku": "SKU-1",
        "name": "Cable",
        "available_stock": 4,
        "stock_on_hand": 5,
        "reorder_level": 2,
    },
}


@pytest.mark.asyncio
async def test_get_sends_zoho_header_org_and_india_host():
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://www.zohoapis.in/inventory/v1/items/it_1").mock(
            return_value=httpx.Response(200, json=ITEM)
        )
        async with httpx.AsyncClient() as http:
            client = _client(http)
            item = await client.get_item("it_1")
        request = route.calls[0].request
        assert request.headers["Authorization"] == "Zoho-oauthtoken test-token"
        assert request.url.params["organization_id"] == "org_1"
        assert item.sku == "SKU-1"
        assert item.available == 4


@pytest.mark.asyncio
async def test_per_minute_429_retries_and_daily_429_fails_fast():
    sleeps = []

    async def sleeper(seconds):
        sleeps.append(seconds)

    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://www.zohoapis.in/inventory/v1/items/it_1").mock(
            side_effect=[
                httpx.Response(429, json={"code": 44, "message": "exceeded the maximum number of requests per minute"}),
                httpx.Response(429, json={"code": 44, "message": "per minute"}),
                httpx.Response(200, json=ITEM),
            ]
        )
        async with httpx.AsyncClient() as http:
            client = _client(http, sleeper=sleeper, max_retries=2)
            item = await client.get_item("it_1")
        assert item.sku == "SKU-1"
        assert len(sleeps) == 2
        assert len(route.calls) == 3

    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://www.zohoapis.in/inventory/v1/items/it_1").mock(
            return_value=httpx.Response(429, json={"code": 45, "message": "maximum call rate limit of 1000"})
        )
        async with httpx.AsyncClient() as http:
            clock = Clock()
            meter = BudgetMeter(daily_limit=1000, per_minute_limit=100, clock=clock)
            client = _client(http, meter=meter, sleeper=sleeper)
            with pytest.raises(RateLimited) as raised:
                await client.get_item("it_1")
            assert raised.value.scope == "daily"
            assert raised.value.retry_after is None
            with pytest.raises(RateLimited):
                await client.get_item("it_2")
        assert len(route.calls) == 1


@pytest.mark.asyncio
async def test_401_refreshes_once():
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://www.zohoapis.in/inventory/v1/items/it_1").mock(
            side_effect=[
                httpx.Response(401, json={"code": 57, "message": "invalid oauth token"}),
                httpx.Response(200, json=ITEM),
            ]
        )
        async with httpx.AsyncClient() as http:
            client = _client(http)
            await client.get_item("it_1")
        assert route.calls[0].request.headers["Authorization"] == "Zoho-oauthtoken test-token"
        assert route.calls[1].request.headers["Authorization"] == "Zoho-oauthtoken refreshed-token"


@pytest.mark.asyncio
async def test_cache_and_inflight_dedup():
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://www.zohoapis.in/inventory/v1/items/it_1").mock(
            return_value=httpx.Response(200, json=ITEM)
        )
        async with httpx.AsyncClient() as http:
            client = _client(http)
            await client.get_item("it_1")
            await client.get_item("it_1")
        assert len(route.calls) == 1

    started = asyncio.Event()
    release = asyncio.Event()
    calls = {"n": 0}

    async def slow(request):
        calls["n"] += 1
        started.set()
        await release.wait()
        return httpx.Response(200, json=ITEM)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://www.zohoapis.in/inventory/v1/items/it_1").mock(side_effect=slow)
        async with httpx.AsyncClient() as http:
            client = _client(http)
            first = asyncio.create_task(client.get_item("it_1"))
            await started.wait()
            second = asyncio.create_task(client.get_item("it_1"))
            await asyncio.sleep(0.05)
            assert calls["n"] == 1
            release.set()
            await asyncio.gather(first, second)
        assert calls["n"] == 1


@pytest.mark.asyncio
async def test_post_is_blocked_before_the_network():
    async with httpx.AsyncClient() as http:
        client = _client(http)
        with pytest.raises(ReadOnlyViolation):
            await client._send("POST", "/salesorders", {})


def test_normalizer_extracts_razorpay_ids_and_drops_notes():
    order = normalize_order(
        {
            "salesorder_id": "so_1",
            "salesorder_number": "SO-1",
            "date": "2026-10-01",
            "status": "confirmed",
            "customer_id": "cus_1",
            "customer_name": "Rahul",
            "total": 299,
            "reference_number": "pay_NotInvoiced1008",
            "notes": "phone 9876543210 and plink_Link99",
            "line_items": [{"item_id": "it", "sku": "SKU-CABLE-C", "name": "Cable", "quantity": 1, "rate": 299}],
        }
    )
    assert order.payment_ids == ["pay_NotInvoiced1008", "plink_Link99"]
    assert "9876543210" not in order.model_dump_json()
    assert not hasattr(order, "notes") or "notes" not in order.model_fields


@pytest.mark.asyncio
async def test_token_bucket_waits_when_empty():
    clock = ManualClock()
    sleeps = []

    async def sleeper(seconds):
        sleeps.append(seconds)
        clock.advance(seconds)

    bucket = TokenBucket(rate_per_minute=60, capacity=1, clock=clock, sleeper=sleeper)
    await bucket.acquire()
    await bucket.acquire()
    assert sleeps and sleeps[0] == pytest.approx(1.0, rel=0.05)
