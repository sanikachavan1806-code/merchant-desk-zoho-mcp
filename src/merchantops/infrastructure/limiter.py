from __future__ import annotations

import asyncio
from collections import deque

from merchantops.infrastructure.clock import Clock


class TokenBucket:
    """Client-side budget under Zoho's 100 requests/minute/organization cap."""

    def __init__(
        self,
        *,
        rate_per_minute: float,
        capacity: float,
        clock: Clock,
        sleeper,
    ) -> None:
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.rate_per_sec = float(rate_per_minute) / 60.0
        self.clock = clock
        self.sleeper = sleeper
        self._updated = clock.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self.clock.monotonic()
        elapsed = max(0.0, now - self._updated)
        self._updated = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_sec)

    async def acquire(self) -> None:
        while True:
            wait = 0.0
            async with self._lock:
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / self.rate_per_sec
            await self.sleeper(wait)


class BudgetMeter:
    """Counts outbound Zoho calls for get_api_budget and the daily fail-fast."""

    def __init__(self, *, daily_limit: int, per_minute_limit: int, clock: Clock) -> None:
        self.daily_limit = daily_limit
        self.per_minute_limit = per_minute_limit
        self.clock = clock
        self.daily_used = 0
        self.daily_exhausted = False
        self._events: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def record(self) -> None:
        async with self._lock:
            self.daily_used += 1
            self._events.append(self.clock.monotonic())

    async def mark_daily_exhausted(self) -> None:
        async with self._lock:
            self.daily_exhausted = True

    def per_minute_used(self) -> int:
        cutoff = self.clock.monotonic() - 60.0
        return sum(1 for ts in self._events if ts >= cutoff)

    def snapshot(self, *, plan: str, budget_per_minute: int, concurrency: int) -> dict:
        remaining = max(0, self.daily_limit - self.daily_used)
        if self.daily_exhausted:
            remaining = 0
        per_minute = self.per_minute_used()
        if self.daily_exhausted or remaining == 0:
            advice = (
                "Daily Zoho quota is exhausted. Do not scan the catalog. "
                "Explain the limit to the merchant and wait for the quota to reset."
            )
        elif per_minute > budget_per_minute * 0.7 or remaining < 50:
            advice = (
                "Quota is getting tight. Prefer get_daily_operations_brief or "
                "detect_operational_risks over per-record fan-out."
            )
        else:
            advice = "Safe to answer a focused question. Avoid walking every item or order."
        return {
            "plan": plan,
            "daily_limit": self.daily_limit,
            "daily_used": self.daily_used,
            "daily_remaining": remaining,
            "daily_exhausted": self.daily_exhausted or remaining == 0,
            "per_minute_platform_limit": self.per_minute_limit,
            "per_minute_budget": budget_per_minute,
            "per_minute_used": per_minute,
            "concurrency_limit": concurrency,
            "advice": advice,
        }
